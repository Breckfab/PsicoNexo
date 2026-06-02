import streamlit as st
from db import get_conn
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

@st.cache_data(ttl=60)
def get_historial(usuario_id, carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.nombre, m.anio, m.cuatrimestre, am.estado,
                       c.anio_cursada, c.cuatrimestre as cuatri_cursada, c.profesor1,
                       AVG(e.nota) as promedio
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
            return cur.fetchall()

@st.cache_data(ttl=300)
def get_nombre_usuario(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nombre FROM usuarios WHERE id = %s;", (usuario_id,))
            row = cur.fetchone()
    return row[0] if row else "Alumno"

CUATRI_TEXTO = {
    "1": "1° Cuat.",
    "2": "2° Cuat.",
    "anual": "Anual",
    "1° Cuatrimestre": "1° Cuat.",
    "2° Cuatrimestre": "2° Cuat.",
    "Anual": "Anual",
}

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

    nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}

    elementos = []
    elementos.append(Paragraph("🧠 PsicoNexo", titulo_style))
    elementos.append(Paragraph("Historial Académico", subtitulo_style))
    elementos.append(Paragraph("Licenciatura en Psicología — UdeMM", subtitulo_style))
    elementos.append(Spacer(1, 0.3*cm))
    elementos.append(Paragraph(f"Alumno/a: {nombre_alumno}", info_style))

    filtros_texto = []
    if filtros.get("estado") != "Todos":
        filtros_texto.append(f"Estado: {filtros['estado']}")
    if filtros.get("anio") != "Todos":
        filtros_texto.append(f"Año: {filtros['anio']}")
    if filtros.get("cuatri") != "Todos":
        filtros_texto.append(f"Cuatrimestre: {filtros['cuatri']}")
    if filtros_texto:
        elementos.append(Paragraph(f"Filtros aplicados: {' · '.join(filtros_texto)}", info_style))

    elementos.append(Paragraph(f"Total de materias: {len(historial)}", info_style))
    elementos.append(Spacer(1, 0.5*cm))

    encabezado = ["Materia", "Año", "Estado", "Cursada", "Promedio"]
    datos = [encabezado]

    for h in historial:
        mnombre, manio, mcuatri, estado, anio_cursada, cuatri_cursada, profesor1, promedio = h
        anio_texto = nombres_anio.get(manio, f"Año {manio}")
        if anio_cursada and cuatri_cursada:
            cuatri_corto = CUATRI_TEXTO.get(cuatri_cursada, cuatri_cursada)
            cursada_texto = f"{anio_cursada} · {cuatri_corto}"
        elif anio_cursada:
            cursada_texto = str(anio_cursada)
        else:
            cursada_texto = "—"
        promedio_texto = f"{float(promedio):.2f}" if promedio is not None else "—"
        datos.append([mnombre, anio_texto, estado.capitalize(), cursada_texto, promedio_texto])

    tabla = Table(datos, colWidths=[6.5*cm, 2.5*cm, 3*cm, 3.5*cm, 2*cm])
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
    doc.build(elementos)
    buffer.seek(0)
    return buffer

def mostrar(usuario):
    st.title("📜 Historial Académico")
    st.caption("Licenciatura en Psicología — UdeMM")

    historial = get_historial(usuario["id"], usuario["carrera_id"])

    if not historial:
        st.info("Todavía no tenés materias con estado registrado.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        estados_disponibles = sorted(set(h[3] for h in historial if h[3]))
        filtro_estado = st.selectbox("Filtrar por estado", ["Todos"] + estados_disponibles)
    with col2:
        anios_disponibles = sorted(set(h[1] for h in historial))
        nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}
        anios_opciones = ["Todos"] + [nombres_anio.get(a, str(a)) for a in anios_disponibles]
        filtro_anio = st.selectbox("Filtrar por año de la carrera", anios_opciones)
    with col3:
        cuatris_disponibles = sorted(set(h[2] for h in historial if h[2]))
        filtro_cuatri = st.selectbox("Filtrar por cuatrimestre", ["Todos"] + cuatris_disponibles)

    resultado = historial
    if filtro_estado != "Todos":
        resultado = [h for h in resultado if h[3] == filtro_estado]
    if filtro_anio != "Todos":
        anio_num = [k for k, v in nombres_anio.items() if v == filtro_anio]
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
        st.markdown(f"**{len(resultado)} materia{'s' if len(resultado) > 1 else ''} encontrada{'s' if len(resultado) > 1 else ''}**")
    with col_pdf:
        nombre_alumno = get_nombre_usuario(usuario["id"])
        filtros = {"estado": filtro_estado, "anio": filtro_anio, "cuatri": filtro_cuatri}
        pdf_buffer = generar_pdf(resultado, nombre_alumno, filtros)
        st.download_button(
            label="⬇️ Descargar PDF",
            data=pdf_buffer,
            file_name="historial_academico.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    COLORES = {
        "cursando": "🟡",
        "regular": "🟠",
        "promocionada": "🟢",
        "aprobada": "🟢",
        "desaprobada": "🔴",
    }

    for h in resultado:
        mnombre, manio, mcuatri, estado, anio_cursada, cuatri_cursada, profesor1, promedio = h
        icono = COLORES.get(estado, "⬜")
        anio_texto = nombres_anio.get(manio, f"Año {manio}")
        cuatri_texto = CUATRI_TEXTO.get(mcuatri, mcuatri)

        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
        with col1:
            st.markdown(f"{icono} **{mnombre}**")
            st.caption(f"{anio_texto} · {cuatri_texto}")
        with col2:
            st.markdown(f"**Estado**")
            st.markdown(f"{estado.capitalize()}")
        with col3:
            st.markdown(f"**Cursada**")
            if anio_cursada and cuatri_cursada:
                cuatri_corto = CUATRI_TEXTO.get(cuatri_cursada, cuatri_cursada)
                st.markdown(f"{anio_cursada} · {cuatri_corto}")
            elif anio_cursada:
                st.markdown(str(anio_cursada))
            else:
                st.markdown("—")
        with col4:
            st.markdown(f"**Promedio**")
            if promedio is not None:
                color = "#2ecc71" if promedio >= 6 else "#e74c3c"
                st.markdown(f"<span style='color:{color}; font-weight:bold;'>{float(promedio):.2f}</span>", unsafe_allow_html=True)
            else:
                st.markdown("—")

        st.markdown("---")
