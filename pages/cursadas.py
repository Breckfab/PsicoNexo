import streamlit as st
from db import get_connection
from datetime import datetime, date

MODALIDADES = ["Presencial", "Híbrida", "Asincrónica"]
TURNOS = ["Mañana", "Tarde", "Noche"]
CUATRIMESTRES = ["1° Cuatrimestre", "2° Cuatrimestre", "Anual"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

def get_materias_cursando(usuario_id, carrera_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.nombre, m.anio
        FROM materias m
        JOIN alumno_materias am ON m.id = am.materia_id
        WHERE am.usuario_id = %s AND am.estado = 'cursando'
        AND m.carrera_id = %s
        ORDER BY m.anio, m.nombre;
    """, (usuario_id, carrera_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_todas_materias(carrera_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nombre, anio FROM materias
        WHERE carrera_id = %s
        ORDER BY anio, nombre;
    """, (carrera_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_cursada(usuario_id, materia_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, anio_cursada, cuatrimestre, modalidad, dias, horario, link, profesor1, profesor2, turno
        FROM cursadas
        WHERE usuario_id = %s AND materia_id = %s
        ORDER BY anio_cursada DESC
        LIMIT 1;
    """, (usuario_id, materia_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def guardar_cursada(usuario_id, materia_id, anio, cuatrimestre, modalidad, turno, dias, horario, link, profesor1, profesor2):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cursadas (usuario_id, materia_id, anio_cursada, cuatrimestre, modalidad, turno, dias, horario, link, profesor1, profesor2)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (usuario_id, materia_id, anio_cursada, cuatrimestre)
        DO UPDATE SET modalidad = EXCLUDED.modalidad, turno = EXCLUDED.turno,
                      dias = EXCLUDED.dias, horario = EXCLUDED.horario,
                      link = EXCLUDED.link, profesor1 = EXCLUDED.profesor1,
                      profesor2 = EXCLUDED.profesor2;
    """, (usuario_id, materia_id, anio, cuatrimestre, modalidad, turno, dias, horario, link, profesor1, profesor2))
    conn.commit()
    cur.close()
    conn.close()

def get_tareas(usuario_id, materia_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, numero, descripcion, fecha_vencimiento, completada
        FROM tareas
        WHERE usuario_id = %s AND materia_id = %s
        ORDER BY numero;
    """, (usuario_id, materia_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def guardar_tarea(usuario_id, materia_id, numero, descripcion, fecha_vencimiento):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tareas (usuario_id, materia_id, numero, descripcion, fecha_vencimiento)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING;
    """, (usuario_id, materia_id, numero, descripcion, fecha_vencimiento))
    conn.commit()
    cur.close()
    conn.close()

def actualizar_tarea(tarea_id, descripcion, fecha_vencimiento, completada):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE tareas SET descripcion = %s, fecha_vencimiento = %s, completada = %s
        WHERE id = %s;
    """, (descripcion, fecha_vencimiento, completada, tarea_id))
    conn.commit()
    cur.close()
    conn.close()

def get_clases_hoy(usuario_id):
    hoy = datetime.now()
    dia_semana = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][hoy.weekday()]
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.nombre, c.horario, c.link, c.modalidad
        FROM cursadas c
        JOIN materias m ON c.materia_id = m.id
        JOIN alumno_materias am ON am.materia_id = m.id AND am.usuario_id = c.usuario_id
        WHERE c.usuario_id = %s
        AND am.estado = 'cursando'
        AND c.dias ILIKE %s;
    """, (usuario_id, f"%{dia_semana}%"))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def mostrar(usuario):
    st.title("🗓️ Cursadas")

    # Mensaje clases de hoy
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
        if not materias_cursando:
            st.info("No tenés materias marcadas como 'cursando'. Cambiá el estado en Plan de Estudios.")
        else:
            for m in materias_cursando:
                mid, mnombre, manio = m
                cursada = get_cursada(usuario["id"], mid)
                with st.expander(f"{nombres_anio.get(manio, '')} — {mnombre}"):
                    if cursada:
                        _, anio, cuatri, modalidad, dias, horario, link, prof1, prof2, turno = cursada
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Año:** {anio}")
                            st.markdown(f"**Cuatrimestre:** {cuatri}")
                            st.markdown(f"**Turno:** {turno or '—'}")
                            st.markdown(f"**Modalidad:** {modalidad}")
                        with col2:
                            st.markdown(f"**Días:** {dias or '—'}")
                            st.markdown(f"**Horario:** {horario or '—'}")
                            if prof1:
                                st.markdown(f"**Profesor/a 1:** {prof1}")
                            if prof2:
                                st.markdown(f"**Profesor/a 2:** {prof2}")
                        if link:
                            st.markdown(f"[🔗 Acceder a la clase]({link})")
                    else:
                        st.warning("Sin datos de cursada cargados.")

    with tab2:
        todas = get_todas_materias(usuario["carrera_id"])
        nombres_anio_map = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
        opciones = {f"{nombres_anio_map.get(m[2], '')} — {m[1]}": m[0] for m in todas}

        with st.form("form_cursada"):
            materia_label = st.selectbox("Materia", list(opciones.keys()))
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
            profesor1 = st.text_input("Profesor/a 1")
            profesor2 = st.text_input("Profesor/a 2 (opcional)")
            submit = st.form_submit_button("Guardar cursada")

        if submit:
            materia_id = opciones[materia_label]
            dias_str = ", ".join(dias_sel) if dias_sel else ""
            guardar_cursada(usuario["id"], materia_id, anio, cuatrimestre, modalidad, turno, dias_str, horario, link, profesor1, profesor2)
            st.success("Cursada guardada correctamente.")
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

            tareas = get_tareas(usuario["id"], materia_tarea_id)
            tareas_dict = {t[1]: t for t in tareas}

            hoy = date.today()

            for num in [1, 2, 3]:
                tarea = tareas_dict.get(num)
                with st.expander(f"📌 Tarea {num}", expanded=True):
                    if tarea:
                        tid, tnum, tdesc, tvenc, tcomp = tarea
                        venc_text = str(tvenc) if tvenc else "Sin fecha"
                        vencida = tvenc and tvenc < hoy and not tcomp
                        estado_icon = "✅" if tcomp else ("🔴 Vencida" if vencida else "⏳ Pendiente")
                        st.markdown(f"**{tdesc or 'Sin descripción'}** — Vence: {venc_text} — {estado_icon}")
                        with st.form(f"form_edit_tarea_{num}"):
                            nueva_desc = st.text_input("Descripción", value=tdesc or "", key=f"desc_{num}")
                            nueva_fecha = st.date_input("Fecha de vencimiento", value=tvenc or hoy, key=f"fecha_{num}")
                            nuevo_comp = st.checkbox("Completada", value=tcomp, key=f"comp_{num}")
                            if st.form_submit_button("Actualizar"):
                                actualizar_tarea(tid, nueva_desc, nueva_fecha, nuevo_comp)
                                st.rerun()
                    else:
                        with st.form(f"form_nueva_tarea_{num}"):
                            desc = st.text_input(f"Descripción de la tarea {num}")
                            fecha = st.date_input("Fecha de vencimiento", value=hoy)
                            if st.form_submit_button("Guardar"):
                                guardar_tarea(usuario["id"], materia_tarea_id, num, desc, fecha)
                                st.rerun()
