import streamlit as st
from db import (
    init_db, crear_admin_si_no_existe, get_uso_almacenamiento, NEON_STORAGE_LIMIT_BYTES,
    generar_backup_sql, generar_backup_csv_zip, restaurar_backup_sql,
)
from auth import login_user, register_user, logout, get_carreras, generar_codigo, get_codigos
import calendar
from datetime import datetime
from pages import home, materias, cursadas, evaluaciones, recursos, profesores, estadisticas, perfil

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
if "tema_oscuro" not in st.session_state:
    st.session_state.tema_oscuro = True

def mostrar_login():
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        st.image("PsicoNexo_png.png", width=150)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("Iniciá sesión")
        with st.form("form_login"):
            email = st.text_input("Email")
            password = st.text_input("Contraseña", type="password")
            submit = st.form_submit_button("Ingresar", use_container_width=True)
        if submit:
            ok, msg, user = login_user(email, password)
            if ok:
                st.session_state.usuario = user
                st.session_state.pagina = "home"
                st.rerun()
            else:
                st.error(msg)
        st.markdown("---")
        if st.button("¿No tenés cuenta? Registrate", use_container_width=True):
            st.session_state.pagina = "registro"
            st.rerun()

def mostrar_registro():
    col1, col2, col3 = st.columns([2, 1, 2])
    with col2:
        st.image("PsicoNexo_png.png", width=150)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
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
            submit = st.form_submit_button("Registrarme", use_container_width=True)
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
        if st.button("← Volver al login", use_container_width=True):
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

    # ── Uso de almacenamiento (Neon) ─────────────────────────────────────
    # Barra de % de espacio ocupado en la base de datos, contra el límite
    # del plan contratado en Neon (NEON_STORAGE_LIMIT_BYTES en db.py — hoy
    # configurado para el plan Free, 0.5 GB). Ítem nuevo, 08/08/2026.
    st.markdown("---")
    st.markdown("### 📦 Uso de almacenamiento (Neon)")

    bytes_usados = get_uso_almacenamiento()
    limite_bytes = NEON_STORAGE_LIMIT_BYTES
    porcentaje_uso = round((bytes_usados / limite_bytes) * 100, 1) if limite_bytes else 0
    mb_usados = bytes_usados / (1024 * 1024)
    mb_limite = limite_bytes / (1024 * 1024)

    if porcentaje_uso < 75:
        color_uso = "#2ecc71"
    elif porcentaje_uso < 90:
        color_uso = "#f39c12"
    else:
        color_uso = "#e74c3c"

    ancho_barra = min(porcentaje_uso, 100)

    st.markdown(f"""
        <div style="margin-top:8px; margin-bottom:4px;">
            <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px;">
                <span style="font-size:14px; color:#ccc;">
                    Usado: <strong style="color:{color_uso};">{porcentaje_uso}%</strong> de 100%
                </span>
                <span style="font-size:12px; color:#888;">
                    {mb_usados:.1f} MB / {mb_limite:.0f} MB
                </span>
            </div>
            <div style="background:#2a2a3e; border-radius:8px; height:16px; overflow:hidden;">
                <div style="width:{ancho_barra}%; background:{color_uso}; height:16px; border-radius:8px;
                            transition:width 0.3s ease;"></div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if porcentaje_uso >= 90:
        st.error("🚨 Estás muy cerca del límite de almacenamiento del plan de Neon.")
    elif porcentaje_uso >= 75:
        st.warning("⚠️ El uso de almacenamiento está creciendo. Contemplá optimizar datos o upgradear el plan.")

    # ── Backup de la base de datos (ítem prioridad alta, 09/08/2026) ──────
    # Dos formatos: SQL (INSERTs, restaurable ejecutándolo contra una base
    # con el esquema ya creado por init_db()) y CSV (.zip con un .csv por
    # tabla, para inspeccionar en Excel/Sheets). No se generan solos en cada
    # carga de la pantalla: el botón "Generar" dispara la consulta bajo
    # demanda (1 sola conexión, todas las tablas adentro) y guarda el
    # resultado en session_state; recién ahí aparece el botón de descarga.
    # NOTA: el botón de acceso rápido del sidebar (ver mostrar_backup_sidebar
    # más abajo) usa la misma clave de session_state "backup_sql_bytes",
    # así que un backup generado desde acá también deja el botón de
    # descarga disponible en el sidebar, y viceversa.
    st.markdown("---")
    st.markdown("### 💾 Backup de la base de datos")
    st.caption(
        "El backup **SQL** trae un INSERT por fila y se puede restaurar ejecutándolo contra "
        "una base con el esquema ya creado (correr la app una vez alcanza, `init_db()` lo crea solo). "
        "El backup **CSV** trae un .zip con un archivo por tabla, para revisar los datos en Excel/Sheets."
    )

    col_bk1, col_bk2 = st.columns(2)

    with col_bk1:
        if st.button("🗄️ Generar backup SQL", use_container_width=True):
            with st.spinner("Generando backup SQL..."):
                st.session_state["backup_sql_bytes"] = generar_backup_sql()
            st.rerun()
        if "backup_sql_bytes" in st.session_state:
            st.download_button(
                label="⬇️ Descargar backup.sql",
                data=st.session_state["backup_sql_bytes"],
                file_name=f"psiconexo_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.sql",
                mime="application/sql",
                key="dl_backup_sql",
                use_container_width=True,
            )

    with col_bk2:
        if st.button("📦 Generar backup CSV (.zip)", use_container_width=True):
            with st.spinner("Generando backup CSV..."):
                st.session_state["backup_csv_bytes"] = generar_backup_csv_zip()
            st.rerun()
        if "backup_csv_bytes" in st.session_state:
            st.download_button(
                label="⬇️ Descargar backup.zip",
                data=st.session_state["backup_csv_bytes"],
                file_name=f"psiconexo_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                key="dl_backup_csv",
                use_container_width=True,
            )

    # ── Restaurar backup (ítem prioridad alta, 10/08/2026) ────────────────
    # Decisiones de diseño (ver comentarios en restaurar_backup_sql(), db.py):
    # upsert por id (no borra nada salvo modo espejo), fila por fila con
    # SAVEPOINT (un error puntual no aborta el resto), doble confirmación
    # antes de ejecutar — mismo patrón que ya se usa para borrar cursadas/
    # tareas/feriados en el resto del sistema.
    st.markdown("---")
    st.markdown("### 📥 Restaurar backup")
    st.caption(
        "Subí un .sql generado por los botones de arriba (o el de acceso rápido del "
        "sidebar). Por cada fila: si el id ya existe en la base, la actualiza con los "
        "valores del backup; si no existe, la inserta. **No borra nada** que esté en la "
        "base y no esté en el backup, salvo que actives el modo espejo de abajo."
    )

    archivo_restore = st.file_uploader(
        "Archivo .sql de backup", type=["sql"], key="uploader_restore_backup"
    )

    modo_espejo = st.checkbox(
        "🗑️ Modo espejo: además, borrar las filas que NO estén en este backup "
        "(incluye vaciar por completo cualquier tabla que en el backup tenga 0 filas). "
        "Deja la base exactamente como estaba en el momento en que se generó el backup.",
        key="chk_modo_espejo_restore",
    )

    if archivo_restore is not None:
        if not st.session_state.get("confirmar_restore_backup"):
            if st.button("♻️ Restaurar backup", use_container_width=True, key="btn_iniciar_restore"):
                st.session_state["confirmar_restore_backup"] = True
                st.rerun()
        else:
            texto_advertencia = "⚠️ Esto va a modificar la base de datos en vivo."
            if modo_espejo:
                texto_advertencia += " Además va a **BORRAR** las filas que no estén en este backup."
            texto_advertencia += " Esta acción no se puede deshacer. ¿Confirmás?"
            st.warning(texto_advertencia)

            col_si, col_no = st.columns(2)
            with col_si:
                if st.button("✅ Sí, restaurar ahora", use_container_width=True, key="btn_confirmar_restore"):
                    try:
                        with st.spinner("Restaurando backup..."):
                            resultado = restaurar_backup_sql(
                                archivo_restore.getvalue(), modo_espejo=modo_espejo
                            )
                        st.session_state["resultado_restore_backup"] = resultado
                    except ValueError as e:
                        st.session_state["resultado_restore_backup"] = None
                        st.session_state["error_restore_backup"] = str(e)
                    st.session_state["confirmar_restore_backup"] = False
                    st.rerun()
            with col_no:
                if st.button("❌ Cancelar", use_container_width=True, key="btn_cancelar_restore"):
                    st.session_state["confirmar_restore_backup"] = False
                    st.rerun()

    if st.session_state.get("error_restore_backup"):
        st.error(f"⚠️ {st.session_state['error_restore_backup']}")
        if st.button("Cerrar", key="cerrar_error_restore"):
            del st.session_state["error_restore_backup"]
            st.rerun()

    if st.session_state.get("resultado_restore_backup"):
        resultado = st.session_state["resultado_restore_backup"]
        st.success(f"✅ {resultado['ok_total']} fila(s) restauradas correctamente (insertadas o actualizadas).")
        if resultado["borradas"]:
            st.info(f"🗑️ {resultado['borradas']} fila(s) borradas por el modo espejo.")
        if resultado["error_total"]:
            st.error(f"⚠️ {resultado['error_total']} fila(s) no se pudieron restaurar.")
            with st.expander("Ver detalle de errores (hasta 50)"):
                for tabla, id_str, msg in resultado["errores"]:
                    st.caption(f"**{tabla}** (id {id_str}): {msg}")
        if st.button("Cerrar resumen", key="cerrar_resumen_restore"):
            del st.session_state["resultado_restore_backup"]
            st.rerun()

def mostrar_backup_sidebar(usuario):
    """
    Acceso rápido al backup SQL desde el sidebar (ítem #2 de
    PSICO_Mejoras_Pendientes_v2.md, 09/08/2026), para no tener que ir hasta
    Administración cada vez. Solo visible para es_admin, mismo criterio que
    el resto del panel de Administración.

    Reutiliza generar_backup_sql() de db.py (sin duplicar lógica) y la
    misma clave de session_state "backup_sql_bytes" que usa el botón de
    Administración, así que generar el backup desde cualquiera de los dos
    lugares deja el botón de descarga disponible en ambos.

    Color: el CSS que fuerza el ámbar (#D97706) vive en mostrar_sidebar()
    (un solo bloque <style> para el botón de acá y el de "Cerrar sesión"),
    apuntando a la clase ".st-key-btn_backup_sidebar" que Streamlit genera
    automáticamente a partir del key del botón — ver el comentario en
    mostrar_sidebar() para el detalle de por qué se cambió de enfoque
    (10/08/2026, fix de color).
    """
    if not usuario.get("es_admin"):
        return

    st.markdown("---")

    if st.button("💾 Backup rápido", use_container_width=True, key="btn_backup_sidebar"):
        with st.spinner("Generando backup..."):
            st.session_state["backup_sql_bytes"] = generar_backup_sql()
        st.rerun()

    if "backup_sql_bytes" in st.session_state:
        st.download_button(
            label="⬇️ Descargar backup.sql",
            data=st.session_state["backup_sql_bytes"],
            file_name=f"psiconexo_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.sql",
            mime="application/sql",
            key="dl_backup_sql_sidebar",
            use_container_width=True,
        )

def mostrar_sidebar(usuario):
    with st.sidebar:
        tema_label = "🌙 Modo oscuro" if st.session_state.tema_oscuro else "☀️ Modo claro"
        if st.button(tema_label, use_container_width=True):
            st.session_state.tema_oscuro = not st.session_state.tema_oscuro
            st.rerun()

        st.markdown("---")

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

        dias_semana = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do"]
        cols = st.columns(7)
        for i, d in enumerate(dias_semana):
            cols[i].markdown(f"<div style='text-align:center; font-size:11px; color:#aaa;'>{d}</div>", unsafe_allow_html=True)

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

        # ── Colores forzados de "Cerrar sesión" y "Backup rápido" (fix
        # 10/08/2026) ────────────────────────────────────────────────────
        # Versión anterior: un <div id="..."> invisible + selector CSS de
        # hermano adyacente ("#ancla + div button"). No funcionaba, porque
        # cada st.markdown()/st.button() queda envuelto en su propio
        # contenedor de Streamlit — el <div> del ancla termina anidado un
        # nivel más adentro de lo que el combinador "+" puede alcanzar, así
        # que la regla nunca llegaba a matchear el botón real (por eso el
        # botón de Backup no salía anaranjado, y el de Salir nunca se forzó
        # a azul).
        #
        # Reemplazado por el patrón soportado de forma nativa por Streamlit:
        # todo widget con un "key" recibe automáticamente la clase CSS
        # ".st-key-<key>" en su contenedor, sin depender de la posición en
        # el DOM. Un solo bloque <style> de acá cubre los dos botones del
        # sidebar (Salir y Backup), cada uno con su propio key:
        #   - "btn_logout_sidebar" → azul (#2563EB, hover #1D4ED8)
        #   - "btn_backup_sidebar" → ámbar/anaranjado (#D97706, hover #B45309)
        st.markdown("""
            <style>
            .st-key-btn_logout_sidebar button {
                background-color: #2563EB !important;
                border-color: #2563EB !important;
                color: white !important;
            }
            .st-key-btn_logout_sidebar button:hover {
                background-color: #1D4ED8 !important;
                border-color: #1D4ED8 !important;
                color: white !important;
            }
            .st-key-btn_backup_sidebar button {
                background-color: #D97706 !important;
                border-color: #D97706 !important;
                color: white !important;
            }
            .st-key-btn_backup_sidebar button:hover {
                background-color: #B45309 !important;
                border-color: #B45309 !important;
                color: white !important;
            }
            </style>
        """, unsafe_allow_html=True)

        if st.button("🚪 Cerrar sesión", use_container_width=True, key="btn_logout_sidebar"):
            logout()
            st.rerun()

        # ── Backup rápido (ítem #2, 09/08/2026) — debajo de "Cerrar sesión",
        # solo para es_admin. Ver mostrar_backup_sidebar() para el detalle.
        mostrar_backup_sidebar(usuario)

def mostrar_navbar(usuario):
    st.markdown("""
        <div style="text-align:center; margin-bottom:8px;">
            <span style="color:white; font-size:16px; font-weight:600; letter-spacing:2px;">
                SISTEMA PARA ESTUDIANTES DE PSICOLOGÍA
            </span>
        </div>
    """, unsafe_allow_html=True)

    legajo_display = usuario.get("legajo") or "Pendiente"

    st.markdown(f"""
        <div style="background-color:#1E1E2E; padding:12px 20px; border-radius:10px; margin-bottom:10px;
                    display:flex; align-items:center; justify-content:center; position:relative;">
            <span style="color:white; font-size:28px; font-weight:bold; text-align:center;">🧠 PsicoNexo</span>
            <div style="position:absolute; right:30px; text-align:right;">
                <div style="color:#ccc; font-size:13px;">👤 {usuario['nombre']}</div>
                <div style="color:#E0D4FF; font-size:15px; font-weight:bold; margin-top:3px;">🪪 Legajo: {legajo_display}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    items = ["🏠 Inicio", "📚 Plan de Estudios", "🗓️ Materias", "📝 Notas", "📂 Recursos", "⭐ Profesores", "📊 Estadísticas", "👤 Mi Perfil"]
    if usuario.get("es_admin"):
        items.append("🔧 Administración")

    paginas = {
        "🏠 Inicio": "home",
        "📚 Plan de Estudios": "materias",
        "🗓️ Materias": "cursadas",
        "📝 Notas": "evaluaciones",
        "📂 Recursos": "recursos",
        "⭐ Profesores": "profesores",
        "📊 Estadísticas": "estadisticas",
        "👤 Mi Perfil": "perfil",
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

    pagina = st.session_state.pagina

    if pagina == "home":
        home.mostrar(usuario)
    elif pagina == "materias":
        materias.mostrar(usuario)
    elif pagina == "cursadas":
        cursadas.mostrar(usuario)
    elif pagina == "evaluaciones":
        evaluaciones.mostrar(usuario)
    elif pagina == "recursos":
        recursos.mostrar(usuario)
    elif pagina == "profesores":
        profesores.mostrar(usuario)
    elif pagina == "estadisticas":
        estadisticas.mostrar(usuario)
    elif pagina == "perfil":
        perfil.mostrar(usuario)
    elif pagina == "admin" and usuario.get("es_admin"):
        mostrar_admin()
    else:
        home.mostrar(usuario)

# ── Punto de entrada principal ─────────────────────────────────────────────
if st.session_state.usuario is None:
    if st.session_state.pagina == "registro":
        mostrar_registro()
    else:
        mostrar_login()
else:
    mostrar_app()
