import streamlit as st
from db import get_conn

@st.cache_data(ttl=300)
def get_perfil(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nombre, email, email_institucional, campus_virtual, portal_alumnos, biblioteca_digital
                FROM usuarios WHERE id = %s;
            """, (usuario_id,))
            return cur.fetchone()

def guardar_perfil(usuario_id, email_institucional, campus_virtual, portal_alumnos, biblioteca_digital):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE usuarios SET email_institucional = %s, campus_virtual = %s,
                portal_alumnos = %s, biblioteca_digital = %s
                WHERE id = %s;
            """, (email_institucional, campus_virtual, portal_alumnos, biblioteca_digital, usuario_id))
        conn.commit()
    get_perfil.clear()

def mostrar(usuario):
    st.title("👤 Mi Perfil")

    perfil = get_perfil(usuario["id"])
    if not perfil:
        st.error("No se pudo cargar el perfil.")
        return

    nombre, email, email_institucional, campus_virtual, portal_alumnos, biblioteca_digital = perfil

    st.markdown("### Datos personales")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Nombre:** {nombre}")
    with col2:
        st.markdown(f"**Email:** {email}")

    st.markdown("---")
    st.markdown("### Datos académicos")

    if "editando_perfil" not in st.session_state:
        st.session_state.editando_perfil = False

    if not st.session_state.editando_perfil:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Email institucional:** {email_institucional or '—'}")
        with col2:
            campus_text = f"[🔗 Campus Virtual]({campus_virtual})" if campus_virtual else "—"
            st.markdown(f"**Campus virtual:** {campus_text}")

        col1, col2 = st.columns(2)
        with col1:
            portal_text = f"[🔗 Portal de Alumnos]({portal_alumnos})" if portal_alumnos else "—"
            st.markdown(f"**Portal de Alumnos:** {portal_text}")
        with col2:
            biblio_text = f"[🔗 Biblioteca Digital]({biblioteca_digital})" if biblioteca_digital else "—"
            st.markdown(f"**Biblioteca Digital:** {biblio_text}")

        st.markdown("---")
        col_edit, col_borrar = st.columns(2)
        with col_edit:
            if st.button("✏️ Editar", use_container_width=True):
                st.session_state.editando_perfil = True
                st.rerun()
        with col_borrar:
            if st.button("🗑️ Borrar datos académicos", use_container_width=True):
                guardar_perfil(usuario["id"], "", "", "", "")
                st.success("Datos borrados.")
                st.rerun()
    else:
        with st.form("form_perfil"):
            nuevo_email_inst = st.text_input("Email institucional", value=email_institucional or "")
            nuevo_campus = st.text_input("Link del campus virtual", value=campus_virtual or "")
            nuevo_portal = st.text_input("Link del portal de alumnos", value=portal_alumnos or "")
            nueva_biblio = st.text_input("Link de la biblioteca digital", value=biblioteca_digital or "")
            col1, col2 = st.columns(2)
            with col1:
                guardar = st.form_submit_button("💾 Guardar", use_container_width=True)
            with col2:
                cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)

        if guardar:
            guardar_perfil(usuario["id"], nuevo_email_inst, nuevo_campus, nuevo_portal, nueva_biblio)
            st.session_state.editando_perfil = False
            st.success("Perfil guardado.")
            st.rerun()
        if cancelar:
            st.session_state.editando_perfil = False
            st.rerun()
