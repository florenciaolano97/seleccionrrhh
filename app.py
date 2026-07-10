from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import secrets
import sqlite3

import pandas as pd
import streamlit as st


# =========================================================
# CONFIGURACIÓN
# =========================================================

APP_NAME = "ALBA v2 | Plataforma de Selección"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "alba_v2.db"
DATA_DIR.mkdir(exist_ok=True)


# =========================================================
# SEGURIDAD
# =========================================================

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


# =========================================================
# BASE DE DATOS
# =========================================================

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            industry TEXT,
            country TEXT,
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

    conn.commit()
    conn.close()


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


# =========================================================
# AUTENTICACIÓN
# =========================================================

def register_company_admin(
    company_name: str,
    industry: str,
    country: str,
    full_name: str,
    email: str,
    password: str,
) -> int:
    if not company_name.strip():
        raise ValueError("Ingresá el nombre de la empresa.")
    if not full_name.strip():
        raise ValueError("Ingresá el nombre del administrador.")
    if not validate_email(email):
        raise ValueError("Ingresá un correo electrónico válido.")

    password_error = validate_password(password)
    if password_error:
        raise ValueError(password_error)

    email = normalize_email(email)
    if fetch_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError("Ya existe un usuario con ese correo.")

    company_id = execute(
        "INSERT INTO companies(name, industry, country) VALUES (?, ?, ?)",
        (company_name.strip(), industry.strip(), country.strip()),
    )

    password_hash, salt = hash_password(password)

    execute(
        """
        INSERT INTO users(
            email, password_hash, password_salt, full_name,
            account_type, company_id, role, permissions_json
        )
        VALUES (?, ?, ?, ?, 'COMPANY', ?, 'ADMIN', ?)
        """,
        (
            email,
            password_hash,
            salt,
            full_name.strip(),
            company_id,
            json.dumps(["ALL"]),
        ),
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
    if not full_name.strip():
        raise ValueError("Ingresá nombre y apellido.")
    if not validate_email(email):
        raise ValueError("Ingresá un correo electrónico válido.")

    password_error = validate_password(password)
    if password_error:
        raise ValueError(password_error)

    email = normalize_email(email)
    if fetch_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise ValueError("Ya existe un usuario con ese correo.")

    password_hash, salt = hash_password(password)

    user_id = execute(
        """
        INSERT INTO users(
            email, password_hash, password_salt,
            full_name, account_type
        )
        VALUES (?, ?, ?, ?, 'CANDIDATE')
        """,
        (
            email,
            password_hash,
            salt,
            full_name.strip(),
        ),
    )

    return execute(
        """
        INSERT INTO candidates(user_id, phone, dni, city)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            phone.strip(),
            dni.strip(),
            city.strip(),
        ),
    )


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

    return user


def current_user() -> dict | None:
    return st.session_state.get("auth_user")


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
        submitted = st.form_submit_button("Ingresar", type="primary")

        if submitted:
            user = authenticate(email, password)
            if not user:
                st.error("Correo o contraseña incorrectos.")
            else:
                st.session_state["auth_user"] = user
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
            company_name = st.text_input("Nombre de la empresa")
            industry = st.text_input("Industria")
            country = st.text_input("País", value="Argentina")
            full_name = st.text_input("Nombre del administrador")
            email = st.text_input("Correo electrónico")
            password = st.text_input("Contraseña", type="password")
            repeat = st.text_input("Repetir contraseña", type="password")

            submitted = st.form_submit_button(
                "Crear empresa",
                type="primary",
            )

            if submitted:
                try:
                    if password != repeat:
                        raise ValueError("Las contraseñas no coinciden.")

                    register_company_admin(
                        company_name,
                        industry,
                        country,
                        full_name,
                        email,
                        password,
                    )

                    st.success("Empresa creada. Ya podés iniciar sesión.")
                except Exception as exc:
                    st.error(str(exc))

    else:
        with st.form("register_candidate"):
            full_name = st.text_input("Nombre y apellido")
            email = st.text_input("Correo electrónico")
            password = st.text_input("Contraseña", type="password")
            repeat = st.text_input("Repetir contraseña", type="password")
            phone = st.text_input("Teléfono")
            dni = st.text_input("DNI")
            city = st.text_input("Ciudad")

            consent = st.checkbox(
                "Acepto el tratamiento de mis datos para gestionar postulaciones."
            )

            submitted = st.form_submit_button(
                "Crear cuenta",
                type="primary",
            )

            if submitted:
                try:
                    if password != repeat:
                        raise ValueError("Las contraseñas no coinciden.")
                    if not consent:
                        raise ValueError("Tenés que aceptar el consentimiento.")

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
# PORTAL DE EMPRESA
# =========================================================

def render_company_portal(user: dict) -> None:
    company = fetch_one(
        "SELECT * FROM companies WHERE id = ?",
        (user["company_id"],),
    )

    if not company:
        st.error("No se encontró la empresa vinculada.")
        return

    st.title(company["name"])
    st.caption(
        f"{company.get('industry') or 'Industria no informada'} · "
        f"{company.get('country') or 'País no informado'}"
    )

    menu = st.sidebar.radio(
        "Menú empresa",
        ["Inicio", "Crear búsqueda", "Búsquedas", "Postulaciones"],
    )

    if menu == "Inicio":
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
            "SELECT COUNT(*) AS total FROM users WHERE company_id = ?",
            (company["id"],),
        )["total"]

        c1.metric("Búsquedas", jobs_total)
        c2.metric("Postulaciones", applications_total)
        c3.metric("Usuarios", users_total)

    elif menu == "Crear búsqueda":
        st.subheader("Nueva búsqueda")

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
                    execute(
                        """
                        INSERT INTO jobs(
                            company_id, title, area, seniority,
                            description, created_by
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            company["id"],
                            title.strip(),
                            area.strip(),
                            seniority,
                            description.strip(),
                            user["id"],
                        ),
                    )
                    st.success("Búsqueda creada correctamente.")
                    st.rerun()

    elif menu == "Búsquedas":
        jobs = fetch_all(
            """
            SELECT id, title, area, seniority, status, created_at
            FROM jobs
            WHERE company_id = ?
            ORDER BY created_at DESC
            """,
            (company["id"],),
        )

        if jobs:
            st.dataframe(
                pd.DataFrame(jobs),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Todavía no hay búsquedas.")

    else:
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
            (company["id"],),
        )

        if applications:
            st.dataframe(
                pd.DataFrame(applications),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Todavía no hay postulaciones.")


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
                companies.name AS company_name
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
                st.subheader(job["title"])
                st.write(f"**Empresa:** {job['company_name']}")
                st.write(f"**Área:** {job.get('area') or 'No informada'}")
                st.write(
                    f"**Seniority:** {job.get('seniority') or 'No informado'}"
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
                    execute(
                        """
                        INSERT INTO applications(candidate_id, job_id)
                        VALUES (?, ?)
                        """,
                        (candidate["id"], job["id"]),
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
    st.caption("Base estable para empresas y candidatos.")

    login_tab, register_tab = st.tabs(
        ["Iniciar sesión", "Registrarse"]
    )

    with login_tab:
        render_login()

    with register_tab:
        render_registration()

else:
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
