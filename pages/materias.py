import streamlit as st
from db import get_connection

ESTADOS = ["pendiente", "cursando", "regular", "promocionada", "aprobada", "desaprobada"]

COLORES = {
    "pendiente": "⬜",
    "cursando": "🟡",
    "regular": "🟠",
    "promocionada": "🟢",
    "aprobada": "🟢",
    "desaprobada": "🔴",
}

def get_materias_con_estado(usuario_id, carrera_id):
    conn = get_connection()
    cur = conn.cursor()
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
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def actualizar_estado(usuario_id, materia_id, nuevo_estado):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO alumno_materias (usuario_id, materia_id, estado)
        VALUES (%s, %s, %s)
        ON CONFLICT (usuario_id, materia_id)
        DO UPDATE SET estado = EXCLUDED.estado;
    """, (usuario_id, materia_id, nuevo_estado))
    conn.commit()
    cur.close()
    conn.close()

def mostrar(usuario):
    st.title("📋 Plan de Estudios")
    st.caption("Licenciatura en Psicología — UdeMM")

    materias = get_materias_con_estado(usuario["id"], usuario["carrera_id"])

    if not materias:
        st.warning("No se encontraron materias para tu carrera.")
        return

    # Agrupar por año
    por_anio = {}
    for m in materias:
        anio = m[3]
        if anio not in por_anio:
            por_anio[anio] = []
        por_anio[anio].append(m)

    nombres_anio = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}

    for anio, lista in por_anio.items():
        st.subheader(nombres_anio.get(anio, f"Año {anio}"))

        for m in lista:
            mid, codigo, nombre, _, cuatri, final_oblig, es_electiva, estado = m

            col1, col2 = st.columns([3, 1])
            with col1:
                etiquetas = []
                if final_oblig:
                    etiquetas.append("📝 Final obligatorio")
                if es_electiva:
                    etiquetas.append("⭐ Electiva")
                cuatri_texto = {"1": "1° cuatrimestre", "2": "2° cuatrimestre", "anual": "Anual"}.get(cuatri, cuatri)

                st.markdown(f"{COLORES[estado]} **{nombre}**")
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

        st.markdown("---")
