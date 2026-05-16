import streamlit as st
from db import init_db, crear_admin_si_no_existe
from auth import login_user, register_user, logout, get_carreras, generar_codigo, get_codigos

st.set_page_config(page_title="PsicoNexo", page_icon="🧠", layout="centered")

# Ocultar sidebar antes del login
if "usuario" not in st.session_state or st.session_state.usuario is None:
    st.markdown("""
        <style>
        [data-testid="stSidebar"] {display: none;}
        </style>
    """, unsafe_allow_html=True)

init_db()
crear_admin_si_no_existe()

if "usuario" not in st.session_state:
    st.session_state.usuario = None
if "pagina" not in st.session_state:
    st.session_state.pagina = "login"

def mostrar_login():
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.image("PsicoNexo_png.png", use_container_width=True)
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
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.image("PsicoNexo_png.png", use_container_width=True)
    st.subheader("Crear cuenta")
    carreras = get_carreras()
    opciones = {f"{c[1]} — {c[2]}": c[0] for c in carreras}
    with st.form("form_registro"):
        nombre = st.text_input("Nombre completo")
        email = st.text_input("Email")
        password = st.text_input("Contraseña", type="password")
        password2 = st.text_input("Repetir contraseña", type="password")
        codigo = st.text_input("Código de invitación")
        carrera_label = st.selectbox("Carrera", list(opciones.keys()))
        submit = st.form_submit_button("Registrarme")
    if submit:
        if not nombre or not email or not password or not codigo:
            st.error("Completá todos los campos.")
        elif password != password2:
            st.error("Las contraseñas no coinciden.")
        else:
            carrera_id = opciones[carrera_label]
            ok, msg = register_user(email, password, nombre, carrera_id, codigo)
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

def mostrar_admin():
    st.title("🔧 Panel de Administración")
    usuario = st.session_state.usuario

    st.markdown("### Generar código de invitación")
    if st.button("Generar nuevo código"):
        codigo = generar_codigo(usuario["id"])
        st.success(f"Código generado: **{codigo}**")

    st.markdown("### Códigos generados")
    codigos = get_codigos(usuario["id"])
    if codigos:
        for c in codigos:
            estado = "✅ Usado" if c[1] else "⏳ Disponible"
            usado_por = f" — usado por {c[2]}" if c[2] else ""
            st.markdown(f"**{c[0]}** — {estado}{usado_por}")
    else:
        st.info("No hay códigos generados todavía.")

def mostrar_app():
    usuario = st.session_state.usuario

    with st.sidebar:
        st.image("PsicoNexo_png.png", use_container_width=True)
        st.markdown(f"### 👤 {usuario['nombre']}")
        st.markdown("---")
        if st.button("🏠 Inicio"):
            st.session_state.pagina = "home"
            st.rerun()
        if st.button("📚 Plan de Estudios"):
            st.session_state.pagina = "materias"
            st.rerun()
        if usuario.get("es_admin"):
            if st.button("🔧 Administración"):
                st.session_state.pagina = "admin"
                st.rerun()
        st.markdown("---")
        if st.button("Cerrar sesión"):
            logout()
            st.rerun()

    if st.session_state.pagina == "materias":
        from pages import materias
        materias.mostrar(usuario)
    elif st.session_state.pagina == "admin":
        mostrar_admin()
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
