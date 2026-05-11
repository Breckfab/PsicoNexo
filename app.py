import streamlit as st
from db import init_db
from auth import login_user, register_user, logout, get_carreras

st.set_page_config(
    page_title="PsicoNexo",
    page_icon="🧠",
    layout="centered"
)

init_db()

if "usuario" not in st.session_state:
    st.session_state.usuario = None
if "pagina" not in st.session_state:
    st.session_state.pagina = "login"

def mostrar_login():
    st.title("🧠 PsicoNexo")
    st.subheader("Iniciá sesión")

    with st.form("form_login"):
        email = st.text_input("Email")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Ingresar")

    if submit:
        ok, msg, user = login_user(email, password)
        if ok:
            st.session_state.usuario = user
            st.session_state.pagina = "home"
            st.rerun()
        else:
            st.error(msg)

    st.markdown("---")
    if st.button("¿No tenés cuenta? Registrate"):
        st.session_state.pagina = "registro"
        st.rerun()

def mostrar_registro():
    st.title("🧠 PsicoNexo")
    st.subheader("Crear cuenta")

    carreras = get_carreras()
    opciones = {f"{c['nombre']} — {c['universidad']}": c["id"] for c in carreras}

    with st.form("form_registro"):
        nombre = st.text_input("Nombre completo")
        email = st.text_input("Email")
        password = st.text_input("Contraseña", type="password")
        password2 = st.text_input("Repetir contraseña", type="password")
        carrera_label = st.selectbox("Carrera", list(opciones.keys(
