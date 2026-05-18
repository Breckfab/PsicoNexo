import streamlit as st
from db import get_connection

VALORACIONES = ["Recomendado", "No recomendado"]

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

def get_opiniones(usuario_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT op.id, op.profesor, op.valoracion, op.observaciones, m.nombre, m.anio
        FROM opiniones_profesores op
        JOIN materias m ON op.materia_id = m.id
        WHERE op.usuario_id = %s
        ORDER BY op.profesor, m.anio, m.nombre;
    """, (usuario_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def agregar_opinion(usuario_id, materia_id, profesor, valoracion, observaciones):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO opiniones_profesores (usuario_id, materia_id, profesor, valoracion, observaciones)
        VALUES (%s, %s, %s, %s, %s);
    """, (usuario_id, materia_id, profesor, valoracion, observaciones))
    conn.commit()
    cur.close()
    conn.close()

def eliminar_opinion(opinion_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM opiniones_profesores WHERE id = %s;", (opinion_id,))
    conn.commit()
    cur.close()
    conn.close()

def mostrar(usuario):
    st.title("⭐ Opiniones de Profesores")
    st.caption("Tus opiniones son privadas y solo las ves vos.")

    tab1, tab2 = st.tabs(["📋 Mis opiniones", "➕ Agregar opinión"])

    with tab1:
        opiniones = get_opiniones(usuario["id"])

        if not opiniones:
            st.info("Todavía no cargaste ninguna opinión.")
        else:
            filtro = st.radio(
                "Filtrar por valoración",
                ["Todas", "Recomendado", "No recomendado"],
                horizontal=True
            )

            if filtro != "Todas":
                opiniones = [o for o in opiniones if o[2] == filtro]

            if not opiniones:
                st.info("No hay opiniones con ese filtro.")
            else:
                por_profesor = {}
                for op in opiniones:
                    oid, profesor, valoracion, observaciones, materia_nombre, materia_anio = op
                    if profesor not in por_profesor:
                        por_profesor[profesor] = []
                    por_profesor[profesor].append(op)

                nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}

                for profesor, ops in por_profesor.items():
                    recomendados = sum(1 for o in ops if o[2] == "Recomendado")
                    icono_prof = "👍" if recomendados >= len(ops) / 2 else "👎"

                    with st.expander(f"{icono_prof} {profesor} ({len(ops)} materia{'s' if len(ops) > 1 else ''})"):
                        for op in ops:
                            oid, _, valoracion, observaciones, materia_nombre, materia_anio = op
                            icono_val = "✅" if valoracion == "Recomendado" else "❌"
                            anio_texto = nombres_anio.get(materia_anio, f"Año {materia_anio}")

                            col1, col2 = st.columns([5, 1])
                            with col1:
                                st.markdown(f"{icono_val} **{valoracion}** — {anio_texto}: {materia_nombre}")
                                if observaciones:
                                    st.caption(f"💬 {observaciones}")
                            with col2:
                                if st.button("🗑️", key=f"del_op_{oid}", use_container_width=True):
                                    eliminar_opinion(oid)
                                    st.rerun()

                        st.markdown("---")

    with tab2:
        nombres_anio_map = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
        todas = get_todas_materias(usuario["carrera_id"])
        opciones = {f"{nombres_anio_map.get(m[2], '')} — {m[1]}": m[0] for m in todas}

        if "form_opinion_key" not in st.session_state:
            st.session_state.form_opinion_key = 0

        with st.form(f"form_opinion_{st.session_state.form_opinion_key}"):
            profesor = st.text_input("Nombre del profesor/a")
            materia_label = st.selectbox("Materia que dicta", list(opciones.keys()))
            valoracion = st.radio("Valoración", VALORACIONES, horizontal=True)
            observaciones = st.text_area("Observaciones (opcional)", height=100)
            submit = st.form_submit_button("💾 Guardar opinión", use_container_width=True)

        if submit:
            if not profesor:
                st.error("Ingresá el nombre del profesor/a.")
            else:
                materia_id = opciones[materia_label]
                agregar_opinion(usuario["id"], materia_id, profesor.strip(), valoracion, observaciones.strip())
                st.session_state.form_opinion_key += 1
                st.success("✅ Opinión guardada.")
                st.rerun()
