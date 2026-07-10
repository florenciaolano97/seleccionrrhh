from pathlib import Path
import json
import sqlite3

import pandas as pd
import streamlit as st


# =========================================================
# CONFIGURACIÓN
# =========================================================

APP_NAME = "Alba | Plataforma de Selección"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "database"
DB_PATH = DATA_DIR / "alba.db"
DATA_DIR.mkdir(exist_ok=True)


# =========================================================
# BASE DE DATOS
# =========================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            industry TEXT,
            country TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            must_have TEXT,
            desirable TEXT,
            status TEXT DEFAULT 'ABIERTA',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            dni TEXT,
            birth_date TEXT,
            city TEXT,
            consent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            status TEXT DEFAULT 'RECIBIDA',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(candidate_id) REFERENCES candidates(id),
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def fetch_all(query, params=()):
    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def execute(query, params=()):
    conn = get_connection()
    cur = conn.execute(query, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


# =========================================================
# SERVICIOS
# =========================================================

def log_event(event_type, entity_type="", entity_id=None, details=""):
    execute(
        """
        INSERT INTO audit_log(event_type, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?)
        """,
        (event_type, entity_type, entity_id, details),
    )


def create_company(name, industry, country):
    company_id = execute(
        "INSERT INTO companies(name, industry, country) VALUES (?, ?, ?)",
        (name.strip(), industry.strip(), country.strip()),
    )
    log_event(
        "CREATE",
        "company",
        company_id,
        json.dumps({"name": name}, ensure_ascii=False),
    )
    return company_id


def list_companies():
    return fetch_all("SELECT * FROM companies ORDER BY created_at DESC")


def create_job(
    company_id,
    title,
    area,
    seniority,
    description,
    must_have,
    desirable,
):
    job_id = execute(
        """
        INSERT INTO jobs(
            company_id, title, area, seniority,
            description, must_have, desirable
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            title.strip(),
            area.strip(),
            seniority,
            description,
            must_have,
            desirable,
        ),
    )
    log_event(
        "CREATE",
        "job",
        job_id,
        json.dumps({"title": title}, ensure_ascii=False),
    )
    return job_id


def list_jobs():
    return fetch_all(
        """
        SELECT jobs.*, companies.name AS company_name
        FROM jobs
        JOIN companies ON companies.id = jobs.company_id
        ORDER BY jobs.created_at DESC
        """
    )


def create_candidate(
    full_name,
    email,
    phone,
    dni,
    birth_date,
    city,
    consent,
):
    candidate_id = execute(
        """
        INSERT INTO candidates(
            full_name, email, phone, dni,
            birth_date, city, consent
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            full_name.strip(),
            email.strip(),
            phone.strip(),
            dni.strip(),
            birth_date,
            city.strip(),
            int(bool(consent)),
        ),
    )
    log_event(
        "CREATE",
        "candidate",
        candidate_id,
        json.dumps({"email": email}, ensure_ascii=False),
    )
    return candidate_id


def create_application(candidate_id, job_id):
    application_id = execute(
        """
        INSERT INTO applications(candidate_id, job_id)
        VALUES (?, ?)
        """,
        (candidate_id, job_id),
    )
    log_event(
        "CREATE",
        "application",
        application_id,
        json.dumps(
            {"candidate_id": candidate_id, "job_id": job_id},
            ensure_ascii=False,
        ),
    )
    return application_id


def list_applications():
    return fetch_all(
        """
        SELECT
            applications.id,
            candidates.full_name AS candidate,
            candidates.email,
            jobs.title AS job,
            companies.name AS company,
            applications.status,
            applications.created_at
        FROM applications
        JOIN candidates
            ON candidates.id = applications.candidate_id
        JOIN jobs
            ON jobs.id = applications.job_id
        JOIN companies
            ON companies.id = jobs.company_id
        ORDER BY applications.created_at DESC
        """
    )


# =========================================================
# POLÍTICA Y SCORING
# =========================================================

def evaluation_policy_text():
    return (
        "La plataforma separa los datos administrativos de los datos evaluables. "
        "DNI, edad, fecha de nacimiento, teléfono y domicilio pueden registrarse "
        "para fines administrativos, pero no se utilizan para puntuar, rankear "
        "ni recomendar decisiones. La IA asiste y la decisión final es humana."
    )


def explain_default_weights():
    return [
        {"Dimensión": "Experiencia relacionada", "Peso": "25%"},
        {"Dimensión": "Conocimientos técnicos", "Peso": "25%"},
        {"Dimensión": "Competencias conductuales", "Peso": "20%"},
        {"Dimensión": "Calidad de las respuestas", "Peso": "15%"},
        {"Dimensión": "Evidencias concretas", "Peso": "10%"},
        {"Dimensión": "Motivación", "Peso": "5%"},
    ]


# =========================================================
# INTERFAZ
# =========================================================

st.set_page_config(
    page_title=APP_NAME,
    page_icon="🤖",
    layout="wide",
)

init_db()

st.title(APP_NAME)
st.caption("Módulo 1: arquitectura, base de datos y portales iniciales")

with st.sidebar:
    portal = st.radio(
        "Ingresar como",
        [
            "Portal Reclutador",
            "Portal Candidato",
            "Criterios y privacidad",
        ],
    )
    st.divider()
    st.info(
        "Base funcional. Los módulos de CV masivo, Alba, ranking "
        "avanzado e informes se incorporarán progresivamente."
    )


if portal == "Portal Reclutador":
    st.header("Portal del reclutador")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Empresas", "Búsquedas", "Postulaciones", "Auditoría"]
    )

    with tab1:
        st.subheader("Crear empresa")

        with st.form("company_form"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Nombre de la empresa")
            industry = c2.text_input("Industria")
            country = c3.text_input("País", value="Argentina")

            submitted = st.form_submit_button("Crear empresa")

            if submitted:
                if not name.strip():
                    st.error("Ingresá el nombre de la empresa.")
                else:
                    create_company(name, industry, country)
                    st.success("Empresa creada correctamente.")
                    st.rerun()

        companies = list_companies()

        if companies:
            st.dataframe(
                pd.DataFrame(companies),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Todavía no hay empresas registradas.")

    with tab2:
        companies = list_companies()

        if not companies:
            st.warning("Primero creá una empresa.")
        else:
            options = {
                f"{company['name']} — "
                f"{company['industry'] or 'Sin industria'}": company["id"]
                for company in companies
            }

            with st.form("job_form"):
                company_label = st.selectbox(
                    "Empresa",
                    list(options.keys()),
                )

                title = st.text_input("Puesto")

                c1, c2 = st.columns(2)
                area = c1.text_input("Área")
                seniority = c2.selectbox(
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

                description = st.text_area("Descripción del puesto")
                must_have = st.text_area("Requisitos excluyentes")
                desirable = st.text_area("Requisitos deseables")

                submitted = st.form_submit_button("Crear búsqueda")

                if submitted:
                    if not title.strip():
                        st.error("Ingresá el nombre del puesto.")
                    else:
                        create_job(
                            options[company_label],
                            title,
                            area,
                            seniority,
                            description,
                            must_have,
                            desirable,
                        )
                        st.success("Búsqueda creada correctamente.")
                        st.rerun()

        jobs = list_jobs()

        if jobs:
            st.dataframe(
                pd.DataFrame(jobs),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Todavía no hay búsquedas registradas.")

    with tab3:
        applications = list_applications()

        if applications:
            st.dataframe(
                pd.DataFrame(applications),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Todavía no hay postulaciones.")

    with tab4:
        audit = fetch_all(
            """
            SELECT *
            FROM audit_log
            ORDER BY created_at DESC
            LIMIT 200
            """
        )

        if audit:
            st.dataframe(
                pd.DataFrame(audit),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Todavía no hay eventos de auditoría.")


elif portal == "Portal Candidato":
    st.header("Portal del candidato")

    jobs = list_jobs()
    open_jobs = [job for job in jobs if job["status"] == "ABIERTA"]

    if not open_jobs:
        st.warning("Todavía no existen búsquedas abiertas.")
    else:
        job_options = {
            f"{job['title']} — {job['company_name']}": job["id"]
            for job in open_jobs
        }

        with st.form("candidate_form"):
            selected = st.selectbox(
                "Búsqueda",
                list(job_options.keys()),
            )

            st.subheader("Datos de contacto")

            c1, c2 = st.columns(2)
            full_name = c1.text_input("Nombre y apellido")
            email = c2.text_input("Correo electrónico")

            c3, c4 = st.columns(2)
            phone = c3.text_input("Teléfono")
            dni = c4.text_input("DNI")

            c5, c6 = st.columns(2)
            birth_date = c5.date_input(
                "Fecha de nacimiento",
                value=None,
            )
            city = c6.text_input("Ciudad")

            consent = st.checkbox(
                "Acepto el tratamiento de mis datos para gestionar "
                "la postulación. Comprendo que los datos administrativos "
                "no se usan para puntuar ni rankear."
            )

            submitted = st.form_submit_button("Enviar postulación")

            if submitted:
                if not full_name.strip() or not email.strip() or not consent:
                    st.error(
                        "Completá nombre, correo y consentimiento."
                    )
                else:
                    candidate_id = create_candidate(
                        full_name,
                        email,
                        phone,
                        dni,
                        birth_date.isoformat() if birth_date else "",
                        city,
                        consent,
                    )

                    application_id = create_application(
                        candidate_id,
                        job_options[selected],
                    )

                    st.success(
                        "Postulación registrada. "
                        f"Código interno: APP-{application_id:06d}"
                    )
                    st.info(
                        "En los próximos módulos se habilitarán "
                        "carga de CV, entrevista con Alba y seguimiento."
                    )


else:
    st.header("Criterios de evaluación y privacidad")

    st.subheader("Distribución inicial del puntaje")

    st.dataframe(
        pd.DataFrame(explain_default_weights()),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "Las ponderaciones serán configurables por búsqueda "
        "en el módulo de scoring avanzado."
    )

    st.subheader("Política de datos")
    st.write(evaluation_policy_text())

    st.markdown(
        """
        **Datos administrativos del candidato:** pueden almacenarse para
        contacto y gestión, pero quedan excluidos del ranking.

        **Datos evaluables:** experiencia, conocimientos, formación,
        competencias, respuestas y resultados de pruebas.

        **Información de la empresa:** no deben cargarse secretos
        comerciales, credenciales, precios, clientes ni procesos
        confidenciales.
        """
    )
