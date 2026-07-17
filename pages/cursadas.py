import streamlit as st
from db import get_conn, get_feriados
from datetime import datetime, date, timedelta

MODALIDADES = ["Presencial", "Híbrida", "Asincrónica"]
TURNOS = ["Mañana", "Tarde", "Noche"]
CUATRIMESTRES = ["1° Cuatrimestre", "2° Cuatrimestre", "Anual"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

DIA_INDEX = {"Lunes": 0, "Martes": 1, "Miércoles": 2, "Jueves": 3, "Viernes": 4, "Sábado": 5, "Domingo": 6}

@st.cache_data(ttl=60)
def get_materias_cursando(usuario_id, carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.nombre, m.anio
                FROM materias m
                JOIN alumno_materias am ON m.id = am.materia_id
                WHERE am.usuario_id = %s AND am.estado = 'cursando'
                AND m.carrera_id = %s
                ORDER BY m.anio, m.nombre;
            """, (usuario_id, carrera_id))
            return cur.fetchall()

@st.cache_data(ttl=120)
def get_todas_materias(carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, anio FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, nombre;
            """, (carrera_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_todas_cursadas(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT materia_id, id, anio_cursada, cuatrimestre, modalidad, dias, horario, link,
                       profesor1, email_profesor1, profesor2, email_profesor2, turno
                FROM cursadas
                WHERE usuario_id = %s
                ORDER BY anio_cursada DESC, id DESC;
            """, (usuario_id,))
            rows = cur.fetchall()
    result = {}
    for row in rows:
        mid = row[0]
        if mid not in result:
            result[mid] = row[1:]
    return result

@st.cache_data(ttl=60)
def get_clases_hoy(usuario_id):
    hoy = datetime.now()
    dia_semana = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][hoy.weekday()]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.nombre, c.horario, c.link, c.modalidad
                FROM cursadas c
                JOIN materias m ON c.materia_id = m.id
                JOIN alumno_materias am ON am.materia_id = m.id AND am.usuario_id = c.usuario_id
                WHERE c.usuario_id = %s
                AND am.estado = 'cursando'
                AND c.dias ILIKE %s;
            """, (usuario_id, f"%{dia_semana}%"))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_todos_programas_cursada(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT materia_id, link FROM programas WHERE usuario_id = %s;", (usuario_id,))
            return {row[0]: row[1] for row in cur.fetchall()}

@st.cache_data(ttl=60)
def get_tareas_materia(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, numero, descripcion, fecha_vencimiento, completada
                FROM tareas
                WHERE usuario_id = %s AND materia_id = %s
                ORDER BY numero;
            """, (usuario_id, materia_id))
            return cur.fetchall()

def guardar_cursada(usuario_id, materia_id, anio, cuatrimestre, modalidad, turno, dias, horario, link, profesor1, email_profesor1, profesor2, email_profesor2):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cursadas (usuario_id, materia_id, anio_cursada, cuatrimestre, modalidad, turno, dias, horario, link, profesor1, email_profesor1, profesor2, email_profesor2)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (usuario_id, materia_id, anio_cursada, cuatrimestre)
                DO UPDATE SET modalidad = EXCLUDED.modalidad, turno = EXCLUDED.turno,
                              dias = EXCLUDED.dias, horario = EXCLUDED.horario,
                              link = EXCLUDED.link, profesor1 = EXCLUDED.profesor1,
                              email_profesor1 = EXCLUDED.email_profesor1,
                              profesor2 = EXCLUDED.profesor2,
                              email_profesor2 = EXCLUDED.email_profesor2;
            """, (usuario_id, materia_id, anio, cuatrimestre, modalidad, turno, dias, horario, link, profesor1, email_profesor1, profesor2, email_profesor2))
        conn.commit()
    get_todas_cursadas.clear()
    get_clases_hoy.clear()

def borrar_cursada(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cursadas WHERE usuario_id = %s AND materia_id = %s;", (usuario_id, materia_id))
        conn.commit()
    get_todas_cursadas.clear()
    get_clases_hoy.clear()

def guardar_tarea(usuario_id, materia_id, numero, descripcion, fecha_vencimiento):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tareas (usuario_id, materia_id, numero, descripcion, fecha_vencimiento)
                VALUES (%s, %s, %s, %s, %s);
            """, (usuario_id, materia_id, numero, descripcion, fecha_vencimiento))
        conn.commit()
    get_tareas_materia.clear()

def actualizar_tarea(tarea_id, descripcion, fecha_vencimiento, completada):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tareas SET descripcion = %s, fecha_vencimiento = %s, completada = %s
                WHERE id = %s;
            """, (descripcion, fecha_vencimiento, completada, tarea_id))
        conn.commit()
    get_tareas_materia.clear()

def borrar_tarea(tarea_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tareas WHERE id = %s;", (tarea_id,))
        conn.commit()
    get_tareas_materia.clear()

def convertir_link_drive(link):
    if "drive.google.com" in link and "/file/d/" in link:
        try:
            file_id = link.split("/file/d/")[1].split("/")[0]
            return f"https://drive.google.com/file/d/{file_id}/preview"
        except:
            return None
    return None

# ─── Asistencia ────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_config_cuatrimestre_materia(usuario_id, anio, cuatrimestre):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha_inicio, fecha_fin
                FROM configuracion_cuatrimestre
                WHERE usuario_id = %s AND anio = %s AND cuatrimestre = %s;
            """, (usuario_id, anio, cuatrimestre))
            return cur.fetchone()

@st.cache_data(ttl=60)
def get_faltas_materia(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, fecha, justificada
                FROM asistencias
                WHERE usuario_id = %s AND materia_id = %s
                ORDER BY fecha DESC;
            """, (usuario_id, materia_id))
            return cur.fetchall()

def agregar_falta(usuario_id, materia_id, fecha, justificada=False):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO asistencias (usuario_id, materia_id, fecha, justificada)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (usuario_id, materia_id, fecha)
                DO UPDATE SET justificada = EXCLUDED.justificada;
            """, (usuario_id, materia_id, fecha, justificada))
        conn.commit()
    get_faltas_materia.clear()

def borrar_falta(falta_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM asistencias WHERE id = %s;", (falta_id,))
        conn.commit()
    get_faltas_materia.clear()

def contar_clases_en_rango(dias_str, fecha_inicio, fecha_fin, feriados=None):
    """Cuenta cuántas veces caen los días de cursada dentro del rango de fechas.
    `feriados`, si se pasa, es un set/conjunto de fechas (date) que se descuentan
    del conteo aunque coincidan con un día de cursada."""
    if not dias_str or not fecha_inicio or not fecha_fin or fecha_fin < fecha_inicio:
        return 0
    dias_lista = [d.strip() for d in dias_str.split(",") if d.strip()]
    indices = {DIA_INDEX[d] for d in dias_lista if d in DIA_INDEX}
    if not indices:
        return 0
    feriados = feriados or set()
    total = 0
    fecha = fecha_inicio
    while fecha <= fecha_fin:
        if fecha.weekday() in indices and fecha not in feriados:
            total += 1
        fecha += timedelta(days=1)
    return total

def clasificar_asistencia(porcentaje):
    """Devuelve (color, negrita) según qué tan cerca está el alumno del límite del 75%."""
    if porcentaje >= 85:
        return "#2ecc71", False
    elif porcentaje >= 75:
        return "#f0c000", True
    else:
        return "#e74c3c", True

def calcular_asistencia(usuario_id, materia_id, dias_str, anio_cursada, cuatrimestre, feriados=None):
    config = get_config_cuatrimestre_materia(usuario_id, anio_cursada, cuatrimestre)
    if not config:
        return None
    fecha_inicio, fecha_fin = config
    clases_totales = contar_clases_en_rango(dias_str, fecha_inicio, fecha_fin, feriados)
    if clases_totales == 0:
        return None
    faltas = get_faltas_materia(usuario_id, materia_id)
    cantidad_faltas = len(faltas)
    porcentaje = round(((clases_totales - cantidad_faltas) / clases_totales) * 100, 1)
    max_faltas_permitidas = int(clases_totales * 0.25)
    faltas_restantes = max_faltas_permitidas - cantidad_faltas
    return {
        "clases_totales": clases_totales,
        "faltas": cantidad_faltas,
        "porcentaje": porcentaje,
        "faltas_restantes": faltas_restantes,
        "max_faltas_permitidas": max_faltas_permitidas,
        "detalle_faltas": faltas,
    }

def mostrar_asistencia(usuario, mid, dias, anio, cuatri):
    st.markdown("---")
    st.markdown("#### 📅 Asistencia")

    # ── Diagnóstico paso a paso (nunca se queda mudo) ─────────────────
    config = get_config_cuatrimestre_materia(usuario["id"], anio, cuatri)
    if not config:
        st.caption(
            f"⚙️ No encontré fechas configuradas para **{cuatri} {anio}**. "
            f"Andá a Inicio → '⚙️ Configurar fechas del cuatrimestre', elegí ese cuatrimestre y ese año, y guardalas."
        )
        return

    feriados_set = {f[1] for f in get_feriados(usuario["id"])}

    fecha_inicio, fecha_fin = config
    clases_totales = contar_clases_en_rango(dias, fecha_inicio, fecha_fin, feriados_set)
    if clases_totales == 0:
        st.caption(
            f"📅 No pude calcular clases. Días cargados: **'{dias or '—'}'** · "
            f"Rango configurado: {fecha_inicio.strftime('%d/%m/%Y')} → {fecha_fin.strftime('%d/%m/%Y')}. "
            f"Revisá que los días de cursada estén cargados en esta materia (editar cursada → Días)."
        )
        return

    stats = calcular_asistencia(usuario["id"], mid, dias, anio, cuatri, feriados_set)
    porcentaje = stats["porcentaje"]
    color, negrita = clasificar_asistencia(porcentaje)
    peso = "bold" if negrita else "normal"
    restantes = max(stats["faltas_restantes"], 0)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"<div style='text-align:center;'><div style='font-size:11px; color:#aaa;'>Asistencia</div>"
            f"<div style='font-size:26px; font-weight:{peso}; color:{color};'>{porcentaje}%</div></div>",
            unsafe_allow_html=True
        )
    with col2:
        st.markdown(
            f"<div style='text-align:center;'><div style='font-size:11px; color:#aaa;'>Faltas usadas</div>"
            f"<div style='font-size:20px; font-weight:bold;'>{stats['faltas']} / {stats['max_faltas_permitidas']}</div></div>",
            unsafe_allow_html=True
        )
    with col3:
        st.markdown(
            f"<div style='text-align:center;'><div style='font-size:11px; color:#aaa;'>Podés faltar</div>"
            f"<div style='font-size:20px; font-weight:{peso}; color:{color};'>{restantes} clase(s) más</div></div>",
            unsafe_allow_html=True
        )

    if porcentaje < 75:
        st.markdown(
            f"<p style='color:{color}; font-weight:bold; text-align:center; margin-top:8px;'>"
            f"🚨 ¡Estás en riesgo de quedar libre por inasistencias!</p>",
            unsafe_allow_html=True
        )
    elif porcentaje < 85:
        st.markdown(
            f"<p style='color:{color}; font-weight:bold; text-align:center; margin-top:8px;'>"
            f"⚠️ Te estás acercando al límite de inasistencias.</p>",
            unsafe_allow_html=True
        )

    with st.expander("📋 Marcar falta / ver faltas registradas"):
        with st.form(f"form_falta_{mid}"):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                fecha_falta = st.date_input("Fecha de la falta", value=date.today(), key=f"fecha_falta_{mid}")
            with col_f2:
                justificada = st.checkbox("¿Justificada?", key=f"just_falta_{mid}")
            agregar = st.form_submit_button("➕ Marcar falta", use_container_width=True)
        if agregar:
            agregar_falta(usuario["id"], mid, fecha_falta, justificada)
            st.success("Falta registrada.")
            st.rerun()

        if stats["detalle_faltas"]:
            st.markdown("**Faltas registradas:**")
            for fid, ffecha, fjust in stats["detalle_faltas"]:
                just_text = " · justificada" if fjust else ""
                col_ff1, col_ff2 = st.columns([4, 1])
                with col_ff1:
                    st.markdown(f"📌 {ffecha.strftime('%d/%m/%Y')}{just_text}")
                with col_ff2:
                    if st.button("🗑️", key=f"del_falta_{fid}", use_container_width=True):
                        borrar_falta(fid)
                        st.rerun()
        else:
            st.caption("No hay faltas registradas todavía. Por defecto se asume presente en todas las clases.")

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("🗓️ Cursadas")

    clases_hoy = get_clases_hoy(usuario["id"])
    if clases_hoy:
        for clase in clases_hoy:
            mnombre, horario, link, modalidad = clase
            horario_text = f"a las {horario}" if horario else ""
            link_text = f" — [🔗 Acceder]({link})" if link else ""
            st.success(f"📚 Hoy tenés clase de **{mnombre}** {horario_text} ({modalidad}){link_text}")
    else:
        st.info("📭 Hoy no cursás ninguna materia.")

    st.markdown("---")

    nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
    tab1, tab2, tab3 = st.tabs(["📋 Mis cursadas", "➕ Registrar cursada", "📌 Tareas"])

    with tab1:
        materias_cursando = get_materias_cursando(usuario["id"], usuario["carrera_id"])
        todas_cursadas = get_todas_cursadas(usuario["id"])
        todos_programas = get_todos_programas_cursada(usuario["id"])

        if not materias_cursando:
            st.info("No tenés materias marcadas como 'cursando'. Cambiá el estado en Plan de Estudios.")
        else:
            for m in materias_cursando:
                mid, mnombre, manio = m
                cursada = todas_cursadas.get(mid)
                programa_link = todos_programas.get(mid)

                with st.expander(f"{nombres_anio.get(manio, '')} — {mnombre}"):
                    if cursada:
                        cid, anio, cuatri, modalidad, dias, horario, link, prof1, email_prof1, prof2, email_prof2, turno = cursada
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Año:** {anio}")
                            st.markdown(f"**Cuatrimestre:** {cuatri}")
                            st.markdown(f"**Turno:** {turno or '—'}")
                            st.markdown(f"**Modalidad:** {modalidad}")
                            st.markdown(f"**Días:** {dias or '—'}")
                            st.markdown(f"**Horario:** {horario or '—'}")
                        with col2:
                            if prof1:
                                st.markdown(f"**Profesor/a 1:** {prof1}")
                                if email_prof1:
                                    st.markdown(f"📧 {email_prof1}")
                            if prof2:
                                st.markdown(f"**Profesor/a 2:** {prof2}")
                                if email_prof2:
                                    st.markdown(f"📧 {email_prof2}")
                        if link:
                            st.markdown(f"[🔗 Acceder a la clase]({link})")

                        if programa_link:
                            st.markdown("---")
                            col_prog1, col_prog2 = st.columns(2)
                            with col_prog1:
                                st.markdown(f"[📋 Ver programa]({programa_link})")
                            with col_prog2:
                                preview_url = convertir_link_drive(programa_link)
                                if preview_url:
                                    if st.button("👁️ Ver PDF", key=f"pdf_prog_cursada_{mid}", use_container_width=True):
                                        st.session_state[f"viendo_pdf_cursada_{mid}"] = not st.session_state.get(f"viendo_pdf_cursada_{mid}", False)
                                        st.rerun()
                            if st.session_state.get(f"viendo_pdf_cursada_{mid}") and convertir_link_drive(programa_link):
                                st.components.v1.iframe(convertir_link_drive(programa_link), height=500)

                        # ── Sección de asistencia ─────────────────────────
                        mostrar_asistencia(usuario, mid, dias, anio, cuatri)

                        st.markdown("---")
                        col_edit, col_borrar = st.columns(2)
                        with col_edit:
                            if st.button("✏️ Editar", key=f"edit_cursada_{mid}", use_container_width=True):
                                st.session_state[f"editando_cursada_{mid}"] = True
                                st.rerun()
                        with col_borrar:
                            key_confirmar = f"confirmar_del_cursada_{mid}"
                            if st.session_state.get(key_confirmar):
                                col_si, col_no = st.columns(2)
                                with col_si:
                                    if st.button("✅ Confirmar", key=f"si_del_cursada_{mid}", use_container_width=True):
                                        borrar_cursada(usuario["id"], mid)
                                        st.session_state[key_confirmar] = False
                                        st.success("Cursada borrada.")
                                        st.rerun()
                                with col_no:
                                    if st.button("❌ Cancelar", key=f"no_del_cursada_{mid}", use_container_width=True):
                                        st.session_state[key_confirmar] = False
                                        st.rerun()
                            else:
                                if st.button("🗑️ Borrar", key=f"borrar_cursada_{mid}", use_container_width=True):
                                    st.session_state[key_confirmar] = True
                                    st.rerun()

                        if st.session_state.get(f"editando_cursada_{mid}"):
                            with st.form(f"form_edit_cursada_{mid}"):
                                col1, col2 = st.columns(2)
                                with col1:
                                    e_anio = st.number_input("Año", min_value=2000, max_value=2100, value=anio)
                                    e_cuatri = st.selectbox("Cuatrimestre", CUATRIMESTRES, index=CUATRIMESTRES.index(cuatri) if cuatri in CUATRIMESTRES else 0)
                                    e_turno = st.selectbox("Turno", TURNOS, index=TURNOS.index(turno) if turno in TURNOS else 0)
                                with col2:
                                    e_modalidad = st.selectbox("Modalidad", MODALIDADES, index=MODALIDADES.index(modalidad) if modalidad in MODALIDADES else 0)
                                    e_horario = st.text_input("Horario", value=horario or "")
                                    e_link = st.text_input("Link", value=link or "")
                                e_dias = st.multiselect("Días", DIAS, default=[d.strip() for d in (dias or "").split(",") if d.strip() in DIAS])
                                e_prof1 = st.text_input("Profesor/a 1", value=prof1 or "")
                                e_email_prof1 = st.text_input("Email Profesor/a 1", value=email_prof1 or "")
                                e_prof2 = st.text_input("Profesor/a 2", value=prof2 or "")
                                e_email_prof2 = st.text_input("Email Profesor/a 2", value=email_prof2 or "")
                                col1, col2 = st.columns(2)
                                with col1:
                                    guardar = st.form_submit_button("💾 Guardar", use_container_width=True)
                                with col2:
                                    cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)
                            if guardar:
                                guardar_cursada(usuario["id"], mid, e_anio, e_cuatri, e_modalidad, e_turno, ", ".join(e_dias), e_horario, e_link, e_prof1, e_email_prof1, e_prof2, e_email_prof2)
                                st.session_state[f"editando_cursada_{mid}"] = False
                                st.success("Cursada actualizada.")
                                st.rerun()
                            if cancelar:
                                st.session_state[f"editando_cursada_{mid}"] = False
                                st.rerun()
                    else:
                        st.warning("Sin datos de cursada cargados.")
                        if programa_link:
                            st.markdown(f"[📋 Ver programa]({programa_link})")

    with tab2:
        todas = get_todas_materias(usuario["carrera_id"])
        nombres_anio_map = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
        opciones = {f"{nombres_anio_map.get(m[2], '')} — {m[1]}": m[0] for m in todas}

        if "form_cursada_key" not in st.session_state:
            st.session_state.form_cursada_key = 0

        st.markdown("### 📅 Elegí el Año y la Materia")

        with st.form(f"form_cursada_{st.session_state.form_cursada_key}"):
            materia_label = st.selectbox("📚 Materia (ordenada por año)", list(opciones.keys()))
            col1, col2 = st.columns(2)
            with col1:
                anio = st.number_input("Año de cursada", min_value=2000, max_value=2100, value=datetime.now().year)
                cuatrimestre = st.selectbox("Cuatrimestre", CUATRIMESTRES)
                turno = st.selectbox("Turno", TURNOS)
            with col2:
                modalidad = st.selectbox("Modalidad", MODALIDADES)
                horario = st.text_input("Horario (ej: 18:30)")
                link = st.text_input("Link de clase online")
            dias_sel = st.multiselect("Días de cursada", DIAS)
            col1, col2 = st.columns(2)
            with col1:
                profesor1 = st.text_input("Profesor/a 1")
                email_profesor1 = st.text_input("Email Profesor/a 1")
            with col2:
                profesor2 = st.text_input("Profesor/a 2 (opcional)")
                email_profesor2 = st.text_input("Email Profesor/a 2 (opcional)")
            submit = st.form_submit_button("💾 Guardar cursada", use_container_width=True)

        if submit:
            materia_id = opciones[materia_label]
            dias_str = ", ".join(dias_sel) if dias_sel else ""
            guardar_cursada(usuario["id"], materia_id, anio, cuatrimestre, modalidad, turno, dias_str, horario, link, profesor1, email_profesor1, profesor2, email_profesor2)
            st.session_state.form_cursada_key += 1
            st.success("✅ Cursada guardada correctamente.")
            st.rerun()

    with tab3:
        st.subheader("📌 Tareas por materia")
        materias_cursando = get_materias_cursando(usuario["id"], usuario["carrera_id"])
        if not materias_cursando:
            st.info("No tenés materias cursando.")
        else:
            nombres_anio_map2 = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
            opciones_tareas = {f"{nombres_anio_map2.get(m[2], '')} — {m[1]}": m[0] for m in materias_cursando}
            materia_tarea_label = st.selectbox("Materia", list(opciones_tareas.keys()), key="sel_tarea")
            materia_tarea_id = opciones_tareas[materia_tarea_label]

            tareas = get_tareas_materia(usuario["id"], materia_tarea_id)
            tareas_dict = {t[1]: t for t in tareas}
            hoy = date.today()

            nums_existentes = sorted(tareas_dict.keys())
            todos_nums = list(range(1, max(nums_existentes) + 2)) if nums_existentes else [1]
            nums_a_mostrar = nums_existentes + [max(todos_nums)]

            for num in nums_existentes:
                tarea = tareas_dict[num]
                with st.expander(f"📌 Tarea {num}", expanded=True):
                    tid, tnum, tdesc, tvenc, tcomp = tarea
                    vencida = tvenc and tvenc < hoy and not tcomp
                    estado_icon = "✅ Completada" if tcomp else ("🔴 Vencida" if vencida else "⏳ Pendiente")
                    st.markdown(f"**{tdesc or 'Sin descripción'}**")
                    st.markdown(f"Vence: {str(tvenc) if tvenc else '—'} — {estado_icon}")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("✏️ Editar", key=f"edit_tarea_{num}_{materia_tarea_id}", use_container_width=True):
                            st.session_state[f"editando_tarea_{num}_{materia_tarea_id}"] = True
                            st.rerun()
                    with col2:
                        if not tcomp:
                            if st.button("✅ Completar", key=f"comp_tarea_{num}_{materia_tarea_id}", use_container_width=True):
                                actualizar_tarea(tid, tdesc, tvenc, True)
                                st.rerun()
                    with col3:
                        key_confirmar_t = f"confirmar_del_tarea_{tid}"
                        if st.session_state.get(key_confirmar_t):
                            col_si, col_no = st.columns(2)
                            with col_si:
                                if st.button("✅", key=f"si_del_t_{tid}", use_container_width=True):
                                    borrar_tarea(tid)
                                    st.session_state[key_confirmar_t] = False
                                    st.rerun()
                            with col_no:
                                if st.button("❌", key=f"no_del_t_{tid}", use_container_width=True):
                                    st.session_state[key_confirmar_t] = False
                                    st.rerun()
                        else:
                            if st.button("🗑️ Borrar", key=f"borrar_tarea_{num}_{materia_tarea_id}", use_container_width=True):
                                st.session_state[key_confirmar_t] = True
                                st.rerun()

                    if st.session_state.get(f"editando_tarea_{num}_{materia_tarea_id}"):
                        with st.form(f"form_edit_tarea_{num}_{materia_tarea_id}"):
                            nueva_desc = st.text_input("Descripción", value=tdesc or "")
                            nueva_fecha = st.date_input("Fecha de vencimiento", value=tvenc or hoy)
                            nuevo_comp = st.checkbox("Completada", value=tcomp)
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("💾 Guardar", use_container_width=True):
                                    actualizar_tarea(tid, nueva_desc, nueva_fecha, nuevo_comp)
                                    st.session_state[f"editando_tarea_{num}_{materia_tarea_id}"] = False
                                    st.rerun()
                            with col2:
                                if st.form_submit_button("❌ Cancelar", use_container_width=True):
                                    st.session_state[f"editando_tarea_{num}_{materia_tarea_id}"] = False
                                    st.rerun()

            nuevo_num = (max(nums_existentes) + 1) if nums_existentes else 1
            st.markdown("---")
            with st.expander(f"➕ Agregar Tarea {nuevo_num}", expanded=False):
                key_nueva = f"tarea_nueva_key_{materia_tarea_id}"
                if key_nueva not in st.session_state:
                    st.session_state[key_nueva] = 0
                with st.form(f"form_nueva_tarea_{materia_tarea_id}_{st.session_state[key_nueva]}"):
                    desc = st.text_input(f"Descripción de la Tarea {nuevo_num}")
                    fecha = st.date_input("Fecha de vencimiento", value=hoy)
                    if st.form_submit_button("💾 Guardar", use_container_width=True):
                        guardar_tarea(usuario["id"], materia_tarea_id, nuevo_num, desc, fecha)
                        st.session_state[key_nueva] += 1
                        st.rerun()
