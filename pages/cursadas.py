import streamlit as st
from db import get_conn
from datetime import datetime, date

MODALIDADES = ["Presencial", "Híbrida", "Asincrónica"]
TURNOS = ["Mañana", "Tarde", "Noche"]
CUATRIMESTRES = ["1° Cuatrimestre", "2° Cuatrimestre", "Anual"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

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
    """Trae todas las cursadas del usuario de una vez."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT materia_id, id, anio_cursada, cuatrimestre, modalidad, dias, horario, link,
                       profesor1, email_profesor1, profesor2, email_profesor2, turno
                FROM cursadas
                WHERE usuario_id = %s
                ORDER BY anio_cursada DESC;
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

def mostrar(usuario):
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

                        col_edit, col_borrar = st.columns(2)
                        with col_edit:
                            if st.button("✏️ Editar", key=f"edit_cursada_{mid}", use_container_width=True):
                                st.session_state[f"editando_cursada_{mid}"] = True
                                st.rerun()
                        with col_borrar:
                            if st.button("🗑️ Borrar", key=f"borrar_cursada_{mid}", use_container_width=True):
                                borrar_cursada(usuario["id"], mid)
                                st.success("Cursada borrada.")
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

            for num in [1, 2, 3]:
                tarea = tareas_dict.get(num)
                with st.expander(f"📌 Tarea {num}", expanded=True):
                    if tarea:
                        tid, tnum, tdesc, tvenc, tcomp = tarea
                        vencida = tvenc and tvenc < hoy and not tcomp
                        estado_icon = "✅ Completada" if tcomp else ("🔴 Vencida" if vencida else "⏳ Pendiente")
                        st.markdown(f"**{tdesc or 'Sin descripción'}**")
                        st.markdown(f"Vence: {str(tvenc) if tvenc else '—'} — {estado_icon}")

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            if st.button("✏️ Editar", key=f"edit_tarea_{num}", use_container_width=True):
                                st.session_state[f"editando_tarea_{num}"] = True
                                st.rerun()
                        with col2:
                            if st.button("✅ Completar", key=f"comp_tarea_{num}", use_container_width=True):
                                actualizar_tarea(tid, tdesc, tvenc, True)
                                st.rerun()
                        with col3:
                            if st.button("🗑️ Borrar", key=f"borrar_tarea_{num}", use_container_width=True):
                                borrar_tarea(tid)
                                st.rerun()

                        if st.session_state.get(f"editando_tarea_{num}"):
                            with st.form(f"form_edit_tarea_{num}"):
                                nueva_desc = st.text_input("Descripción", value=tdesc or "")
                                nueva_fecha = st.date_input("Fecha de vencimiento", value=tvenc or hoy)
                                nuevo_comp = st.checkbox("Completada", value=tcomp)
                                col1, col2 = st.columns(2)
                                with col1:
                                    if st.form_submit_button("💾 Guardar", use_container_width=True):
                                        actualizar_tarea(tid, nueva_desc, nueva_fecha, nuevo_comp)
                                        st.session_state[f"editando_tarea_{num}"] = False
                                        st.rerun()
                                with col2:
                                    if st.form_submit_button("❌ Cancelar", use_container_width=True):
                                        st.session_state[f"editando_tarea_{num}"] = False
                                        st.rerun()
                    else:
                        if f"tarea_key_{num}" not in st.session_state:
                            st.session_state[f"tarea_key_{num}"] = 0
                        with st.form(f"form_nueva_tarea_{num}_{st.session_state[f'tarea_key_{num}']}"):
                            desc = st.text_input(f"Descripción de la tarea {num}")
                            fecha = st.date_input("Fecha de vencimiento", value=hoy)
                            if st.form_submit_button("💾 Guardar", use_container_width=True):
                                guardar_tarea(usuario["id"], materia_tarea_id, num, desc, fecha)
                                st.session_state[f"tarea_key_{num}"] += 1
                                st.rerun()
