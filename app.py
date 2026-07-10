El error ocurre porque la consulta SQL (`INSERT INTO jobs`) incluye 17 columnas, pero en la cláusula `VALUES` solo proporcionas 15 marcadores de posición (`?`). Específicamente, faltan dos `?` para coincidir con la cantidad de campos, lo que provoca un fallo de sintaxis en SQLite.

Aquí tenés el código completo con el error corregido en la función `render_job_form`:

```python
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import hashlib
import io
import json
import re
import secrets
import sqlite3

import pandas as pd
import streamlit as st
from PIL import Image
from pypdf import PdfReader
from docx import Document


# =========================================================
# CONFIGURACIÓN
# =========================================================

APP_NAME = "Alba | Plataforma de Selección"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGO_DIR = DATA_DIR / "logos"
DB_PATH = DATA_DIR / "alba.db"

DATA_DIR.mkdir(exist_ok=True)
LOGO_DIR.mkdir(exist_ok=True)

PERMISSIONS = {
    "manage_company": "Administrar empresa y logo",
    "manage_users": "Crear usuarios y asignar permisos",
    "manage_jobs": "Crear y editar búsquedas",
    "view_candidates": "Ver candidatos y postulaciones",
    "manage_candidates": "Modificar etapas y decisiones",
    "view_audit": "Consultar auditoría",
}

DEFAULT_ROLE_PERMISSIONS = {
    "ADMIN": list(PERMISSIONS.keys()),
    "RECRUITER": [
        "manage_jobs",
        "view_candidates",
        "manage_candidates",
    ],
    "VIEWER": [
        "view_candidates",
    ],
}


# =========================================================
# UTILIDADES
# =========================================================

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        180_000,
    )
    return digest.hex(), salt


def verify_password(password: str, expected_hash: str, salt: str) -> bool:
    current_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(current_hash, expected_hash)


def validate_password(password: str) -> str | None:
    if len(password) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if not re.search(r"[A-Za-z]", password):
        return "La contraseña debe incluir al menos una letra."
    if not re.search(r"\d", password):
        return "La contraseña debe incluir al menos un número."
    return None


def safe_filename(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "archivo")
    return clean[:120]


def load_logo_bytes(company_id: int) -> bytes | None:
    rows = fetch_all(
        "SELECT logo_path FROM companies WHERE id = ?",
        (company_id,),
    )
    if not rows or not rows[0].get("logo_path"):
        return None

    path = Path(rows[0]["logo_path"])
    if path.exists():
        return path.read_bytes()
    return None


def save_logo(company_id: int, uploaded_file) -> str:
    extension = Path(uploaded_file.name).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("El logo debe ser PNG, JPG, JPEG o WEBP.")

    raw = uploaded_file.getvalue()
    Image.open(io.BytesIO(raw)).verify()

    path = LOGO_DIR / f"company_{company_id}{extension}"
    path.write_bytes(raw)

    execute(
        "UPDATE companies SET logo_path = ? WHERE id = ?",
        (str(path), company_id),
    )
    return str(path)


# =========================================================
# BASE DE DATOS
# =========================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(table_name: str) -> set[str]:
    conn = get_connection()
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    conn.close()
    return {row["name"] for row in rows}


def add_column_if_missing(table_name: str, column_name: str, definition: str):
    if column_name not in table_columns(table_name):
        conn = get_connection()
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )
        conn.commit()
        conn.close()


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            industry TEXT,
            country TEXT,
            logo_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            full_name TEXT NOT NULL,
            account_type TEXT NOT NULL,
            company_id INTEGER,
            role TEXT,
            permissions_json TEXT DEFAULT '[]',
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            area TEXT,
            seniority TEXT,
            location TEXT,
            work_mode TEXT,
            contract_type TEXT,
            description TEXT,
            must_have TEXT,
            desirable TEXT,
            responsibilities TEXT,
            competencies TEXT,
            status TEXT DEFAULT 'ABIERTA',
            source_filename TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT,
            FOREIGN KEY(company_id) REFERENCES companies(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            phone TEXT,
            dni TEXT,
            birth_date TEXT,
            city TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            status TEXT DEFAULT 'RECIBIDA',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id),
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            event_type TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()

    # Migraciones automáticas para bases creadas por módulos anteriores.
    add_column_if_missing("companies", "logo_path", "TEXT")

    for column, definition in {
        "location": "TEXT",
        "work_mode": "TEXT",
        "contract_type": "TEXT",
        "responsibilities": "TEXT",
        "competencies": "TEXT",
        "source_filename": "TEXT",
        "created_by": "INTEGER",
        "updated_at": "TEXT",
    }.items():
        add_column_if_missing("jobs", column, definition)

    add_column_if_missing("audit_log", "user_id", "INTEGER")
    add_column_if_missing("candidates", "user_id", "INTEGER")

    for column, definition in {
        "phone": "TEXT",
        "dni": "TEXT",
        "birth_date": "TEXT",
        "city": "TEXT",
    }.items():
        add_column_if_missing("candidates", column, definition)


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def execute(query: str, params: tuple = ()) -> int:
    conn = get_connection()
    cur = conn.execute(query, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def log_event(
    user_id: int | None,
    event_type: str,
    entity_type: str = "",
    entity_id: int | None = None,
    details: dict | str | None = None,
):
    if isinstance(details, dict):
        details = json.dumps(details, ensure_ascii=False)

    execute(
        """
        INSERT INTO audit_log(
            user_id, event_type, entity_type, entity_id, details, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            event_type,
            entity_type,
            entity_id,
            details or "",
            now_iso(),
        ),
    )


# =========================================================
# AUTENTICACIÓN Y PERMISOS
# =========================================================

def create_user(
    email: str,
    password: str,
    full_name: str,
    account_type: str,
    company_id: int | None = None,
    role: str | None = None,
    permissions: list[str] | None = None,
) -> int:
    email = normalize_email(email)
    if not email or "@" not in email:
        raise ValueError("Ingresá un correo electrónico válido.")

    error = validate_password(password)
    if error:
        raise ValueError(error)

    if fetch_all("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError("Ya existe un usuario registrado con ese correo.")

    password_hash, salt = hash_password(password)
    return execute(
        """
        INSERT INTO users(
            email, password_hash, password_salt, full_name,
            account_type, company_id, role, permissions_json,
            active, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            email,
            password_hash,
            salt,
            full_name.strip(),
            account_type,
            company_id,
            role,
            json.dumps(permissions or [], ensure_ascii=False),
            now_iso(),
        ),
    )


def authenticate(email: str, password: str) -> dict | None:
    email = normalize_email(email)
    rows = fetch_all(
        "SELECT * FROM users WHERE email = ? AND active = 1",
        (email,),
    )
    if not rows:
        return None

    user = rows[0]
    if not verify_password(
        password,
        user["password_hash"],
        user["password_salt"],
    ):
        return None

    try:
        user["permissions"] = json.loads(user.get("permissions_json") or "[]")
    except json.JSONDecodeError:
        user["permissions"] = []

    return user


def current_user() -> dict | None:
    return st.session_state.get("auth_user")


def has_permission(permission: str) -> bool:
    user = current_user()
    if not user:
        return False
    if user.get("account_type") != "COMPANY":
        return False
    if user.get("role") == "ADMIN":
        return True
    return permission in user.get("permissions", [])


def logout():
    for key in [
        "auth_user",
        "job_import_data",
        "job_import_filename",
    ]:
        st.session_state.pop(key, None)
    st.rerun()


# =========================================================
# IMPORTACIÓN Y AUTOCOMPLETADO DE BÚSQUEDAS
# =========================================================

def extract_text_from_pdf(raw: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def extract_text_from_docx(raw: bytes) -> str:
    document = Document(io.BytesIO(raw))
    blocks = [paragraph.text for paragraph in document.paragraphs]

    for table in document.tables:
        for row in table.rows:
            blocks.append(" | ".join(cell.text for cell in row.cells))

    return "\n".join(blocks)


def extract_text_from_excel(raw: bytes) -> str:
    workbook = pd.ExcelFile(io.BytesIO(raw))
    blocks = []

    for sheet_name in workbook.sheet_names[:5]:
        frame = pd.read_excel(workbook, sheet_name=sheet_name, header=None)
        frame = frame.dropna(how="all")
        blocks.append(f"HOJA: {sheet_name}")
        blocks.append(
            "\n".join(
                " | ".join(
                    str(value)
                    for value in row
                    if pd.notna(value)
                )
                for row in frame.values.tolist()
            )
        )

    return "\n".join(blocks)


def extract_uploaded_job_text(uploaded_file) -> str:
    extension = Path(uploaded_file.name).suffix.lower()
    raw = uploaded_file.getvalue()

    if extension == ".pdf":
        return extract_text_from_pdf(raw)
    if extension == ".docx":
        return extract_text_from_docx(raw)
    if extension in {".xlsx", ".xls"}:
        return extract_text_from_excel(raw)

    raise ValueError(
        "Formato no compatible. Usá PDF, DOCX, XLSX o XLS."
    )


SECTION_ALIASES = {
    "title": [
        "puesto",
        "título del puesto",
        "titulo del puesto",
        "posición",
        "posicion",
        "cargo",
        "vacante",
    ],
    "area": [
        "área",
        "area",
        "departamento",
        "sector",
    ],
    "seniority": [
        "seniority",
        "nivel",
        "jerarquía",
        "jerarquia",
    ],
    "location": [
        "ubicación",
        "ubicacion",
        "localidad",
        "lugar de trabajo",
        "sede",
    ],
    "work_mode": [
        "modalidad",
        "modalidad de trabajo",
    ],
    "contract_type": [
        "tipo de contratación",
        "tipo de contratacion",
        "contrato",
        "jornada",
    ],
    "description": [
        "descripción",
        "descripcion",
        "objetivo del puesto",
        "misión",
        "mision",
        "resumen",
    ],
    "responsibilities": [
        "responsabilidades",
        "funciones",
        "tareas",
        "principales tareas",
    ],
    "must_have": [
        "requisitos excluyentes",
        "requisitos obligatorios",
        "excluyentes",
        "must have",
    ],
    "desirable": [
        "requisitos deseables",
        "deseables",
        "se valorará",
        "se valorara",
        "nice to have",
    ],
    "competencies": [
        "competencias",
        "habilidades",
        "skills",
        "competencias requeridas",
    ],
}


def clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" \t-•|:")


def split_into_sections(text: str) -> dict[str, str]:
    result = {key: "" for key in SECTION_ALIASES}
    current_section = None
    section_lines: dict[str, list[str]] = {
        key: [] for key in SECTION_ALIASES
    }

    lines = [clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    for line in lines:
        lower_line = line.lower()
        detected = None
        inline_value = ""

        for field, aliases in SECTION_ALIASES.items():
            for alias in aliases:
                pattern = rf"^{re.escape(alias)}\s*[:\-]\s*(.*)$"
                match = re.match(pattern, lower_line, flags=re.I)
                if match:
                    detected = field
                    inline_value = line.split(":", 1)[-1].strip() if ":" in line else ""
                    break

                if lower_line == alias:
                    detected = field
                    break

            if detected:
                break

        if detected:
            current_section = detected
            if inline_value:
                section_lines[detected].append(inline_value)
            continue

        if current_section:
            section_lines[current_section].append(line)

    for field, values in section_lines.items():
        result[field] = "\n".join(values).strip()

    if not result["title"] and lines:
        likely_title = next(
            (
                line
                for line in lines[:12]
                if 2 <= len(line.split()) <= 10
                and len(line) <= 100
            ),
            "",
        )
        result["title"] = likely_title

    full_lower = text.lower()

    if not result["seniority"]:
        seniority_matches = [
            ("Pasantía", ["pasantía", "pasantia", "intern"]),
            ("Junior", ["junior", "jr."]),
            ("Semi Senior", ["semi senior", "ssr"]),
            ("Senior", ["senior", "sr."]),
            ("Liderazgo", ["supervisor", "líder", "lider", "jefatura"]),
            ("Dirección", ["director", "dirección", "direccion", "gerencia"]),
        ]
        for label, keywords in seniority_matches:
            if any(keyword in full_lower for keyword in keywords):
                result["seniority"] = label
                break

    if not result["work_mode"]:
        for label, keywords in {
            "Presencial": ["presencial"],
            "Híbrido": ["híbrido", "hibrido"],
            "Remoto": ["remoto", "home office"],
        }.items():
            if any(keyword in full_lower for keyword in keywords):
                result["work_mode"] = label
                break

    if not result["description"]:
        result["description"] = text[:2500].strip()

    return result


def render_job_form(
    company_id: int,
    user_id: int,
    imported: dict | None = None,
    source_filename: str = "",
):
    imported = imported or {}

    seniority_options = [
        "Pasantía",
        "Junior",
        "Semi Senior",
        "Senior",
        "Liderazgo",
        "Dirección",
        "No especificado",
    ]
    work_mode_options = [
        "Presencial",
        "Híbrido",
        "Remoto",
        "No especificado",
    ]

    imported_seniority = imported.get("seniority") or "No especificado"
    if imported_seniority not in seniority_options:
        imported_seniority = "No especificado"

    imported_work_mode = imported.get("work_mode") or "No especificado"
    if imported_work_mode not in work_mode_options:
        imported_work_mode = "No especificado"

    with st.form("editable_job_form"):
        st.caption(
            "Los campos se autocompletan con el archivo y pueden editarse antes de guardar."
        )

        title = st.text_input(
            "Puesto",
            value=imported.get("title", ""),
        )

        c1, c2 = st.columns(2)
        area = c1.text_input(
            "Área",
            value=imported.get("area", ""),
        )
        seniority = c2.selectbox(
            "Seniority",
            seniority_options,
            index=seniority_options.index(imported_seniority),
        )

        c3, c4 = st.columns(2)
        location = c3.text_input(
            "Ubicación",
            value=imported.get("location", ""),
        )
        work_mode = c4.selectbox(
            "Modalidad",
            work_mode_options,
            index=work_mode_options.index(imported_work_mode),
        )

        contract_type = st.text_input(
            "Tipo de contratación / jornada",
            value=imported.get("contract_type", ""),
        )

        description = st.text_area(
            "Descripción del puesto",
            value=imported.get("description", ""),
            height=180,
        )
        responsibilities = st.text_area(
            "Responsabilidades y tareas",
            value=imported.get("responsibilities", ""),
            height=140,
        )
        must_have = st.text_area(
            "Requisitos excluyentes",
            value=imported.get("must_have", ""),
            height=130,
        )
        desirable = st.text_area(
            "Requisitos deseables",
            value=imported.get("desirable", ""),
            height=130,
        )
        competencies = st.text_area(
            "Competencias",
            value=imported.get("competencies", ""),
            height=120,
        )

        submitted = st.form_submit_button(
            "Guardar búsqueda",
            type="primary",
            use_container_width=True,
        )

        if submitted:
            if not title.strip():
                st.error("Ingresá el nombre del puesto.")
                return

            try:
                # CORRECCIÓN: Se agregaron los dos marcadores '?, ?' faltantes en VALUES (eran 15 y debían ser 17)
                job_id = execute(
                    """
                    INSERT INTO jobs(
                        company_id, title, area, seniority, location,
                        work_mode, contract_type, description,
                        responsibilities, must_have, desirable,
                        competencies, status, source_filename,
                        created_by, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ABIERTA', ?, ?, ?, ?)
                    """,
                    (
                        company_id,
                        title.strip(),
                        area.strip(),
                        seniority,
                        location.strip(),
                        work_mode,
                        contract_type.strip(),
                        description.strip(),
                        responsibilities.strip(),
                        must_have.strip(),
                        desirable.strip(),
                        competencies.strip(),
                        source_filename,
                        user_id,
                        now_iso(),
                        now_iso(),
                    ),
                )

                log_event(
                    user_id,
                    "CREATE",
                    "job",
                    job_id,
                    {
                        "title": title,
                        "source_filename": source_filename,
                    },
                )

                st.session_state.pop("job_import_data", None)
                st.session_state.pop("job_import_filename", None)
                st.success("Búsqueda creada correctamente.")
                st.rerun()

            except sqlite3.Error as exc:
                st.error(
                    "No se pudo guardar la búsqueda por un error de base de datos. "
                    f"Detalle técnico: {exc}"
                )
            except Exception as exc:
                st.error(
                    "No se pudo guardar la búsqueda. "
                    f"Detalle técnico: {exc}"
                )


# =========================================================
# REGISTRO Y LOGIN
# =========================================================

def render_registration():
    st.subheader("Crear una cuenta")

    account_type = st.radio(
        "Tipo de cuenta",
        ["Empresa", "Candidato"],
        horizontal=True,
    )

    if account_type == "Empresa":
        with st.form("register_company"):
            st.markdown("#### Datos de la empresa")
            company_name = st.text_input("Nombre de la empresa")
            c1, c2 = st.columns(2)
            industry = c1.text_input("Industria")
            country = c2.text_input("País", value="Argentina")
            logo = st.file_uploader(
                "Logo de la empresa",
                type=["png", "jpg", "jpeg", "webp"],
            )

            st.markdown("#### Usuario administrador")
            admin_name = st.text_input("Nombre y apellido")
            admin_email = st.text_input("Correo electrónico")
            password = st.text_input("Contraseña", type="password")
            password_repeat = st.text_input(
                "Repetir contraseña",
                type="password",
            )

            submitted = st.form_submit_button(
                "Crear empresa y usuario administrador",
                type="primary",
            )

            if submitted:
                try:
                    if not company_name.strip():
                        raise ValueError("Ingresá el nombre de la empresa.")
                    if not admin_name.strip():
                        raise ValueError("Ingresá el nombre del administrador.")
                    if password != password_repeat:
                        raise ValueError("Las contraseñas no coinciden.")
                    if logo is None:
                        raise ValueError(
                            "Para registrar la empresa tenés que subir su logo."
                        )

                    company_id = execute(
                        """
                        INSERT INTO companies(
                            name, industry, country, created_at
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            company_name.strip(),
                            industry.strip(),
                            country.strip(),
                            now_iso(),
                        ),
                    )

                    save_logo(company_id, logo)

                    user_id = create_user(
                        email=admin_email,
                        password=password,
                        full_name=admin_name,
                        account_type="COMPANY",
                        company_id=company_id,
                        role="ADMIN",
                        permissions=DEFAULT_ROLE_PERMISSIONS["ADMIN"],
                    )

                    log_event(
                        user_id,
                        "REGISTER",
                        "company",
                        company_id,
                        {"company": company_name},
                    )

                    st.success(
                        "Empresa registrada. Ya podés iniciar sesión."
                    )
                except Exception as exc:
                    st.error(str(exc))

    else:
        with st.form("register_candidate"):
            full_name = st.text_input("Nombre y apellido")
            email = st.text_input("Correo electrónico")
            password = st.text_input("Contraseña", type="password")
            password_repeat = st.text_input(
                "Repetir contraseña",
                type="password",
            )

            c1, c2 = st.columns(2)
            phone = c1.text_input("Teléfono")
            dni = c2.text_input("DNI")

            c3, c4 = st.columns(2)
            birth_date = c3.date_input(
                "Fecha de nacimiento",
                value=None,
            )
            city = c4.text_input("Ciudad")

            consent = st.checkbox(
                "Acepto el tratamiento de mis datos para gestionar postulaciones. "
                "Los datos administrativos no se usarán para puntuar ni rankear."
            )

            submitted = st.form_submit_button(
                "Crear cuenta de candidato",
                type="primary",
            )

            if submitted:
                try:
                    if not full_name.strip():
                        raise ValueError("Ingresá tu nombre y apellido.")
                    if password != password_repeat:
                        raise ValueError("Las contraseñas no coinciden.")
                    if not consent:
                        raise ValueError(
                            "Tenés que aceptar el consentimiento."
                        )

                    user_id = create_user(
                        email=email,
                        password=password,
                        full_name=full_name,
                        account_type="CANDIDATE",
                    )

                    execute(
                        """
                        INSERT INTO candidates(
                            user_id, phone, dni, birth_date,
                            city, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            phone.strip(),
                            dni.strip(),
                            birth_date.isoformat() if birth_date else "",
                            city.strip(),
                            now_iso(),
                        ),
                    )

                    log_event(
                        user_id,
                        "REGISTER",
                        "candidate",
                        user_id,
                        {"email": normalize_email(email)},
                    )

                    st.success(
                        "Cuenta creada. Ya podés iniciar sesión."
                    )
                except Exception as exc:
                    st.error(str(exc))


def render_login():
    st.subheader("Iniciar sesión")

    with st.form("login_form"):
        email = st.text_input("Correo electrónico")
        password = st.text_input("Contraseña", type="password")

        submitted = st.form_submit_button(
            "Ingresar",
            type="primary",
            use_container_width=True,
        )

        if submitted:
            user = authenticate(email, password)
            if not user:
                st.error("Correo o contraseña incorrectos.")
            else:
                st.session_state["auth_user"] = user
                log_event(
                    user["id"],
                    "LOGIN",
                    "user",
                    user["id"],
                    {"email": user["email"]},
                )
                st.rerun()


# =========================================================
# PORTAL DE EMPRESA
# =========================================================

def render_company_header(user: dict):
    company = fetch_all(
        "SELECT * FROM companies WHERE id = ?",
        (user["company_id"],),
    )
    if not company:
        st.error("No se encontró la empresa vinculada.")
        return None

    company = company[0]
    c1, c2 = st.columns([1, 5])

    logo_bytes = load_logo_bytes(company["id"])
    with c1:
        if logo_bytes:
            st.image(logo_bytes, width=130)

    with c2:
        st.title(company["name"])
        st.caption(
            f"{company.get('industry') or 'Industria no informada'} · "
            f"{company.get('country') or 'País no informado'}"
        )

    return company


def render_company_settings(user: dict, company: dict):
    st.subheader("Configuración de empresa")

    if not has_permission("manage_company"):
        st.warning("No tenés permiso para administrar la empresa.")
        return

    with st.form("company_settings_form"):
        name = st.text_input(
            "Nombre de la empresa",
            value=company["name"],
        )
        industry = st.text_input(
            "Industria",
            value=company.get("industry") or "",
        )
        country = st.text_input(
            "País",
            value=company.get("country") or "",
        )
        logo = st.file_uploader(
            "Reemplazar logo",
            type=["png", "jpg", "jpeg", "webp"],
        )

        submitted = st.form_submit_button("Guardar cambios")

        if submitted:
            execute(
                """
                UPDATE companies
                SET name = ?, industry = ?, country = ?
                WHERE id = ?
                """,
                (
                    name.strip(),
                    industry.strip(),
                    country.strip(),
                    company["id"],
                ),
            )

            if logo is not None:
                save_logo(company["id"], logo)

            log_event(
                user["id"],
                "UPDATE",
                "company",
                company["id"],
                {"name": name},
            )
            st.success("Datos actualizados.")
            st.rerun()


def render_user_management(user: dict):
    st.subheader("Usuarios, permisos y accesos")

    if not has_permission("manage_users"):
        st.warning("No tenés permiso para administrar usuarios.")
        return

    st.markdown("#### Crear usuario")

    with st.form("create_company_user"):
        c1, c2 = st.columns(2)
        full_name = c1.text_input("Nombre y apellido")
        email = c2.text_input("Correo electrónico")

        c3, c4 = st.columns(2)
        role = c3.selectbox(
            "Rol base",
            ["ADMIN", "RECRUITER", "VIEWER"],
        )
        password = c4.text_input(
            "Contraseña provisoria",
            type="password",
        )

        st.markdown("**Permisos personalizados**")
        selected_permissions = []

        default_permissions = DEFAULT_ROLE_PERMISSIONS[role]
        cols = st.columns(2)

        for index, (permission_key, permission_label) in enumerate(
            PERMISSIONS.items()
        ):
            checked = cols[index % 2].checkbox(
                permission_label,
                value=permission_key in default_permissions,
                key=f"perm_{permission_key}",
            )
            if checked:
                selected_permissions.append(permission_key)

        submitted = st.form_submit_button("Crear usuario")

        if submitted:
            try:
                if not full_name.strip():
                    raise ValueError("Ingresá el nombre del usuario.")

                new_user_id = create_user(
                    email=email,
                    password=password,
                    full_name=full_name,
                    account_type="COMPANY",
                    company_id=user["company_id"],
                    role=role,
                    permissions=selected_permissions,
                )

                log_event(
                    user["id"],
                    "CREATE",
                    "user",
                    new_user_id,
                    {
                        "email": normalize_email(email),
                        "role": role,
                    },
                )

                st.success("Usuario creado correctamente.")
                st.rerun()

            except Exception as exc:
                st.error(str(exc))

    st.markdown("#### Usuarios existentes")

    users = fetch_all(
        """
        SELECT id, full_name, email, role,
               permissions_json, active, created_at
        FROM users
        WHERE company_id = ?
        ORDER BY created_at DESC
        """,
        (user["company_id"],),
    )

    if users:
        display_rows = []
        for row in users:
            try:
                permissions = json.loads(
                    row.get("permissions_json") or "[]"
                )
            except json.JSONDecodeError:
                permissions = []

            display_rows.append(
                {
                    "ID": row["id"],
                    "Nombre": row["full_name"],
                    "Email": row["email"],
                    "Rol": row["role"],
                    "Permisos": ", ".join(
                        PERMISSIONS.get(permission, permission)
                        for permission in permissions
                    ),
                    "Activo": "Sí" if row["active"] else "No",
                }
            )

        st.dataframe(
            pd.DataFrame(display_rows),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("#### Editar accesos")

        editable_options = {
            f"{row['full_name']} — {row['email']}": row
            for row in users
        }
        selected_label = st.selectbox(
            "Seleccionar usuario",
            list(editable_options.keys()),
        )
        selected_user = editable_options[selected_label]

        try:
            current_permissions = json.loads(
                selected_user.get("permissions_json") or "[]"
            )
        except json.JSONDecodeError:
            current_permissions = []

        with st.form("edit_company_user"):
            new_role = st.selectbox(
                "Rol",
                ["ADMIN", "RECRUITER", "VIEWER"],
                index=["ADMIN", "RECRUITER", "VIEWER"].index(
                    selected_user["role"]
                ),
            )
            active = st.checkbox(
                "Usuario activo",
                value=bool(selected_user["active"]),
            )

            updated_permissions = []
            permission_columns = st.columns(2)
            for index, (permission_key, permission_label) in enumerate(
                PERMISSIONS.items()
            ):
                checked = permission_columns[index % 2].checkbox(
                    permission_label,
                    value=permission_key in current_permissions,
                    key=f"edit_perm_{selected_user['id']}_{permission_key}",
                )
                if checked:
                    updated_permissions.append(permission_key)

            submitted = st.form_submit_button("Guardar accesos")

            if submitted:
                execute(
                    """
                    UPDATE users
                    SET role = ?, permissions_json = ?, active = ?
                    WHERE id = ? AND company_id = ?
                    """,
                    (
                        new_role,
                        json.dumps(
                            updated_permissions,
                            ensure_ascii=False,
                        ),
                        int(active),
                        selected_user["id"],
                        user["company_id"],
                    ),
                )

                log_event(
                    user["id"],
                    "UPDATE_PERMISSIONS",
                    "user",
                    selected_user["id"],
                    {
                        "role": new_role,
                        "active": active,
                        "permissions": updated_permissions,
                    },
                )

                st.success("Permisos actualizados.")
                st.rerun()
    else:
        st.info("Todavía no hay usuarios registrados.")


def render_jobs(user: dict):
    st.subheader("Búsquedas laborales")

    if not has_permission("manage_jobs"):
        st.warning("No tenés permiso para crear o editar búsquedas.")
    else:
        mode = st.radio(
            "Cómo querés crear la búsqueda",
            [
                "Importar archivo y autocompletar",
                "Crear manualmente",
            ],
            horizontal=True,
        )

        if mode == "Importar archivo y autocompletar":
            uploaded_file = st.file_uploader(
                "Subí el requerimiento en Excel, PDF o Word",
                type=["xlsx", "xls", "pdf", "docx"],
            )

            if uploaded_file is not None:
                if st.button(
                    "Analizar archivo y autocompletar",
                    type="primary",
                ):
                    try:
                        text = extract_uploaded_job_text(uploaded_file)
                        parsed = split_into_sections(text)

                        st.session_state["job_import_data"] = parsed
                        st.session_state["job_import_filename"] = (
                            uploaded_file.name
                        )
                        st.success(
                            "Archivo analizado. Revisá y editá los campos."
                        )
                    except Exception as exc:
                        st.error(f"No se pudo analizar el archivo: {exc}")

            imported_data = st.session_state.get(
                "job_import_data",
                {},
            )
            source_filename = st.session_state.get(
                "job_import_filename",
                "",
            )

            if imported_data:
                with st.expander(
                    "Ver datos detectados",
                    expanded=False,
                ):
                    st.json(imported_data)

                render_job_form(
                    user["company_id"],
                    user["id"],
                    imported=imported_data,
                    source_filename=source_filename,
                )

        else:
            render_job_form(
                user["company_id"],
                user["id"],
            )

    st.divider()
    st.markdown("#### Búsquedas registradas")

    jobs = fetch_all(
        """
        SELECT
            id, title, area, seniority, location,
            work_mode, contract_type, status,
            source_filename, created_at
        FROM jobs
        WHERE company_id = ?
        ORDER BY created_at DESC
        """,
        (user["company_id"],),
    )

    if jobs:
        st.dataframe(
            pd.DataFrame(jobs),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Todavía no hay búsquedas registradas.")


def render_applications(user: dict):
    st.subheader("Candidatos y postulaciones")

    if not has_permission("view_candidates"):
        st.warning("No tenés permiso para ver candidatos.")
        return

    applications = fetch_all(
        """
        SELECT
            applications.id,
            company_user.full_name AS candidate,
            company_user.email,
            jobs.title AS job,
            applications.status,
            applications.created_at
        FROM applications
        JOIN candidates
            ON candidates.id = applications.candidate_id
        JOIN users AS company_user
            ON company_user.id = candidates.user_id
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE jobs.company_id = ?
        ORDER BY applications.created_at DESC
        """,
        (user["company_id"],),
    )

    if applications:
        st.dataframe(
            pd.DataFrame(applications),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Todavía no hay postulaciones.")


def render_audit(user: dict):
    st.subheader("Auditoría")

    if not has_permission("view_audit"):
        st.warning("No tenés permiso para consultar auditoría.")
        return

    audit = fetch_all(
        """
        SELECT
            audit_log.id,
            audit_log.event_type,
            audit_log.entity_type,
            audit_log.entity_id,
            audit_log.details,
            audit_log.created_at,
            users.email AS user_email
        FROM audit_log
        LEFT JOIN users
            ON users.id = audit_log.user_id
        WHERE users.company_id = ? OR audit_log.user_id IS NULL
        ORDER BY audit_log.created_at DESC
        LIMIT 500
        """,
        (user["company_id"],),
    )

    if audit:
        st.dataframe(
            pd.DataFrame(audit),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Todavía no hay eventos de auditoría.")


def render_company_portal(user: dict):
    company = render_company_header(user)
    if not company:
        return

    st.sidebar.success(
        f"{user['full_name']}\n\n{user['email']}"
    )
    if st.sidebar.button("Cerrar sesión"):
        logout()

    menu_options = ["Inicio", "Búsquedas"]

    if has_permission("view_candidates"):
        menu_options.append("Candidatos")
    if has_permission("manage_users"):
        menu_options.append("Usuarios y permisos")
    if has_permission("manage_company"):
        menu_options.append("Empresa")
    if has_permission("view_audit"):
        menu_options.append("Auditoría")

    section = st.sidebar.radio(
        "Menú",
        menu_options,
    )

    if section == "Inicio":
        st.header("Panel de empresa")

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Búsquedas",
            fetch_all(
                "SELECT COUNT(*) AS total FROM jobs WHERE company_id = ?",
                (user["company_id"],),
            )[0]["total"],
        )
        c2.metric(
            "Usuarios",
            fetch_all(
                "SELECT COUNT(*) AS total FROM users WHERE company_id = ?",
                (user["company_id"],),
            )[0]["total"],
        )
        c3.metric(
            "Postulaciones",
            fetch_all(
                """
                SELECT COUNT(*) AS total
                FROM applications
                JOIN jobs ON jobs.id = applications.job_id
                WHERE jobs.company_id = ?
                """,
                (user["company_id"],),
            )[0]["total"],
        )

        st.info(
            "Este módulo incorpora autenticación, logo, usuarios, "
            "permisos e importación editable de búsquedas."
        )

    elif section == "Búsquedas":
        render_jobs(user)
    elif section == "Candidatos":
        render_applications(user)
    elif section == "Usuarios y permisos":
        render_user_management(user)
    elif section == "Empresa":
        render_company_settings(user, company)
    elif section == "Auditoría":
        render_audit(user)


# =========================================================
# PORTAL DEL CANDIDATO
# =========================================================

def render_candidate_portal(user: dict):
    st.title("Portal del candidato")
    st.caption(f"Sesión iniciada como {user['email']}")

    if st.sidebar.button("Cerrar sesión"):
        logout()

    candidate = fetch_all(
        "SELECT * FROM candidates WHERE user_id = ?",
        (user["id"],),
    )
    if not candidate:
        st.error("No se encontró el perfil del candidato.")
        return

    candidate = candidate[0]

    menu = st.sidebar.radio(
        "Menú",
        ["Búsquedas abiertas", "Mis postulaciones", "Mi perfil"],
    )

    if menu == "Búsquedas abiertas":
        jobs = fetch_all(
            """
            SELECT
                jobs.id,
                jobs.title,
                jobs.area,
                jobs.seniority,
                jobs.location,
                jobs.work_mode,
                jobs.contract_type,
                jobs.description,
                companies.name AS company_name,
                companies.logo_path
            FROM jobs
            JOIN companies
                ON companies.id = jobs.company_id
            WHERE jobs.status = 'ABIERTA'
            ORDER BY jobs.created_at DESC
            """
        )

        if not jobs:
            st.info("No hay búsquedas abiertas.")
            return

        for job in jobs:
            with st.container(border=True):
                col_logo, col_content = st.columns([1, 5])

                with col_logo:
                    logo_path = job.get("logo_path")
                    if logo_path and Path(logo_path).exists():
                        st.image(logo_path, width=90)

                with col_content:
                    st.subheader(job["title"])
                    st.write(f"**Empresa:** {job['company_name']}")
                    st.write(
                        f"**Área:** {job.get('area') or 'No informada'}"
                    )
                    st.write(
                        f"**Modalidad:** {job.get('work_mode') or 'No informada'}"
                    )
                    st.write(
                        f"**Ubicación:** {job.get('location') or 'No informada'}"
                    )
                    st.write(job.get("description") or "")

                    already_applied = fetch_all(
                        """
                        SELECT id
                        FROM applications
                        WHERE candidate_id = ? AND job_id = ?
                        """,
                        (candidate["id"], job["id"]),
                    )

                    if already_applied:
                        st.success("Ya te postulaste a esta búsqueda.")
                    elif st.button(
                        "Postularme",
                        key=f"apply_{job['id']}",
                    ):
                        application_id = execute(
                            """
                            INSERT INTO applications(
                                candidate_id, job_id,
                                status, created_at
                            )
                            VALUES (?, ?, 'RECIBIDA', ?)
                            """,
                            (
                                candidate["id"],
                                job["id"],
                                now_iso(),
                            ),
                        )
                        log_event(
                            user["id"],
                            "CREATE",
                            "application",
                            application_id,
                            {"job_id": job["id"]},
                        )
                        st.success("Postulación enviada.")
                        st.rerun()

    elif menu == "Mis postulaciones":
        applications = fetch_all(
            """
            SELECT
                applications.id,
                jobs.title,
                companies.name AS company,
                applications.status,
                applications.created_at
            FROM applications
            JOIN jobs
                ON jobs.id = applications.job_id
            JOIN companies
                ON companies.id = jobs.company_id
            WHERE applications.candidate_id = ?
            ORDER BY applications.created_at DESC
            """,
            (candidate["id"],),
        )

        if applications:
            st.dataframe(
                pd.DataFrame(applications),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Todavía no realizaste postulaciones.")

    else:
        with st.form("candidate_profile_form"):
            st.text_input(
                "Nombre y apellido",
                value=user["full_name"],
                disabled=True,
            )
            st.text_input(
                "Correo electrónico",
                value=user["email"],
                disabled=True,
            )
            phone = st.text_input(
                "Teléfono",
                value=candidate.get("phone") or "",
            )
            dni = st.text_input(
                "DNI",
                value=candidate.get("dni") or "",
            )
            city = st.text_input(
                "Ciudad",
                value=candidate.get("city") or "",
            )
            submitted = st.form_submit_button("Guardar perfil")

            if submitted:
                execute(
                    """
                    UPDATE candidates
                    SET phone = ?, dni = ?, city = ?
                    WHERE id = ?
                    """,
                    (
                        phone.strip(),
                        dni.strip(),
                        city.strip(),
                        candidate["id"],
                    ),
                )
                log_event(
                    user["id"],
                    "UPDATE",
                    "candidate",
                    candidate["id"],
                    {"profile": True},
                )
                st.success("Perfil actualizado.")


# =========================================================
# APLICACIÓN PRINCIPAL
# =========================================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🤖",
    layout="wide",
)

init_db()

user = current_user()

if not user:
    st.title(APP_NAME)
    st.caption(
        "Plataforma de selección con portales separados "
        "para empresas y candidatos."
    )

    login_tab, registration_tab, privacy_tab = st.tabs(
        ["Iniciar sesión", "Registrarse", "Privacidad"]
    )

    with login_tab:
        render_login()

    with registration_tab:
        render_registration()

    with privacy_tab:
        st.subheader("Política de datos")
        st.write(
            "El correo electrónico funciona como nombre de usuario. "
            "Las contraseñas se almacenan mediante hash y salt."
        )
        st.write(
            "DNI, edad, fecha de nacimiento y teléfono pueden registrarse "
            "para fines administrativos, pero no deben formar parte del "
            "puntaje ni del ranking."
        )
        st.write(
            "La empresa no debe cargar secretos comerciales, credenciales, "
            "precios, clientes, fórmulas, planos ni procesos confidenciales."
        )

else:
    refreshed = fetch_all(
        "SELECT * FROM users WHERE id = ? AND active = 1",
        (user["id"],),
    )

    if not refreshed:
        st.session_state.pop("auth_user", None)
        st.error("El usuario fue desactivado.")
        st.stop()

    user = refreshed[0]
    try:
        user["permissions"] = json.loads(
            user.get("permissions_json") or "[]"
        )
    except json.JSONDecodeError:
        user["permissions"] = []
    st.session_state["auth_user"] = user

    if user["account_type"] == "COMPANY":
        render_company_portal(user)
    elif user["account_type"] == "CANDIDATE":
        render_candidate_portal(user)
    else:
        st.error("Tipo de cuenta no reconocido.")

```
