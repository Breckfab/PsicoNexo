import streamlit as st
import pandas as pd
from db import get_conn

NOMBRES_ANIO = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
ORDEN_CUATRI = {"1° Cuatrimestre": 1, "2° Cuatrimestre": 2, "Anual": 3,
                "1": 1, "2": 2, "anual": 3}

@st.cache_data(ttl=60)
def get_avance_carrera(usuario_id, carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.anio, COALESCE(am.estado, 'pendiente') as estado, COUNT(*) as cantidad
                FROM materias m
                LEFT JOIN alumno_materias am ON m.id = am.materia_id AND am.usuario_id = %s
                WHERE m.carrera_id = %s
                GROUP BY m.anio, estado
                ORDER BY m.anio;
            """, (usuario_id, carrera_id))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_evolucion_promedios(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.anio_cursada, c.cuatrimestre, AVG(e.nota) as promedio
                FROM evaluaciones e
                JOIN cursadas c ON c.materia_id = e.materia_id AND c.usuario_id = e.usuario_id
                WHERE e.usuario_id = %s AND e.nota IS NOT NULL
                GROUP BY c.anio_cursada, c.cuatrimestre
                ORDER BY c.anio_cursada;
            """, (usuario_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_promedio_materias(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.nombre, m.anio, AVG(e.nota) as promedio, COUNT(e.id) as cantidad_notas
                FROM evaluaciones e
                JOIN materias m ON e.materia_id = m.id
                WHERE e.usuario_id = %s AND e.nota IS NOT NULL
                GROUP BY m.nombre, m.anio
                ORDER BY promedio DESC;
            """, (usuario_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_notas(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nota FROM evaluaciones
                WHERE usuario_id = %s AND nota IS NOT NULL;
            """, (usuario_id,))
            return [r[0] for r in cur.fetchall()]

@st.cache_data(ttl=60)
def get_tasa_aprobacion(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tipo,
                       COUNT(*) FILTER (WHERE aprobado = TRUE) as aprobados,
                       COUNT(*) as total
                FROM evaluaciones
                WHERE usuario_id = %s
                GROUP BY tipo;
            """, (usuario_id,))
            return cur.fetchall()


def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("📊 Estadísticas y Analíticas")
    st.caption("Un vistazo completo a tu rendimiento académico.")

    # ── Avance de carrera ──────────────────────────────────────────
    st.markdown("### 🎯 Avance de carrera")
    avance_rows = get_avance_carrera(usuario["id"], usuario["carrera_id"])

    if not avance_rows:
        st.info("No hay datos suficientes todavía.")
    else:
        data = {}
        for anio, estado, cantidad in avance_rows:
            anio_label = NOMBRES_ANIO.get(anio, f"Año {anio}")
            if anio_label not in data:
                data[anio_label] = {"Aprobada": 0, "Cursando": 0, "Regular": 0, "Pendiente": 0, "Desaprobada": 0}
            if estado in ("aprobada", "promocionada"):
                data[anio_label]["Aprobada"] += cantidad
            elif estado == "cursando":
                data[anio_label]["Cursando"] += cantidad
            elif estado == "regular":
                data[anio_label]["Regular"] += cantidad
            elif estado == "desaprobada":
                data[anio_label]["Desaprobada"] += cantidad
            else:
                data[anio_label]["Pendiente"] += cantidad

        df_avance = pd.DataFrame(data).T
        orden = [v for v in NOMBRES_ANIO.values() if v in df_avance.index]
        df_avance = df_avance.reindex(orden)
        st.bar_chart(df_avance, color=["#2ecc71", "#f0c000", "#f07800", "#555577", "#e74c3c"])

    st.markdown("---")

    # ── Evolución de promedios ─────────────────────────────────────
    st.markdown("### 📈 Evolución de promedios")
    evol_rows = get_evolucion_promedios(usuario["id"])

    if not evol_rows:
        st.info("Todavía no tenés notas cargadas con cursadas asociadas.")
    else:
        cuatri_texto = {"1": "1° Cuat.", "2": "2° Cuat.", "anual": "Anual",
                         "1° Cuatrimestre": "1° Cuat.", "2° Cuatrimestre": "2° Cuat.", "Anual": "Anual"}
        filas_ordenadas = sorted(evol_rows, key=lambda r: (r[0], ORDEN_CUATRI.get(r[1], 9)))

        etiquetas, valores = [], []
        for anio_c, cuatri, promedio in filas_ordenadas:
            etiquetas.append(f"{cuatri_texto.get(cuatri, cuatri)} {anio_c}")
            valores.append(round(float(promedio), 2))

        df_evol = pd.DataFrame({"Promedio": valores}, index=etiquetas)
        st.line_chart(df_evol)

    st.markdown("---")

    # ── Promedio por materia ────────────────────────────────────────
    st.markdown("### 🏆 Promedio por materia")
    prom_rows = get_promedio_materias(usuario["id"])

    if not prom_rows:
        st.info("Todavía no tenés notas cargadas.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**🟢 Mejores promedios**")
            for nombre, anio, promedio, cant in prom_rows[:5]:
                st.markdown(f"**{float(promedio):.2f}** — {nombre} _{NOMBRES_ANIO.get(anio, '')}_")
        with col2:
            st.markdown("**🔴 Promedios más bajos**")
            for nombre, anio, promedio, cant in prom_rows[-5:][::-1]:
                st.markdown(f"**{float(promedio):.2f}** — {nombre} _{NOMBRES_ANIO.get(anio, '')}_")

        with st.expander("📋 Ver ranking completo"):
            df_ranking = pd.DataFrame(
                [(n, NOMBRES_ANIO.get(a, a), round(float(p), 2), c) for n, a, p, c in prom_rows],
                columns=["Materia", "Año", "Promedio", "Cant. Notas"]
            )
            st.dataframe(df_ranking, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Distribución de notas ───────────────────────────────────────
    st.markdown("### 📊 Distribución de notas")
    notas = get_notas(usuario["id"])

    if not notas:
        st.info("Todavía no tenés notas cargadas.")
    else:
        buckets = {"0-3": 0, "4-5": 0, "6-7": 0, "8-10": 0}
        for n in notas:
            n = float(n)
            if n <= 3:
                buckets["0-3"] += 1
            elif n <= 5:
                buckets["4-5"] += 1
            elif n <= 7:
                buckets["6-7"] += 1
            else:
                buckets["8-10"] += 1

        df_dist = pd.DataFrame({"Cantidad": buckets.values()}, index=buckets.keys())
        st.bar_chart(df_dist, color="#7B2FBE")

    st.markdown("---")

    # ── Tasa de aprobación por tipo ──────────────────────────────────
    st.markdown("### ✅ Tasa de aprobación por tipo de evaluación")
    tasa_rows = get_tasa_aprobacion(usuario["id"])

    if not tasa_rows:
        st.info("Todavía no tenés evaluaciones cargadas.")
    else:
        cols = st.columns(len(tasa_rows))
        for i, (tipo, aprobados, total) in enumerate(tasa_rows):
            porcentaje = round((aprobados / total) * 100, 1) if total > 0 else 0
            with cols[i]:
                st.metric(tipo, f"{porcentaje}%", f"{aprobados}/{total}")
