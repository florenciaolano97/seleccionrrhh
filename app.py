from __future__ import annotations

from pathlib import Path
import hashlib
import io
import json
import re
import secrets
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image


# =========================================================
# CONFIGURACIÓN
# =========================================================

APP_NAME = "ALBA v2 | Plataforma de Selección"
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
    "view_audit": "Consultar auditoría",
}

ROLE_DEFAULTS = {
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
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(table_name: str) -> set[str]:
    conn = get_connection()
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    conn.close()
    return {row["name"] for row in rows}


def add_column_if_missing(
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if column_name in table_columns(table_name):
        return

    conn = get_connection()
    conn.execute(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
    )
    conn.commit()
    conn.close()


def init_db() -> None:
    conn = get_connection()
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
    conn.close()

    # Migraciones para una base creada por el Módulo 1.
    add_column_if_missing("companies", "logo_blob", "BLOB")
    add_column_if_missing("companies", "logo_mime", "TEXT")
    add_column_if_missing("users", "role", "TEXT")
    add_column_if_missing("users", "permissions_json", "TEXT DEFAULT '[]'")
    add_column_if_missing("users", "active", "INTEGER DEFAULT 1")


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_one(query: str, params: tuple = ()) -> dict | None:
    conn = get_connection()
    row = conn.execute(query, params).fetchone()
    conn.close()
    return dict(row) if row else None


def execute(query: str, params: tuple = ()) -> int:
    conn = get_connection()
    cur = conn.execute(query, params)
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def log_event(
    company_id: int | None,
    user_id: int | None,
    event_type: str,
    entity_type: str = "",
    entity_id: int | None = None,
    details: dict | str | None = None,
) -> None:
    if isinstance(details, dict):
        details = json.dumps(details, ensure_ascii=False)

    execute(
        """
        INSERT INTO audit_log(
            company_id, user_id, event_type,
            entity_type, entity_id, details, created_at
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
# EMPRESA: BÚSQUEDAS Y POSTULACIONES
# =========================================================

def render_jobs(user: dict) -> None:
    st.subheader("Búsquedas laborales")

    if has_permission("manage_jobs"):
        with st.expander("Crear búsqueda", expanded=True):
            with st.form("job_form"):
                title = st.text_input("Puesto")
                area = st.text_input("Área")
                seniority = st.selectbox(
                    "Seniority",
                    [
                        "Pasantía",
                        "Junior",
                        "Semi Senior",
                        "Senior",
                        "Liderazgo",
                        "Dirección",
                    ],
                )
                description = st.text_area("Descripción")

                submitted = st.form_submit_button(
                    "Guardar búsqueda",
                    type="primary",
                )

                if submitted:
                    if not title.strip():
                        st.error("Ingresá el nombre del puesto.")
                    else:
                        job_id = execute(
                            """
                            INSERT INTO jobs(
                                company_id, title, area,
                                seniority, description,
                                created_by, created_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                user["company_id"],
                                title.strip(),
                                area.strip(),
                                seniority,
                                description.strip(),
                                user["id"],
                                now_iso(),
                            ),
                        )

                        log_event(
                            user["company_id"],
                            user["id"],
                            "CREATE_JOB",
                            "job",
                            job_id,
                            {"title": title},
                        )

                        st.success("Búsqueda creada correctamente.")
                        st.rerun()
    else:
        st.warning("No tenés permiso para crear búsquedas.")

    jobs = fetch_all(
        """
        SELECT
            id, title, area, seniority,
            status, created_at
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
        st.info("Todavía no hay búsquedas.")


def render_applications(user: dict) -> None:
    st.subheader("Candidatos y postulaciones")

    if not has_permission("view_candidates"):
        st.warning("No tenés permiso para ver candidatos.")
        return

    applications = fetch_all(
        """
        SELECT
            applications.id,
            users.full_name AS candidate,
            users.email,
            jobs.title AS job,
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
            "Módulo 2 activo: logo, configuración de empresa, "
            "usuarios internos, roles, permisos y auditoría."
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
        ["Búsquedas abiertas", "Mis postulaciones"],
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
                        st.image(job["logo_blob"], width=80)

                with c2:
                    st.subheader(job["title"])
                    st.write(f"**Empresa:** {job['company_name']}")
                    st.write(
                        f"**Área:** {job.get('area') or 'No informada'}"
                    )
                    st.write(
                        f"**Seniority:** "
                        f"{job.get('seniority') or 'No informado'}"
                    )
                    st.write(job.get("description") or "")

                    already_applied = fetch_one(
                        """
                        SELECT id
                        FROM applications
                        WHERE candidate_id = ? AND job_id = ?
                        """,
                        (candidate["id"], job["id"]),
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
                            None,
                            user["id"],
                            "CREATE_APPLICATION",
                            "application",
                            application_id,
                            {"job_id": job["id"]},
                        )

                        st.success("Postulación enviada.")
                        st.rerun()

    else:
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

    if st.sidebar.button("Cerrar sesión"):
        logout()

    if user["account_type"] == "COMPANY":
        render_company_portal(user)
    elif user["account_type"] == "CANDIDATE":
        render_candidate_portal(user)
    else:
        st.error("Tipo de cuenta no válido.")
