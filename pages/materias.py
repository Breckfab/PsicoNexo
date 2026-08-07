import streamlit as st
from db import get_conn
from utils import NOMBRES_ANIO

ESTADOS = ["pendiente", "cursando", "regular", "aprobada", "desaprobada", "promocionada"]

ESTADO_LABELS = {
    "pendiente": "⬜ Pendiente",
    "cursando": "🟡 Cursando",
    "regular": "🟠 Regular",
    "aprobada": "🟢 Aprobada",
    "desaprobada": "🔴 Desaprobada",
    "promocionada": "🟢 Promocionada",
}

ESTADOS_APROBADOS = ("aprobada", "promocionada")


@st.cache_data(ttl=60)
def get_materias_carrera(carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, anio, cuatrimestre, final_obligatorio, es_electiva
                FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, cuatrimestre, nombre;
            """, (carrera_id,))
            return cur.fetchall()


@st.cache_data(ttl=60)
def get_estados_alumno(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT materia_id, estado
                FROM alumno_materias
                WHERE usuario_id = %s;
            """, (usuario_id,))
            return {r[0]: r[1] for r in cur.fetchall()}


@st.cache_data(ttl=300)
def get_correlativas_carrera(carrera_id):
    """
    Devuelve {materia_id: [(requiere_materia_id, requiere_nombre), ...]} con
    las correlatividades de todas las materias de la carrera. TTL largo
    porque esto casi nunca cambia (se carga una sola vez en seed_materias.py).
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT co.materia_id, r.id, r.nombre
                FROM correlatividades co
                JOIN materias m ON m.id = co.materia_id
                JOIN materias r ON r.id = co.requiere_materia_id
                WHERE m.carrera_id = %s
                ORDER BY r.anio, r.nombre;
            """, (carrera_id,))
            rows = cur.fetchall()
    resultado = {}
    for materia_id, requiere_id, requiere_nombre in rows:
        resultado.setdefault(materia_id, []).append((requiere_id, requiere_nombre))
    return resultado


def actualizar_estado_materia(usuario_id, materia_id, nuevo_estado):
    """
    Alta/actualización del estado de una materia para el alumno. Es el único
    lugar del repo que escribe en alumno_materias (antes de esta
    reconstrucción la tabla solo se leía — bug crítico relevado 07/08/2026:
    ningún alumno podía avanzar su plan de estudios desde la app).
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alumno_materias (usuario_id, materia_id, estado)
                VALUES (%s, %s, %s)
                ON CONFLICT (usuario_id, materia_id)
                DO UPDATE SET estado = EXCLUDED.estado;
            """, (usuario_id, materia_id, nuevo_estado))
        conn.commit()
    get_estados_alumno.clear()


def correlativas_cumplidas(materia_id, correlativas_map, estados_map):
    """
    (cumplidas: bool, faltantes: [nombres]) — evalúa si todas las materias
    requeridas por `materia_id` están 'aprobada' o 'promocionada' para
    este alumno.
    """
    requisitos = correlativas_map.get(materia_id, [])
    faltantes = [
        nombre for req_id, nombre in requisitos
        if estados_map.get(req_id, "pendiente") not in ESTADOS_APROBADOS
    ]
    return (len(faltantes) == 0, faltantes)


def calcular_sugeridas(materias, estados_map, correlativas_map):
    """Materias todavía pendientes cuyas correlativas ya están cumplidas."""
    sugeridas = []
    for mid, nombre, anio, cuatri, final_obligatorio, es_electiva in materias:
        if estados_map.get(mid, "pendiente") != "pendiente":
            continue
        cumplidas, _ = correlativas_cumplidas(mid, correlativas_map, estados_map)
        if cumplidas:
            sugeridas.append((mid, nombre, anio))
    return sugeridas


def mostrar_materia(usuario, materia, estados_map, correlativas_map):
    mid, nombre, anio, cuatri, final_obligatorio, es_electiva = materia
    estado_actual = estados_map.get(mid, "pendiente")
    cumplidas, faltantes = correlativas_cumplidas(mid, correlativas_map, estados_map)

    badges = []
    if es_electiva:
        badges.append("🔀 Electiva")
    badges.append("🎓 Final obligatorio" if final_obligatorio else "📈 Promocionable")

    titulo = f"{ESTADO_LABELS.get(estado_actual, estado_actual)} — {nombre}"

    with st.expander(titulo):
        st.caption(" · ".join(badges))

        requisitos = correlativas_map.get(mid, [])
        if requisitos:
            if cumplidas:
                st.success("✅ Correlativas cumplidas — podés cursarla.")
            else:
                st.warning("⚠️ Te faltan aprobar: " + ", ".join(faltantes))
            with st.expander("📋 Ver correlativas requeridas", expanded=False):
                for req_id, req_nombre in requisitos:
                    estado_req = estados_map.get(req_id, "pendiente")
                    icono_req = "✅" if estado_req in ESTADOS_APROBADOS else "❌"
                    st.caption(f"{icono_req} {req_nombre} — {ESTADO_LABELS.get(estado_req, estado_req)}")
        else:
            st.caption("Sin correlativas previas.")

        # Contador de reseteo (mismo patrón que el resto de los formularios
        # del sistema, ítem "formularios deben volver limpios", 02-04/08/2026).
        fk_key = f"estado_form_key_{mid}"
        if fk_key not in st.session_state:
            st.session_state[fk_key] = 0
        fk = st.session_state[fk_key]

        with st.form(f"form_estado_{mid}_{fk}"):
            nuevo_estado = st.selectbox(
                "Estado",
                ESTADOS,
                index=ESTADOS.index(estado_actual) if estado_actual in ESTADOS else 0,
                format_func=lambda e: ESTADO_LABELS.get(e, e),
                key=f"sel_estado_{mid}_{fk}",
            )
            guardar = st.form_submit_button("💾 Guardar estado", use_container_width=True)

        if guardar:
            if nuevo_estado == "cursando" and not cumplidas:
                st.error(
                    "🚫 No podés marcarla como 'Cursando': te faltan aprobar "
                    + ", ".join(faltantes)
                )
            else:
                actualizar_estado_materia(usuario["id"], mid, nuevo_estado)
                st.session_state[fk_key] += 1
                st.success("Estado actualizado.")
                st.rerun()


def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("📚 Plan de Estudios")
    st.caption("Marcá el estado de cada materia a medida que avanzás en la carrera. Las correlativas se validan automáticamente.")

    materias = get_materias_carrera(usuario["carrera_id"])
    if not materias:
        st.warning("No hay materias cargadas para tu carrera todavía.")
        return

    estados_map = get_estados_alumno(usuario["id"])
    correlativas_map = get_correlativas_carrera(usuario["carrera_id"])

    total = len(materias)
    aprobadas = sum(1 for m in materias if estados_map.get(m[0], "pendiente") in ESTADOS_APROBADOS)
    avance = round((aprobadas / total) * 100, 1) if total else 0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("✅ Aprobadas", f"{aprobadas} / {total}")
    with col2:
        st.metric("🎯 Avance de carrera", f"{avance}%")
    with col3:
        cursando_count = sum(1 for m in materias if estados_map.get(m[0]) == "cursando")
        st.metric("📖 Cursando", cursando_count)

    st.progress(avance / 100)
    st.markdown("---")

    sugeridas = calcular_sugeridas(materias, estados_map, correlativas_map)
    if sugeridas:
        st.markdown("### ✅ Materias habilitadas para cursar")
        st.caption("Ya cumplís las correlativas de estas materias:")
        for mid, nombre, anio in sugeridas:
            st.markdown(f"- {NOMBRES_ANIO.get(anio, '')} — **{nombre}**")
        st.markdown("---")

    st.markdown("### 📋 Todas las materias")

    filtro_col1, filtro_col2 = st.columns(2)
    with filtro_col1:
        anios_disponibles = sorted(set(m[2] for m in materias))
        opciones_anio = ["Todos"] + [NOMBRES_ANIO.get(a, str(a)) for a in anios_disponibles]
        filtro_anio = st.selectbox("Filtrar por año", opciones_anio)
    with filtro_col2:
        opciones_estado = ["Todos"] + [ESTADO_LABELS[e] for e in ESTADOS]
        filtro_estado_label = st.selectbox("Filtrar por estado", opciones_estado)

    materias_filtradas = materias
    if filtro_anio != "Todos":
        anio_num = [a for a in anios_disponibles if NOMBRES_ANIO.get(a, str(a)) == filtro_anio]
        if anio_num:
            materias_filtradas = [m for m in materias_filtradas if m[2] == anio_num[0]]
    if filtro_estado_label != "Todos":
        estado_sel = next(e for e in ESTADOS if ESTADO_LABELS[e] == filtro_estado_label)
        materias_filtradas = [m for m in materias_filtradas if estados_map.get(m[0], "pendiente") == estado_sel]

    if not materias_filtradas:
        st.info("No hay materias que coincidan con los filtros seleccionados.")
        return

    por_anio = {}
    for m in materias_filtradas:
        por_anio.setdefault(m[2], []).append(m)

    for anio in sorted(por_anio.keys()):
        st.markdown(f"#### {NOMBRES_ANIO.get(anio, f'Año {anio}')}")
        for materia in por_anio[anio]:
            mostrar_materia(usuario, materia, estados_map, correlativas_map)
