# correlatividades.py - 20/09/2026

import html
import shutil
import subprocess
import textwrap
import streamlit as st
from db import get_materias_data_completo
from utils import NOMBRES_ANIO

# ─── Sección Correlatividades (20/09/2026) ─────────────────────────────────
# Muestra un mapa con flechas de las correlatividades del plan de estudios,
# limitado a un rango de años que elige el alumno (los dos selectores
# arrancan vacíos, no hay rango por defecto). Cada flecha sale de la materia
# que hay que aprobar y llega a la materia que habilita.
#
# Se ve online (st.graphviz_chart) y se puede descargar como PDF.
#
# Latencia: no abre ninguna consulta nueva a la base. Reutiliza
# get_materias_data_completo() (db.py), que ya está cacheada y es la misma
# que usa Plan de Estudios.
#
# PDF: se genera con el programa "dot" de Graphviz, a partir del mismo
# texto DOT que se dibuja en pantalla (así lo que se descarga es idéntico
# a lo que se ve). Para que "dot" exista en Streamlit Community Cloud hace
# falta un archivo packages.txt en la raíz del repo (ver instrucciones).
# No se agrega ninguna librería de Python nueva. El resultado se cachea:
# si el alumno no cambia el rango ni sus estados, no se vuelve a generar.

ESTADOS_APROBADOS = ("aprobada", "promocionada")

# Colores de relleno según el estado de la materia para este alumno.
# Son tonos claros con texto oscuro, para que se lean igual en modo claro
# y en modo oscuro (y al imprimir).
COLOR_ESTADO = {
    "pendiente": "#E5E7EB",
    "cursando": "#FDE68A",
    "regular": "#FDBA74",
    "aprobada": "#86EFAC",
    "promocionada": "#86EFAC",
    "desaprobada": "#FCA5A5",
}

LEYENDA_COLORES = [
    ("Pendiente", COLOR_ESTADO["pendiente"]),
    ("Cursando", COLOR_ESTADO["cursando"]),
    ("Regular", COLOR_ESTADO["regular"]),
    ("Aprobada / Promocionada", COLOR_ESTADO["aprobada"]),
    ("Desaprobada", COLOR_ESTADO["desaprobada"]),
]

LEYENDA = (
    "⬜ Pendiente · 🟡 Cursando · 🟠 Regular · "
    "🟢 Aprobada / Promocionada · 🔴 Desaprobada"
)


def _nombre_anio(anio):
    return NOMBRES_ANIO.get(anio, f"Año {anio}")


def _etiqueta_nodo(nombre, anio):
    """Nombre de la materia partido en líneas cortas + el año abajo."""
    lineas = textwrap.wrap(nombre, width=24) or [nombre]
    lineas.append(f"[{anio}° año]")
    return "\\n".join(l.replace('"', '\\"') for l in lineas)


def _encabezado_pdf(nombre_alumno, anio_desde, anio_hasta):
    """
    Título + alumno + leyenda de colores, como etiqueta HTML de Graphviz,
    para que el PDF descargado los lleve arriba del mapa.
    """
    titulo = html.escape(
        f"PsicoNexo · Correlatividades: {_nombre_anio(anio_desde)} a {_nombre_anio(anio_hasta)}"
    )
    alumno = html.escape(f"Alumno/a: {nombre_alumno}")
    celdas = "".join(
        f'<TD BGCOLOR="{color}">{html.escape(texto)}</TD>' for texto, color in LEYENDA_COLORES
    )
    return (
        '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="4">'
        f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="22"><B>{titulo}</B></FONT></TD></TR>'
        f'<TR><TD ALIGN="LEFT">{alumno}</TD></TR>'
        '<TR><TD ALIGN="LEFT"><TABLE BORDER="0" CELLBORDER="1" CELLSPACING="4" CELLPADDING="4">'
        f"<TR>{celdas}</TR></TABLE></TD></TR>"
        "</TABLE>>"
    )


def armar_dot(materias, estados_map, correlativas_map, anio_desde, anio_hasta, encabezado=None):
    """
    Arma el grafo en formato DOT para las materias entre anio_desde y
    anio_hasta (ambos incluidos). Solo se dibujan las flechas cuyo origen y
    destino están dentro del rango; las correlativas que quedan fuera del
    rango se listan aparte, en el detalle de texto.

    `encabezado`, si se pasa, es una etiqueta HTML de Graphviz que se pone
    arriba del grafo (se usa solo para el PDF).

    Devuelve (dot, cantidad_de_materias, cantidad_de_flechas).
    """
    en_rango = {m[0]: m for m in materias if anio_desde <= m[2] <= anio_hasta}

    lineas = [
        "digraph correlatividades {",
        "  rankdir=LR;",
        "  nodesep=0.25;",
        "  ranksep=0.9;",
    ]
    if encabezado:
        lineas.append('  bgcolor="white";')
        lineas.append('  fontname="Helvetica";')
        lineas.append("  pad=0.4;")
        lineas.append("  labelloc=t;")
        lineas.append("  labeljust=l;")
        lineas.append(f"  label={encabezado};")
    else:
        lineas.append('  bgcolor="transparent";')
    lineas.append(
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", '
        'fontsize=11, fontcolor="#1F2937", color="#6B7280", margin="0.15,0.08"];'
    )
    lineas.append('  edge [color="#8B8BA7", arrowsize=0.7];')

    for mid, m in en_rango.items():
        _, nombre, anio, _cuatri, _final, _electiva = m
        estado = estados_map.get(mid, "pendiente")
        color = COLOR_ESTADO.get(estado, COLOR_ESTADO["pendiente"])
        lineas.append(
            f'  m{mid} [label="{_etiqueta_nodo(nombre, anio)}", fillcolor="{color}"];'
        )

    flechas = 0
    for mid in en_rango:
        for req_id, _req_nombre in correlativas_map.get(mid, []):
            if req_id in en_rango:
                lineas.append(f"  m{req_id} -> m{mid};")
                flechas += 1

    lineas.append("}")
    return "\n".join(lineas), len(en_rango), flechas


@st.cache_data(ttl=300)
def generar_pdf_correlatividades(dot):
    """
    Convierte el texto DOT a PDF con el programa "dot" de Graphviz.
    Devuelve los bytes del PDF, o None si no se pudo generar. Se cachea por
    el texto DOT: mientras el rango y los estados no cambien, no se vuelve
    a ejecutar.
    """
    try:
        resultado = subprocess.run(
            ["dot", "-Tpdf"], input=dot.encode("utf-8"),
            capture_output=True, timeout=30
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if resultado.returncode != 0 or not resultado.stdout.startswith(b"%PDF"):
        return None
    return resultado.stdout


def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("🔗 Correlatividades")
    st.caption(
        "Elegí el rango de años que querés ver. Cada flecha sale de la materia que tenés "
        "que aprobar y llega a la materia que habilita."
    )

    materias, estados_map, correlativas_map = get_materias_data_completo(
        usuario["id"], usuario["carrera_id"]
    )

    if not materias:
        st.warning("No hay materias cargadas para tu carrera todavía.")
        return

    anios = sorted({m[2] for m in materias})

    # index=None: los dos selectores arrancan vacíos, con la leyenda adentro.
    # El alumno tiene que elegir el rango; no hay ninguno por defecto.
    col1, col2 = st.columns(2)
    with col1:
        anio_desde = st.selectbox(
            "Desde", anios, index=None, placeholder="Elegí desde qué año",
            format_func=_nombre_anio, key="corr_anio_desde"
        )
    with col2:
        anio_hasta = st.selectbox(
            "Hasta", anios, index=None, placeholder="Elegí hasta qué año",
            format_func=_nombre_anio, key="corr_anio_hasta"
        )

    if anio_desde is None and anio_hasta is None:
        st.info("Elegí desde qué año y hasta qué año para ver el mapa de correlatividades.")
        return
    if anio_desde is None:
        st.info("Falta elegir desde qué año.")
        return
    if anio_hasta is None:
        st.info("Falta elegir hasta qué año.")
        return
    if anio_desde > anio_hasta:
        st.error("El año de inicio no puede ser posterior al año tope.")
        return

    dot, cant_materias, cant_flechas = armar_dot(
        materias, estados_map, correlativas_map, anio_desde, anio_hasta
    )

    col_a, col_b = st.columns(2)
    with col_a:
        st.metric("Materias en el rango", cant_materias)
    with col_b:
        st.metric("Correlatividades dentro del rango", cant_flechas)

    # ── Descarga en PDF ────────────────────────────────────────────────────
    if shutil.which("dot"):
        dot_pdf, _, _ = armar_dot(
            materias, estados_map, correlativas_map, anio_desde, anio_hasta,
            encabezado=_encabezado_pdf(usuario["nombre"], anio_desde, anio_hasta)
        )
        pdf_bytes = generar_pdf_correlatividades(dot_pdf)
        if pdf_bytes:
            st.download_button(
                label="⬇️ Descargar mapa en PDF",
                data=pdf_bytes,
                file_name=f"correlatividades_{anio_desde}_a_{anio_hasta}.pdf",
                mime="application/pdf",
                key="dl_correlatividades_pdf",
                use_container_width=True,
            )
        else:
            st.warning("No se pudo generar el PDF en este momento. Probá de nuevo.")
    else:
        st.warning(
            "Para descargar el PDF falta instalar Graphviz en el servidor: agregá un "
            "archivo packages.txt en la raíz del repo de GitHub con la palabra graphviz."
        )

    st.caption(LEYENDA)

    if cant_flechas == 0:
        st.info(
            "En este rango ninguna materia depende de otra del mismo rango. "
            "Probá ampliando el año tope, o mirá el detalle de abajo."
        )
    st.graphviz_chart(dot, use_container_width=True)

    # ── Detalle en texto ───────────────────────────────────────────────────
    # Incluye también las correlativas que están FUERA del rango elegido
    # (por ejemplo, una materia de 2° que pide una de 1° cuando el rango
    # arranca en 2°), que en el gráfico no se dibujan.
    info = {m[0]: (m[1], m[2]) for m in materias}

    with st.expander("📋 Detalle: qué pide cada materia"):
        for m in materias:
            mid, nombre, anio = m[0], m[1], m[2]
            if not (anio_desde <= anio <= anio_hasta):
                continue

            st.markdown(f"**{nombre}** · {_nombre_anio(anio)}")
            requisitos = correlativas_map.get(mid, [])
            if not requisitos:
                st.caption("Sin correlativas previas.")
                continue

            for req_id, req_nombre in requisitos:
                estado_req = estados_map.get(req_id, "pendiente")
                icono = "✅" if estado_req in ESTADOS_APROBADOS else "❌"
                req_anio = info.get(req_id, (req_nombre, None))[1]
                anio_txt = f" · {_nombre_anio(req_anio)}" if req_anio else ""
                fuera = " _(fuera del rango)_" if req_anio and req_anio < anio_desde else ""
                st.caption(f"{icono} {req_nombre}{anio_txt}{fuera}")
