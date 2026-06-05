import streamlit as st
from db import get_conn
from datetime import datetime, date

def get_cuatrimestre_actual():
    mes = datetime.now().month
    if 3 <= mes <= 7:
        return "1° Cuatrimestre"
    elif 8 <= mes <= 12:
        return "2° Cuatrimestre"
    else:
        return "2° Cuatrimestre"

@st.cache_data(ttl=60)
def get_stats(usuario_id, carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
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
            row = cur.fetchone()
    total, aprobadas, cursando, regulares, desaprobadas = row
    avance = round((aprobadas / total) * 100, 1) if total > 0 else 0
    return total, aprobadas, cursando, regulares, desaprobadas, avance

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
                        m.id AS materia_id,
                        am.usuario_id
                    FROM alumno_materias am
                    JOIN materias m ON am.materia_id = m.id
                    JOIN cursadas c ON c.materia_id = m.id AND c.usuario_id = am.usuario_id
                    WHERE am.usuario_id = %s
                      AND am.estado = 'cursando'
                      AND c.anio_cursada = %s
                      AND (c.cuatrimestre = %s OR c.cuatrimestre = 'Anual')
                ),
                notas_agg AS (
                    SELECT
                        e.materia_id,
                        e.usuario_id,
                        COUNT(e.id)                                                        AS total_notas,
                        ROUND(AVG(e.nota)::numeric, 2)                                     AS promedio,
                        COUNT(e.id) FILTER (WHERE e.aprobado = TRUE)                       AS aprobadas,
                        COUNT(e.id) FILTER (WHERE e.aprobado = FALSE AND e.nota IS NOT NULL) AS desaprobadas,
                        STRING_AGG(
                            CASE WHEN e.nota IS NOT NULL
                                THEN e.tipo || ': ' || e.nota::text
                            END,
                            ' · ' ORDER BY e.fecha ASC NULLS LAST
                        ) AS detalle_notas
                    FROM evaluaciones e
                    WHERE e.usuario_id = %s
                    GROUP BY e.materia_id, e.usuario_id
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
                    COALESCE(na.total_notas, 0)   AS total_notas,
                    na.promedio,
                    COALESCE(na.aprobadas, 0)      AS aprobadas,
                    COALESCE(na.desaprobadas, 0)   AS desaprobadas,
                    na.detalle_notas
                FROM materias_cursando mc
                LEFT JOIN notas_agg na
                    ON na.materia_id = mc.materia_id AND na.usuario_id = mc.usuario_id
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

def mostrar(usuario):
    st.title("🧠 PsicoNexo")
    st.markdown(f"### Bienvenido/a, {usuario['nombre'].split()[0]} 👋")

    total, aprobadas, cursando, regulares, desaprobadas, avance = get_stats(usuario["id"], usuario["carrera_id"])

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
        st.metric("🎯 Avance", f"{avance}%")

    st.markdown("---")
    st.markdown(f"**Progreso de la carrera: {aprobadas} de {total} materias aprobadas**")
    st.progress(avance / 100)

    st.markdown("---")

    cuatrimestre_actual = get_cuatrimestre_actual()
    mes_actual = datetime.now().month
    anio_actual = datetime.now().year if mes_actual >= 3 else datetime.now().year - 1

    st.markdown(f"### 📚 Cursando — {cuatrimestre_actual} {anio_actual}")
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
