import streamlit as st
from db import init_db, crear_admin_si_no_existe
from auth import login_user, register_user, logout, get_carreras, generar_codigo, get_codigos
import calendar
from datetime import datetime

st.set_page_config(page_title="PsicoNexo", page_icon="Psicologia_favicon_png.png", layout="wide")

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
if "cal_mes" not in st.session_state:
    st.session_state.cal_mes = datetime.now().month
if "cal_anio" not in st.session_state:
    st.session_state.cal_anio = datetime.now().year

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

def mostrar_sidebar(usuario):
    with st.sidebar:
        # Reloj y fecha
        st.components.v1.html("""
            <div style="text-align:center; padding:10px 0;">
                <div id="reloj" style="font-family:monospace; font-size:32px; font-weight:bold; color:#A78BFA;"></div>
                <div id="fecha" style="font-size:12px; color:#aaa; margin-top:4px;"></div>
            </div>
            <script>
            const dias = ['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'];
            const meses = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
            function actualizar() {
                const now = new Date();
                const h = String(now.getHours()).padStart(2,'0');
                const m = String(now.getMinutes()).padStart(2,'0');
                const s = String(now.getSeconds()).padStart(2,'0');
                document.getElementById('reloj').textContent = h + ':' + m + ':' + s;
                const dia = dias[now.getDay()];
                const fecha = now.getDate() + ' de ' + meses[now.getMonth()] + ' de ' + now.getFullYear();
                document.getElementById('fecha').textContent = dia + ', ' + fecha;
            }
            actualizar();
            setInterval(actualizar, 1000);
            </script>
        """, height=80)

        st.markdown("---")

        # Calendario
        hoy = datetime.now()
        mes = st.session_state.cal_mes
        anio = st.session_state.cal_anio

        nombres_meses = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                         "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

        col_prev, col_titulo, col_next = st.columns([1, 3, 1])
        with col_prev:
            if st.button("◀", key="cal_prev"):
                if mes == 1:
                    st.session_state.cal_mes = 12
                    st.session_state.cal_anio = anio - 1
                else:
                    st.session_state.cal_mes = mes - 1
                st.rerun()
        with col_titulo:
            st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:13px;'>{nombres_meses[mes-1]} {anio}</div>", unsafe_allow_html=True)
        with col_next:
            if st.button("▶", key="cal_next"):
                if mes == 12:
                    st.session_state.cal_mes = 1
                    st.session_state.cal_anio = anio + 1
                else:
                    st.session_state.cal_mes = mes + 1
                st.rerun()

        # Días de la semana
        dias_semana = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]
        cols = st.columns(7)
        for i, d in enumerate(dias_semana):
            cols[i].markdown(f"<div style='text-align:center; font-size:11px; color:#aaa;'>{d}</div>", unsafe_allow_html=True)

        # Días del mes
        cal = calendar.monthcalendar(anio, mes)
        for semana in cal:
            cols = st.columns(7)
            for i, dia in enumerate(semana):
                if dia == 0:
                    cols[i].markdown(" ")
                elif dia == hoy.day and mes == hoy.month and anio == hoy.year:
                    cols[i].markdown(f"<div style='text-align:center; background:#7B2FBE; color:white; border-radius:50%; font-size:12px; font-weight:bold;'>{dia}</div>", unsafe_allow_html=True)
                else:
                    cols[i].markdown(f"<div style='text-align:center; font-size:12px;'>{dia}</div>", unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🚪 Cerrar sesión", use_container_width=True):
            logout()
            st.rerun()

def mostrar_navbar(usuario):
    st.markdown("""
        <div style="text-align:center; margin-bottom:8px;">
            <span style="color:white; font-size:16px; font-weight:600; letter-spacing:2px;">
                SISTEMA PARA ESTUDIANTES DE PSICOLOGÍA
            </span>
        </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <div style="background-color:#1E1E2E; padding:8px 20px; border-radius:10px; margin-bottom:10px;
                    display:flex; align-items:center; justify-content:space-between;">
            <span style="color:white; font-size:18px; font-weight:bold;">🧠 PsicoNexo</span>
            <span style="color:#ccc; font-size:13px;">👤 {usuario['nombre']}</span>
        </div>
    """, unsafe_allow_html=True)

    items = ["🏠 Inicio", "📚 Plan de Estudios", "🗓️ Cursadas", "📂 Recursos"]
    if usuario.get("es_admin"):
        items.append("🔧 Administración")

    paginas = {
        "🏠 Inicio": "home",
        "📚 Plan de Estudios": "materias",
        "🗓️ Cursadas": "cursadas",
        "📂 Recursos": "recursos",
        "🔧 Administración": "admin",
    }

    cols = st.columns(len(items))
    for i, item in enumerate(items):
        with cols[i]:
            if st.button(item, use_container_width=True):
                st.session_state.pagina = paginas[item]
                st.rerun()

def mostrar_app():
    usuario = st.session_state.usuario
    mostrar_sidebar(usuario)
    mostrar_navbar(usuario)

    if st.session_state.pagina == "materias":
        from pages import materias
        materias.mostrar(usuario)
    elif st.session_state.pagina == "cursadas":
        from pages import cursadas
        cursadas.mostrar(usuario)
    elif st.session_state.pagina == "recursos":
        from pages import recursos
        recursos.mostrar(usuario)
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
