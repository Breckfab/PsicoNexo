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

@st.cache_data(ttl=600)
def get_correlatividades_completas(carrera_id, usuario_id):
    """Trae todos los arcos del grafo: (materia_id, requiere_materia_id)"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.materia_id, c.requiere_materia_id
                FROM correlatividades c
                JOIN materias m ON c.materia_id = m.id
                WHERE m.carrera_id = %s;
            """, (carrera_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_todos_programas(usuario_id):
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

def render_mapa_correlativas(materias, arcos):
    """Genera el HTML del grafo interactivo con vis-network."""

    COLORES_NODO = {
        "pendiente":    {"bg": "#2a2a3e", "border": "#555577", "font": "#aaaacc"},
        "cursando":     {"bg": "#7c6800", "border": "#f0c000", "font": "#ffe066"},
        "regular":      {"bg": "#7c3d00", "border": "#f07800", "font": "#ffb066"},
        "promocionada": {"bg": "#1a5c2a", "border": "#2ecc71", "font": "#80ffaa"},
        "aprobada":     {"bg": "#1a5c2a", "border": "#2ecc71", "font": "#80ffaa"},
        "desaprobada":  {"bg": "#5c1a1a", "border": "#e74c3c", "font": "#ff8080"},
    }

    # Agrupar por año para el layout jerárquico
    anio_orden = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

    nodes_js = []
    for m in materias:
        mid, codigo, nombre, anio, cuatri, final_oblig, es_electiva, estado = m
        c = COLORES_NODO.get(estado, COLORES_NODO["pendiente"])
        nivel = anio_orden.get(anio, anio - 1)
        # Etiqueta corta para el nodo
        label = nombre if len(nombre) <= 28 else nombre[:26] + "…"
        nodes_js.append(
            f'{{id:{mid}, label:{repr(label)}, title:{repr(f"{nombre}\\n{estado.capitalize()}")}, '
            f'level:{nivel}, '
            f'color:{{background:{repr(c["bg"])}, border:{repr(c["border"])}, '
            f'highlight:{{background:{repr(c["bg"])}, border:"#ffffff"}}}}, '
            f'font:{{color:{repr(c["font"])}, size:12}}, '
            f'shape:"box", margin:6, widthConstraint:{{minimum:120, maximum:180}}}}'
        )

    edges_js = []
    for from_id, to_id in arcos:
        # Arco: to_id es requisito de from_id → flecha de requisito hacia materia
        edges_js.append(
            f'{{from:{to_id}, to:{from_id}, '
            f'arrows:"to", color:{{color:"#444466", highlight:"#9b8bf4"}}, smooth:{{type:"cubicBezier"}}}}'
        )

    nodes_str = "[" + ",\n".join(nodes_js) + "]"
    edges_str = "[" + ",\n".join(edges_js) + "]"

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body {{ margin:0; padding:0; background:#0e0e1a; font-family: sans-serif; }}
  #legend {{
    display:flex; flex-wrap:wrap; gap:10px;
    padding:10px 14px; background:#1a1a2e; border-bottom:1px solid #2a2a4a;
  }}
  .leg {{ display:flex; align-items:center; gap:6px; font-size:12px; }}
  .leg-dot {{ width:12px; height:12px; border-radius:3px; border:2px solid; flex-shrink:0; }}
  #network {{
    width:100%; height:640px; background:#0e0e1a;
    border:1px solid #2a2a4a;
  }}
  #tooltip {{
    position:absolute; background:#1e1e3a; color:#ddd;
    border:1px solid #7B2FBE; border-radius:8px;
    padding:8px 12px; font-size:13px; pointer-events:none;
    display:none; max-width:220px; z-index:999;
  }}
</style>
</head>
<body>
<div id="legend">
  <div class="leg"><div class="leg-dot" style="background:#2a2a3e;border-color:#555577"></div><span style="color:#aaa">Pendiente</span></div>
  <div class="leg"><div class="leg-dot" style="background:#7c6800;border-color:#f0c000"></div><span style="color:#ffe066">Cursando</span></div>
  <div class="leg"><div class="leg-dot" style="background:#7c3d00;border-color:#f07800"></div><span style="color:#ffb066">Regular</span></div>
  <div class="leg"><div class="leg-dot" style="background:#1a5c2a;border-color:#2ecc71"></div><span style="color:#80ffaa">Aprobada / Promocionada</span></div>
  <div class="leg"><div class="leg-dot" style="background:#5c1a1a;border-color:#e74c3c"></div><span style="color:#ff8080">Desaprobada</span></div>
  <div style="margin-left:auto;color:#666;font-size:11px;align-self:center;">Scrollá · arrastá · pinchá para hacer zoom</div>
</div>
<div id="network"></div>
<div id="tooltip"></div>

<script>
const nodes = new vis.DataSet({nodes_str});
const edges = new vis.DataSet({edges_str});

const container = document.getElementById("network");
const options = {{
  layout: {{
    hierarchical: {{
      enabled: true,
      direction: "LR",
      sortMethod: "directed",
      levelSeparation: 220,
      nodeSpacing: 90,
      treeSpacing: 150,
      blockShifting: true,
      edgeMinimization: true,
      parentCentralization: true,
    }}
  }},
  physics: {{ enabled: false }},
  interaction: {{
    hover: true,
    tooltipDelay: 100,
    navigationButtons: false,
    keyboard: true,
    zoomView: true,
    dragView: true,
  }},
  edges: {{
    width: 1.5,
    selectionWidth: 3,
  }},
  nodes: {{
    borderWidth: 2,
    borderWidthSelected: 3,
    shadow: {{ enabled: true, color: "rgba(0,0,0,0.4)", size:6, x:2, y:2 }},
  }},
}};

const network = new vis.Network(container, {{ nodes, edges }}, options);

// Resaltar camino al hacer click
network.on("click", function(params) {{
  if (params.nodes.length === 0) {{
    nodes.forEach(n => nodes.update({{id: n.id, opacity: 1}}));
    return;
  }}
  const selected = params.nodes[0];
  // Obtener todos los nodos conectados (upstream y downstream)
  const connected = new Set([selected]);
  edges.forEach(e => {{
    if (e.from === selected || e.to === selected) {{
      connected.add(e.from);
      connected.add(e.to);
    }}
  }});
  nodes.forEach(n => {{
    nodes.update({{id: n.id, opacity: connected.has(n.id) ? 1 : 0.2}});
  }});
}});
</script>
</body>
</html>
"""
    return html


def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("📋 Plan de Estudios")
    st.caption("Licenciatura en Psicología — UdeMM")

    materias = get_materias_con_estado(usuario["id"], usuario["carrera_id"])
    correlatividades_map = get_todas_correlatividades(usuario["carrera_id"], usuario["id"])
    programas_map = get_todos_programas(usuario["id"])

    if not materias:
        st.warning("No se encontraron materias para tu carrera.")
        return

    tab1, tab2 = st.tabs(["📋 Plan de Estudios", "🗺️ Mapa de Correlativas"])

    # ── TAB 1: Plan de estudios (código original) ──────────────────────────────
    with tab1:
        busqueda = st.text_input("🔍 Buscar materia", placeholder="Escribí el nombre de la materia...")

        materias_filtradas = materias
        if busqueda.strip():
            materias_filtradas = [m for m in materias if busqueda.strip().lower() in m[2].lower()]
            if not materias_filtradas:
                st.info("No se encontraron materias que coincidan con la búsqueda.")
                return

        por_anio = {}
        for m in materias_filtradas:
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

                correlativas = correlatividades_map.get(mid, [])
                if correlativas:
                    with st.expander(f"📎 Correlativas ({len(correlativas)})", expanded=False):
                        for cnombre, cestado in correlativas:
                            icono = COLORES.get(cestado, "⬜")
                            st.markdown(f"{icono} {cnombre} — *{cestado.capitalize()}*")

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

    # ── TAB 2: Mapa visual de correlativas ────────────────────────────────────
    with tab2:
        st.markdown("### 🗺️ Mapa de Correlativas")
        st.caption("Cada nodo es una materia. Las flechas indican que la materia origen **requiere** la de destino. Hacé click en un nodo para ver sus conexiones.")

        col_leg1, col_leg2, col_leg3 = st.columns(3)
        with col_leg1:
            filtro_anio = st.selectbox(
                "Filtrar por año",
                ["Todos los años", "1° Año", "2° Año", "3° Año", "4° Año", "5° Año"],
                key="mapa_filtro_anio"
            )
        with col_leg2:
            filtro_estado = st.selectbox(
                "Resaltar estado",
                ["Todos", "pendiente", "cursando", "regular", "aprobada", "promocionada", "desaprobada"],
                key="mapa_filtro_estado"
            )

        arcos = get_correlatividades_completas(usuario["carrera_id"], usuario["id"])

        # Filtrar materias si se eligió un año
        anio_num_map = {"1° Año": 1, "2° Año": 2, "3° Año": 3, "4° Año": 4, "5° Año": 5}
        materias_mapa = materias
        if filtro_anio != "Todos los años":
            anio_sel = anio_num_map[filtro_anio]
            # Para el mapa incluimos el año seleccionado + sus dependencias directas
            ids_anio = {m[0] for m in materias if m[3] == anio_sel}
            # IDs de requisitos de esas materias (año anterior conectado)
            ids_req = {to_id for from_id, to_id in arcos if from_id in ids_anio}
            ids_visibles = ids_anio | ids_req
            materias_mapa = [m for m in materias if m[0] in ids_visibles]
            arcos = [(f, t) for f, t in arcos if f in ids_visibles and t in ids_visibles]

        # Si hay filtro de estado, opacar los demás (lo manejamos desde JS vía opacidad inicial)
        if filtro_estado != "Todos":
            # Re-construimos materias_mapa marcando cuáles destacar
            # Lo hacemos cambiando el estado de los no-seleccionados a "__dim" para colorearlos gris
            materias_mapa = [
                m if m[7] == filtro_estado else (*m[:7], "__dim")
                for m in materias_mapa
            ]

        # Agregar "__dim" al diccionario de colores
        COLORES_NODO_DIM = {
            "__dim": {"bg": "#1a1a2a", "border": "#333344", "font": "#444455"},
        }

        html_mapa = render_mapa_correlativas(materias_mapa, arcos)
        st.components.v1.html(html_mapa, height=720, scrolling=False)

        # Estadísticas rápidas debajo del mapa
        st.markdown("---")
        total_m = len(materias)
        aprobadas_c = sum(1 for m in materias if m[7] in ("aprobada", "promocionada"))
        cursando_c  = sum(1 for m in materias if m[7] == "cursando")
        pendientes_c = sum(1 for m in materias if m[7] == "pendiente")
        desap_c = sum(1 for m in materias if m[7] == "desaprobada")

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total", total_m)
        col2.metric("✅ Aprobadas", aprobadas_c)
        col3.metric("📖 Cursando", cursando_c)
        col4.metric("⏳ Pendientes", pendientes_c)
        col5.metric("❌ Desaprobadas", desap_c)
