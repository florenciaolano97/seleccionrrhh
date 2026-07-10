import pandas as pd
import streamlit as st
from database.db import execute, fetch_all, fetch_one

def render_company_portal(user):
    company = fetch_one("SELECT * FROM companies WHERE id = ?", (user["company_id"],))
    if not company:
        st.error("No se encontró la empresa vinculada.")
        return
    st.title(company["name"])
    st.caption(f"{company.get('industry') or 'Industria no informada'} · {company.get('country') or 'País no informado'}")
    menu = st.sidebar.radio("Menú empresa", ["Inicio", "Crear búsqueda", "Búsquedas", "Postulaciones"])

    if menu == "Inicio":
        c1, c2, c3 = st.columns(3)
        c1.metric("Búsquedas", fetch_one("SELECT COUNT(*) AS total FROM jobs WHERE company_id = ?", (company["id"],))["total"])
        c2.metric("Postulaciones", fetch_one(
            "SELECT COUNT(*) AS total FROM applications JOIN jobs ON jobs.id = applications.job_id WHERE jobs.company_id = ?",
            (company["id"],),
        )["total"])
        c3.metric("Usuarios", fetch_one("SELECT COUNT(*) AS total FROM users WHERE company_id = ?", (company["id"],))["total"])

    elif menu == "Crear búsqueda":
        st.subheader("Nueva búsqueda")
        with st.form("job_form"):
            title = st.text_input("Puesto")
            area = st.text_input("Área")
            seniority = st.selectbox("Seniority", ["Pasantía", "Junior", "Semi Senior", "Senior", "Liderazgo", "Dirección"])
            description = st.text_area("Descripción")
            submitted = st.form_submit_button("Guardar búsqueda", type="primary")
            if submitted:
                if not title.strip():
                    st.error("Ingresá el nombre del puesto.")
                else:
                    execute(
                        "INSERT INTO jobs(company_id, title, area, seniority, description, created_by) VALUES (?, ?, ?, ?, ?, ?)",
                        (company["id"], title.strip(), area.strip(), seniority, description.strip(), user["id"]),
                    )
                    st.success("Búsqueda creada correctamente.")
                    st.rerun()

    elif menu == "Búsquedas":
        jobs = fetch_all(
            "SELECT id, title, area, seniority, status, created_at FROM jobs WHERE company_id = ? ORDER BY created_at DESC",
            (company["id"],),
        )
        if jobs:
            st.dataframe(pd.DataFrame(jobs), use_container_width=True, hide_index=True)
        else:
            st.info("Todavía no hay búsquedas.")

    else:
        applications = fetch_all(
            '''SELECT applications.id, users.full_name AS candidate, users.email,
                      jobs.title AS job, applications.status, applications.created_at
               FROM applications
               JOIN candidates ON candidates.id = applications.candidate_id
               JOIN users ON users.id = candidates.user_id
               JOIN jobs ON jobs.id = applications.job_id
               WHERE jobs.company_id = ?
               ORDER BY applications.created_at DESC''',
            (company["id"],),
        )
        if applications:
            st.dataframe(pd.DataFrame(applications), use_container_width=True, hide_index=True)
        else:
            st.info("Todavía no hay postulaciones.")
