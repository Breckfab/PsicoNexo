import streamlit as st
from db import get_conn
from datetime import datetime, date, timedelta

def get_cuatrimestre_actual():
    mes = datetime.now().month
    if 3 <= mes <= 7:
        return "1° Cuatrimestre"
    elif 8 <= mes <= 12:
        return "2° Cuatrimestre"
    else:
        return "2° Cuatrimestre"

# ─── Configuración de cuatrimestre ────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_config_cuatrimestre(usuario_id, anio, cuatrimestre):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha_inicio, fecha_fin
                FROM configuracion_cuatrimestre
                WHERE usuario_id = %s AND anio = %s AND cuatrimestre = %s;
            """, (usuario_id, anio, cuatrimestre))
            return cur.fetchone()

@st.cache_data(ttl=300)
def get_todas_configs(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT anio, cuatrimestre, fecha_inicio, fecha_fin
                FROM configuracion_cuatrimestre
                WHERE usuario_id = %s
                ORDER BY anio DESC, cuatrimestre;
            """, (usuario_id,))
            rows = cur.fetchall()
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}

def guardar_config_cuatrimestre(usuario_id, anio, cuatrimestre, fecha_inicio, fecha_fin):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO configuracion_cuatrimestre (usuario_id, anio, cuatrimestre, fecha_inicio, fecha_fin)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (usuario_id, anio, cuatrimestre)
                DO UPDATE SET fecha_inicio = EXCLUDED.fecha_inicio, fecha_fin = EXCLUDED.fecha_fin;
            """, (usuario_id, anio, cuatrimestre, fecha_inicio, fecha_fin))
        conn.commit()
    get_config_cuatrimestre.clear()
    get_todas_configs.clear()
    get_home_data.clear()

def calcular_progreso_cuatrimestre(fecha_inicio, fecha_fin):
    hoy = date.today()
    if hoy < fecha_inicio:
        return 0, 0, (fecha_fin - fecha_inicio).days, "No iniciado"
    if hoy > fecha_fin:
        return 100, (fecha_fin - fecha_inicio).days, (fecha_fin - fecha_inicio).days, "Finalizado"
    dias_transcurridos = (hoy - fecha_inicio).days
    dias_totales = (fecha_fin - fecha_inicio).days
    porcentaje = round((dias_transcurridos / dias_totales) * 100, 1) if dias_totales > 0 else 0
    dias_restantes = (fecha_fin - hoy).days
    return porcentaje, dias_transcurridos, dias_totales, f"{dias_restantes} días restantes"

# ─── Batch query principal — 1 roundtrip para stats + configs ─────────────────

@st.cache_data(ttl=60)
def get_home_data(usuario_id, carrera_id):
    """
    Trae en un solo roundtrip:
      - stats de materias (aprobadas, cursando, regulares, desaprobadas, total)
      - todas las configuraciones de cuatrimestre del usuario
    Devuelve: (total, aprobadas, cursando, regulares, desaprobadas, avance, configs_dict)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Stats
            cur.execute("""
                WITH conteos AS (
                    SELECT
                        COUNT(*) FILTER (WHERE estado IN ('aprobada', 'promocionada')) AS aprobadas,
                        COUNT(*) FILTER (WHERE estado = 'cursando')                    AS cursando,
                        COUNT(*) FILTER (WHERE estado = 'regular')                     AS regulares,
                        COUNT(*) FILTER (WHERE estado = 'desaprobada')                 AS desaprobadas
                    FROM alumno_materias
                    WHERE usuario_id = %s
                ),
                total AS (
                    SELECT COUNT(*) AS total FROM materias WHERE carrera_id = %s
                )
                SELECT t.total, c.aprobadas, c.cursando, c.regulares, c.desaprobadas
                FROM total t, conteos c;
            """, (usuario_id, carrera_id))
            stats_row = cur.fetchone()

            # Configs
            cur.execute("""
                SELECT anio, cuatrimestre, fecha_inicio, fecha_fin
                FROM configuracion_cuatrimestre
                WHERE usuario_id = %s
                ORDER BY anio DESC, cuatrimestre;
            """, (usuario_id,))
            config_rows = cur.fetchall()

    total, aprobadas, cursando, regulares, desaprobadas = stats_row
    avance = round((aprobadas / total) * 100, 1) if total > 0 else 0
    configs = {(r[0], r[1]): (r[2], r[3]) for r in config_rows}
    return total, aprobadas, cursando, regulares, desaprobadas, avance, configs

# ─── Queries secundarias ───────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_clases_hoy(usuario_id):
    hoy = datetime.now()
    dia_semana = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][hoy.weekday()]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.nombre, c.horario, c.link, c.modalidad, c.turno
                FROM cursadas c
                JOIN materias m ON c.materia_id = m.id
                JOIN alumno_materias am ON am.materia_id = m.id AND am.usuario_id = c.usuario_id
                WHERE c.usuario_id = %s
                AND am.estado = 'cursando'
                AND c.dias ILIKE %s;
            """, (usuario_id, f"%{dia_semana}%"))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_tareas_pendientes(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.numero, t.descripcion, t.fecha_vencimiento, m.nombre
                FROM tareas t
                JOIN materias m ON t.materia_id = m.id
                WHERE t.usuario_id = %s AND t.completada = FALSE
                ORDER BY t.fecha_vencimiento ASC NULLS LAST;
            """, (usuario_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_materias_cursando_con_notas(usuario_id, anio_actual, cuatrimestre_actual):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH materias_cursando AS (
                    SELECT
                        m.nombre,
                        m.anio,
                        c.cuatrimestre,
                        c.anio_cursada,
                        c.profesor1,
                        c.dias,
                        c.horario,
                        c.modalidad,
                        m.id         AS materia_id,
                        am.usuario_id
                    FROM alumno_materias am
                    JOIN materias m  ON am.materia_id = m.id
                    JOIN cursadas c  ON c.materia_id = m.id AND c.usuario_id = am.usuario_id
                    WHERE am.usuario_id   = %s
                      AND am.estado       = 'cursando'
                      AND c.anio_cursada  = %s
                      AND (c.cuatrimestre = %s OR c.cuatrimestre = 'Anual')
                ),
                evals_usuario AS (
                    SELECT
                        materia_id,
                        COUNT(id)                                                            AS total_notas,
                        ROUND(AVG(nota)::numeric, 2)                                         AS promedio,
                        COUNT(id) FILTER (WHERE aprobado = TRUE)                             AS aprobadas,
                        COUNT(id) FILTER (WHERE aprobado = FALSE AND nota IS NOT NULL)        AS desaprobadas,
                        STRING_AGG(
                            CASE WHEN nota IS NOT NULL
                                THEN tipo || ': ' || nota::text
                            END,
                            ' · ' ORDER BY fecha ASC NULLS LAST
                        ) AS detalle_notas
                    FROM evaluaciones
                    WHERE usuario_id = %s
                    GROUP BY materia_id
                )
                SELECT
                    mc.nombre,
                    mc.anio,
                    mc.cuatrimestre,
                    mc.anio_cursada,
                    mc.profesor1,
                    mc.dias,
                    mc.horario,
                    mc.modalidad,
                    COALESCE(ev.total_notas, 0)  AS total_notas,
                    ev.promedio,
                    COALESCE(ev.aprobadas, 0)    AS aprobadas,
                    COALESCE(ev.desaprobadas, 0) AS desaprobadas,
                    ev.detalle_notas
                FROM materias_cursando mc
                LEFT JOIN evals_usuario ev ON ev.materia_id = mc.materia_id
                ORDER BY mc.anio, mc.nombre;
            """, (usuario_id, anio_actual, cuatrimestre_actual, usuario_id))
            return cur.fetchall()

def calcular_estado_cursada(cuatrimestre):
    mes = datetime.now().month
    if cuatrimestre == "Anual":
        return "En curso" if 3 <= mes <= 11 else "Finalizada"
    elif cuatrimestre == "1° Cuatrimestre":
        return "En curso" if 3 <= mes <= 7 else "Finalizada"
    elif cuatrimestre == "2° Cuatrimestre":
        return "En curso" if 8 <= mes <= 12 else "Finalizada"
    return "En curso"

# ─── Panel de configuración de fechas ─────────────────────────────────────────

def mostrar_config_fechas(usuario_id, anio_actual, cuatrimestre_actual, todas_configs):
    config_actual = todas_configs.get((anio_actual, cuatrimestre_actual))

    with st.expander("⚙️ Configurar fechas del cuatrimestre", expanded=not config_actual):
        st.caption("Definí las fechas de inicio y fin para calcular el progreso de cada materia.")

        defaults = {
            "1° Cuatrimestre": (date(anio_actual, 3, 17), date(anio_actual, 7, 18)),
            "2° Cuatrimestre": (date(anio_actual, 8, 4),  date(anio_actual, 11, 28)),
            "Anual":           (date(anio_actual, 3, 17), date(anio_actual, 11, 28)),
        }

        CUATRIS = ["1° Cuatrimestre", "2° Cuatrimestre", "Anual"]

        col_sel, _ = st.columns([2, 3])
        with col_sel:
            cuatri_editar = st.selectbox(
                "Cuatrimestre a configurar",
                CUATRIS,
                index=CUATRIS.index(cuatrimestre_actual) if cuatrimestre_actual in CUATRIS else 0,
                key="cfg_cuatri_sel"
            )

        config_existente = todas_configs.get((anio_actual, cuatri_editar))
        def_ini, def_fin = defaults.get(cuatri_editar, (date(anio_actual, 3, 1), date(anio_actual, 11, 30)))

        with st.form("form_config_cuatrimestre"):
            col1, col2, col3 = st.columns(3)
            with col1:
                anio_cfg = st.number_input("Año", min_value=2020, max_value=2040,
                                           value=anio_actual, key="cfg_anio")
            with col2:
                fecha_ini = st.date_input("Fecha de inicio",
                                          value=config_existente[0] if config_existente else def_ini,
                                          key="cfg_ini")
            with col3:
                fecha_fin = st.date_input("Fecha de fin",
                                          value=config_existente[1] if config_existente else def_fin,
                                          key="cfg_fin")

            col_g, col_c = st.columns(2)
            with col_g:
                guardar = st.form_submit_button("💾 Guardar fechas", use_container_width=True)
            with col_c:
                st.form_submit_button("❌ Cancelar", use_container_width=True)

        if guardar:
            if fecha_fin <= fecha_ini:
                st.error("La fecha de fin debe ser posterior a la de inicio.")
            else:
                guardar_config_cuatrimestre(usuario_id, anio_cfg, cuatri_editar, fecha_ini, fecha_fin)
                st.success(f"✅ Fechas guardadas: {fecha_ini.strftime('%d/%m/%Y')} → {fecha_fin.strftime('%d/%m/%Y')}")
                st.rerun()

        if todas_configs:
            st.markdown("**Configuraciones guardadas:**")
            for (anio_c, cuatri_c), (fi, ff) in sorted(todas_configs.items(), reverse=True):
                st.caption(f"📅 {cuatri_c} {anio_c}: {fi.strftime('%d/%m/%Y')} → {ff.strftime('%d/%m/%Y')}")

# ─── Barra de progreso de cuatrimestre ────────────────────────────────────────

def mostrar_barra_cuatrimestre(cuatrimestre, anio_cursada, todas_configs):
    config = todas_configs.get((anio_cursada, cuatrimestre))
    if not config:
        st.caption("⚙️ Configurá las fechas del cuatrimestre para ver el progreso temporal.")
        return

    fecha_inicio, fecha_fin = config
    porcentaje, dias_trans, dias_total, estado_texto = calcular_progreso_cuatrimestre(fecha_inicio, fecha_fin)

    color_barra = "#2ecc71" if porcentaje < 75 else ("#f39c12" if porcentaje < 90 else "#e74c3c")

    st.markdown(
        f"""
        <div style="margin-top:8px; margin-bottom:4px;">
            <div style="display:flex; justify-content:space-between; font-size:11px; color:#aaa; margin-bottom:3px;">
                <span>📅 {fecha_inicio.strftime('%d/%m')} → {fecha_fin.strftime('%d/%m/%Y')}</span>
                <span style="color:{color_barra}; font-weight:bold;">{porcentaje}% — {estado_texto}</span>
            </div>
            <div style="background:#2a2a3e; border-radius:6px; height:8px; overflow:hidden;">
                <div style="width:{porcentaje}%; background:{color_barra}; height:8px; border-radius:6px;
                            transition:width 0.3s ease;"></div>
            </div>
            <div style="font-size:10px; color:#666; margin-top:2px;">
                {dias_trans} de {dias_total} días cursados
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# ─── Vista principal ───────────────────────────────────────────────────────────

def mostrar(usuario):
    st.title("🧠 PsicoNexo")
    st.markdown(f"### Bienvenido/a, {usuario['nombre'].split()[0]} 👋")

    cuatrimestre_actual = get_cuatrimestre_actual()
    mes_actual = datetime.now().month
    anio_actual = datetime.now().year if mes_actual >= 3 else datetime.now().year - 1

    # 1 roundtrip: stats + configs
    total, aprobadas, cursando, regulares, desaprobadas, avance, todas_configs = get_home_data(
        usuario["id"], usuario["carrera_id"]
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("✅ Aprobadas", aprobadas)
    with col2:
        st.metric("📖 Cursando", cursando)
    with col3:
        st.metric("📋 Regulares", regulares)
    with col4:
        st.metric("❌ Desaprobadas", desaprobadas)
    with col5:
        st.metric("🎯 Avance carrera", f"{avance}%")

    st.markdown("---")
    st.markdown(f"**Progreso de la carrera: {aprobadas} de {total} materias aprobadas**")
    st.progress(avance / 100)

    st.markdown("---")

    # Panel de config recibe configs ya cargadas — sin roundtrip extra
    mostrar_config_fechas(usuario["id"], anio_actual, cuatrimestre_actual, todas_configs)

    st.markdown("---")

    st.markdown(f"### 📚 Cursando — {cuatrimestre_actual} {anio_actual}")
    # 2do roundtrip: materias + notas
    materias_cursando = get_materias_cursando_con_notas(
        usuario["id"], anio_actual, cuatrimestre_actual
    )

    if not materias_cursando:
        st.info("No tenés materias registradas para este cuatrimestre.")
    else:
        for m in materias_cursando:
            (mnombre, manio, mcuatri, manio_cursada, mprofesor,
             mdias, mhorario, mmodalidad, total_notas,
             promedio, aprobadas_ev, desaprobadas_ev, detalle_notas) = m

            estado = calcular_estado_cursada(mcuatri)
            badge_color = "#2ecc71" if estado == "En curso" else "#95a5a6"

            with st.expander(f"📖 {mnombre}", expanded=True):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    if mprofesor:
                        st.caption(f"👨‍🏫 {mprofesor}")
                    if mdias or mhorario:
                        dias_text = mdias or ""
                        horario_text = f"· {mhorario}" if mhorario else ""
                        st.caption(f"🗓️ {dias_text} {horario_text} — {mmodalidad or ''}")
                with col_b:
                    st.markdown(
                        f"<div style='text-align:right;'>"
                        f"<span style='background:{badge_color}; color:white; "
                        f"padding:3px 10px; border-radius:12px; font-size:12px;'>"
                        f"{estado}</span></div>",
                        unsafe_allow_html=True
                    )

                mostrar_barra_cuatrimestre(mcuatri, manio_cursada, todas_configs)

                st.markdown("**Notas cargadas:**")
                if total_notas and int(total_notas) > 0:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        color_prom = "#2ecc71" if promedio and promedio >= 6 else "#e74c3c"
                        st.markdown(
                            f"<div style='text-align:center;'>"
                            f"<div style='font-size:11px; color:#aaa;'>Promedio</div>"
                            f"<div style='font-size:24px; font-weight:bold; color:{color_prom};'>"
                            f"{promedio}</div></div>",
                            unsafe_allow_html=True
                        )
                    with col2:
                        st.markdown(
                            f"<div style='text-align:center;'>"
                            f"<div style='font-size:11px; color:#aaa;'>✅ Aprobadas</div>"
                            f"<div style='font-size:20px; font-weight:bold; color:#2ecc71;'>"
                            f"{aprobadas_ev}</div></div>",
                            unsafe_allow_html=True
                        )
                    with col3:
                        st.markdown(
                            f"<div style='text-align:center;'>"
                            f"<div style='font-size:11px; color:#aaa;'>❌ Desaprobadas</div>"
                            f"<div style='font-size:20px; font-weight:bold; color:#e74c3c;'>"
                            f"{desaprobadas_ev}</div></div>",
                            unsafe_allow_html=True
                        )
                    if detalle_notas:
                        st.caption(f"📋 {detalle_notas}")
                else:
                    st.caption("Todavía no cargaste notas para esta materia.")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 📅 Hoy")
        # 3er roundtrip: clases de hoy
        clases_hoy = get_clases_hoy(usuario["id"])
        if clases_hoy:
            for clase in clases_hoy:
                mnombre, horario, link, modalidad, turno = clase
                horario_text = f"a las {horario}" if horario else ""
                turno_text = f"({turno})" if turno else ""
                link_text = f" [🔗 Acceder]({link})" if link else ""
                st.success(f"📚 **{mnombre}** {horario_text} {turno_text}{link_text}")
        else:
            st.info("📭 Hoy no cursás ninguna materia.")

    with col2:
        st.markdown("### 📌 Tareas pendientes")
        # 4to roundtrip: tareas
        tareas = get_tareas_pendientes(usuario["id"])
        if tareas:
            hoy = date.today()
            for t in tareas:
                tnum, tdesc, tvenc, mnom = t
                vencida = tvenc and tvenc < hoy
                icono = "🔴" if vencida else "⏳"
                venc_text = str(tvenc) if tvenc else "Sin fecha"
                st.markdown(f"{icono} **Tarea {tnum}** — {mnom}")
                st.caption(f"{tdesc or 'Sin descripción'} — Vence: {venc_text}")
        else:
            st.info("No tenés tareas pendientes.")
