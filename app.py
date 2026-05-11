import streamlit as st
from db import init_db
from auth import login_user, register_user, logout, get_carreras

st.set_page_config(page_title="PsicoNexo", page_icon="🧠", layout="centered")

init_db()

if "usuario" not in st.session_state:
    st.session_state.usuario = None
if "pagina" not in st.session_state:
    st.session_state.pagina = "login"

if st.session_state.usuario is None:
    st.title("🧠 PsicoNexo")
    st.write("Sistema cargando...")
else:
    st.write("Bienvenido")
