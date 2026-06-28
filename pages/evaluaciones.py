import streamlit as st
from db import get_conn
from datetime import date

TIPOS = ["Parcial", "Trabajo Práctico", "Recuperatorio", "Reincorporatorio", "Final"]

@st.cache_data(ttl=60)
def get_todas_materias(carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, anio, final_obligatorio
                FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, nombre;
            """, (carrera_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_evaluaciones(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, tipo, descripcion, nota, fecha, aprobado
                FROM evaluaciones
                WHERE usuario_id = %s AND materia_id = %s
                ORDER BY fecha ASC NULLS LAST, tipo;
            """, (usuario_id, materia_id))
            return cur.fetchall()

def agregar_evaluacion(usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO evaluaciones (usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado))
        conn.commit()
    get_evaluaciones.clear()

def actualizar_evaluacion(eval_id, descripcion, nota, fecha, aprobado):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE evaluaciones
                SET descripcion = %s, nota = %s, fecha = %s, aprobado = %s
                WHERE id = %s;
            """, (descripcion, nota, fecha, aprobado, eval_id))
        conn.commit()
    get_evaluaciones.clear()

def eliminar_evaluacion(eval_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM evaluaciones WHERE id = %s;", (eval_id,))
        conn.commit()
    get_evaluaciones.clear()

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return
    st.title("📝 Notas y Evaluaciones")

    nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
    todas = get_todas_materias(usuario["carrera_id"])
    opciones = {f"{nombres_anio.get(m[2], '')} — {m[1]}": (m[0], m[3]) for m in todas}

    opciones_lista = ["Elegí una materia"] + list(opciones.keys())
    materia_label = st.selectbox("Seleccioná una materia", opciones_lista, index=0)

    if materia_label == "Elegí una materia":
        st.info("Seleccioná una materia para ver sus notas.")
        return

    materia_id, final_obligatorio = opciones[materia_label]

    st.markdown("---")

    evaluaciones = get_evaluaciones(usuario["id"], materia_id)

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

    tabs = st.tabs(["📋 Parciales", "📄 Trabajos Prácticos", "🔄 Recuperatorios", "🔁 Reincorporatorios", "🎓 Final"])
    tipos_tab = ["Parcial", "Trabajo Práctico", "Recuperatorio", "Reincorporatorio", "Final"]

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
                    key_edit = f"editando_eval_{eid}"

                    if st.session_state.get(key_edit):
                        # ── Formulario de edición inline ──────────────────
                        with st.form(f"form_edit_eval_{eid}"):
                            st.markdown(f"**✏️ Editando: {edesc or tipo}**")
                            col1, col2 = st.columns(2)
                            with col1:
                                nueva_desc = st.text_input(
                                    "Descripción",
                                    value=edesc or "",
                                    key=f"desc_{eid}"
                                )
                                nueva_nota = st.number_input(
                                    "Nota",
                                    min_value=0.0, max_value=10.0, step=0.25,
                                    value=float(enota) if enota is not None else 0.0,
                                    key=f"nota_{eid}"
                                )
                            with col2:
                                nueva_fecha = st.date_input(
                                    "Fecha",
                                    value=efecha if efecha else date.today(),
                                    key=f"fecha_{eid}"
                                )
                                nuevo_aprobado = st.checkbox(
                                    "¿Aprobado?",
                                    value=bool(eaprobado),
                                    key=f"aprobado_{eid}"
                                )
                            col_g, col_c = st.columns(2)
                            with col_g:
                                guardar = st.form_submit_button("💾 Guardar", use_container_width=True)
                            with col_c:
                                cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)

                        if guardar:
                            actualizar_evaluacion(eid, nueva_desc, nueva_nota, nueva_fecha, nuevo_aprobado)
                            st.session_state[key_edit] = False
                            st.success("Evaluación actualizada.")
                            st.rerun()
                        if cancelar:
                            st.session_state[key_edit] = False
                            st.rerun()

                    else:
                        # ── Vista normal ──────────────────────────────────
                        col1, col2, col3 = st.columns([4, 1, 1])
                        with col1:
                            desc_text = edesc if edesc else tipo
                            nota_text = f"**{enota}**" if enota is not None else "Sin nota"
                            fecha_text = str(efecha) if efecha else "Sin fecha"
                            aprobado_icon = "✅" if eaprobado else "❌"
                            st.markdown(f"{aprobado_icon} {desc_text} — Nota: {nota_text} — Fecha: {fecha_text}")
                        with col2:
                            if st.button("✏️ Editar", key=f"btn_edit_{eid}", use_container_width=True):
                                st.session_state[key_edit] = True
                                st.rerun()
                        with col3:
                            key_confirmar = f"confirmar_del_{eid}"
                            if st.session_state.get(key_confirmar):
                                col_si, col_no = st.columns(2)
                                with col_si:
                                    if st.button("✅", key=f"si_del_{eid}", use_container_width=True):
                                        eliminar_evaluacion(eid)
                                        st.session_state[key_confirmar] = False
                                        st.success("Evaluación eliminada.")
                                        st.rerun()
                                with col_no:
                                    if st.button("❌", key=f"no_del_{eid}", use_container_width=True):
                                        st.session_state[key_confirmar] = False
                                        st.rerun()
                            else:
                                if st.button("🗑️", key=f"del_eval_{eid}", use_container_width=True):
                                    st.session_state[key_confirmar] = True
                                    st.rerun()

            else:
                st.info(f"No hay {tipo.lower()}s cargados.")

            with st.expander(f"➕ Agregar {tipo}"):
                with st.form(f"form_{tipo.replace(' ', '_')}_{materia_id}"):
                    descripcion = st.text_input("Descripción (ej: Parcial 1, TP N°2)")
                    nota = st.number_input("Nota", min_value=0.0, max_value=10.0, step=0.25, value=0.0)
                    fecha = st.date_input("Fecha", value=date.today())
                    aprobado = st.checkbox("¿Aprobado? (marcá si la nota es ≥ 6)", value=False)
                    submit = st.form_submit_button("💾 Guardar", use_container_width=True)
                if submit:
                    agregar_evaluacion(usuario["id"], materia_id, tipo, descripcion, nota, fecha, aprobado)
                    st.success(f"{tipo} guardado.")
                    st.rerun()
