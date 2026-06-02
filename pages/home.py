import streamlit as st
from db import get_conn
from datetime import datetime, date

@st.cache_data(ttl=60)
def get_stats(usuario_id, carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM materias WHERE carrera_id = %s;", (carrera_id,))
            total = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM alumno_materias
                WHERE usuario_id = %s AND estado IN ('aprobada', 'promocionada');
            """, (usuario_id,))
            aprobadas = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM alumno_materias
                WHERE usuario_id = %s AND estado = 'cursando';
            """, (usuario_id,))
            cursando = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM alumno_materias
                WHERE usuario_id = %s AND estado = 'regular';
            """, (usuario_id,))
            regulares = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM alumno_materias
                WHERE usuario_id = %s AND estado = 'desaprobada';
            """, (usuario_id,))
            desaprobadas = cur.fetchone()[0]

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
