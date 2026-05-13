import streamlit as st
from db import init_db
from auth import login_user, register_user, logout, get_carreras

st.set_page_config(page_title="PsicoNexo", page_icon="🧠", layout="centered")

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
    opciones = {f"{c[1]} — {c[2]}": c[0] for c in carreras}
    with st.form("form_registro"):
        nombre = st.text_input("Nombre completo")
        email = st.text_input("Email")
        password = st.text_input("Contraseña", type="password")
        password2 = st.text_input("Repetir contraseña", type="password")
        carrera_label = st.selectbox("Carrera", list(opciones.keys()))
        submit = st.form_submit_button("Registrarme")
    if submit:
        if not nombre or not email or not password:
            st.error("Completá todos los campos.")
        elif password != password2:
            st.error("Las contraseñas no coinciden.")
        else:
            carrera_id = opciones[carrera_label]
            ok, msg = register_user(email, password, nombre, carrera_id)
            if ok:
                st.success("Cuenta creada. Ya podés iniciar sesión.")
                st.session_state.pagina = "login"
                st.rerun()
            else:
                st.error(msg)
    st.markdown("---")
    if st.button("← Volver al login"):
        st.session_state.pagina = "login"
        st.rerun()

def mostrar_app():
    usuario = st.session_state.usuario

    with st.sidebar:
        st.markdown(f"### 👤 {usuario['nombre']}")
        st.markdown("---")
        st.markdown("📋 **Menú**")
        if st.button("🏠 Inicio"):
            st.session_state.pagina = "home"
            st.rerun()
        if st.button("📚 Plan de Estudios"):
            st.session_state.pagina = "materias"
            st.rerun()
        st.markdown("---")
        if st.button("Cerrar sesión"):
            logout()
            st.rerun()

    st.write(f"DEBUG carrera_id: {usuario['carrera_id']}")

    if st.session_state.pagina == "materias":
        from pages import materias
        materias.mostrar(usuario)
    else:
        from pages import home
        home.mostrar(usuario)

if st.session_state.usuario is None:
    if st.session_state.pagina == "registro":
        mostrar_registro()
    else:
        mostrar_login()
else:
    mostrar_app()
