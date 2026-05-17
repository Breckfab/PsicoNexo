import streamlit as st
from db import get_connection
from datetime import date

TIPOS = ["Parcial", "Trabajo Práctico", "Recuperatorio", "Final"]

def get_todas_materias(carrera_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nombre, anio, final_obligatorio
        FROM materias
        WHERE carrera_id = %s
        ORDER BY anio, nombre;
    """, (carrera_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_evaluaciones(usuario_id, materia_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, tipo, descripcion, nota, fecha, aprobado
        FROM evaluaciones
        WHERE usuario_id = %s AND materia_id = %s
        ORDER BY fecha ASC NULLS LAST, tipo;
    """, (usuario_id, materia_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def agregar_evaluacion(usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO evaluaciones (usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, (usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado))
    conn.commit()
    cur.close()
    conn.close()

def eliminar_evaluacion(eval_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM evaluaciones WHERE id = %s;", (eval_id,))
    conn.commit()
    cur.close()
    conn.close()

def mostrar(usuario):
    st.title("📝 Notas y Evaluaciones")

    nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
    todas = get_todas_materias(usuario["carrera_id"])
    opciones = {f"{nombres_anio.get(m[2], '')} — {m[1]}": (m[0], m[3]) for m in todas}

    materia_label = st.selectbox("Seleccioná una materia", list(opciones.keys()))
    materia_id, final_obligatorio = opciones[materia_label]

    st.markdown("---")

    evaluaciones = get_evaluaciones(usuario["id"], materia_id)

    # Promedio general
    notas = [e[3] for e in evaluaciones if e[3] is not None]
    if notas:
        promedio = sum(notas) / len(notas)
        color = "#2ecc71" if promedio >= 6 else "#e74c3c"
        st.markdown(f"""
            <div style="background-color:#1E1E2E; padding:12px 20px; border-radius:10px; 
                        display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <span style="color:white; font-size:16px;">📊 Promedio general</span>
                <span style="color:{color}; font-size:28px; font-weight:bold;">{promedio:.2f}</span>
            </div>
        """, unsafe_allow_html=True)

    # Tabs por tipo
    tabs = st.tabs(["📋 Parciales", "📄 Trabajos Prácticos", "🔄 Recuperatorios", "🎓 Final"])
    tipos_tab = ["Parcial", "Trabajo Práctico", "Recuperatorio", "Final"]

    for tab, tipo in zip(tabs, tipos_tab):
        with tab:
            evals_tipo = [e for e in evaluaciones if e[1] == tipo]

            if evals_tipo:
                notas_tipo = [e[3] for e in evals_tipo if e[3] is not None]
                if notas_tipo:
                    prom_tipo = sum(notas_tipo) / len(notas_tipo)
                    st.markdown(f"**Promedio {tipo}:** `{prom_tipo:.2f}`")

                for e in evals_tipo:
                    eid, etipo, edesc, enota, efecha, eaprobado = e
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        desc_text = edesc if edesc else tipo
                        nota_text = f"**{enota}**" if enota is not None else "Sin nota"
                        fecha_text = str(efecha) if efecha else "Sin fecha"
                        aprobado_icon = "✅" if eaprobado else "❌"
                        st.markdown(f"{aprobado_icon} {desc_text} — Nota: {nota_text} — Fecha: {fecha_text}")
                    with col2:
                        if st.button("🗑️", key=f"del_eval_{eid}"):
                            eliminar_evaluacion(eid)
                            st.rerun()
            else:
                st.info(f"No hay {tipo.lower()}s cargados.")

            # Formulario para agregar
            with st.expander(f"➕ Agregar {tipo}"):
                with st.form(f"form_{tipo.replace(' ', '_')}"):
                    descripcion = st.text_input("Descripción (ej: Parcial 1, TP N°2)")
                    nota = st.number_input("Nota", min_value=0.0, max_value=10.0, step=0.25, value=0.0)
                    fecha = st.date_input("Fecha", value=date.today())
                    aprobado = st.checkbox("¿Aprobado?", value=nota >= 6)
                    submit = st.form_submit_button("Guardar")
                if submit:
                    agregar_evaluacion(usuario["id"], materia_id, tipo, descripcion, nota, fecha, aprobado)
                    st.success(f"{tipo} guardado.")
                    st.rerun()
