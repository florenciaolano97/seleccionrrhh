import streamlit as st
from auth.service import authenticate, register_candidate, register_company_admin

def render_login():
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

def render_registration():
    st.subheader("Crear cuenta")
    account_type = st.radio("Tipo de cuenta", ["Empresa", "Candidato"], horizontal=True)
    if account_type == "Empresa":
        with st.form("register_company"):
            company_name = st.text_input("Nombre de la empresa")
            industry = st.text_input("Industria")
            country = st.text_input("País", value="Argentina")
            full_name = st.text_input("Nombre del administrador")
            email = st.text_input("Correo electrónico")
            password = st.text_input("Contraseña", type="password")
            repeat = st.text_input("Repetir contraseña", type="password")
            submitted = st.form_submit_button("Crear empresa", type="primary")
            if submitted:
                try:
                    if password != repeat:
                        raise ValueError("Las contraseñas no coinciden.")
                    register_company_admin(company_name, industry, country, full_name, email, password)
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
            consent = st.checkbox("Acepto el tratamiento de mis datos para gestionar postulaciones.")
            submitted = st.form_submit_button("Crear cuenta", type="primary")
            if submitted:
                try:
                    if password != repeat:
                        raise ValueError("Las contraseñas no coinciden.")
                    if not consent:
                        raise ValueError("Tenés que aceptar el consentimiento.")
                    register_candidate(full_name, email, password, phone, dni, city)
                    st.success("Cuenta creada. Ya podés iniciar sesión.")
                except Exception as exc:
                    st.error(str(exc))
