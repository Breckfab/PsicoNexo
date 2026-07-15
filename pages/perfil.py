import streamlit as st
import psycopg
from db import get_conn

@st.cache_data(ttl=300)
def get_perfil(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nombre, email, email_institucional, campus_virtual, portal_alumnos, biblioteca_digital, legajo
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

def actualizar_legajo(usuario_id, legajo):
    """
    Actualiza el número de legajo del alumno. El legajo es único a nivel de base
    de datos (constraint UNIQUE en usuarios.legajo), por lo que si otro alumno ya
    lo tiene cargado, devolvemos un mensaje claro en vez de un traceback crudo.
    Un legajo vacío se guarda como NULL (estado "pendiente").
    """
    legajo_normalizado = legajo.strip() if legajo and legajo.strip() else None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE usuarios SET legajo = %s WHERE id = %s;
                """, (legajo_normalizado, usuario_id))
            conn.commit()
        get_perfil.clear()
        return True, "Legajo actualizado.", legajo_normalizado
    except psycopg.errors.UniqueViolation:
        return False, f"El legajo '{legajo_normalizado}' ya está en uso por otro alumno.", None
    except Exception as e:
        return False, f"Error al guardar el legajo: {e}", None

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("👤 Mi Perfil")

    perfil = get_perfil(usuario["id"])
    if not perfil:
        st.error("No se pudo cargar el perfil.")
        return

    nombre, email, email_institucional, campus_virtual, portal_alumnos, biblioteca_digital, legajo = perfil

    st.markdown("### Datos personales")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Nombre:** {nombre}")
    with col2:
        st.markdown(f"**Email:** {email}")

    if "editando_legajo" not in st.session_state:
        st.session_state.editando_legajo = False

    if not st.session_state.editando_legajo:
        col_leg1, col_leg2 = st.columns([3, 1])
        with col_leg1:
            legajo_text = legajo if legajo else "⏳ Pendiente"
            st.markdown(f"**Número de legajo:** {legajo_text}")
        with col_leg2:
            if st.button("✏️ Editar legajo", use_container_width=True):
                st.session_state.editando_legajo = True
                st.rerun()
    else:
        with st.form("form_legajo"):
            nuevo_legajo = st.text_input(
                "Número de legajo",
                value=legajo or "",
                help="Dejalo vacío si todavía no te asignaron legajo."
            )
            col_g, col_c = st.columns(2)
            with col_g:
                guardar_legajo = st.form_submit_button("💾 Guardar", use_container_width=True)
            with col_c:
                cancelar_legajo = st.form_submit_button("❌ Cancelar", use_container_width=True)

        if guardar_legajo:
            ok, msg, legajo_guardado = actualizar_legajo(usuario["id"], nuevo_legajo)
            if ok:
                usuario["legajo"] = legajo_guardado
                st.session_state.usuario["legajo"] = legajo_guardado
                st.session_state.editando_legajo = False
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        if cancelar_legajo:
            st.session_state.editando_legajo = False
            st.rerun()

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
