import streamlit as st
from db import get_conn
from utils import NOMBRES_ANIO, convertir_link_preview

TIPOS = ["Bibliografía", "Apunte", "NotebookLM", "Programa de la Materia", "Otro"]

@st.cache_data(ttl=60)
def get_materias_alumno(carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, anio FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, nombre;
            """, (carrera_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_recursos(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, tipo, link
                FROM recursos
                WHERE usuario_id = %s AND materia_id = %s
                ORDER BY tipo, nombre;
            """, (usuario_id, materia_id))
            return cur.fetchall()

def agregar_recurso(usuario_id, materia_id, nombre, tipo, link):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO recursos (usuario_id, materia_id, nombre, tipo, link)
                VALUES (%s, %s, %s, %s, %s);
            """, (usuario_id, materia_id, nombre, tipo, link))
        conn.commit()
    get_recursos.clear()

def actualizar_recurso(recurso_id, nombre, tipo, link):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE recursos SET nombre = %s, tipo = %s, link = %s
                WHERE id = %s;
            """, (nombre, tipo, link, recurso_id))
        conn.commit()
    get_recursos.clear()

def eliminar_recurso(recurso_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM recursos WHERE id = %s;", (recurso_id,))
        conn.commit()
    get_recursos.clear()

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("📂 Recursos por Materia")

    materias = get_materias_alumno(usuario["carrera_id"])
    if not materias:
        st.warning("No hay materias disponibles.")
        return

    opciones = {f"{NOMBRES_ANIO.get(m[2], '')} — {m[1]}": m[0] for m in materias}

    opciones_lista = ["Elegí una materia"] + list(opciones.keys())
    materia_label = st.selectbox("Seleccioná una materia", opciones_lista, index=0)

    if materia_label == "Elegí una materia":
        st.info("Seleccioná una materia para ver sus recursos.")
        return

    materia_id = opciones[materia_label]

    st.markdown("---")

    with st.expander("➕ Agregar nuevo recurso"):
        # Contador de reseteo (ítem "formularios deben volver limpios",
        # 02/08/2026): se incrementa después de guardar para que el form se
        # recree con keys nuevas y no quede con nombre/link recién tipeados.
        if "recurso_form_key" not in st.session_state:
            st.session_state.recurso_form_key = 0
        fk = st.session_state.recurso_form_key

        with st.form(f"form_recurso_{fk}"):
            nombre = st.text_input("Nombre del recurso", key=f"recurso_nombre_{fk}")
            tipo = st.selectbox("Tipo", TIPOS, key=f"recurso_tipo_{fk}")
            link = st.text_input("Link (Google Drive, Dropbox, NotebookLM, etc.)", key=f"recurso_link_{fk}")
            submit = st.form_submit_button("💾 Guardar", use_container_width=True)
        if submit:
            if not nombre or not link:
                st.error("Completá nombre y link.")
            else:
                agregar_recurso(usuario["id"], materia_id, nombre, tipo, link)
                st.session_state.recurso_form_key += 1
                st.success("Recurso agregado.")
                st.rerun()

    recursos = get_recursos(usuario["id"], materia_id)

    if not recursos:
        st.info("No hay recursos cargados para esta materia.")
    else:
        tipo_actual = None
        for r in recursos:
            rid, rnombre, rtipo, rlink = r

            if rtipo != tipo_actual:
                tipo_actual = rtipo
                iconos = {"Bibliografía": "📚", "Apunte": "📝", "NotebookLM": "🤖", "Programa de la Materia": "📋", "Otro": "🔗"}
                st.markdown(f"### {iconos.get(rtipo, '🔗')} {rtipo}")

            key_edit_rec = f"editando_recurso_{rid}"

            if st.session_state.get(key_edit_rec):
                # ── Formulario de edición inline ──────────────────
                with st.form(f"form_edit_recurso_{rid}"):
                    nueva_nombre = st.text_input("Nombre del recurso", value=rnombre, key=f"edit_nombre_rec_{rid}")
                    nuevo_tipo = st.selectbox(
                        "Tipo", TIPOS,
                        index=TIPOS.index(rtipo) if rtipo in TIPOS else 0,
                        key=f"edit_tipo_rec_{rid}"
                    )
                    nuevo_link = st.text_input(
                        "Link (Google Drive, Dropbox, NotebookLM, etc.)", value=rlink, key=f"edit_link_rec_{rid}"
                    )
                    col_gr, col_cr = st.columns(2)
                    with col_gr:
                        guardar_rec_edit = st.form_submit_button("💾 Guardar", use_container_width=True)
                    with col_cr:
                        cancelar_rec_edit = st.form_submit_button("❌ Cancelar", use_container_width=True)

                if guardar_rec_edit:
                    if not nueva_nombre.strip() or not nuevo_link.strip():
                        st.error("Completá nombre y link.")
                    else:
                        actualizar_recurso(rid, nueva_nombre.strip(), nuevo_tipo, nuevo_link.strip())
                        st.session_state[key_edit_rec] = False
                        st.success("Recurso actualizado.")
                        st.rerun()
                if cancelar_rec_edit:
                    st.session_state[key_edit_rec] = False
                    st.rerun()

            else:
                col1, col2, col3 = st.columns([4, 1, 1])
                with col1:
                    st.markdown(f"**{rnombre}**")
                    preview_url = convertir_link_preview(rlink)
                    if preview_url:
                        st.markdown(f"[🔗 Abrir]({rlink})")
                        with st.expander("👁️ Ver PDF"):
                            st.components.v1.iframe(preview_url, height=500)
                    else:
                        st.markdown(f"[🔗 Abrir]({rlink})")
                with col2:
                    if st.button("✏️ Editar", key=f"edit_recurso_{rid}", use_container_width=True):
                        st.session_state[key_edit_rec] = True
                        st.rerun()
                with col3:
                    if st.button("🗑️ Borrar", key=f"del_{rid}", use_container_width=True):
                        eliminar_recurso(rid)
                        st.rerun()

        st.markdown("---")
