# historial.py - 04.10.2026

import streamlit as st
from db import get_conn
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from utils import NOMBRES_ANIO, CUATRI_TEXTO, COLORES

# ─── Batch único de la pantalla (ítem prioridad alta, "Seguir optimizando
# latencia", 14/08/2026) ────────────────────────────────────────────────────
# Antes: 2 conexiones fijas al pool en cada carga (get_historial y
# get_nombre_usuario). La segunda solo se necesita para armar el
# encabezado "Alumno/a: ..." del PDF, pero abría su propia conexión al
# pool cada vez que había resultados para mostrar (el caso normal). Se
# consolidan acá en una sola conexión, mismo criterio que el resto del
# proyecto (Home, Plan de Estudios, tab "Cursando actualmente",
# Estadísticas, Profesores).
#
# Reemplaza a las 2 funciones cacheadas viejas (get_historial,
# get_nombre_usuario), eliminadas porque no las usaba ningún otro módulo
# fuera de esta pantalla (estadisticas.py tiene su propia copia de
# get_nombre_usuario, deliberadamente duplicada — ver comentario ahí — así
# que no se toca).
#
# Versión 4 (04/10/2026): promedios separados. En vez de un solo promedio
# que mezclaba todas las notas, cada fila trae tres promedios
# independientes (TP, Parciales y Recuperatorios), más la nota del 1er y
# 2do parcial. Finales y Reincorporatorios no entran en ningún promedio.
# Todo sale de la misma consulta: no hay conexiones ni columnas nuevas.

@st.cache_data(ttl=60)
def get_historial_data_completo(usuario_id, carrera_id):
    """
    Devuelve, en una sola conexión, todo lo que necesita pages/historial.py:
    (historial, nombre_alumno)
    Cada fila de historial:
    (nombre, anio, cuatrimestre, estado, anio_cursada, cuatri_cursada,
     profesor1, prom_tp, prom_parciales, prom_recuperatorios,
     parcial1, parcial2)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.nombre, m.anio, m.cuatrimestre, am.estado,
                       c.anio_cursada, c.cuatrimestre as cuatri_cursada, c.profesor1,
                       AVG(e.nota) FILTER (WHERE e.tipo = 'Trabajo Práctico') as prom_tp,
                       AVG(e.nota) FILTER (WHERE e.tipo = 'Parcial')          as prom_parciales,
                       AVG(e.nota) FILTER (WHERE e.tipo = 'Recuperatorio')    as prom_recuperatorios,
                       MAX(e.nota) FILTER (WHERE e.tipo = 'Parcial' AND e.numero = 1) as parcial1,
                       MAX(e.nota) FILTER (WHERE e.tipo = 'Parcial' AND e.numero = 2) as parcial2
                FROM materias m
                LEFT JOIN alumno_materias am ON m.id = am.materia_id AND am.usuario_id = %s
                LEFT JOIN cursadas c ON m.id = c.materia_id AND c.usuario_id = %s
                LEFT JOIN evaluaciones e ON m.id = e.materia_id AND e.usuario_id = %s
                WHERE m.carrera_id = %s
                AND am.estado IS NOT NULL
                AND am.estado != 'pendiente'
                GROUP BY m.nombre, m.anio, m.cuatrimestre, am.estado,
                         c.anio_cursada, c.cuatrimestre, c.profesor1
                ORDER BY m.anio, m.cuatrimestre, m.nombre;
            """, (usuario_id, usuario_id, usuario_id, carrera_id))
            historial = cur.fetchall()

            cur.execute("SELECT nombre FROM usuarios WHERE id = %s;", (usuario_id,))
            row_nombre = cur.fetchone()
            nombre_alumno = row_nombre[0] if row_nombre else "Alumno"

    return historial, nombre_alumno

def _texto_prom(valor):
    return "{:.2f}".format(float(valor)) if valor is not None else "-"

def _texto_promedios_html(prom_tp, prom_parc, prom_rec):
    """
    "TP 7.50 · Parciales 8.00 · Recuperatorios —". Verde si el valor es 6 o
    más, rojo si es menor, gris con "—" si el grupo no tiene notas (mismos
    criterios que en Inicio, Notas y Materias aprobadas).
    """
    partes = []
    for etiqueta, valor in (("TP", prom_tp), ("Parciales", prom_parc), ("Recuperatorios", prom_rec)):
        if valor is None:
            texto, color = "—", "#888888"
        else:
            texto = "{:.2f}".format(float(valor))
            color = "#2ecc71" if float(valor) >= 6 else "#e74c3c"
        partes.append(etiqueta + " <span style='color:" + color + "; font-weight:bold;'>" + texto + "</span>")
    return " · ".join(partes)

def _texto_parciales_html(parcial1, parcial2):
    """
    "1er Parcial 8.00 · 2do Parcial Sin nota cargada aún". Devuelve None si
    no hay ninguna de las dos notas.
    """
    if parcial1 is None and parcial2 is None:
        return None
    partes = []
    for etiqueta, valor in (("1er Parcial", parcial1), ("2do Parcial", parcial2)):
        if valor is None:
            texto, color = "Sin nota cargada aún", "#888888"
        else:
            texto = "{:.2f}".format(float(valor))
            color = "#2ecc71" if float(valor) >= 6 else "#e74c3c"
        partes.append(etiqueta + " <span style='color:" + color + ";'>" + texto + "</span>")
    return " · ".join(partes)

def generar_pdf(historial, nombre_alumno, filtros):
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
    # Estilo para el nombre de la materia: con la tabla más angosta por las
    # tres columnas de promedio, los nombres largos tienen que poder
    # partirse en varias líneas.
    celda_materia_style = ParagraphStyle(
        "celda_materia",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
        textColor=colors.black
    )

    elementos = []
    elementos.append(Paragraph("PsicoNexo", titulo_style))
    elementos.append(Paragraph("Historial Academico", subtitulo_style))
    elementos.append(Paragraph("Licenciatura en Psicologia - UdeMM", subtitulo_style))
    elementos.append(Spacer(1, 0.3*cm))
    elementos.append(Paragraph("Alumno/a: " + nombre_alumno, info_style))

    filtros_texto = []
    if filtros.get("estado") != "Todos":
        filtros_texto.append("Estado: " + filtros["estado"])
    if filtros.get("anio") != "Todos":
        filtros_texto.append("Anio: " + filtros["anio"])
    if filtros.get("cuatri") != "Todos":
        filtros_texto.append("Cuatrimestre: " + filtros["cuatri"])
    if filtros_texto:
        elementos.append(Paragraph("Filtros: " + " - ".join(filtros_texto), info_style))

    elementos.append(Paragraph("Total: " + str(len(historial)) + " materias", info_style))
    elementos.append(Spacer(1, 0.5*cm))

    encabezado = ["Materia", "Año", "Estado", "Cursada", "TP", "Parc.", "Recup."]
    datos = [encabezado]

    for h in historial:
        (mnombre, manio, mcuatri, estado, anio_cursada, cuatri_cursada, profesor1,
         prom_tp, prom_parc, prom_rec, parcial1, parcial2) = h
        anio_texto = NOMBRES_ANIO.get(manio, "Año " + str(manio))
        if anio_cursada and cuatri_cursada:
            cuatri_corto = CUATRI_TEXTO.get(cuatri_cursada, cuatri_cursada)
            cursada_texto = str(anio_cursada) + " - " + cuatri_corto
        elif anio_cursada:
            cursada_texto = str(anio_cursada)
        else:
            cursada_texto = "-"
        datos.append([
            Paragraph(escape(mnombre), celda_materia_style),
            anio_texto,
            estado.capitalize(),
            cursada_texto,
            _texto_prom(prom_tp),
            _texto_prom(prom_parc),
            _texto_prom(prom_rec),
        ])

    # Ancho total: 17 cm (A4 menos los márgenes de 2 cm de cada lado).
    tabla = Table(datos, colWidths=[5*cm, 2*cm, 2.6*cm, 3*cm, 1.4*cm, 1.4*cm, 1.6*cm])
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
        ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F0FF")]),
    ]))

    elementos.append(tabla)
    doc.build(elementos)
    buffer.seek(0)
    return buffer

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("📜 Historial Académico")
    st.caption("Licenciatura en Psicología — UdeMM")

    # ── Batch único de la pantalla (ítem prioridad alta, latencia de carga,
    # 14/08/2026): antes eran 2 conexiones fijas al pool (get_historial +
    # get_nombre_usuario). Ahora es 1 sola — ver get_historial_data_completo
    # más arriba.
    historial, nombre_alumno = get_historial_data_completo(usuario["id"], usuario["carrera_id"])

    if not historial:
        st.info("Todavía no tenés materias con estado registrado.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        estados_disponibles = sorted(set(h[3] for h in historial if h[3]))
        filtro_estado = st.selectbox("Filtrar por estado", ["Todos"] + estados_disponibles)
    with col2:
        anios_disponibles = sorted(set(h[1] for h in historial))
        anios_opciones = ["Todos"] + [NOMBRES_ANIO.get(a, str(a)) for a in anios_disponibles]
        filtro_anio = st.selectbox("Filtrar por año de la carrera", anios_opciones)
    with col3:
        cuatris_disponibles = sorted(set(h[2] for h in historial if h[2]))
        filtro_cuatri = st.selectbox("Filtrar por cuatrimestre", ["Todos"] + cuatris_disponibles)

    resultado = historial
    if filtro_estado != "Todos":
        resultado = [h for h in resultado if h[3] == filtro_estado]
    if filtro_anio != "Todos":
        anio_num = [k for k, v in NOMBRES_ANIO.items() if v == filtro_anio]
        if anio_num:
            resultado = [h for h in resultado if h[1] == anio_num[0]]
    if filtro_cuatri != "Todos":
        resultado = [h for h in resultado if h[2] == filtro_cuatri]

    if not resultado:
        st.info("No hay materias que coincidan con los filtros seleccionados.")
        return

    st.markdown("---")

    col_count, col_pdf = st.columns([3, 1])
    with col_count:
        cant = len(resultado)
        st.markdown("**" + str(cant) + " materia" + ("s" if cant > 1 else "") + " encontrada" + ("s" if cant > 1 else "") + "**")
    with col_pdf:
        filtros = {"estado": filtro_estado, "anio": filtro_anio, "cuatri": filtro_cuatri}
        pdf_buffer = generar_pdf(resultado, nombre_alumno, filtros)
        st.download_button(
            label="⬇️ Descargar PDF",
            data=pdf_buffer,
            file_name="historial_academico.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    for h in resultado:
        (mnombre, manio, mcuatri, estado, anio_cursada, cuatri_cursada, profesor1,
         prom_tp, prom_parc, prom_rec, parcial1, parcial2) = h
        icono = COLORES.get(estado, "⬜")
        anio_texto = NOMBRES_ANIO.get(manio, "Año " + str(manio))
        cuatri_texto = CUATRI_TEXTO.get(mcuatri, mcuatri)

        col1, col2, col3, col4 = st.columns([3, 1, 1, 3])
        with col1:
            st.markdown(icono + " **" + mnombre + "**")
            st.caption(anio_texto + " · " + cuatri_texto)
        with col2:
            st.markdown("**Estado**")
            st.markdown(estado.capitalize())
        with col3:
            st.markdown("**Cursada**")
            if anio_cursada and cuatri_cursada:
                cuatri_corto = CUATRI_TEXTO.get(cuatri_cursada, cuatri_cursada)
                st.markdown(str(anio_cursada) + " · " + cuatri_corto)
            elif anio_cursada:
                st.markdown(str(anio_cursada))
            else:
                st.markdown("—")
        with col4:
            st.markdown("**Promedios**")
            if prom_tp is None and prom_parc is None and prom_rec is None:
                st.markdown("—")
            else:
                st.markdown(
                    _texto_promedios_html(prom_tp, prom_parc, prom_rec),
                    unsafe_allow_html=True
                )
            parciales_html = _texto_parciales_html(parcial1, parcial2)
            if parciales_html:
                st.markdown(
                    "<div style='font-size:13px;'>📝 " + parciales_html + "</div>",
                    unsafe_allow_html=True
                )

        st.markdown("---")
