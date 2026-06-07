import streamlit as st
from db import get_conn

ESTADOS = ["pendiente", "cursando", "regular", "promocionada", "aprobada", "desaprobada"]

COLORES = {
    "pendiente": "⬜",
    "cursando": "🟡",
    "regular": "🟠",
    "promocionada": "🟢",
    "aprobada": "🟢",
    "desaprobada": "🔴",
}

@st.cache_data(ttl=300)
def get_materias_con_estado(usuario_id, carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.codigo, m.nombre, m.anio, m.cuatrimestre,
                       m.final_obligatorio, m.es_electiva,
                       COALESCE(am.estado, 'pendiente') as estado
                FROM materias m
                LEFT JOIN alumno_materias am
                    ON m.id = am.materia_id AND am.usuario_id = %s
                WHERE m.carrera_id = %s
                ORDER BY m.anio, m.cuatrimestre, m.nombre;
            """, (usuario_id, carrera_id))
            return cur.fetchall()

@st.cache_data(ttl=600)
def get_todas_correlatividades(carrera_id, usuario_id):
    """Trae TODAS las correlatividades de la carrera en una sola query."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.materia_id, m.nombre, COALESCE(am.estado, 'pendiente') as estado
                FROM correlatividades c
                JOIN materias m ON c.requiere_materia_id = m.id
                LEFT JOIN alumno_materias am ON am.materia_id = m.id AND am.usuario_id = %s
                WHERE m.carrera_id = %s
                ORDER BY m.anio, m.nombre;
            """, (usuario_id, carrera_id))
            rows = cur.fetchall()
    result = {}
    for materia_id, nombre, estado in rows:
        result.setdefault(materia_id, []).append((nombre, estado))
    return result

@st.cache_data(ttl=60)
def get_todos_programas(usuario_id):
    """Trae todos los programas del usuario en una sola query."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT materia_id, id, link FROM programas WHERE usuario_id = %s;
            """, (usuario_id,))
            rows = cur.fetchall()
    return {materia_id: (pid, link) for materia_id, pid, link in rows}

def actualizar_estado(usuario_id, materia_id, nuevo_estado):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alumno_materias (usuario_id, materia_id, estado)
                VALUES (%s, %s, %s)
                ON CONFLICT (usuario_id, materia_id)
                DO UPDATE SET estado = EXCLUDED.estado;
            """, (usuario_id, materia_id, nuevo_estado))
        conn.commit()
    get_materias_con_estado.clear()

def guardar_programa(usuario_id, materia_id, link):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO programas (usuario_id, materia_id, link)
                VALUES (%s, %s, %s)
                ON CONFLICT (usuario_id, materia_id)
                DO UPDATE SET link = EXCLUDED.link;
            """, (usuario_id, materia_id, link))
        conn.commit()
    get_todos_programas.clear()

def borrar_programa(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM programas WHERE usuario_id = %s AND materia_id = %s;
            """, (usuario_id, materia_id))
        conn.commit()
    get_todos_programas.clear()

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
    st.title("📋 Plan de Estudios")
    st.caption("Licenciatura en Psicología — UdeMM")

    # Una sola pasada a la DB para todo
    materias = get_materias_con_estado(usuario["id"], usuario["carrera_id"])
    correlatividades_map = get_todas_correlatividades(usuario["carrera_id"], usuario["id"])
    programas_map = get_todos_programas(usuario["id"])

    if not materias:
        st.warning("No se encontraron materias para tu carrera.")
        return

    busqueda = st.text_input("🔍 Buscar materia", placeholder="Escribí el nombre de la materia...")

    if busqueda.strip():
        materias = [m for m in materias if busqueda.strip().lower() in m[2].lower()]
        if not materias:
            st.info("No se encontraron materias que coincidan con la búsqueda.")
            return

    por_anio = {}
    for m in materias:
        anio = m[3]
        if anio not in por_anio:
            por_anio[anio] = []
        por_anio[anio].append(m)

    nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}

    for anio, lista in por_anio.items():
        st.subheader(nombres_anio.get(anio, f"Año {anio}"))

        for m in lista:
            mid, codigo, nombre, _, cuatri, final_oblig, es_electiva, estado = m

            programa = programas_map.get(mid)

            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                etiquetas = []
                if final_oblig:
                    etiquetas.append("📝 Final obligatorio")
                if es_electiva:
                    etiquetas.append("⭐ Electiva")
                cuatri_texto = {"1": "1° cuatrimestre", "2": "2° cuatrimestre", "anual": "Anual"}.get(cuatri, cuatri)
                icono_programa = " 📋" if programa else ""
                st.markdown(f"{COLORES[estado]} **{nombre}**{icono_programa}")
                st.caption(f"{codigo or ''} · {cuatri_texto} {'· ' + ' · '.join(etiquetas) if etiquetas else ''}")

            with col2:
                nuevo_estado = st.selectbox(
                    "Estado",
                    ESTADOS,
                    index=ESTADOS.index(estado),
                    key=f"estado_{mid}",
                    label_visibility="collapsed"
                )
                if nuevo_estado != estado:
                    actualizar_estado(usuario["id"], mid, nuevo_estado)
                    st.rerun()

            with col3:
                if programa:
                    if st.button("📋 Programa", key=f"ver_prog_{mid}", use_container_width=True):
                        st.session_state[f"viendo_programa_{mid}"] = not st.session_state.get(f"viendo_programa_{mid}", False)
                        st.rerun()
                else:
                    if st.button("➕ Programa", key=f"add_prog_{mid}", use_container_width=True):
                        st.session_state[f"cargando_programa_{mid}"] = True
                        st.rerun()

            # Correlatividades — sin query extra por materia
            correlativas = correlatividades_map.get(mid, [])
            if correlativas:
                with st.expander(f"📎 Correlativas ({len(correlativas)})", expanded=False):
                    for cnombre, cestado in correlativas:
                        icono = COLORES.get(cestado, "⬜")
                        st.markdown(f"{icono} {cnombre} — *{cestado.capitalize()}*")

            # Panel de programa (ver/editar/borrar)
            if programa and st.session_state.get(f"viendo_programa_{mid}"):
                pid, plink = programa
                with st.container():
                    st.markdown(f"🔗 [Abrir programa]({plink})")
                    preview_url = convertir_link_preview(plink)
                    if preview_url:
                        with st.expander("👁️ Ver PDF"):
                            st.components.v1.iframe(preview_url, height=500)
                    col_edit, col_del = st.columns(2)
                    with col_edit:
                        if st.button("✏️ Editar link", key=f"edit_prog_{mid}", use_container_width=True):
                            st.session_state[f"editando_programa_{mid}"] = True
                            st.rerun()
                    with col_del:
                        if st.button("🗑️ Borrar programa", key=f"del_prog_{mid}", use_container_width=True):
                            borrar_programa(usuario["id"], mid)
                            st.session_state[f"viendo_programa_{mid}"] = False
                            st.rerun()

                    if st.session_state.get(f"editando_programa_{mid}"):
                        with st.form(f"form_edit_prog_{mid}"):
                            nuevo_link = st.text_input("Nuevo link", value=plink)
                            col1f, col2f = st.columns(2)
                            with col1f:
                                if st.form_submit_button("💾 Guardar", use_container_width=True):
                                    if nuevo_link.strip():
                                        guardar_programa(usuario["id"], mid, nuevo_link.strip())
                                        st.session_state[f"editando_programa_{mid}"] = False
                                        st.rerun()
                            with col2f:
                                if st.form_submit_button("❌ Cancelar", use_container_width=True):
                                    st.session_state[f"editando_programa_{mid}"] = False
                                    st.rerun()

            # Panel de carga nuevo programa
            if not programa and st.session_state.get(f"cargando_programa_{mid}"):
                with st.form(f"form_prog_{mid}"):
                    nuevo_link = st.text_input("Link del programa (Google Drive, Dropbox, PDF, etc.)")
                    col1f, col2f = st.columns(2)
                    with col1f:
                        if st.form_submit_button("💾 Guardar", use_container_width=True):
                            if nuevo_link.strip():
                                guardar_programa(usuario["id"], mid, nuevo_link.strip())
                                st.session_state[f"cargando_programa_{mid}"] = False
                                st.rerun()
                    with col2f:
                        if st.form_submit_button("❌ Cancelar", use_container_width=True):
                            st.session_state[f"cargando_programa_{mid}"] = False
                            st.rerun()

        st.markdown("---")
