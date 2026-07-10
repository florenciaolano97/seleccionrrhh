import streamlit as st


def current_user():
    return st.session_state.get("auth_user")


def logout():
    st.session_state.pop("auth_user", None)
    st.rerun()
