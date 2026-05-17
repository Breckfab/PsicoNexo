import streamlit as st
from db import get_connection
from datetime import datetime

MODALIDADES = ["Presencial", "Online", "Híbrida"]
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
        SELECT id, anio_cursada, cuatrimestre, modalidad, dias, horario, link, profesor1, profesor2
        FROM cursadas
        WHERE usuario_id = %s AND materia_id = %s
        ORDER BY anio_cursada DESC, cuatrimestre DESC
        LIMIT 1;
    """, (usuario_id, materia_id))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def guardar_cursada(usuario_id, materia_id, anio, cuatrimestre, modalidad, dias, horario, link, profesor1, profesor2):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cursadas (usuario_id, materia_id, anio_cursada, cuatrimestre, modalidad, dias, horario, link, profesor1, profesor2)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (usuario_id, materia_id, anio_cursada, cuatrimestre)
        DO UPDATE SET modalidad = EXCLUDED.modalidad, dias = EXCLUDED.dias,
                      horario = EXCLUDED.horario, link = EXCLUDED.link,
                      profesor1 = EXCLUDED.profesor1, profesor2 = EXCLUDED.profesor2;
    """, (usuario_id, materia_id, anio, cuatrimestre, modalidad, dias, horario, link, profesor1, profesor2))
    conn.commit()
    cur.close()
    conn.close()

def mostrar(usuario):
    st.title("🗓️ Cursadas")

    nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}

    tab1, tab2 = st.tabs(["📋 Mis cursadas actuales", "➕ Registrar cursada"])

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
                        _, anio, cuatri, modalidad, dias, horario, link, prof1, prof2 = cursada
                        st.markdown(f"**Año:** {anio} · **Cuatrimestre:** {cuatri}")
                        st.markdown(f"**Modalidad:** {modalidad}")
                        if dias:
                            st.markdown(f"**Días:** {dias}")
                        if horario:
                            st.markdown(f"**Horario:** {horario}")
                        if link:
                            st.markdown(f"**Link:** [Acceder]({link})")
                        if prof1:
                            st.markdown(f"**Profesor/a 1:** {prof1}")
                        if prof2:
                            st.markdown(f"**Profesor/a 2:** {prof2}")
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
            with col2:
                cuatrimestre = st.selectbox("Cuatrimestre", CUATRIMESTRES)
            modalidad = st.selectbox("Modalidad", MODALIDADES)
            dias_sel = st.multiselect("Días", DIAS)
            horario = st.text_input("Horario (ej: 18:00 - 21:00)")
            link = st.text_input("Link de clase (si es online o híbrida)")
            profesor1 = st.text_input("Profesor/a 1")
            profesor2 = st.text_input("Profesor/a 2 (opcional)")
            submit = st.form_submit_button("Guardar cursada")

        if submit:
            materia_id = opciones[materia_label]
            dias_str = ", ".join(dias_sel) if dias_sel else ""
            guardar_cursada(usuario["id"], materia_id, anio, cuatrimestre, modalidad, dias_str, horario, link, profesor1, profesor2)
            st.success("Cursada guardada correctamente.")
            st.rerun()
