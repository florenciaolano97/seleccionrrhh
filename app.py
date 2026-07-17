from __future__ import annotations

from pathlib import Path
import hashlib
import io
import json
import re
import secrets
import sqlite3
import time
import traceback
import unicodedata
import uuid
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image
from pypdf import PdfReader
from docx import Document


# =========================================================
# CONFIGURACIÓN
# =========================================================

APP_NAME = "ALBA v2 | Plataforma de Selección"
APP_VERSION = "4.0.0"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "alba_v2.db"
DATA_DIR.mkdir(exist_ok=True)

PERMISSIONS = {
    "manage_company": "Administrar datos y logo de la empresa",
    "manage_users": "Crear usuarios y administrar accesos",
    "manage_jobs": "Crear y administrar búsquedas",
    "view_candidates": "Ver candidatos y postulaciones",
    "manage_candidates": "Modificar etapas y decisiones",
    "manage_cv_pool": "Cargar CV y ejecutar preselección",
    "view_audit": "Consultar auditoría",
}

ROLE_DEFAULTS = {
    "ADMIN": list(PERMISSIONS.keys()),
    "RECRUITER": [
        "manage_jobs",
        "view_candidates",
        "manage_candidates",
        "manage_cv_pool",
    ],
    "VIEWER": [
        "view_candidates",
    ],
}


APPLICATION_STATUSES = [
    "RECIBIDA",
    "EN REVISIÓN",
    "ENTREVISTA",
    "FINALISTA",
    "SELECCIONADA",
    "RECHAZADA",
]

MAX_CV_SIZE_BYTES = 5 * 1024 * 1024
MAX_CV_BATCH = 50

SCORING_NOTICE = (
    "El puntaje es una ayuda de preselección y no reemplaza la decisión "
    "humana. No utiliza nombre, correo, DNI, edad, teléfono ni ciudad."
)


# =========================================================
# UTILIDADES
# =========================================================

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> bool:
    email = normalize_email(email)
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


def validate_password(password: str) -> str | None:
    if len(password) < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if not re.search(r"[A-Za-z]", password):
        return "La contraseña debe incluir al menos una letra."
    if not re.search(r"\d", password):
        return "La contraseña debe incluir al menos un número."
    return None


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


def validate_logo(uploaded_file) -> tuple[bytes, str]:
    if uploaded_file is None:
        raise ValueError("Tenés que subir el logo de la empresa.")

    raw = uploaded_file.getvalue()
    if not raw:
        raise ValueError("El archivo del logo está vacío.")

    try:
        image = Image.open(io.BytesIO(raw))
        image.verify()
    except Exception as exc:
        raise ValueError("El archivo subido no es una imagen válida.") from exc

    mime_type = uploaded_file.type or "image/png"
    if mime_type not in {
        "image/png",
        "image/jpeg",
        "image/webp",
    }:
        raise ValueError("El logo debe ser PNG, JPG, JPEG o WEBP.")

    return raw, mime_type


# =========================================================
# BASE DE DATOS
# =========================================================

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def table_columns(table_name: str) -> set[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
        return {row["name"] for row in rows}
    finally:
        conn.close()


def add_column_if_missing(
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if column_name in table_columns(table_name):
        return

    conn = get_connection()
    try:
        conn.execute(
            f"ALTER TABLE {table_name} "
            f"ADD COLUMN {column_name} {definition}"
        )
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                industry TEXT,
                country TEXT,
                logo_blob BLOB,
                logo_mime TEXT,
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
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                phone TEXT,
                dni TEXT,
                city TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                area TEXT,
                seniority TEXT,
                description TEXT,
                status TEXT DEFAULT 'ABIERTA',
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(company_id) REFERENCES companies(id),
                FOREIGN KEY(created_by) REFERENCES users(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                status TEXT DEFAULT 'RECIBIDA',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(candidate_id, job_id),
                FOREIGN KEY(candidate_id) REFERENCES candidates(id),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        """)


        cur.execute("""
            CREATE TABLE IF NOT EXISTS candidate_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                mime_type TEXT,
                content_blob BLOB NOT NULL,
                extracted_text TEXT,
                parsed_json TEXT,
                uploaded_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(candidate_id) REFERENCES candidates(id),
                FOREIGN KEY(uploaded_by) REFERENCES users(id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER,
                user_id INTEGER,
                event_type TEXT NOT NULL,
                entity_type TEXT,
                entity_id INTEGER,
                details TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(company_id) REFERENCES companies(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        conn.commit()
    finally:
        conn.close()

    add_column_if_missing("companies", "logo_blob", "BLOB")
    add_column_if_missing("companies", "logo_mime", "TEXT")
    add_column_if_missing("users", "role", "TEXT")
    add_column_if_missing(
        "users",
        "permissions_json",
        "TEXT DEFAULT '[]'",
    )
    add_column_if_missing(
        "users",
        "active",
        "INTEGER DEFAULT 1",
    )

    for column_name, definition in {
        "location": "TEXT",
        "work_mode": "TEXT",
        "contract_type": "TEXT",
        "responsibilities": "TEXT",
        "must_have": "TEXT",
        "desirable": "TEXT",
        "competencies": "TEXT",
        "source_filename": "TEXT",
        "updated_at": "TEXT",
    }.items():
        add_column_if_missing(
            "jobs",
            column_name,
            definition,
        )


    # Compatibilidad con bases creadas por versiones anteriores.
    for column_name, definition in {
        "company_id": "INTEGER",
        "user_id": "INTEGER",
        "event_type": "TEXT DEFAULT ''",
        "entity_type": "TEXT",
        "entity_id": "INTEGER",
        "details": "TEXT",
        "created_at": "TEXT",
    }.items():
        add_column_if_missing(
            "audit_log",
            column_name,
            definition,
        )

    for column_name, definition in {
        "user_id": "INTEGER",
        "phone": "TEXT",
        "dni": "TEXT",
        "city": "TEXT",
    }.items():
        add_column_if_missing(
            "candidates",
            column_name,
            definition,
        )


    for column_name, definition in {
        "source": "TEXT DEFAULT 'PORTAL'",
        "headline": "TEXT",
        "education_summary": "TEXT",
        "experience_summary": "TEXT",
        "skills_text": "TEXT",
        "languages_text": "TEXT",
        "updated_at": "TEXT",
    }.items():
        add_column_if_missing(
            "candidates",
            column_name,
            definition,
        )

    for column_name, definition in {
        "score_total": "REAL",
        "score_breakdown_json": "TEXT",
        "screening_recommendation": "TEXT",
        "screening_summary": "TEXT",
        "screened_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        add_column_if_missing(
            "applications",
            column_name,
            definition,
        )


def fetch_all(
    query: str,
    params: tuple = (),
) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def fetch_one(
    query: str,
    params: tuple = (),
) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute(
    query: str,
    params: tuple = (),
    retries: int = 3,
) -> int:
    last_error = None

    for attempt in range(retries):
        conn = get_connection()
        try:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid
        except sqlite3.OperationalError as exc:
            conn.rollback()
            last_error = exc

            if (
                "locked" in str(exc).lower()
                and attempt < retries - 1
            ):
                time.sleep(0.35 * (attempt + 1))
                continue

            raise
        finally:
            conn.close()

    if last_error:
        raise last_error

    raise RuntimeError("No se pudo ejecutar la operación.")


def log_event(
    company_id: int | None,
    user_id: int | None,
    event_type: str,
    entity_type: str = "",
    entity_id: int | None = None,
    details: dict | str | None = None,
) -> bool:
    """
    La auditoría nunca debe bloquear la operación principal.
    """
    if isinstance(details, dict):
        details = json.dumps(details, ensure_ascii=False)

    try:
        execute(
            """
            INSERT INTO audit_log(
                company_id,
                user_id,
                event_type,
                entity_type,
                entity_id,
                details,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                user_id,
                event_type,
                entity_type,
                entity_id,
                details or "",
                now_iso(),
            ),
        )
        return True

    except Exception as exc:
        try:
            st.session_state["audit_warning"] = (
                "La acción principal se guardó, pero no pudo "
                f"registrarse en auditoría: {exc}"
            )
        except Exception:
            pass
        return False


# =========================================================
# AUTENTICACIÓN Y SESIÓN
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

    if not validate_email(email):
        raise ValueError("Ingresá un correo electrónico válido.")

    password_error = validate_password(password)
    if password_error:
        raise ValueError(password_error)

    if not full_name.strip():
        raise ValueError("Ingresá nombre y apellido.")

    if fetch_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError("Ya existe un usuario registrado con ese correo.")

    password_hash, salt = hash_password(password)

    return execute(
        """
        INSERT INTO users(
            email, password_hash, password_salt, full_name,
            account_type, company_id, role,
            permissions_json, active, created_at
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


def register_company_admin(
    company_name: str,
    industry: str,
    country: str,
    logo_file,
    full_name: str,
    email: str,
    password: str,
) -> int:
    if not company_name.strip():
        raise ValueError("Ingresá el nombre de la empresa.")

    logo_blob, logo_mime = validate_logo(logo_file)

    company_id = execute(
        """
        INSERT INTO companies(
            name, industry, country,
            logo_blob, logo_mime, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            company_name.strip(),
            industry.strip(),
            country.strip(),
            logo_blob,
            logo_mime,
            now_iso(),
        ),
    )

    try:
        user_id = create_user(
            email=email,
            password=password,
            full_name=full_name,
            account_type="COMPANY",
            company_id=company_id,
            role="ADMIN",
            permissions=ROLE_DEFAULTS["ADMIN"],
        )
    except Exception:
        execute("DELETE FROM companies WHERE id = ?", (company_id,))
        raise

    log_event(
        company_id,
        user_id,
        "REGISTER_COMPANY",
        "company",
        company_id,
        {"company_name": company_name},
    )

    return company_id


def register_candidate(
    full_name: str,
    email: str,
    password: str,
    phone: str = "",
    dni: str = "",
    city: str = "",
) -> int:
    user_id = create_user(
        email=email,
        password=password,
        full_name=full_name,
        account_type="CANDIDATE",
    )

    candidate_id = execute(
        """
        INSERT INTO candidates(
            user_id, phone, dni, city, created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            phone.strip(),
            dni.strip(),
            city.strip(),
            now_iso(),
        ),
    )

    log_event(
        None,
        user_id,
        "REGISTER_CANDIDATE",
        "candidate",
        candidate_id,
        {"email": normalize_email(email)},
    )

    return candidate_id


def authenticate(email: str, password: str) -> dict | None:
    user = fetch_one(
        "SELECT * FROM users WHERE email = ? AND active = 1",
        (normalize_email(email),),
    )

    if not user:
        return None

    if not verify_password(
        password,
        user["password_hash"],
        user["password_salt"],
    ):
        return None

    try:
        user["permissions"] = json.loads(
            user.get("permissions_json") or "[]"
        )
    except json.JSONDecodeError:
        user["permissions"] = []

    return user


def current_user() -> dict | None:
    return st.session_state.get("auth_user")


def refresh_user(user_id: int) -> dict | None:
    user = fetch_one(
        "SELECT * FROM users WHERE id = ? AND active = 1",
        (user_id,),
    )

    if not user:
        return None

    try:
        user["permissions"] = json.loads(
            user.get("permissions_json") or "[]"
        )
    except json.JSONDecodeError:
        user["permissions"] = []

    return user


def has_permission(permission: str) -> bool:
    user = current_user()

    if not user or user.get("account_type") != "COMPANY":
        return False

    if user.get("role") == "ADMIN":
        return True

    return permission in user.get("permissions", [])


def logout() -> None:
    st.session_state.pop("auth_user", None)
    st.rerun()


# =========================================================
# UI DE ACCESO
# =========================================================

def render_login() -> None:
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
                    user.get("company_id"),
                    user["id"],
                    "LOGIN",
                    "user",
                    user["id"],
                    {"email": user["email"]},
                )

                st.rerun()


def render_registration() -> None:
    st.subheader("Crear cuenta")

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

            logo_file = st.file_uploader(
                "Logo de la empresa",
                type=["png", "jpg", "jpeg", "webp"],
            )

            st.markdown("#### Usuario administrador")

            full_name = st.text_input("Nombre y apellido")
            email = st.text_input("Correo electrónico")
            password = st.text_input("Contraseña", type="password")
            repeat = st.text_input("Repetir contraseña", type="password")

            submitted = st.form_submit_button(
                "Crear empresa",
                type="primary",
                use_container_width=True,
            )

            if submitted:
                try:
                    if password != repeat:
                        raise ValueError("Las contraseñas no coinciden.")

                    register_company_admin(
                        company_name,
                        industry,
                        country,
                        logo_file,
                        full_name,
                        email,
                        password,
                    )

                    st.success(
                        "Empresa y usuario administrador creados. "
                        "Ya podés iniciar sesión."
                    )
                except Exception as exc:
                    st.error(str(exc))

    else:
        with st.form("register_candidate"):
            full_name = st.text_input("Nombre y apellido")
            email = st.text_input("Correo electrónico")
            password = st.text_input("Contraseña", type="password")
            repeat = st.text_input("Repetir contraseña", type="password")

            c1, c2 = st.columns(2)
            phone = c1.text_input("Teléfono")
            dni = c2.text_input("DNI")

            city = st.text_input("Ciudad")

            consent = st.checkbox(
                "Acepto el tratamiento de mis datos para gestionar "
                "postulaciones. Los datos administrativos no se usarán "
                "para puntuar ni rankear."
            )

            submitted = st.form_submit_button(
                "Crear cuenta",
                type="primary",
                use_container_width=True,
            )

            if submitted:
                try:
                    if password != repeat:
                        raise ValueError("Las contraseñas no coinciden.")
                    if not consent:
                        raise ValueError(
                            "Tenés que aceptar el consentimiento."
                        )

                    register_candidate(
                        full_name,
                        email,
                        password,
                        phone,
                        dni,
                        city,
                    )

                    st.success("Cuenta creada. Ya podés iniciar sesión.")
                except Exception as exc:
                    st.error(str(exc))


# =========================================================
# EMPRESA: ENCABEZADO Y CONFIGURACIÓN
# =========================================================

def get_company(company_id: int) -> dict | None:
    return fetch_one(
        "SELECT * FROM companies WHERE id = ?",
        (company_id,),
    )


def render_company_header(company: dict) -> None:
    c1, c2 = st.columns([1, 5])

    with c1:
        if company.get("logo_blob"):
            st.image(company["logo_blob"], width=120)

    with c2:
        st.title(company["name"])
        st.caption(
            f"{company.get('industry') or 'Industria no informada'} · "
            f"{company.get('country') or 'País no informado'}"
        )


def render_company_settings(user: dict, company: dict) -> None:
    st.subheader("Configuración de empresa")

    if not has_permission("manage_company"):
        st.warning("No tenés permiso para modificar la empresa.")
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

        logo_file = st.file_uploader(
            "Reemplazar logo",
            type=["png", "jpg", "jpeg", "webp"],
        )

        submitted = st.form_submit_button(
            "Guardar cambios",
            type="primary",
        )

        if submitted:
            if not name.strip():
                st.error("Ingresá el nombre de la empresa.")
                return

            if logo_file is None:
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
            else:
                logo_blob, logo_mime = validate_logo(logo_file)

                execute(
                    """
                    UPDATE companies
                    SET name = ?, industry = ?, country = ?,
                        logo_blob = ?, logo_mime = ?
                    WHERE id = ?
                    """,
                    (
                        name.strip(),
                        industry.strip(),
                        country.strip(),
                        logo_blob,
                        logo_mime,
                        company["id"],
                    ),
                )

            log_event(
                company["id"],
                user["id"],
                "UPDATE_COMPANY",
                "company",
                company["id"],
                {"name": name},
            )

            st.success("Empresa actualizada.")
            st.rerun()


# =========================================================
# EMPRESA: USUARIOS Y PERMISOS
# =========================================================

def count_active_admins(company_id: int) -> int:
    result = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE company_id = ?
          AND role = 'ADMIN'
          AND active = 1
        """,
        (company_id,),
    )
    return int(result["total"])


def render_user_management(user: dict) -> None:
    st.subheader("Usuarios, roles y permisos")

    if not has_permission("manage_users"):
        st.warning("No tenés permiso para administrar usuarios.")
        return

    with st.expander("Crear usuario interno", expanded=True):
        with st.form("create_internal_user"):
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

            selected_permissions: list[str] = []
            permission_columns = st.columns(2)
            defaults = ROLE_DEFAULTS[role]

            for index, (key, label) in enumerate(PERMISSIONS.items()):
                checked = permission_columns[index % 2].checkbox(
                    label,
                    value=key in defaults,
                    key=f"new_permission_{key}",
                )
                if checked:
                    selected_permissions.append(key)

            submitted = st.form_submit_button(
                "Crear usuario",
                type="primary",
            )

            if submitted:
                try:
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
                        user["company_id"],
                        user["id"],
                        "CREATE_USER",
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

    users = fetch_all(
        """
        SELECT
            id, full_name, email, role,
            permissions_json, active, created_at
        FROM users
        WHERE company_id = ?
        ORDER BY created_at DESC
        """,
        (user["company_id"],),
    )

    if not users:
        st.info("No hay usuarios internos.")
        return

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
                "Activo": "Sí" if row["active"] else "No",
                "Permisos": ", ".join(
                    PERMISSIONS.get(item, item)
                    for item in permissions
                ),
            }
        )

    st.dataframe(
        pd.DataFrame(display_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Editar accesos")

    options = {
        f"{row['full_name']} — {row['email']}": row
        for row in users
    }

    selected_label = st.selectbox(
        "Usuario",
        list(options.keys()),
    )
    selected_user = options[selected_label]

    try:
        current_permissions = json.loads(
            selected_user.get("permissions_json") or "[]"
        )
    except json.JSONDecodeError:
        current_permissions = []

    with st.form("edit_internal_user"):
        role_options = ["ADMIN", "RECRUITER", "VIEWER"]
        role = st.selectbox(
            "Rol",
            role_options,
            index=role_options.index(
                selected_user.get("role") or "VIEWER"
            ),
        )

        active = st.checkbox(
            "Usuario activo",
            value=bool(selected_user["active"]),
        )

        updated_permissions: list[str] = []
        permission_columns = st.columns(2)

        for index, (key, label) in enumerate(PERMISSIONS.items()):
            checked = permission_columns[index % 2].checkbox(
                label,
                value=key in current_permissions,
                key=f"edit_permission_{selected_user['id']}_{key}",
            )
            if checked:
                updated_permissions.append(key)

        reset_password = st.text_input(
            "Nueva contraseña (opcional)",
            type="password",
            help="Dejá el campo vacío para conservar la contraseña actual.",
        )

        submitted = st.form_submit_button(
            "Guardar accesos",
            type="primary",
        )

        if submitted:
            if selected_user["id"] == user["id"] and not active:
                st.error("No podés desactivar tu propia cuenta.")
                return

            if (
                selected_user.get("role") == "ADMIN"
                and role != "ADMIN"
                and bool(selected_user["active"])
                and count_active_admins(user["company_id"]) <= 1
            ):
                st.error(
                    "La empresa debe conservar al menos un administrador activo."
                )
                return

            if (
                selected_user.get("role") == "ADMIN"
                and not active
                and count_active_admins(user["company_id"]) <= 1
            ):
                st.error(
                    "La empresa debe conservar al menos un administrador activo."
                )
                return

            execute(
                """
                UPDATE users
                SET role = ?, permissions_json = ?, active = ?
                WHERE id = ? AND company_id = ?
                """,
                (
                    role,
                    json.dumps(
                        updated_permissions,
                        ensure_ascii=False,
                    ),
                    int(active),
                    selected_user["id"],
                    user["company_id"],
                ),
            )

            if reset_password.strip():
                password_error = validate_password(reset_password)
                if password_error:
                    st.error(password_error)
                    return

                password_hash, salt = hash_password(reset_password)

                execute(
                    """
                    UPDATE users
                    SET password_hash = ?, password_salt = ?
                    WHERE id = ? AND company_id = ?
                    """,
                    (
                        password_hash,
                        salt,
                        selected_user["id"],
                        user["company_id"],
                    ),
                )

            log_event(
                user["company_id"],
                user["id"],
                "UPDATE_USER_ACCESS",
                "user",
                selected_user["id"],
                {
                    "role": role,
                    "active": active,
                    "permissions": updated_permissions,
                    "password_reset": bool(reset_password.strip()),
                },
            )

            st.success("Accesos actualizados.")
            st.rerun()



# =========================================================
# IMPORTACIÓN Y AUTOCOMPLETADO DE BÚSQUEDAS
# =========================================================

JOB_SECTION_ALIASES = {
    "title": [
        "puesto", "título del puesto", "titulo del puesto",
        "posición", "posicion", "cargo", "vacante",
    ],
    "area": ["área", "area", "departamento", "sector"],
    "seniority": ["seniority", "nivel", "jerarquía", "jerarquia"],
    "location": [
        "ubicación", "ubicacion", "localidad",
        "lugar de trabajo", "sede",
    ],
    "work_mode": ["modalidad", "modalidad de trabajo"],
    "contract_type": [
        "tipo de contratación", "tipo de contratacion",
        "contrato", "jornada",
    ],
    "description": [
        "descripción", "descripcion", "objetivo del puesto",
        "misión", "mision", "resumen",
    ],
    "responsibilities": [
        "responsabilidades", "funciones", "tareas",
        "principales tareas",
    ],
    "must_have": [
        "requisitos excluyentes", "requisitos obligatorios",
        "excluyentes", "must have",
    ],
    "desirable": [
        "requisitos deseables", "deseables",
        "se valorará", "se valorara", "nice to have",
    ],
    "competencies": [
        "competencias", "habilidades", "skills",
        "competencias requeridas",
    ],
}


def clean_import_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line)).strip(" \t-•|:")


def extract_pdf_text(raw: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw))
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise ValueError(
            "El PDF no contiene texto extraíble. "
            "Si es un escaneo, convertílo a PDF con texto antes de subirlo."
        )
    return text


def extract_docx_text(raw: bytes) -> str:
    document = Document(io.BytesIO(raw))
    blocks = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            blocks.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(blocks).strip()


def extract_excel_text(raw: bytes) -> str:
    workbook = pd.ExcelFile(io.BytesIO(raw))
    blocks: list[str] = []

    for sheet_name in workbook.sheet_names[:10]:
        frame = pd.read_excel(
            workbook,
            sheet_name=sheet_name,
            header=None,
        ).dropna(how="all")

        blocks.append(f"HOJA: {sheet_name}")

        for row in frame.values.tolist():
            values = [
                clean_import_line(value)
                for value in row
                if pd.notna(value) and clean_import_line(value)
            ]
            if values:
                blocks.append(" | ".join(values))

    return "\n".join(blocks).strip()


def extract_job_file_text(uploaded_file) -> str:
    extension = Path(uploaded_file.name).suffix.lower()
    raw = uploaded_file.getvalue()

    if extension == ".pdf":
        return extract_pdf_text(raw)
    if extension == ".docx":
        return extract_docx_text(raw)
    if extension in {".xlsx", ".xls"}:
        return extract_excel_text(raw)

    raise ValueError("Usá un archivo PDF, DOCX, XLSX o XLS.")


def parse_job_text(text: str) -> dict[str, str]:
    result = {field: "" for field in JOB_SECTION_ALIASES}
    section_values = {field: [] for field in JOB_SECTION_ALIASES}
    current_section: str | None = None

    lines = [
        clean_import_line(line)
        for line in text.splitlines()
        if clean_import_line(line)
    ]

    for line in lines:
        detected_field = None
        inline_value = ""

        for field, aliases in JOB_SECTION_ALIASES.items():
            for alias in aliases:
                match = re.match(
                    rf"^{re.escape(alias)}\s*[:\-]\s*(.*)$",
                    line,
                    flags=re.IGNORECASE,
                )
                if match:
                    detected_field = field
                    inline_value = match.group(1).strip()
                    break

                if line.lower() == alias.lower():
                    detected_field = field
                    break

            if detected_field:
                break

        if detected_field:
            current_section = detected_field
            if inline_value:
                section_values[detected_field].append(inline_value)
            continue

        if current_section:
            section_values[current_section].append(line)

    for field, values in section_values.items():
        result[field] = "\n".join(values).strip()

    full_lower = text.lower()

    if not result["title"] and lines:
        result["title"] = next(
            (
                line for line in lines[:15]
                if 2 <= len(line.split()) <= 12 and len(line) <= 120
            ),
            "",
        )

    if not result["seniority"]:
        seniority_map = [
            ("Pasantía", ["pasantía", "pasantia", "internship"]),
            ("Junior", [" junior", "jr.", " jr "]),
            ("Semi Senior", ["semi senior", "semisenior", "ssr"]),
            ("Senior", [" senior", "sr.", " sr "]),
            ("Liderazgo", ["supervisor", "jefatura", "líder", "lider"]),
            ("Dirección", ["dirección", "direccion", "director", "gerencia"]),
        ]
        padded = f" {full_lower} "
        for label, keywords in seniority_map:
            if any(keyword in padded for keyword in keywords):
                result["seniority"] = label
                break

    if not result["work_mode"]:
        for label, keywords in {
            "Presencial": ["presencial"],
            "Híbrido": ["híbrido", "hibrido"],
            "Remoto": ["remoto", "home office", "teletrabajo"],
        }.items():
            if any(keyword in full_lower for keyword in keywords):
                result["work_mode"] = label
                break

    if not result["description"]:
        result["description"] = text[:3000].strip()

    return result


def save_new_job(
    user: dict,
    values: dict,
    source_filename: str = "",
) -> int:
    return execute(
        """
        INSERT INTO jobs(
            company_id, title, area, seniority,
            location, work_mode, contract_type,
            description, responsibilities, must_have,
            desirable, competencies, status,
            source_filename, created_by, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user["company_id"],
            values["title"].strip(),
            values["area"].strip(),
            values["seniority"],
            values["location"].strip(),
            values["work_mode"],
            values["contract_type"].strip(),
            values["description"].strip(),
            values["responsibilities"].strip(),
            values["must_have"].strip(),
            values["desirable"].strip(),
            values["competencies"].strip(),
            values.get("status", "ABIERTA"),
            source_filename,
            user["id"],
            now_iso(),
            now_iso(),
        ),
    )



def update_job_record(
    user: dict,
    job_id: int,
    values: dict,
) -> None:
    """
    Confirma primero los cambios de la búsqueda.
    La auditoría se intenta después y no puede revertirlos.
    """
    conn = get_connection()

    try:
        cursor = conn.execute(
            """
            UPDATE jobs
            SET title = ?,
                area = ?,
                seniority = ?,
                location = ?,
                work_mode = ?,
                contract_type = ?,
                description = ?,
                responsibilities = ?,
                must_have = ?,
                desirable = ?,
                competencies = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?
              AND company_id = ?
            """,
            (
                values["title"].strip(),
                values["area"].strip(),
                values["seniority"],
                values["location"].strip(),
                values["work_mode"],
                values["contract_type"].strip(),
                values["description"].strip(),
                values["responsibilities"].strip(),
                values["must_have"].strip(),
                values["desirable"].strip(),
                values["competencies"].strip(),
                values["status"],
                now_iso(),
                job_id,
                user["company_id"],
            ),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            raise ValueError(
                "La búsqueda no existe o no pertenece "
                "a la empresa del usuario."
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    log_event(
        user["company_id"],
        user["id"],
        "UPDATE_JOB",
        "job",
        job_id,
        {
            "title": values["title"],
            "status": values["status"],
        },
    )


def render_job_fields(
    prefix: str,
    initial: dict | None = None,
    include_status: bool = False,
) -> dict:
    initial = initial or {}

    seniority_options = [
        "Pasantía", "Junior", "Semi Senior",
        "Senior", "Liderazgo", "Dirección",
        "No especificado",
    ]
    work_mode_options = [
        "Presencial", "Híbrido", "Remoto", "No especificado"
    ]

    initial_seniority = initial.get("seniority") or "No especificado"
    if initial_seniority not in seniority_options:
        initial_seniority = "No especificado"

    initial_mode = initial.get("work_mode") or "No especificado"
    if initial_mode not in work_mode_options:
        initial_mode = "No especificado"

    title = st.text_input(
        "Puesto",
        value=initial.get("title") or "",
        key=f"{prefix}_title",
    )

    c1, c2 = st.columns(2)
    area = c1.text_input(
        "Área",
        value=initial.get("area") or "",
        key=f"{prefix}_area",
    )
    seniority = c2.selectbox(
        "Seniority",
        seniority_options,
        index=seniority_options.index(initial_seniority),
        key=f"{prefix}_seniority",
    )

    c3, c4 = st.columns(2)
    location = c3.text_input(
        "Ubicación",
        value=initial.get("location") or "",
        key=f"{prefix}_location",
    )
    work_mode = c4.selectbox(
        "Modalidad",
        work_mode_options,
        index=work_mode_options.index(initial_mode),
        key=f"{prefix}_work_mode",
    )

    contract_type = st.text_input(
        "Tipo de contratación / jornada",
        value=initial.get("contract_type") or "",
        key=f"{prefix}_contract_type",
    )

    description = st.text_area(
        "Descripción del puesto",
        value=initial.get("description") or "",
        height=160,
        key=f"{prefix}_description",
    )
    responsibilities = st.text_area(
        "Responsabilidades y tareas",
        value=initial.get("responsibilities") or "",
        height=130,
        key=f"{prefix}_responsibilities",
    )
    must_have = st.text_area(
        "Requisitos excluyentes",
        value=initial.get("must_have") or "",
        height=120,
        key=f"{prefix}_must_have",
    )
    desirable = st.text_area(
        "Requisitos deseables",
        value=initial.get("desirable") or "",
        height=120,
        key=f"{prefix}_desirable",
    )
    competencies = st.text_area(
        "Competencias",
        value=initial.get("competencies") or "",
        height=110,
        key=f"{prefix}_competencies",
    )

    status = initial.get("status") or "ABIERTA"
    if include_status:
        status_options = ["ABIERTA", "PAUSADA", "CERRADA"]
        if status not in status_options:
            status = "ABIERTA"
        status = st.selectbox(
            "Estado",
            status_options,
            index=status_options.index(status),
            key=f"{prefix}_status",
        )

    return {
        "title": title,
        "area": area,
        "seniority": seniority,
        "location": location,
        "work_mode": work_mode,
        "contract_type": contract_type,
        "description": description,
        "responsibilities": responsibilities,
        "must_have": must_have,
        "desirable": desirable,
        "competencies": competencies,
        "status": status,
    }



# =========================================================
# EMPRESA: BÚSQUEDAS Y POSTULACIONES
# =========================================================

def render_jobs(user: dict) -> None:
    st.subheader("Búsquedas laborales")

    create_tab, manage_tab = st.tabs(
        ["Crear o importar", "Administrar búsquedas"]
    )

    with create_tab:
        if not has_permission("manage_jobs"):
            st.warning("No tenés permiso para crear búsquedas.")
        else:
            mode = st.radio(
                "Método de carga",
                ["Importar archivo", "Crear manualmente"],
                horizontal=True,
                key="job_creation_mode",
            )

            if mode == "Importar archivo":
                uploaded_file = st.file_uploader(
                    "Subí el requerimiento en Excel, PDF o Word",
                    type=["xlsx", "xls", "pdf", "docx"],
                    key="job_import_file",
                )

                st.caption(
                    "El sistema extrae texto del archivo y propone valores. "
                    "Siempre podés revisar y modificar los campos antes de guardar."
                )

                if uploaded_file is not None and st.button(
                    "Analizar y autocompletar",
                    type="primary",
                    key="analyze_job_file",
                ):
                    try:
                        extracted_text = extract_job_file_text(uploaded_file)
                        parsed = parse_job_text(extracted_text)
                        st.session_state["job_import_parsed"] = parsed
                        st.session_state["job_import_filename"] = uploaded_file.name
                        st.session_state["job_import_preview"] = extracted_text[:5000]
                        st.success(
                            "Archivo analizado. Revisá y editá la información."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"No se pudo analizar el archivo: {exc}")

                parsed = st.session_state.get("job_import_parsed")
                if parsed:
                    with st.expander("Texto detectado en el archivo"):
                        st.text(
                            st.session_state.get("job_import_preview", "")
                        )

                    with st.form("imported_job_form"):
                        values = render_job_fields(
                            "imported_job",
                            initial=parsed,
                        )
                        submitted = st.form_submit_button(
                            "Guardar búsqueda",
                            type="primary",
                            use_container_width=True,
                        )

                        if submitted:
                            if not values["title"].strip():
                                st.error("Ingresá el nombre del puesto.")
                            else:
                                try:
                                    job_id = save_new_job(
                                        user,
                                        values,
                                        st.session_state.get(
                                            "job_import_filename",
                                            "",
                                        ),
                                    )
                                    log_event(
                                        user["company_id"],
                                        user["id"],
                                        "CREATE_JOB_FROM_FILE",
                                        "job",
                                        job_id,
                                        {
                                            "title": values["title"],
                                            "source_filename": st.session_state.get(
                                                "job_import_filename",
                                                "",
                                            ),
                                        },
                                    )
                                    for key in [
                                        "job_import_parsed",
                                        "job_import_filename",
                                        "job_import_preview",
                                    ]:
                                        st.session_state.pop(key, None)
                                    st.success(
                                        "Búsqueda importada y guardada."
                                    )
                                    st.rerun()
                                except Exception as exc:
                                    st.error(
                                        f"No se pudo guardar la búsqueda: {exc}"
                                    )

            else:
                with st.form("manual_job_form"):
                    values = render_job_fields("manual_job")
                    submitted = st.form_submit_button(
                        "Guardar búsqueda",
                        type="primary",
                        use_container_width=True,
                    )

                    if submitted:
                        if not values["title"].strip():
                            st.error("Ingresá el nombre del puesto.")
                        else:
                            try:
                                job_id = save_new_job(user, values)
                                log_event(
                                    user["company_id"],
                                    user["id"],
                                    "CREATE_JOB",
                                    "job",
                                    job_id,
                                    {"title": values["title"]},
                                )
                                st.success(
                                    "Búsqueda creada correctamente."
                                )
                                st.rerun()
                            except Exception as exc:
                                st.error(
                                    f"No se pudo guardar la búsqueda: {exc}"
                                )

    with manage_tab:
        jobs = fetch_all(
            """
            SELECT *
            FROM jobs
            WHERE company_id = ?
            ORDER BY created_at DESC
            """,
            (user["company_id"],),
        )

        if not jobs:
            st.info("Todavía no hay búsquedas.")
            return

        summary_rows = [
            {
                "ID": job["id"],
                "Puesto": job["title"],
                "Área": job.get("area") or "",
                "Seniority": job.get("seniority") or "",
                "Modalidad": job.get("work_mode") or "",
                "Estado": job.get("status") or "ABIERTA",
                "Archivo de origen": job.get("source_filename") or "",
                "Creada": job.get("created_at") or "",
            }
            for job in jobs
        ]

        st.dataframe(
            pd.DataFrame(summary_rows),
            use_container_width=True,
            hide_index=True,
        )

        if not has_permission("manage_jobs"):
            st.info(
                "Tenés acceso de consulta, pero no permiso para editar."
            )
            return

        job_options = {
            f"#{job['id']} — {job['title']}": job
            for job in jobs
        }
        selected_label = st.selectbox(
            "Seleccionar búsqueda para editar",
            list(job_options.keys()),
            key="selected_job_edit",
        )
        selected_job = job_options[selected_label]

        with st.form(f"edit_job_form_{selected_job['id']}"):
            edited_values = render_job_fields(
                f"edit_job_{selected_job['id']}",
                initial=selected_job,
                include_status=True,
            )

            submitted = st.form_submit_button(
                "Guardar cambios",
                type="primary",
                use_container_width=True,
            )

            if submitted:
                if not edited_values["title"].strip():
                    st.error("Ingresá el nombre del puesto.")
                else:
                    try:
                        update_job_record(
                            user=user,
                            job_id=selected_job["id"],
                            values=edited_values,
                        )

                        st.session_state[
                            "job_update_success"
                        ] = (
                            "Búsqueda actualizada correctamente."
                        )

                    except sqlite3.Error as exc:
                        st.error(
                            "No se pudo actualizar la búsqueda "
                            "por un error de base de datos."
                        )
                        st.code(str(exc))

                    except Exception as exc:
                        st.error(
                            "No se pudo actualizar la búsqueda."
                        )
                        st.exception(exc)

        if st.session_state.pop(
            "job_update_success",
            None,
        ):
            st.success(
                "Búsqueda actualizada correctamente. "
                "Los cambios quedaron confirmados en la base."
            )
            st.caption(
                f"Corrección activa: versión {APP_VERSION}"
            )




# =========================================================
# CANDIDATOS, CV Y PRESELECCIÓN
# =========================================================

CV_SECTION_ALIASES = {
    "experience_summary": [
        "experiencia",
        "experiencia laboral",
        "experiencia profesional",
        "antecedentes laborales",
        "employment",
        "work experience",
    ],
    "education_summary": [
        "educación",
        "educacion",
        "formación",
        "formacion",
        "estudios",
        "academic background",
        "education",
    ],
    "skills_text": [
        "habilidades",
        "competencias",
        "herramientas",
        "tecnologías",
        "tecnologias",
        "skills",
        "technical skills",
    ],
    "languages_text": [
        "idiomas",
        "languages",
    ],
}

SCORING_STOPWORDS = {
    "para", "como", "con", "los", "las", "una", "uno", "del", "por",
    "que", "se", "de", "en", "y", "o", "al", "el", "la", "un",
    "requisito", "requisitos", "experiencia", "conocimiento",
    "conocimientos", "manejo", "nivel", "años", "anos", "deseable",
    "excluyente", "excluyentes", "competencia", "competencias",
}


def normalize_match_text(value: str) -> str:
    normalized = unicodedata.normalize(
        "NFKD",
        value or "",
    )
    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    without_accents = without_accents.lower()
    without_accents = re.sub(
        r"[^a-z0-9+#.\s-]",
        " ",
        without_accents,
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def validate_cv_file(uploaded_file) -> tuple[bytes, str]:
    if uploaded_file is None:
        raise ValueError("Seleccioná un CV.")

    raw = uploaded_file.getvalue()
    if not raw:
        raise ValueError("El CV está vacío.")

    if len(raw) > MAX_CV_SIZE_BYTES:
        raise ValueError(
            "El CV supera el máximo permitido de 5 MB."
        )

    extension = Path(uploaded_file.name).suffix.lower()
    if extension not in {".pdf", ".docx"}:
        raise ValueError("El CV debe estar en PDF o DOCX.")

    mime_type = (
        uploaded_file.type
        or (
            "application/pdf"
            if extension == ".pdf"
            else "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
    )
    return raw, mime_type


def extract_cv_text(uploaded_file) -> tuple[bytes, str, str]:
    raw, mime_type = validate_cv_file(uploaded_file)
    extension = Path(uploaded_file.name).suffix.lower()

    if extension == ".pdf":
        text = extract_pdf_text(raw)
    else:
        text = extract_docx_text(raw)

    if len(text.strip()) < 30:
        raise ValueError(
            "No se pudo extraer suficiente texto del CV."
        )

    return raw, mime_type, text.strip()


def extract_named_cv_sections(text: str) -> dict[str, str]:
    results = {
        field: ""
        for field in CV_SECTION_ALIASES
    }
    collected = {
        field: []
        for field in CV_SECTION_ALIASES
    }
    current_field = None

    lines = [
        clean_import_line(line)
        for line in text.splitlines()
        if clean_import_line(line)
    ]

    for line in lines:
        normalized_line = normalize_match_text(line)
        detected_field = None
        inline_value = ""

        for field, aliases in CV_SECTION_ALIASES.items():
            for alias in aliases:
                normalized_alias = normalize_match_text(alias)

                if normalized_line == normalized_alias:
                    detected_field = field
                    break

                prefix_pattern = (
                    rf"^{re.escape(normalized_alias)}\s*[:\-]\s*(.*)$"
                )
                match = re.match(
                    prefix_pattern,
                    normalized_line,
                )
                if match:
                    detected_field = field
                    if ":" in line:
                        inline_value = line.split(":", 1)[1].strip()
                    elif "-" in line:
                        inline_value = line.split("-", 1)[1].strip()
                    break

            if detected_field:
                break

        if detected_field:
            current_field = detected_field
            if inline_value:
                collected[detected_field].append(inline_value)
            continue

        if current_field:
            collected[current_field].append(line)

    for field, values in collected.items():
        results[field] = "\n".join(values[:30]).strip()

    return results


def extract_candidate_name(
    text: str,
    fallback_filename: str,
) -> str:
    lines = [
        clean_import_line(line)
        for line in text.splitlines()
        if clean_import_line(line)
    ]

    for line in lines[:12]:
        if "@" in line:
            continue
        if re.search(r"\d{6,}", line):
            continue
        if normalize_match_text(line) in {
            "curriculum vitae",
            "curriculum",
            "cv",
            "resume",
        }:
            continue

        words = line.split()
        if 2 <= len(words) <= 6 and len(line) <= 80:
            return line.title()

    fallback = Path(fallback_filename).stem
    fallback = re.sub(r"[_\-]+", " ", fallback)
    fallback = re.sub(
        r"\b(cv|curriculum|vitae|resume)\b",
        " ",
        fallback,
        flags=re.I,
    )
    fallback = re.sub(r"\s+", " ", fallback).strip()
    return fallback.title() or "Candidato sin identificar"


def parse_cv_text(
    text: str,
    fallback_filename: str,
) -> dict[str, str]:
    email_match = re.search(
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        text,
    )
    phone_match = re.search(
        r"(?:\+?\d[\d\s().-]{7,}\d)",
        text,
    )

    sections = extract_named_cv_sections(text)

    lines = [
        clean_import_line(line)
        for line in text.splitlines()
        if clean_import_line(line)
    ]

    headline_lines = []
    for line in lines[:18]:
        if "@" in line:
            continue
        if phone_match and phone_match.group(0) in line:
            continue
        if line.lower() == extract_candidate_name(
            text,
            fallback_filename,
        ).lower():
            continue
        headline_lines.append(line)
        if len(headline_lines) >= 3:
            break

    return {
        "full_name": extract_candidate_name(
            text,
            fallback_filename,
        ),
        "email": (
            normalize_email(email_match.group(0))
            if email_match
            else ""
        ),
        "phone": (
            re.sub(r"\s+", " ", phone_match.group(0)).strip()
            if phone_match
            else ""
        ),
        "headline": " · ".join(headline_lines)[:500],
        "education_summary": sections["education_summary"][:5000],
        "experience_summary": sections["experience_summary"][:7000],
        "skills_text": sections["skills_text"][:4000],
        "languages_text": sections["languages_text"][:2000],
    }


def extract_scoring_terms(value: str) -> list[str]:
    if not value:
        return []

    segments = re.split(
        r"[\n;•|]+",
        value,
    )
    terms: list[str] = []

    for segment in segments:
        for part in segment.split(","):
            cleaned = normalize_match_text(part)
            cleaned = re.sub(
                r"^(requisitos?|excluyentes?|deseables?|"
                r"competencias?|habilidades?)\s*[:\-]?\s*",
                "",
                cleaned,
            ).strip()

            if not cleaned:
                continue

            words = [
                word
                for word in cleaned.split()
                if len(word) >= 3
                and word not in SCORING_STOPWORDS
            ]

            if not words:
                continue

            if len(words) <= 7:
                terms.append(" ".join(words))
            else:
                terms.extend(words)

    unique_terms = []
    seen = set()

    for term in terms:
        if term not in seen:
            unique_terms.append(term)
            seen.add(term)

    return unique_terms[:50]


def score_dimension(
    label: str,
    terms: list[str],
    cv_text_normalized: str,
    weight: float,
) -> dict:
    matched = [
        term
        for term in terms
        if term in cv_text_normalized
    ]
    missing = [
        term
        for term in terms
        if term not in cv_text_normalized
    ]

    coverage = (
        len(matched) / len(terms)
        if terms
        else None
    )

    return {
        "label": label,
        "weight": weight,
        "criteria_count": len(terms),
        "matched": matched,
        "missing": missing,
        "coverage": coverage,
    }


def calculate_match_score(
    job: dict,
    cv_text: str,
) -> dict:
    cv_normalized = normalize_match_text(cv_text)

    dimensions = [
        score_dimension(
            "Requisitos excluyentes",
            extract_scoring_terms(job.get("must_have") or ""),
            cv_normalized,
            50,
        ),
        score_dimension(
            "Requisitos deseables",
            extract_scoring_terms(job.get("desirable") or ""),
            cv_normalized,
            20,
        ),
        score_dimension(
            "Competencias",
            extract_scoring_terms(job.get("competencies") or ""),
            cv_normalized,
            15,
        ),
        score_dimension(
            "Contexto del puesto",
            extract_scoring_terms(
                " | ".join(
                    [
                        job.get("title") or "",
                        job.get("area") or "",
                        job.get("seniority") or "",
                    ]
                )
            ),
            cv_normalized,
            15,
        ),
    ]

    active_dimensions = [
        dimension
        for dimension in dimensions
        if dimension["criteria_count"] > 0
    ]

    if not active_dimensions:
        return {
            "total": None,
            "recommendation": "REVISIÓN MANUAL",
            "summary": (
                "La búsqueda no tiene criterios suficientes para "
                "calcular una coincidencia."
            ),
            "dimensions": dimensions,
            "notice": SCORING_NOTICE,
        }

    active_weight = sum(
        dimension["weight"]
        for dimension in active_dimensions
    )

    weighted_points = sum(
        dimension["weight"]
        * float(dimension["coverage"])
        for dimension in active_dimensions
    )

    total = round(
        (weighted_points / active_weight) * 100,
        1,
    )

    for dimension in dimensions:
        if dimension["coverage"] is None:
            dimension["points"] = None
        else:
            normalized_weight = (
                dimension["weight"] / active_weight
            ) * 100
            dimension["points"] = round(
                normalized_weight
                * float(dimension["coverage"]),
                1,
            )

    if total >= 75:
        recommendation = "AVANZA"
    elif total >= 50:
        recommendation = "REVISAR"
    else:
        recommendation = "BAJA COINCIDENCIA"

    matched_count = sum(
        len(dimension["matched"])
        for dimension in active_dimensions
    )
    criteria_count = sum(
        dimension["criteria_count"]
        for dimension in active_dimensions
    )

    return {
        "total": total,
        "recommendation": recommendation,
        "summary": (
            f"Coincide con {matched_count} de {criteria_count} "
            "criterios detectados en la búsqueda."
        ),
        "dimensions": dimensions,
        "notice": SCORING_NOTICE,
    }


def get_latest_cv(candidate_id: int) -> dict | None:
    return fetch_one(
        """
        SELECT *
        FROM candidate_documents
        WHERE candidate_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (candidate_id,),
    )


def save_candidate_document(
    candidate_id: int,
    filename: str,
    mime_type: str,
    raw: bytes,
    extracted_text: str,
    parsed: dict,
    uploaded_by: int | None,
) -> int:
    return execute(
        """
        INSERT INTO candidate_documents(
            candidate_id,
            filename,
            mime_type,
            content_blob,
            extracted_text,
            parsed_json,
            uploaded_by,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            filename,
            mime_type,
            raw,
            extracted_text,
            json.dumps(parsed, ensure_ascii=False),
            uploaded_by,
            now_iso(),
        ),
    )


def update_candidate_profile(
    candidate_id: int,
    values: dict,
) -> None:
    execute(
        """
        UPDATE candidates
        SET phone = ?,
            city = ?,
            headline = ?,
            education_summary = ?,
            experience_summary = ?,
            skills_text = ?,
            languages_text = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            values.get("phone", "").strip(),
            values.get("city", "").strip(),
            values.get("headline", "").strip(),
            values.get("education_summary", "").strip(),
            values.get("experience_summary", "").strip(),
            values.get("skills_text", "").strip(),
            values.get("languages_text", "").strip(),
            now_iso(),
            candidate_id,
        ),
    )


def score_application(application_id: int) -> dict:
    application = fetch_one(
        """
        SELECT
            applications.id,
            applications.candidate_id,
            applications.job_id,
            jobs.*
        FROM applications
        JOIN jobs
            ON jobs.id = applications.job_id
        WHERE applications.id = ?
        """,
        (application_id,),
    )

    if not application:
        raise ValueError("No se encontró la postulación.")

    latest_cv = get_latest_cv(application["candidate_id"])

    if not latest_cv or not latest_cv.get("extracted_text"):
        result = {
            "total": None,
            "recommendation": "PENDIENTE DE CV",
            "summary": (
                "No hay un CV con texto disponible para analizar."
            ),
            "dimensions": [],
            "notice": SCORING_NOTICE,
        }
    else:
        result = calculate_match_score(
            application,
            latest_cv["extracted_text"],
        )

    execute(
        """
        UPDATE applications
        SET score_total = ?,
            score_breakdown_json = ?,
            screening_recommendation = ?,
            screening_summary = ?,
            screened_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            result["total"],
            json.dumps(result, ensure_ascii=False),
            result["recommendation"],
            result["summary"],
            now_iso(),
            now_iso(),
            application_id,
        ),
    )

    return result


def rescore_candidate_applications(candidate_id: int) -> None:
    application_rows = fetch_all(
        """
        SELECT id
        FROM applications
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    )

    for application_row in application_rows:
        score_application(application_row["id"])


def get_or_create_candidate_from_cv(
    parsed: dict,
    raw: bytes,
    mime_type: str,
    extracted_text: str,
    filename: str,
    uploaded_by: int,
) -> tuple[int, int]:
    email = normalize_email(parsed.get("email") or "")
    user = None

    if email:
        existing_user = fetch_one(
            "SELECT * FROM users WHERE email = ?",
            (email,),
        )
        if (
            existing_user
            and existing_user.get("account_type") == "CANDIDATE"
        ):
            user = existing_user

    if not user:
        digest = hashlib.sha256(raw).hexdigest()[:16]
        synthetic_email = (
            email
            if email and not fetch_one(
                "SELECT id FROM users WHERE email = ?",
                (email,),
            )
            else f"cv-{digest}@alba.local"
        )

        random_password = secrets.token_urlsafe(24)
        password_hash, salt = hash_password(random_password)

        user_id = execute(
            """
            INSERT INTO users(
                email,
                password_hash,
                password_salt,
                full_name,
                account_type,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, 'CANDIDATE', 0, ?)
            """,
            (
                synthetic_email,
                password_hash,
                salt,
                parsed.get("full_name")
                or "Candidato sin identificar",
                now_iso(),
            ),
        )

        user = fetch_one(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        )

    candidate = fetch_one(
        "SELECT * FROM candidates WHERE user_id = ?",
        (user["id"],),
    )

    if not candidate:
        candidate_id = execute(
            """
            INSERT INTO candidates(
                user_id,
                phone,
                city,
                source,
                headline,
                education_summary,
                experience_summary,
                skills_text,
                languages_text,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 'CARGA_RRHH', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                parsed.get("phone", ""),
                "",
                parsed.get("headline", ""),
                parsed.get("education_summary", ""),
                parsed.get("experience_summary", ""),
                parsed.get("skills_text", ""),
                parsed.get("languages_text", ""),
                now_iso(),
                now_iso(),
            ),
        )
    else:
        candidate_id = candidate["id"]

        execute(
            """
            UPDATE candidates
            SET phone = CASE
                    WHEN ? <> '' THEN ?
                    ELSE phone
                END,
                headline = ?,
                education_summary = ?,
                experience_summary = ?,
                skills_text = ?,
                languages_text = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                parsed.get("phone", ""),
                parsed.get("phone", ""),
                parsed.get("headline", ""),
                parsed.get("education_summary", ""),
                parsed.get("experience_summary", ""),
                parsed.get("skills_text", ""),
                parsed.get("languages_text", ""),
                now_iso(),
                candidate_id,
            ),
        )

    document_id = save_candidate_document(
        candidate_id,
        filename,
        mime_type,
        raw,
        extracted_text,
        parsed,
        uploaded_by,
    )

    return candidate_id, document_id


def create_or_refresh_application(
    candidate_id: int,
    job_id: int,
) -> tuple[int, dict]:
    existing = fetch_one(
        """
        SELECT id
        FROM applications
        WHERE candidate_id = ?
          AND job_id = ?
        """,
        (candidate_id, job_id),
    )

    if existing:
        application_id = existing["id"]
        execute(
            """
            UPDATE applications
            SET updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), application_id),
        )
    else:
        application_id = execute(
            """
            INSERT INTO applications(
                candidate_id,
                job_id,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, 'RECIBIDA', ?, ?)
            """,
            (
                candidate_id,
                job_id,
                now_iso(),
                now_iso(),
            ),
        )

    result = score_application(application_id)
    return application_id, result


def render_score_report(report: dict) -> None:
    total = report.get("total")
    recommendation = report.get(
        "recommendation",
        "REVISIÓN MANUAL",
    )

    c1, c2 = st.columns(2)
    c1.metric(
        "Coincidencia",
        "Pendiente"
        if total is None
        else f"{float(total):.1f}%",
    )
    c2.metric("Recomendación", recommendation)

    st.write(report.get("summary") or "")
    st.caption(report.get("notice") or SCORING_NOTICE)

    for dimension in report.get("dimensions", []):
        if not dimension.get("criteria_count"):
            continue

        with st.expander(
            f"{dimension['label']} · "
            f"{round(float(dimension.get('coverage') or 0) * 100)}%",
        ):
            st.write(
                f"**Puntos:** "
                f"{dimension.get('points', 0)}"
            )
            st.write(
                "**Coincidencias:** "
                + (
                    ", ".join(dimension.get("matched") or [])
                    or "Ninguna"
                )
            )
            st.write(
                "**Brechas:** "
                + (
                    ", ".join(dimension.get("missing") or [])
                    or "Ninguna"
                )
            )


def render_bulk_cv_upload(user: dict) -> None:
    st.markdown("### Carga masiva de CV")

    if not has_permission("manage_cv_pool"):
        st.warning(
            "No tenés permiso para cargar y analizar CV."
        )
        return

    jobs = fetch_all(
        """
        SELECT id, title, status
        FROM jobs
        WHERE company_id = ?
          AND status <> 'CERRADA'
        ORDER BY created_at DESC
        """,
        (user["company_id"],),
    )

    if not jobs:
        st.info(
            "Primero creá una búsqueda abierta o pausada."
        )
        return

    job_options = {
        f"{job['title']} · {job['status']}": job["id"]
        for job in jobs
    }

    selected_job_label = st.selectbox(
        "Búsqueda a la que se asignarán los CV",
        list(job_options.keys()),
        key="bulk_cv_job",
    )
    selected_job_id = job_options[selected_job_label]

    uploaded_files = st.file_uploader(
        "Subí hasta 50 CV en PDF o DOCX",
        type=["pdf", "docx"],
        accept_multiple_files=True,
        key="bulk_cv_files",
    )

    st.caption(
        "Cada archivo puede pesar hasta 5 MB. "
        + SCORING_NOTICE
    )

    if st.button(
        "Procesar CV y generar ranking",
        type="primary",
        key="process_bulk_cv",
    ):
        if not uploaded_files:
            st.error("Seleccioná al menos un CV.")
            return

        if len(uploaded_files) > MAX_CV_BATCH:
            st.error(
                f"El máximo por lote es {MAX_CV_BATCH} CV."
            )
            return

        results = []

        for uploaded_file in uploaded_files:
            try:
                raw, mime_type, text = extract_cv_text(
                    uploaded_file
                )
                parsed = parse_cv_text(
                    text,
                    uploaded_file.name,
                )
                candidate_id, document_id = (
                    get_or_create_candidate_from_cv(
                        parsed,
                        raw,
                        mime_type,
                        text,
                        uploaded_file.name,
                        user["id"],
                    )
                )
                application_id, score_result = (
                    create_or_refresh_application(
                        candidate_id,
                        selected_job_id,
                    )
                )

                results.append(
                    {
                        "Archivo": uploaded_file.name,
                        "Candidato": parsed.get("full_name"),
                        "Email detectado": (
                            parsed.get("email")
                            or "No detectado"
                        ),
                        "Puntaje": score_result.get("total"),
                        "Recomendación": score_result.get(
                            "recommendation"
                        ),
                        "Estado": "Procesado",
                    }
                )

                log_event(
                    user["company_id"],
                    user["id"],
                    "UPLOAD_CV",
                    "candidate_document",
                    document_id,
                    {
                        "application_id": application_id,
                        "job_id": selected_job_id,
                        "filename": uploaded_file.name,
                    },
                )

            except Exception as exc:
                results.append(
                    {
                        "Archivo": uploaded_file.name,
                        "Candidato": "",
                        "Email detectado": "",
                        "Puntaje": None,
                        "Recomendación": "",
                        "Estado": f"Error: {exc}",
                    }
                )

        st.session_state["bulk_cv_results"] = results
        st.success("El lote terminó de procesarse.")

    results = st.session_state.get(
        "bulk_cv_results",
        [],
    )
    if results:
        st.dataframe(
            pd.DataFrame(results),
            use_container_width=True,
            hide_index=True,
        )


def render_candidate_profile(
    user: dict,
    candidate: dict,
) -> None:
    st.subheader("Mi perfil y CV")

    latest_cv = get_latest_cv(candidate["id"])

    uploaded_file = st.file_uploader(
        "Subir o reemplazar CV",
        type=["pdf", "docx"],
        key=f"candidate_cv_{candidate['id']}",
    )

    if st.button(
        "Analizar CV",
        key=f"analyze_candidate_cv_{candidate['id']}",
    ):
        if uploaded_file is None:
            st.error("Seleccioná un CV.")
        else:
            try:
                raw, mime_type, text = extract_cv_text(
                    uploaded_file
                )
                parsed = parse_cv_text(
                    text,
                    uploaded_file.name,
                )

                st.session_state[
                    f"candidate_cv_draft_{candidate['id']}"
                ] = {
                    "filename": uploaded_file.name,
                    "mime_type": mime_type,
                    "raw": raw,
                    "text": text,
                    "parsed": parsed,
                }

                st.success(
                    "CV analizado. Revisá los datos y guardá el perfil."
                )
            except Exception as exc:
                st.error(str(exc))

    draft = st.session_state.get(
        f"candidate_cv_draft_{candidate['id']}",
        {},
    )
    parsed = draft.get("parsed", {})

    with st.form(
        f"candidate_profile_form_{candidate['id']}"
    ):
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

        c1, c2 = st.columns(2)
        phone = c1.text_input(
            "Teléfono",
            value=(
                parsed.get("phone")
                or candidate.get("phone")
                or ""
            ),
        )
        city = c2.text_input(
            "Ciudad",
            value=candidate.get("city") or "",
        )

        headline = st.text_area(
            "Perfil profesional",
            value=(
                parsed.get("headline")
                or candidate.get("headline")
                or ""
            ),
            height=100,
        )
        education_summary = st.text_area(
            "Formación",
            value=(
                parsed.get("education_summary")
                or candidate.get("education_summary")
                or ""
            ),
            height=130,
        )
        experience_summary = st.text_area(
            "Experiencia",
            value=(
                parsed.get("experience_summary")
                or candidate.get("experience_summary")
                or ""
            ),
            height=170,
        )
        skills_text = st.text_area(
            "Habilidades y herramientas",
            value=(
                parsed.get("skills_text")
                or candidate.get("skills_text")
                or ""
            ),
            height=120,
        )
        languages_text = st.text_area(
            "Idiomas",
            value=(
                parsed.get("languages_text")
                or candidate.get("languages_text")
                or ""
            ),
            height=80,
        )

        submitted = st.form_submit_button(
            "Guardar perfil y CV",
            type="primary",
        )

        if submitted:
            try:
                update_candidate_profile(
                    candidate["id"],
                    {
                        "phone": phone,
                        "city": city,
                        "headline": headline,
                        "education_summary": education_summary,
                        "experience_summary": experience_summary,
                        "skills_text": skills_text,
                        "languages_text": languages_text,
                    },
                )

                if draft:
                    document_id = save_candidate_document(
                        candidate["id"],
                        draft["filename"],
                        draft["mime_type"],
                        draft["raw"],
                        draft["text"],
                        draft["parsed"],
                        user["id"],
                    )
                    log_event(
                        None,
                        user["id"],
                        "UPLOAD_OWN_CV",
                        "candidate_document",
                        document_id,
                        {"candidate_id": candidate["id"]},
                    )
                    st.session_state.pop(
                        f"candidate_cv_draft_{candidate['id']}",
                        None,
                    )

                rescore_candidate_applications(
                    candidate["id"]
                )

                st.success(
                    "Perfil guardado y postulaciones recalculadas."
                )
                st.rerun()

            except Exception as exc:
                st.error(str(exc))

    if latest_cv:
        st.caption(
            f"Último CV: {latest_cv['filename']} · "
            f"{latest_cv['created_at']}"
        )
        st.download_button(
            "Descargar mi CV",
            data=latest_cv["content_blob"],
            file_name=latest_cv["filename"],
            mime=latest_cv.get("mime_type")
            or "application/octet-stream",
            key=f"download_own_cv_{latest_cv['id']}",
        )

def render_applications(user: dict) -> None:
    st.subheader("Candidatos, CV y ranking")

    if not has_permission("view_candidates"):
        st.warning("No tenés permiso para ver candidatos.")
        return

    st.info(SCORING_NOTICE)

    tab_ranking, tab_detail, tab_upload = st.tabs(
        [
            "Ranking y pipeline",
            "Detalle del candidato",
            "Carga masiva de CV",
        ]
    )

    jobs = fetch_all(
        """
        SELECT id, title
        FROM jobs
        WHERE company_id = ?
        ORDER BY created_at DESC
        """,
        (user["company_id"],),
    )

    with tab_ranking:
        filter_options = {"Todas las búsquedas": None}
        filter_options.update(
            {
                job["title"]: job["id"]
                for job in jobs
            }
        )

        selected_label = st.selectbox(
            "Filtrar por búsqueda",
            list(filter_options.keys()),
            key="ranking_job_filter",
        )
        selected_job_id = filter_options[selected_label]

        query = """
            SELECT
                applications.id AS application_id,
                users.full_name AS candidate,
                users.email,
                candidates.source,
                jobs.title AS job,
                applications.score_total,
                applications.screening_recommendation,
                applications.status,
                applications.created_at
            FROM applications
            JOIN candidates
                ON candidates.id = applications.candidate_id
            JOIN users
                ON users.id = candidates.user_id
            JOIN jobs
                ON jobs.id = applications.job_id
            WHERE jobs.company_id = ?
        """
        params: tuple = (user["company_id"],)

        if selected_job_id is not None:
            query += " AND jobs.id = ?"
            params = (
                user["company_id"],
                selected_job_id,
            )

        query += """
            ORDER BY
                CASE
                    WHEN applications.score_total IS NULL THEN 1
                    ELSE 0
                END,
                applications.score_total DESC,
                applications.created_at DESC
        """

        applications = fetch_all(query, params)

        if applications:
            display_rows = []
            for item in applications:
                display_rows.append(
                    {
                        "Postulación": item["application_id"],
                        "Candidato": item["candidate"],
                        "Email": (
                            "Sin email de acceso"
                            if str(item["email"]).endswith(
                                "@alba.local"
                            )
                            else item["email"]
                        ),
                        "Origen": item.get("source") or "PORTAL",
                        "Búsqueda": item["job"],
                        "Puntaje": item.get("score_total"),
                        "Recomendación": (
                            item.get("screening_recommendation")
                            or "PENDIENTE"
                        ),
                        "Etapa": item["status"],
                        "Fecha": item["created_at"],
                    }
                )

            st.dataframe(
                pd.DataFrame(display_rows),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Todavía no hay postulaciones.")

    with tab_detail:
        detail_rows = fetch_all(
            """
            SELECT
                applications.*,
                users.full_name AS candidate_name,
                users.email,
                candidates.id AS candidate_id,
                candidates.phone,
                candidates.city,
                candidates.source,
                candidates.headline,
                candidates.education_summary,
                candidates.experience_summary,
                candidates.skills_text,
                candidates.languages_text,
                jobs.title AS job_title
            FROM applications
            JOIN candidates
                ON candidates.id = applications.candidate_id
            JOIN users
                ON users.id = candidates.user_id
            JOIN jobs
                ON jobs.id = applications.job_id
            WHERE jobs.company_id = ?
            ORDER BY applications.created_at DESC
            """,
            (user["company_id"],),
        )

        if not detail_rows:
            st.info("No hay candidatos para mostrar.")
        else:
            detail_options = {
                (
                    f"#{row['id']} · {row['candidate_name']} · "
                    f"{row['job_title']}"
                ): row
                for row in detail_rows
            }
            selected_detail_label = st.selectbox(
                "Seleccionar postulación",
                list(detail_options.keys()),
                key="candidate_detail_select",
            )
            selected = detail_options[
                selected_detail_label
            ]

            c1, c2 = st.columns(2)
            with c1:
                st.markdown(
                    f"### {selected['candidate_name']}"
                )
                st.write(
                    f"**Búsqueda:** {selected['job_title']}"
                )
                st.write(
                    f"**Origen:** "
                    f"{selected.get('source') or 'PORTAL'}"
                )
                if not str(selected["email"]).endswith(
                    "@alba.local"
                ):
                    st.write(
                        f"**Correo:** {selected['email']}"
                    )
                st.write(
                    f"**Teléfono:** "
                    f"{selected.get('phone') or 'No informado'}"
                )
                st.write(
                    f"**Ciudad:** "
                    f"{selected.get('city') or 'No informada'}"
                )

            with c2:
                if has_permission("manage_candidates"):
                    current_status = (
                        selected.get("status")
                        if selected.get("status")
                        in APPLICATION_STATUSES
                        else "RECIBIDA"
                    )
                    new_status = st.selectbox(
                        "Etapa del proceso",
                        APPLICATION_STATUSES,
                        index=APPLICATION_STATUSES.index(
                            current_status
                        ),
                        key=f"stage_{selected['id']}",
                    )

                    if st.button(
                        "Actualizar etapa",
                        type="primary",
                        key=f"update_stage_{selected['id']}",
                    ):
                        execute(
                            """
                            UPDATE applications
                            SET status = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                new_status,
                                now_iso(),
                                selected["id"],
                            ),
                        )
                        log_event(
                            user["company_id"],
                            user["id"],
                            "UPDATE_APPLICATION_STAGE",
                            "application",
                            selected["id"],
                            {"status": new_status},
                        )
                        st.success("Etapa actualizada.")
                        st.rerun()

            st.markdown("#### Perfil extraído")
            st.write(
                selected.get("headline")
                or "Sin perfil resumido."
            )

            with st.expander("Experiencia"):
                st.write(
                    selected.get("experience_summary")
                    or "No detectada."
                )
            with st.expander("Formación"):
                st.write(
                    selected.get("education_summary")
                    or "No detectada."
                )
            with st.expander("Habilidades"):
                st.write(
                    selected.get("skills_text")
                    or "No detectadas."
                )
            with st.expander("Idiomas"):
                st.write(
                    selected.get("languages_text")
                    or "No detectados."
                )

            latest_cv = get_latest_cv(
                selected["candidate_id"]
            )
            if latest_cv:
                st.download_button(
                    "Descargar CV",
                    data=latest_cv["content_blob"],
                    file_name=latest_cv["filename"],
                    mime=latest_cv.get("mime_type")
                    or "application/octet-stream",
                    key=f"download_cv_{latest_cv['id']}",
                )

            if st.button(
                "Recalcular coincidencia",
                key=f"rescore_{selected['id']}",
            ):
                try:
                    score_application(selected["id"])
                    st.success("Coincidencia recalculada.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

            st.markdown("#### Informe de coincidencia")
            try:
                report = json.loads(
                    selected.get("score_breakdown_json")
                    or "{}"
                )
            except json.JSONDecodeError:
                report = {}

            if report:
                render_score_report(report)
            else:
                st.info(
                    "La postulación todavía no tiene un "
                    "análisis de coincidencia."
                )

    with tab_upload:
        render_bulk_cv_upload(user)

def render_audit(user: dict) -> None:
    st.subheader("Auditoría")

    if not has_permission("view_audit"):
        st.warning("No tenés permiso para consultar auditoría.")
        return

    records = fetch_all(
        """
        SELECT
            audit_log.id,
            users.email AS user_email,
            audit_log.event_type,
            audit_log.entity_type,
            audit_log.entity_id,
            audit_log.details,
            audit_log.created_at
        FROM audit_log
        LEFT JOIN users
            ON users.id = audit_log.user_id
        WHERE audit_log.company_id = ?
        ORDER BY audit_log.created_at DESC
        LIMIT 500
        """,
        (user["company_id"],),
    )

    if records:
        st.dataframe(
            pd.DataFrame(records),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Todavía no hay eventos de auditoría.")


# =========================================================
# PORTAL DE EMPRESA
# =========================================================

def render_company_portal(user: dict) -> None:
    company = get_company(user["company_id"])

    if not company:
        st.error("No se encontró la empresa vinculada.")
        return

    render_company_header(company)

    menu = ["Inicio", "Búsquedas"]

    if has_permission("view_candidates"):
        menu.append("Candidatos")
    if has_permission("manage_users"):
        menu.append("Usuarios y permisos")
    if has_permission("manage_company"):
        menu.append("Empresa")
    if has_permission("view_audit"):
        menu.append("Auditoría")

    selected = st.sidebar.radio("Menú empresa", menu)

    if selected == "Inicio":
        c1, c2, c3 = st.columns(3)

        jobs_total = fetch_one(
            "SELECT COUNT(*) AS total FROM jobs WHERE company_id = ?",
            (company["id"],),
        )["total"]

        applications_total = fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE jobs.company_id = ?
            """,
            (company["id"],),
        )["total"]

        users_total = fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM users
            WHERE company_id = ?
            """,
            (company["id"],),
        )["total"]

        c1.metric("Búsquedas", jobs_total)
        c2.metric("Postulaciones", applications_total)
        c3.metric("Usuarios", users_total)

        st.info(
            "Módulo 4 activo: gestión de CV, carga masiva, ranking "
            "explicable, informes y pipeline de candidatos."
        )

    elif selected == "Búsquedas":
        render_jobs(user)
    elif selected == "Candidatos":
        render_applications(user)
    elif selected == "Usuarios y permisos":
        render_user_management(user)
    elif selected == "Empresa":
        render_company_settings(user, company)
    elif selected == "Auditoría":
        render_audit(user)


# =========================================================
# PORTAL DEL CANDIDATO
# =========================================================

def render_candidate_portal(user: dict) -> None:
    candidate = fetch_one(
        "SELECT * FROM candidates WHERE user_id = ?",
        (user["id"],),
    )

    if not candidate:
        st.error("No se encontró el perfil del candidato.")
        return

    st.title("Portal del candidato")
    st.caption(user["email"])

    menu = st.sidebar.radio(
        "Menú candidato",
        [
            "Búsquedas abiertas",
            "Mis postulaciones",
            "Mi perfil y CV",
        ],
    )

    if menu == "Búsquedas abiertas":
        jobs = fetch_all(
            """
            SELECT
                jobs.id,
                jobs.title,
                jobs.area,
                jobs.seniority,
                jobs.description,
                jobs.location,
                jobs.work_mode,
                jobs.contract_type,
                jobs.responsibilities,
                jobs.must_have,
                jobs.desirable,
                jobs.competencies,
                companies.name AS company_name,
                companies.logo_blob
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
                c1, c2 = st.columns([1, 5])

                with c1:
                    if job.get("logo_blob"):
                        st.image(
                            job["logo_blob"],
                            width=80,
                        )

                with c2:
                    st.subheader(job["title"])
                    st.write(
                        f"**Empresa:** {job['company_name']}"
                    )
                    st.write(
                        f"**Área:** "
                        f"{job.get('area') or 'No informada'}"
                    )
                    st.write(
                        f"**Seniority:** "
                        f"{job.get('seniority') or 'No informado'}"
                    )
                    st.write(
                        f"**Modalidad:** "
                        f"{job.get('work_mode') or 'No informada'}"
                    )
                    st.write(
                        f"**Ubicación:** "
                        f"{job.get('location') or 'No informada'}"
                    )
                    st.write(
                        f"**Contratación:** "
                        f"{job.get('contract_type') or 'No informada'}"
                    )

                    if job.get("description"):
                        st.markdown("**Descripción**")
                        st.write(job["description"])
                    if job.get("responsibilities"):
                        st.markdown("**Responsabilidades**")
                        st.write(job["responsibilities"])
                    if job.get("must_have"):
                        st.markdown(
                            "**Requisitos excluyentes**"
                        )
                        st.write(job["must_have"])
                    if job.get("desirable"):
                        st.markdown(
                            "**Requisitos deseables**"
                        )
                        st.write(job["desirable"])
                    if job.get("competencies"):
                        st.markdown("**Competencias**")
                        st.write(job["competencies"])

                    already_applied = fetch_one(
                        """
                        SELECT id
                        FROM applications
                        WHERE candidate_id = ?
                          AND job_id = ?
                        """,
                        (
                            candidate["id"],
                            job["id"],
                        ),
                    )

                    if already_applied:
                        st.success("Ya te postulaste.")
                    elif st.button(
                        "Postularme",
                        key=f"apply_{job['id']}",
                    ):
                        application_id = execute(
                            """
                            INSERT INTO applications(
                                candidate_id,
                                job_id,
                                status,
                                created_at,
                                updated_at
                            )
                            VALUES (?, ?, 'RECIBIDA', ?, ?)
                            """,
                            (
                                candidate["id"],
                                job["id"],
                                now_iso(),
                                now_iso(),
                            ),
                        )

                        score_application(application_id)

                        log_event(
                            None,
                            user["id"],
                            "CREATE_APPLICATION",
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
            st.info("Todavía no tenés postulaciones.")

    else:
        render_candidate_profile(user, candidate)


# =========================================================
# APLICACIÓN
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
        "Plataforma de selección con portales para empresas y candidatos."
    )

    login_tab, register_tab, privacy_tab = st.tabs(
        ["Iniciar sesión", "Registrarse", "Privacidad"]
    )

    with login_tab:
        render_login()

    with register_tab:
        render_registration()

    with privacy_tab:
        st.subheader("Política de datos")
        st.write(
            "El correo electrónico funciona como usuario. "
            "Las contraseñas se guardan con hash y salt."
        )
        st.write(
            "DNI, teléfono y ubicación pueden registrarse para gestión, "
            "pero no deben utilizarse para puntuar o rankear."
        )
        st.write(
            "El análisis de coincidencia usa únicamente el contenido "
            "profesional del CV y los criterios de la búsqueda. "
            "La decisión final debe quedar en manos de una persona."
        )
        st.write(
            "La empresa no debe cargar credenciales, secretos comerciales, "
            "precios, clientes, fórmulas ni procesos confidenciales."
        )

else:
    refreshed_user = refresh_user(user["id"])

    if not refreshed_user:
        st.session_state.pop("auth_user", None)
        st.error("El usuario fue desactivado.")
        st.stop()

    st.session_state["auth_user"] = refreshed_user
    user = refreshed_user

    st.sidebar.success(
        f"{user['full_name']}\n\n{user['email']}"
    )

    st.sidebar.caption(f"Versión {APP_VERSION}")

    audit_warning = st.session_state.pop(
        "audit_warning",
        None,
    )
    if audit_warning:
        st.warning(audit_warning)

    if st.sidebar.button("Cerrar sesión"):
        logout()

    try:
        if user["account_type"] == "COMPANY":
            render_company_portal(user)
        elif user["account_type"] == "CANDIDATE":
            render_candidate_portal(user)
        else:
            st.error("Tipo de cuenta no válido.")

    except Exception as exc:
        st.error(
            "Se produjo un error dentro de la aplicación. "
            "El detalle aparece debajo para poder corregirlo."
        )
        st.exception(exc)

        with st.expander("Diagnóstico técnico"):
            st.code(traceback.format_exc())
