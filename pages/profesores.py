import streamlit as st
from db import get_conn
from utils import NOMBRES_ANIO

VALORACIONES = ["Recomendado", "No recomendado"]

# ─── Batch único de la pantalla (ítem prioridad alta, "Seguir optimizando
# latencia", 14/08/2026) ────────────────────────────────────────────────────
# Antes: 3 conexiones fijas al pool en cada carga (get_todas_materias,
# get_opiniones, get_recomendaciones_terceros). Con st.tabs las tres se
# disparan igual en cada rerun aunque el alumno esté mirando una sola tab
# (Streamlit ejecuta el contenido de las 3 tabs siempre, no solo la visible
# — eso es una limitación del componente en sí, no se resuelve batcheando).
# Lo que sí se puede evitar es que cada una de las 3 queries abra su propia
# conexión al pool: se consolidan acá en una sola conexión, mismo criterio
# que el resto del proyecto (Home, Plan de Estudios, tab "Cursando
# actualmente", Estadísticas) — en Neon serverless el costo real es el
# round-trip de adquirir la conexión, no las queries en sí.
#
# Reemplaza a las 3 funciones cacheadas viejas (get_todas_materias,
# get_opiniones, get_recomendaciones_terceros), eliminadas porque no las
# usaba ningún otro módulo fuera de esta pantalla.
#
# Invalidación de caché: agregar_opinion/actualizar_opinion/eliminar_opinion
# y agregar_recomendacion_tercero/actualizar_recomendacion_tercero/
# eliminar_recomendacion_tercero limpian este caché (ver más abajo).

@st.cache_data(ttl=60)
def get_profesores_data_completo(usuario_id, carrera_id):
    """
    Devuelve, en una sola conexión, todo lo que necesita pages/profesores.py:
    (todas_materias, opiniones, recomendaciones_terceros)
    - todas_materias: [(id, nombre, anio), ...]
    - opiniones: [(id, profesor, valoracion, observaciones, materia_nombre, materia_anio), ...]
    - recomendaciones_terceros: [(id, apellido, nombre, valoracion, observaciones,
      cargado_por, cargado_por_nombre, materia_ids, materia_nombres, materia_anios), ...]
    Mismo formato de fila que devolvían las 3 funciones originales.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # ── Todas las materias de la carrera (para los selectores) ───
            cur.execute("""
                SELECT id, nombre, anio FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, nombre;
            """, (carrera_id,))
            todas_materias = cur.fetchall()

            # ── Opiniones propias del alumno (privadas) ──────────────────
            cur.execute("""
                SELECT op.id, op.profesor, op.valoracion, op.observaciones, m.nombre, m.anio
                FROM opiniones_profesores op
                JOIN materias m ON op.materia_id = m.id
                WHERE op.usuario_id = %s
                ORDER BY op.profesor, m.anio, m.nombre;
            """, (usuario_id,))
            opiniones = cur.fetchall()

            # ── Recomendaciones de terceros (compartidas por carrera) ────
            cur.execute("""
                SELECT rt.id, rt.apellido, rt.nombre, rt.valoracion, rt.observaciones,
                       rt.cargado_por, u.nombre AS cargado_por_nombre,
                       ARRAY_AGG(m.id ORDER BY m.anio, m.nombre) AS materia_ids,
                       ARRAY_AGG(m.nombre ORDER BY m.anio, m.nombre) AS materia_nombres,
                       ARRAY_AGG(m.anio ORDER BY m.anio, m.nombre) AS materia_anios
                FROM recomendaciones_terceros rt
                JOIN recomendaciones_terceros_materias rtm ON rtm.recomendacion_id = rt.id
                JOIN materias m ON rtm.materia_id = m.id
                LEFT JOIN usuarios u ON rt.cargado_por = u.id
                WHERE m.carrera_id = %s
                GROUP BY rt.id, rt.apellido, rt.nombre, rt.valoracion, rt.observaciones,
                         rt.cargado_por, u.nombre
                ORDER BY rt.apellido, rt.nombre;
            """, (carrera_id,))
            recomendaciones_terceros = cur.fetchall()

    return todas_materias, opiniones, recomendaciones_terceros

def agregar_opinion(usuario_id, materia_id, profesor, valoracion, observaciones):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO opiniones_profesores (usuario_id, materia_id, profesor, valoracion, observaciones)
                VALUES (%s, %s, %s, %s, %s);
            """, (usuario_id, materia_id, profesor, valoracion, observaciones))
        conn.commit()
    get_profesores_data_completo.clear()

def actualizar_opinion(opinion_id, valoracion, observaciones):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE opiniones_profesores SET valoracion = %s, observaciones = %s
                WHERE id = %s;
            """, (valoracion, observaciones, opinion_id))
        conn.commit()
    get_profesores_data_completo.clear()

def eliminar_opinion(opinion_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM opiniones_profesores WHERE id = %s;", (opinion_id,))
        conn.commit()
    get_profesores_data_completo.clear()

# ─── Profesores recomendados por terceros ───────────────────────────────────
# A diferencia de opiniones_profesores (privada, un alumno opina de una
# materia que él mismo cursó), esta sección es COMPARTIDA entre todos los
# alumnos de la carrera: sirve para cargar profesores de los que un alumno
# se enteró por un tercero, sin haber cursado él mismo con ellos. Un mismo
# profesor puede dictar hasta 5 materias, guardadas en la tabla puente
# recomendaciones_terceros_materias. Solo quien cargó una recomendación
# puede editarla o borrarla (agregado 29/07/2026).

def agregar_recomendacion_tercero(usuario_id, apellido, nombre, valoracion, observaciones, materia_ids):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO recomendaciones_terceros (apellido, nombre, valoracion, observaciones, cargado_por)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
            """, (apellido, nombre, valoracion, observaciones, usuario_id))
            recomendacion_id = cur.fetchone()[0]
            for materia_id in materia_ids:
                cur.execute("""
                    INSERT INTO recomendaciones_terceros_materias (recomendacion_id, materia_id)
                    VALUES (%s, %s)
                    ON CONFLICT (recomendacion_id, materia_id) DO NOTHING;
                """, (recomendacion_id, materia_id))
        conn.commit()
    get_profesores_data_completo.clear()

def actualizar_recomendacion_tercero(recomendacion_id, apellido, nombre, valoracion, observaciones, materia_ids):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE recomendaciones_terceros
                SET apellido = %s, nombre = %s, valoracion = %s, observaciones = %s
                WHERE id = %s;
            """, (apellido, nombre, valoracion, observaciones, recomendacion_id))
            cur.execute("DELETE FROM recomendaciones_terceros_materias WHERE recomendacion_id = %s;", (recomendacion_id,))
            for materia_id in materia_ids:
                cur.execute("""
                    INSERT INTO recomendaciones_terceros_materias (recomendacion_id, materia_id)
                    VALUES (%s, %s)
                    ON CONFLICT (recomendacion_id, materia_id) DO NOTHING;
                """, (recomendacion_id, materia_id))
        conn.commit()
    get_profesores_data_completo.clear()

def eliminar_recomendacion_tercero(recomendacion_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM recomendaciones_terceros WHERE id = %s;", (recomendacion_id,))
        conn.commit()
    get_profesores_data_completo.clear()

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("⭐ Opiniones de Profesores")
    st.caption("Tus opiniones son privadas y solo las ves vos.")

    # ── Batch único de la pantalla (ítem prioridad alta, latencia de carga,
    # 14/08/2026): antes eran 3 conexiones fijas al pool (todas_materias,
    # opiniones, recomendaciones_terceros). Ahora es 1 sola — ver
    # get_profesores_data_completo más arriba.
    todas, opiniones_todas, recomendaciones = get_profesores_data_completo(
        usuario["id"], usuario["carrera_id"]
    )
    opciones = {f"{NOMBRES_ANIO.get(m[2], '')} — {m[1]}": m[0] for m in todas}

    tab1, tab2, tab3 = st.tabs([
        "📋 Mis opiniones",
        "➕ Agregar opinión",
        "🗣️ Profesores recomendados por terceros",
    ])

    with tab1:
        opiniones = opiniones_todas

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


                for profesor, ops in por_profesor.items():
                    recomendados = sum(1 for o in ops if o[2] == "Recomendado")
                    icono_prof = "👍" if recomendados >= len(ops) / 2 else "👎"

                    with st.expander(f"{icono_prof} {profesor} ({len(ops)} materia{'s' if len(ops) > 1 else ''})"):
                        for op in ops:
                            oid, _, valoracion, observaciones, materia_nombre, materia_anio = op
                            key_edit_op = f"editando_opinion_{oid}"
                            anio_texto = NOMBRES_ANIO.get(materia_anio, f"Año {materia_anio}")

                            if st.session_state.get(key_edit_op):
                                # ── Formulario de edición inline ──────────────────
                                with st.form(f"form_edit_opinion_{oid}"):
                                    st.markdown(f"**✏️ Editando opinión — {anio_texto}: {materia_nombre}**")
                                    nueva_valoracion = st.radio(
                                        "Valoración", VALORACIONES,
                                        index=VALORACIONES.index(valoracion) if valoracion in VALORACIONES else 0,
                                        horizontal=True,
                                        key=f"edit_val_{oid}"
                                    )
                                    nuevas_obs = st.text_area(
                                        "Observaciones (opcional)",
                                        value=observaciones or "",
                                        height=100,
                                        key=f"edit_obs_{oid}"
                                    )
                                    col_go, col_co = st.columns(2)
                                    with col_go:
                                        guardar_op_edit = st.form_submit_button("💾 Guardar", use_container_width=True)
                                    with col_co:
                                        cancelar_op_edit = st.form_submit_button("❌ Cancelar", use_container_width=True)

                                if guardar_op_edit:
                                    actualizar_opinion(oid, nueva_valoracion, nuevas_obs.strip())
                                    st.session_state[key_edit_op] = False
                                    st.success("Opinión actualizada.")
                                    st.rerun()
                                if cancelar_op_edit:
                                    st.session_state[key_edit_op] = False
                                    st.rerun()

                            else:
                                icono_val = "✅" if valoracion == "Recomendado" else "❌"

                                col1, col2, col3 = st.columns([5, 1, 1])
                                with col1:
                                    st.markdown(f"{icono_val} **{valoracion}** — {anio_texto}: {materia_nombre}")
                                    if observaciones:
                                        st.caption(f"💬 {observaciones}")
                                with col2:
                                    if st.button("✏️", key=f"edit_op_{oid}", use_container_width=True):
                                        st.session_state[key_edit_op] = True
                                        st.rerun()
                                with col3:
                                    if st.button("🗑️", key=f"del_op_{oid}", use_container_width=True):
                                        eliminar_opinion(oid)
                                        st.rerun()

                        st.markdown("---")

    with tab2:
        opciones_lista = ["Elegí una materia"] + list(opciones.keys())

        if "form_opinion_key" not in st.session_state:
            st.session_state.form_opinion_key = 0
        fk = st.session_state.form_opinion_key

        # Cada widget lleva su propia key atada al contador de reseteo `fk`
        # (mismo patrón que feriados/faltas/comisiones/evaluaciones/recursos,
        # ítem "formularios deben volver limpios", 02/08/2026). Sin esto, el
        # form_opinion_key igual cambia el nombre del st.form, pero los
        # widgets de adentro conservan lo tipeado porque no tenían key propia.
        with st.form(f"form_opinion_{fk}"):
            profesor = st.text_input("Nombre del profesor/a", key=f"opinion_profesor_{fk}")
            materia_label = st.selectbox(
                "Materia que dicta", opciones_lista, index=0, key=f"opinion_materia_{fk}"
            )
            valoracion = st.radio(
                "Valoración", VALORACIONES, horizontal=True, key=f"opinion_valoracion_{fk}"
            )
            observaciones = st.text_area(
                "Observaciones (opcional)", height=100, key=f"opinion_obs_{fk}"
            )
            submit = st.form_submit_button("💾 Guardar opinión", use_container_width=True)

        if submit:
            if not profesor:
                st.error("Ingresá el nombre del profesor/a.")
            elif materia_label == "Elegí una materia":
                st.error("Seleccioná una materia.")
            else:
                materia_id = opciones[materia_label]
                agregar_opinion(usuario["id"], materia_id, profesor.strip(), valoracion, observaciones.strip())
                st.session_state.form_opinion_key += 1
                st.success("✅ Opinión guardada.")
                st.rerun()

    with tab3:
        st.caption(
            "Recomendaciones **compartidas con todos los alumnos**, sobre profesores de los "
            "que te enteraste por un tercero (no cursaste vos mismo/a con ellos)."
        )

        opciones_mat = opciones
        opciones_mat_lista = ["—"] + list(opciones_mat.keys())

        if "form_terceros_key" not in st.session_state:
            st.session_state.form_terceros_key = 0
        fk_t = st.session_state.form_terceros_key

        # Cada widget con key atada a `fk_t` (mismo patrón que el resto de
        # los formularios "que deben volver limpios", 02/08/2026 / 04/08/2026).
        with st.expander("➕ Cargar recomendación de un tercero"):
            with st.form(f"form_terceros_{fk_t}"):
                col_ap, col_no = st.columns(2)
                with col_ap:
                    t_apellido = st.text_input("Apellido del profesor/a", key=f"terceros_apellido_{fk_t}")
                with col_no:
                    t_nombre = st.text_input("Nombre del profesor/a", key=f"terceros_nombre_{fk_t}")

                t_valoracion = st.radio(
                    "Valoración", VALORACIONES, horizontal=True, key=f"terceros_valoracion_{fk_t}"
                )

                st.markdown("**Materias que dicta** _(hasta 5, completá al menos una)_")
                t_materias_labels = []
                for i in range(5):
                    t_materias_labels.append(
                        st.selectbox(
                            f"Materia {i + 1}", opciones_mat_lista, index=0,
                            key=f"terceros_materia_{i}_{fk_t}"
                        )
                    )

                t_observaciones = st.text_area(
                    "Observaciones (opcional)", height=100, key=f"terceros_obs_{fk_t}"
                )
                submit_terceros = st.form_submit_button("💾 Guardar recomendación", use_container_width=True)

            if submit_terceros:
                materia_ids_sel = [opciones_mat[lbl] for lbl in t_materias_labels if lbl != "—"]
                if not t_apellido.strip() or not t_nombre.strip():
                    st.error("Completá apellido y nombre del profesor/a.")
                elif not materia_ids_sel:
                    st.error("Seleccioná al menos una materia.")
                else:
                    agregar_recomendacion_tercero(
                        usuario["id"], t_apellido.strip(), t_nombre.strip(),
                        t_valoracion, t_observaciones.strip(), materia_ids_sel
                    )
                    st.session_state.form_terceros_key += 1
                    st.success("✅ Recomendación guardada. Ya la pueden ver todos los alumnos.")
                    st.rerun()

        st.markdown("---")

        if not recomendaciones:
            st.info("Todavía no hay recomendaciones de terceros cargadas.")
        else:
            # Agrupar por profesor (apellido + nombre, sin importar mayúsculas/
            # espacios) para que si dos alumnos distintos cargan al mismo
            # profesor por separado, aparezca combinado en un solo bloque.
            por_profesor_t = {}
            for r in recomendaciones:
                r_apellido, r_nombre = r[1], r[2]
                clave = (r_apellido.strip().lower(), r_nombre.strip().lower())
                if clave not in por_profesor_t:
                    por_profesor_t[clave] = {"apellido": r_apellido, "nombre": r_nombre, "entradas": []}
                por_profesor_t[clave]["entradas"].append(r)

            for clave, grupo in por_profesor_t.items():
                entradas = grupo["entradas"]
                recomendados_t = sum(1 for e in entradas if e[3] == "Recomendado")
                icono_prof_t = "👍" if recomendados_t >= len(entradas) / 2 else "👎"

                materias_combinadas = set()
                for e in entradas:
                    for mn in e[8]:
                        materias_combinadas.add(mn)

                titulo_expander = f"{icono_prof_t} {grupo['apellido']}, {grupo['nombre']} — {', '.join(sorted(materias_combinadas))}"

                with st.expander(titulo_expander):
                    for e in entradas:
                        (eid, e_apellido, e_nombre, e_val, e_obs, e_cargado_por,
                         e_cargado_por_nombre, e_mat_ids, e_mat_nombres, e_mat_anios) = e

                        key_edit_t = f"editando_terceros_{eid}"
                        es_propia = usuario["id"] == e_cargado_por

                        if es_propia and st.session_state.get(key_edit_t):
                            # ── Formulario de edición inline (solo el dueño llega acá) ──
                            with st.form(f"form_edit_terceros_{eid}"):
                                ec_apellido = st.text_input("Apellido del profesor/a", value=e_apellido, key=f"e_ap_{eid}")
                                ec_nombre = st.text_input("Nombre del profesor/a", value=e_nombre, key=f"e_no_{eid}")
                                ec_valoracion = st.radio(
                                    "Valoración", VALORACIONES,
                                    index=VALORACIONES.index(e_val) if e_val in VALORACIONES else 0,
                                    horizontal=True, key=f"e_val_{eid}"
                                )

                                st.markdown("**Materias que dicta** _(hasta 5)_")
                                materia_ids_actuales = list(e_mat_ids)
                                ec_materias_labels = []
                                for i in range(5):
                                    default_label = "—"
                                    if i < len(materia_ids_actuales):
                                        for lbl, mid_opt in opciones_mat.items():
                                            if mid_opt == materia_ids_actuales[i]:
                                                default_label = lbl
                                                break
                                    idx_default = opciones_mat_lista.index(default_label) if default_label in opciones_mat_lista else 0
                                    ec_materias_labels.append(
                                        st.selectbox(f"Materia {i + 1}", opciones_mat_lista, index=idx_default, key=f"e_mat_{i}_{eid}")
                                    )

                                ec_observaciones = st.text_area("Observaciones (opcional)", value=e_obs or "", height=100, key=f"e_obs_{eid}")

                                col_ge, col_ce = st.columns(2)
                                with col_ge:
                                    guardar_t_edit = st.form_submit_button("💾 Guardar", use_container_width=True)
                                with col_ce:
                                    cancelar_t_edit = st.form_submit_button("❌ Cancelar", use_container_width=True)

                            if guardar_t_edit:
                                materia_ids_edit_sel = [opciones_mat[lbl] for lbl in ec_materias_labels if lbl != "—"]
                                if not ec_apellido.strip() or not ec_nombre.strip():
                                    st.error("Completá apellido y nombre del profesor/a.")
                                elif not materia_ids_edit_sel:
                                    st.error("Seleccioná al menos una materia.")
                                else:
                                    actualizar_recomendacion_tercero(
                                        eid, ec_apellido.strip(), ec_nombre.strip(),
                                        ec_valoracion, ec_observaciones.strip(), materia_ids_edit_sel
                                    )
                                    st.session_state[key_edit_t] = False
                                    st.success("Recomendación actualizada.")
                                    st.rerun()
                            if cancelar_t_edit:
                                st.session_state[key_edit_t] = False
                                st.rerun()

                        else:
                            icono_val_t = "✅" if e_val == "Recomendado" else "❌"
                            materias_texto = ", ".join(e_mat_nombres)

                            if es_propia:
                                col1, col2, col3 = st.columns([5, 1, 1])
                                with col1:
                                    st.markdown(f"{icono_val_t} **{e_val}** — {materias_texto}")
                                    if e_obs:
                                        st.caption(f"💬 {e_obs}")
                                    st.caption("Cargado por: vos")
                                with col2:
                                    if st.button("✏️", key=f"edit_terceros_{eid}", use_container_width=True):
                                        st.session_state[key_edit_t] = True
                                        st.rerun()
                                with col3:
                                    if st.button("🗑️", key=f"del_terceros_{eid}", use_container_width=True):
                                        eliminar_recomendacion_tercero(eid)
                                        st.rerun()
                            else:
                                st.markdown(f"{icono_val_t} **{e_val}** — {materias_texto}")
                                if e_obs:
                                    st.caption(f"💬 {e_obs}")
                                st.caption(f"Cargado por: {e_cargado_por_nombre or 'otro alumno'}")

                        st.markdown("---")
