from __future__ import annotations

import streamlit as st

from auth.ui import render_login, render_registration
from candidate.portal import render_candidate_portal
from company.portal import render_company_portal
from config import APP_NAME
from database.db import init_db
from shared.session import current_user, logout


st.set_page_config(
    page_title=APP_NAME,
    page_icon="🤖",
    layout="wide",
)

init_db()

user = current_user()

if not user:
    st.title(APP_NAME)
    st.caption("Base modular estable para empresas y candidatos.")

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
