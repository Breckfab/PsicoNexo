import streamlit as st
import pandas as pd
import altair as alt
from db import get_conn, get_feriados, get_periodos_comision
from utils import (
    NOMBRES_ANIO, ORDEN_CUATRI, CUATRI_TEXTO,
    contar_clases_en_rango, contar_clases_multi_periodo, clasificar_asistencia,
)
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

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

# ─── Historial visual de asistencia (ítem #1 de "Cosas por Hacer", 03/08/2026) ──
# Reutiliza el mismo criterio de cálculo que ya usan home.py y cursadas.py
# (contar_clases_en_rango / contar_clases_multi_periodo + clasificar_asistencia),
# para que el % de asistencia mostrado acá sea siempre consistente con el que
# ve el alumno en esas otras pantallas. Cubre TODAS las cursadas del alumno
# (no solo la del cuatrimestre actual), para que sirva como historial.

@st.cache_data(ttl=60)
def get_cursadas_para_asistencia(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.nombre, m.anio, c.id, c.anio_cursada, c.cuatrimestre,
                       c.dias, c.numero_comision, c.fecha_desde_comision
                FROM cursadas c
                JOIN materias m ON c.materia_id = m.id
                WHERE c.usuario_id = %s
                ORDER BY c.anio_cursada DESC, c.cuatrimestre, m.nombre;
            """, (usuario_id,))
            return cur.fetchall()

@st.cache_data(ttl=300)
def get_configs_cuatrimestre_estadisticas(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT anio, cuatrimestre, fecha_inicio, fecha_fin
                FROM configuracion_cuatrimestre
                WHERE usuario_id = %s;
            """, (usuario_id,))
            rows = cur.fetchall()
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}

@st.cache_data(ttl=60)
def get_faltas_todas_materias(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT materia_id, COUNT(*)
                FROM asistencias
                WHERE usuario_id = %s
                GROUP BY materia_id;
            """, (usuario_id,))
            return {r[0]: r[1] for r in cur.fetchall()}

# Duplicada deliberadamente de historial.py (mismo criterio que ya se usa en
# el resto del proyecto para queries chicas y de un solo uso — ver
# get_todas_materias en cursadas.py/evaluaciones.py/profesores.py, o
# get_materias_alumno en materias.py/recursos.py). Se necesita acá para poder
# armar el encabezado "Alumno/a: ..." del PDF de asistencia sin que
# cursadas.py tenga que ir a buscarla a otro módulo de página aparte.
@st.cache_data(ttl=300)
def get_nombre_usuario(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nombre FROM usuarios WHERE id = %s;", (usuario_id,))
            row = cur.fetchone()
    return row[0] if row else "Alumno"

def calcular_historial_asistencia(usuario_id):
    """
    Devuelve una lista de dicts, uno por cada cursada del alumno que tenga
    fechas de cuatrimestre configuradas y días de cursada cargados:
    {materia, anio, anio_cursada, cuatrimestre, numero_comision,
     clases_totales, faltas, porcentaje}
    Cursadas sin config de fechas o sin clases calculables se omiten
    (mismo criterio silencioso que ya usan mostrar_asistencia() en
    cursadas.py y mostrar_chip_asistencia() en home.py).
    """
    cursadas = get_cursadas_para_asistencia(usuario_id)
    if not cursadas:
        return []

    configs = get_configs_cuatrimestre_estadisticas(usuario_id)
    faltas_map = get_faltas_todas_materias(usuario_id)
    feriados_set = {f[1] for f in get_feriados(usuario_id)}

    resultado = []
    for (mid, mnombre, manio, cid, anio_cursada, cuatri, dias,
         numero_comision, fecha_desde_comision) in cursadas:

        config = configs.get((anio_cursada, cuatri))
        if not config:
            continue
        fecha_inicio, fecha_fin = config

        if cid and fecha_desde_comision:
            periodos = get_periodos_comision(cid, dias, fecha_desde_comision)
            clases_totales = contar_clases_multi_periodo(periodos, fecha_inicio, fecha_fin, feriados_set)
        else:
            clases_totales = contar_clases_en_rango(dias, fecha_inicio, fecha_fin, feriados_set)

        if clases_totales == 0:
            continue

        faltas = faltas_map.get(mid, 0)
        porcentaje = round(((clases_totales - faltas) / clases_totales) * 100, 1)

        resultado.append({
            "materia": mnombre,
            "anio": manio,
            "anio_cursada": anio_cursada,
            "cuatrimestre": cuatri,
            "numero_comision": numero_comision,
            "clases_totales": clases_totales,
            "faltas": faltas,
            "porcentaje": porcentaje,
        })

    resultado.sort(key=lambda r: (-r["anio_cursada"], ORDEN_CUATRI.get(r["cuatrimestre"], 9), r["materia"]))
    return resultado

# ─── Exportar asistencia a PDF (ítem de prioridad media-alta, 05/08/2026) ───
# Reutiliza el mismo patrón de generar_pdf() que ya está en historial.py
# (mismos estilos, misma paleta violeta #7B2FBE) y la data ya armada por
# calcular_historial_asistencia(), para no duplicar lógica de cálculo.
# Los botones de descarga viven en cursadas.py (no acá), tanto el general
# (todas las cursadas del alumno) como el individual por materia — esta
# función solo arma el documento; recibe la lista de dicts ya filtrada
# según corresponda.
#
# Si `filtro_materia` viene con un nombre, se asume que `datos` ya está
# filtrado a esa materia (una o más cursadas de la misma materia, por si
# se cursó más de una vez) y se omite la columna "Materia" de la tabla,
# ya que es redundante con el título del PDF.

def generar_pdf_asistencia(datos, nombre_alumno, filtro_materia=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle(
        "titulo",
        parent=styles["Title"],
        fontSize=18,
        textColor=colors.HexColor("#7B2FBE"),
        alignment=TA_CENTER,
        spaceAfter=4
    )
    subtitulo_style = ParagraphStyle(
        "subtitulo",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER,
        spaceAfter=2
    )
    info_style = ParagraphStyle(
        "info",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#333333"),
        spaceAfter=2
    )

    elementos = []
    elementos.append(Paragraph("PsicoNexo", titulo_style))
    subtitulo_texto = f"Asistencia — {filtro_materia}" if filtro_materia else "Historial de Asistencia"
    elementos.append(Paragraph(subtitulo_texto, subtitulo_style))
    elementos.append(Paragraph("Licenciatura en Psicologia - UdeMM", subtitulo_style))
    elementos.append(Spacer(1, 0.3*cm))
    elementos.append(Paragraph("Alumno/a: " + nombre_alumno, info_style))

    cant = len(datos)
    cursada_texto = "cursada" if cant == 1 else "cursadas"
    elementos.append(Paragraph("Total: " + str(cant) + " " + cursada_texto, info_style))
    elementos.append(Spacer(1, 0.5*cm))

    if filtro_materia:
        encabezado = ["Cuatrimestre", "Año cursada", "Comisión", "Clases", "Faltas", "Asistencia %"]
        col_widths = [4.5*cm, 3*cm, 3*cm, 2.5*cm, 2.5*cm, 2.5*cm]
    else:
        encabezado = ["Materia", "Cuatrimestre", "Año", "Comisión", "Clases", "Faltas", "Asist. %"]
        col_widths = [5*cm, 3*cm, 2*cm, 2.5*cm, 2*cm, 2*cm, 2.5*cm]

    filas = [encabezado]
    for d in datos:
        cuatri_texto = CUATRI_TEXTO.get(d["cuatrimestre"], d["cuatrimestre"])
        comision_texto = d["numero_comision"] or "-"
        if filtro_materia:
            filas.append([
                cuatri_texto,
                str(d["anio_cursada"]),
                comision_texto,
                str(d["clases_totales"]),
                str(d["faltas"]),
                f"{d['porcentaje']}%",
            ])
        else:
            filas.append([
                d["materia"],
                cuatri_texto,
                str(d["anio_cursada"]),
                comision_texto,
                str(d["clases_totales"]),
                str(d["faltas"]),
                f"{d['porcentaje']}%",
            ])

    tabla = Table(filas, colWidths=col_widths)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7B2FBE")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F0FF")]),
    ]))

    elementos.append(tabla)

    if not datos:
        elementos.append(Spacer(1, 0.5*cm))
        elementos.append(Paragraph("No hay datos de asistencia disponibles todavia.", info_style))

    doc.build(elementos)
    buffer.seek(0)
    return buffer

def mostrar_historial_asistencia(usuario_id):
    st.markdown("### 📅 Historial de asistencia")

    datos = calcular_historial_asistencia(usuario_id)

    if not datos:
        st.info(
            "Todavía no hay datos suficientes para calcular el historial de asistencia. "
            "Necesitás tener días de cursada cargados y las fechas del cuatrimestre configuradas en Inicio."
        )
        return

    df = pd.DataFrame(datos)
    df["cuatri_texto"] = df["cuatrimestre"].map(lambda c: CUATRI_TEXTO.get(c, c))
    df["etiqueta"] = df.apply(
        lambda r: f"{r['materia']} — {r['cuatri_texto']} {r['anio_cursada']}"
        + (f" ({r['numero_comision']})" if r["numero_comision"] else ""),
        axis=1
    )
    df["color"] = df["porcentaje"].apply(
        lambda p: clasificar_asistencia(p)[0]
    )

    altura = max(200, 36 * len(df))

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("porcentaje:Q", title="Asistencia (%)", scale=alt.Scale(domain=[0, 100])),
        y=alt.Y("etiqueta:N", sort="-x", title=None),
        color=alt.Color("color:N", scale=None, legend=None),
        tooltip=[
            alt.Tooltip("materia:N", title="Materia"),
            alt.Tooltip("cuatri_texto:N", title="Cuatrimestre"),
            alt.Tooltip("anio_cursada:N", title="Año cursada"),
            alt.Tooltip("porcentaje:Q", title="Asistencia %"),
            alt.Tooltip("faltas:Q", title="Faltas"),
            alt.Tooltip("clases_totales:Q", title="Clases totales"),
        ]
    ).properties(height=altura)

    linea_75 = alt.Chart(pd.DataFrame({"x": [75]})).mark_rule(
        color="#e74c3c", strokeDash=[4, 4]
    ).encode(x="x:Q")

    st.altair_chart(chart + linea_75, use_container_width=True)
    st.caption("La línea punteada roja marca el 75% mínimo de asistencia.")

    with st.expander("📋 Ver detalle completo"):
        df_detalle = df[["materia", "anio", "cuatri_texto", "anio_cursada", "numero_comision",
                          "clases_totales", "faltas", "porcentaje"]].copy()
        df_detalle["anio"] = df_detalle["anio"].map(lambda a: NOMBRES_ANIO.get(a, a))
        df_detalle = df_detalle.rename(columns={
            "materia": "Materia",
            "anio": "Año carrera",
            "cuatri_texto": "Cuatrimestre",
            "anio_cursada": "Año cursada",
            "numero_comision": "Comisión",
            "clases_totales": "Clases totales",
            "faltas": "Faltas",
            "porcentaje": "Asistencia %",
        })
        st.dataframe(df_detalle, use_container_width=True, hide_index=True)


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
        filas_ordenadas = sorted(evol_rows, key=lambda r: (r[0], ORDEN_CUATRI.get(r[1], 9)))

        etiquetas, valores = [], []
        for anio_c, cuatri, promedio in filas_ordenadas:
            etiquetas.append(f"{CUATRI_TEXTO.get(cuatri, cuatri)} {anio_c}")
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

    st.markdown("---")

    # ── Historial visual de asistencia ────────────────────────────────
    mostrar_historial_asistencia(usuario["id"])
