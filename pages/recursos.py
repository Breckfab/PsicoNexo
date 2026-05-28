import streamlit as st
from db import get_connection

TIPOS = ["Bibliografía", "Apunte", "NotebookLM", "Otro"]

def get_materias_alumno(usuario_id, carrera_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nombre, anio FROM materias
        ORDER BY anio, nombre;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_recursos(usuario_id, materia_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nombre, tipo, link
        FROM recursos
        WHERE usuario_id = %s AND materia_id = %s
        ORDER BY tipo, nombre;
    """, (usuario_id, materia_id))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def agregar_recurso(usuario_id, materia_id, nombre, tipo, link):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO recursos (usuario_id, materia_id, nombre, tipo, link)
        VALUES (%s, %s, %s, %s, %s);
    """, (usuario_id, materia_id, nombre, tipo, link))
    conn.commit()
    cur.close()
    conn.close()

def eliminar_recurso(recurso_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM recursos WHERE id = %s;", (recurso_id,))
    conn.commit()
    cur.close()
    conn.close()

def convertir_link_preview(link):
    if "drive.google.com" in link and "/file/d/" in link:
        try:
            file_id = link.split("/file/d/")[1].split("/")[0]
            return f"https://drive.google.com/file/d/{file_id}/preview"
        except:
            return None
    if "dropbox.com" in link:
        try:
            url = link.split("?")[0]
            return f"{url}?raw=1"
        except:
            return None
    return None

def mostrar(usuario):
    st.title("📂 Recursos por Materia")

    materias = get_materias_alumno(usuario["id"], usuario["carrera_id"])
    if not materias:
        st.warning("No hay materias disponibles.")
        return

    nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
    opciones = {f"{nombres_anio.get(m[2], '')} — {m[1]}": m[0] for m in materias}

    materia_label = st.selectbox("Seleccioná una materia", list(opciones.keys()))
    materia_id = opciones[materia_label]

    st.markdown("---")

    with st.expander("➕ Agregar nuevo recurso"):
        with st.form("form_recurso"):
            nombre = st.text_input("Nombre del recurso")
            tipo = st.selectbox("Tipo", TIPOS)
            link = st.text_input("Link (Google Drive, Dropbox, NotebookLM, etc.)")
            submit = st.form_submit_button("💾 Guardar", use_container_width=True)
        if submit:
            if not nombre or not link:
                st.error("Completá nombre y link.")
            else:
                agregar_recurso(usuario["id"], materia_id, nombre, tipo, link)
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
                iconos = {"Bibliografía": "📚", "Apunte": "📝", "NotebookLM": "🤖", "Otro": "🔗"}
                st.markdown(f"### {iconos.get(rtipo, '🔗')} {rtipo}")

            col1, col2 = st.columns([4, 1])
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
                if st.button("🗑️ Borrar", key=f"del_{rid}", use_container_width=True):
                    eliminar_recurso(rid)
                    st.rerun()

        st.markdown("---")
