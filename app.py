import pandas as pd
import streamlit as st

from config import APP_NAME
from modules.database import init_db, fetch_all
from modules.privacy import evaluation_policy_text
from modules.scoring import explain_default_weights
from modules.services import (
    create_application,
    create_candidate,
    create_company,
    create_job,
    list_applications,
    list_companies,
    list_jobs,
)

st.set_page_config(page_title=APP_NAME, page_icon="🤖", layout="wide")
init_db()

st.title(APP_NAME)
st.caption("Módulo 1: arquitectura, base de datos y portales iniciales")

with st.sidebar:
    portal = st.radio("Ingresar como", ["Portal Reclutador", "Portal Candidato", "Criterios y privacidad"])
    st.divider()
    st.info("Esta versión es una base funcional. Los módulos de CV masivo, Alba, ranking avanzado e informes se incorporan en las próximas entregas.")

if portal == "Portal Reclutador":
    st.header("Portal del reclutador")
    tab1, tab2, tab3, tab4 = st.tabs(["Empresas", "Búsquedas", "Postulaciones", "Auditoría"])

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
            st.dataframe(pd.DataFrame(companies), use_container_width=True, hide_index=True)
        else:
            st.info("Todavía no hay empresas registradas.")

    with tab2:
        companies = list_companies()
        if not companies:
            st.warning("Primero creá una empresa.")
        else:
            options = {f"{c['name']} — {c['industry'] or 'Sin industria'}": c["id"] for c in companies}
            with st.form("job_form"):
                company_label = st.selectbox("Empresa", list(options.keys()))
                title = st.text_input("Puesto")
                c1, c2 = st.columns(2)
                area = c1.text_input("Área")
                seniority = c2.selectbox("Seniority", ["Pasantía", "Junior", "Semi Senior", "Senior", "Liderazgo", "Dirección"])
                description = st.text_area("Descripción del puesto")
                must_have = st.text_area("Requisitos excluyentes")
                desirable = st.text_area("Requisitos deseables")
                submitted = st.form_submit_button("Crear búsqueda")
                if submitted:
                    if not title.strip():
                        st.error("Ingresá el nombre del puesto.")
                    else:
                        create_job(options[company_label], title, area, seniority, description, must_have, desirable)
                        st.success("Búsqueda creada correctamente.")
                        st.rerun()

        jobs = list_jobs()
        if jobs:
            st.dataframe(pd.DataFrame(jobs), use_container_width=True, hide_index=True)

    with tab3:
        applications = list_applications()
        if applications:
            df = pd.DataFrame(applications)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Todavía no hay postulaciones.")

    with tab4:
        audit = fetch_all("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200")
        if audit:
            st.dataframe(pd.DataFrame(audit), use_container_width=True, hide_index=True)
        else:
            st.info("Todavía no hay eventos de auditoría.")

elif portal == "Portal Candidato":
    st.header("Portal del candidato")
    jobs = list_jobs()
    if not jobs:
        st.warning("Todavía no existen búsquedas abiertas.")
    else:
        job_options = {f"{j['title']} — {j['company_name']}": j["id"] for j in jobs if j["status"] == "ABIERTA"}
        with st.form("candidate_form"):
            selected = st.selectbox("Búsqueda", list(job_options.keys()))
            st.subheader("Datos de contacto")
            c1, c2 = st.columns(2)
            full_name = c1.text_input("Nombre y apellido")
            email = c2.text_input("Correo electrónico")
            c3, c4 = st.columns(2)
            phone = c3.text_input("Teléfono")
            dni = c4.text_input("DNI")
            c5, c6 = st.columns(2)
            birth_date = c5.date_input("Fecha de nacimiento", value=None)
            city = c6.text_input("Ciudad")
            consent = st.checkbox(
                "Acepto que mis datos sean tratados para gestionar la postulación. Comprendo que los datos administrativos no se usarán para puntuar ni rankear."
            )
            submitted = st.form_submit_button("Enviar postulación")
            if submitted:
                if not full_name.strip() or not email.strip() or not consent:
                    st.error("Completá nombre, correo y consentimiento.")
                else:
                    candidate_id = create_candidate(
                        full_name, email, phone, dni, birth_date.isoformat() if birth_date else "", city, consent
                    )
                    app_id = create_application(candidate_id, job_options[selected])
                    st.success(f"Postulación registrada. Código interno: APP-{app_id:06d}")
                    st.info("En los próximos módulos se habilitarán carga de CV, entrevista con Alba y seguimiento.")

else:
    st.header("Criterios de evaluación y privacidad")
    st.subheader("Distribución inicial del puntaje")
    st.dataframe(pd.DataFrame(explain_default_weights()), use_container_width=True, hide_index=True)
    st.caption("Las ponderaciones serán configurables por búsqueda en el módulo de scoring avanzado.")

    st.subheader("Política de datos")
    st.write(evaluation_policy_text())
    st.markdown(
        """
        **Datos administrativos del candidato:** pueden almacenarse para contacto y gestión, pero quedan excluidos del ranking.

        **Datos evaluables:** experiencia, conocimientos, formación, competencias, respuestas y resultados de pruebas.

        **Información de la empresa:** no deben cargarse secretos comerciales, credenciales, precios, clientes ni procesos confidenciales.
        """
    )
