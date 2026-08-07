import streamlit as st
from db import get_conn, get_feriados, get_clases_hoy, get_historial_comisiones, get_periodos_comision
from datetime import datetime, date, timedelta
import re
from utils import NOMBRES_ANIO, DIA_INDEX, contar_clases_en_rango, contar_clases_multi_periodo, clasificar_asistencia, convertir_link_preview
from pages.estadisticas import calcular_historial_asistencia, generar_pdf_asistencia, get_nombre_usuario

MODALIDADES = ["Presencial", "Híbrida", "Asincrónica"]
TURNOS = ["Mañana", "Tarde", "Noche"]
CUATRIMESTRES = ["1° Cuatrimestre", "2° Cuatrimestre", "Anual"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]


def normalizar_horario(texto):
    """
    Intenta interpretar `texto` como una hora y devolverla siempre en formato
    "HH:MM" (24hs), sin importar cómo la haya tipeado el alumno.

    Formatos soportados:
    - "18:30", "18.30", "18,30", "18 30", "1830" → "18:30"
    - "18" (solo la hora)                        → "18:00"
    - "6:30 pm", "6:30pm", "6pm", "6 am"          → 24hs equivalente

    Devuelve:
    - "" si el texto viene vacío (el horario es opcional).
    - El horario normalizado "HH:MM" si se pudo interpretar.
    - None si el texto no es vacío pero no se pudo interpretar como hora
      válida (el llamador debe mostrar un error y no guardar).
    """
    if texto is None:
        return ""
    texto = texto.strip()
    if not texto:
        return ""

    t = texto.lower().replace(" ", "")

    # ── Detectar am/pm ──────────────────────────────────────────────
    es_pm = False
    es_am = False
    if t.endswith("pm"):
        es_pm = True
        t = t[:-2]
    elif t.endswith("am"):
        es_am = True
        t = t[:-2]

    if not t:
        return None

    # ── Separador explícito: ":", ".", "," ─────────────────────────
    match = re.match(r"^(\d{1,2})[:.,](\d{1,2})$", t)
    if match:
        hora, minuto = int(match.group(1)), int(match.group(2))
    else:
        # ── Solo dígitos: "18", "1830", "830" ──────────────────────
        match = re.match(r"^(\d{1,4})$", t)
        if not match:
            return None
        digitos = match.group(1)
        if len(digitos) <= 2:
            hora, minuto = int(digitos), 0
        elif len(digitos) == 3:
            hora, minuto = int(digitos[0]), int(digitos[1:])
        else:
            hora, minuto = int(digitos[:2]), int(digitos[2:])

    if minuto > 59:
        return None

    if es_pm and hora < 12:
        hora += 12
    if es_am and hora == 12:
        hora = 0

    if hora > 23:
        return None

    return f"{hora:02d}:{minuto:02d}"

@st.cache_data(ttl=60)
def get_materias_cursando(usuario_id, carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.nombre, m.anio
                FROM materias m
                JOIN alumno_materias am ON m.id = am.materia_id
                WHERE am.usuario_id = %s AND am.estado = 'cursando'
                AND m.carrera_id = %s
                ORDER BY m.anio, m.nombre;
            """, (usuario_id, carrera_id))
            return cur.fetchall()

@st.cache_data(ttl=120)
def get_todas_materias(carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, anio FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, nombre;
            """, (carrera_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_todas_cursadas(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT materia_id, id, anio_cursada, cuatrimestre, modalidad, dias, horario, link,
                       profesor1, email_profesor1, profesor2, email_profesor2, turno,
                       fecha_parcial1, fecha_parcial2, fecha_final,
                       numero_comision, fecha_desde_comision
                FROM cursadas
                WHERE usuario_id = %s
                ORDER BY anio_cursada DESC, id DESC;
            """, (usuario_id,))
            rows = cur.fetchall()
    result = {}
    for row in rows:
        mid = row[0]
        if mid not in result:
            result[mid] = row[1:]
    return result

@st.cache_data(ttl=60)
def get_todos_programas_cursada(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT materia_id, link FROM programas WHERE usuario_id = %s;", (usuario_id,))
            return {row[0]: row[1] for row in cur.fetchall()}

@st.cache_data(ttl=60)
def get_tareas_materia(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, numero, descripcion, fecha_vencimiento, completada
                FROM tareas
                WHERE usuario_id = %s AND materia_id = %s
                ORDER BY numero;
            """, (usuario_id, materia_id))
            return cur.fetchall()

# ─── Materias aprobadas / promocionadas ─────────────────────────────────────
# Se usan en la tab "✅ Materias aprobadas" (ítem de prioridad máxima,
# 27/07/2026). Se separan en dos queries chicas en vez de un JOIN grande con
# `cursadas` + `evaluaciones` para no arrastrar el problema de duplicación
# de filas que aparece cuando una materia tiene más de una cursada o más de
# una nota (el JOIN multiplicaría filas y el AVG saldría mal). En su lugar,
# se resuelve cada pieza por separado y se combina en Python, reutilizando
# get_todas_cursadas() (ya cacheada) para los datos de la cursada.

@st.cache_data(ttl=60)
def get_materias_aprobadas(usuario_id, carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT m.id, m.nombre, m.anio, am.estado
                FROM materias m
                JOIN alumno_materias am ON m.id = am.materia_id AND am.usuario_id = %s
                WHERE m.carrera_id = %s
                AND am.estado IN ('aprobada', 'promocionada')
                ORDER BY m.anio, m.nombre;
            """, (usuario_id, carrera_id))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_promedios_por_materia(usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT materia_id, AVG(nota) as promedio
                FROM evaluaciones
                WHERE usuario_id = %s AND nota IS NOT NULL
                GROUP BY materia_id;
            """, (usuario_id,))
            return {row[0]: row[1] for row in cur.fetchall()}

def guardar_cursada(usuario_id, materia_id, anio, cuatrimestre, modalidad, turno, dias, horario, link,
                     profesor1, email_profesor1, profesor2, email_profesor2,
                     fecha_parcial1=None, fecha_parcial2=None, fecha_final=None,
                     numero_comision=None):
    """
    Alta / corrección de una cursada. IMPORTANTE: esto es para cargar datos
    o corregir errores de tipeo — NO historiza cambios de comisión. Si el
    alumno cambió de comisión (ej. de "COM III" a "COM V") a mitad de
    cuatrimestre, hay que usar cambiar_comision(), que sí archiva el
    período anterior en comisiones_historial. Por eso el ON CONFLICT de acá
    deliberadamente no toca numero_comision ni fecha_desde_comision: esos
    campos solo se fijan al crear la cursada por primera vez.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cursadas (usuario_id, materia_id, anio_cursada, cuatrimestre, modalidad, turno, dias, horario, link, profesor1, email_profesor1, profesor2, email_profesor2, fecha_parcial1, fecha_parcial2, fecha_final, numero_comision, fecha_desde_comision)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)
                ON CONFLICT (usuario_id, materia_id, anio_cursada, cuatrimestre)
                DO UPDATE SET modalidad = EXCLUDED.modalidad, turno = EXCLUDED.turno,
                              dias = EXCLUDED.dias, horario = EXCLUDED.horario,
                              link = EXCLUDED.link, profesor1 = EXCLUDED.profesor1,
                              email_profesor1 = EXCLUDED.email_profesor1,
                              profesor2 = EXCLUDED.profesor2,
                              email_profesor2 = EXCLUDED.email_profesor2,
                              fecha_parcial1 = EXCLUDED.fecha_parcial1,
                              fecha_parcial2 = EXCLUDED.fecha_parcial2,
                              fecha_final = EXCLUDED.fecha_final;
            """, (usuario_id, materia_id, anio, cuatrimestre, modalidad, turno, dias, horario, link,
                  profesor1, email_profesor1, profesor2, email_profesor2,
                  fecha_parcial1, fecha_parcial2, fecha_final,
                  numero_comision or "COM I"))
        conn.commit()
    get_todas_cursadas.clear()
    get_clases_hoy.clear()

def cambiar_comision(usuario_id, materia_id, fecha_cambio, nuevo_numero, nuevo_turno, nuevos_dias,
                      nuevo_horario, nuevo_link, nuevo_prof1, nuevo_email_prof1, nuevo_prof2, nuevo_email_prof2):
    """
    Registra un cambio de comisión a mitad de cursada (ítem #6, 02/08/2026):
    no se puede estar en dos comisiones a la vez, pero sí cambiar de una a
    otra durante el cuatrimestre. Cierra el período de la comisión vigente
    en comisiones_historial (con los datos que tenía hasta ahora) y
    actualiza la cursada con los datos de la nueva comisión a partir de
    `fecha_cambio`, para que el cálculo de asistencia pueda sumar
    correctamente las clases dictadas de cada tramo.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, numero_comision, turno, dias, horario, link,
                       profesor1, email_profesor1, profesor2, email_profesor2, fecha_desde_comision
                FROM cursadas
                WHERE usuario_id = %s AND materia_id = %s;
            """, (usuario_id, materia_id))
            row = cur.fetchone()
            if not row:
                return False, "No se encontró la cursada de esta materia."

            (cursada_id, numero_actual, turno_actual, dias_actual, horario_actual, link_actual,
             prof1_actual, email1_actual, prof2_actual, email2_actual, fecha_desde_actual) = row

            if fecha_desde_actual and fecha_cambio <= fecha_desde_actual:
                return False, "La fecha de cambio debe ser posterior a la fecha de inicio de la comisión actual."

            if fecha_desde_actual:
                fecha_hasta_cierre = fecha_cambio - timedelta(days=1)
                cur.execute("""
                    INSERT INTO comisiones_historial
                    (cursada_id, numero_comision, turno, dias, horario, link,
                     profesor1, email_profesor1, profesor2, email_profesor2,
                     fecha_desde, fecha_hasta)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """, (cursada_id, numero_actual or "COM I", turno_actual, dias_actual, horario_actual, link_actual,
                      prof1_actual, email1_actual, prof2_actual, email2_actual,
                      fecha_desde_actual, fecha_hasta_cierre))

            cur.execute("""
                UPDATE cursadas
                SET numero_comision = %s, turno = %s, dias = %s, horario = %s, link = %s,
                    profesor1 = %s, email_profesor1 = %s, profesor2 = %s, email_profesor2 = %s,
                    fecha_desde_comision = %s
                WHERE id = %s;
            """, (nuevo_numero, nuevo_turno, nuevos_dias, nuevo_horario, nuevo_link,
                  nuevo_prof1, nuevo_email_prof1, nuevo_prof2, nuevo_email_prof2,
                  fecha_cambio, cursada_id))
        conn.commit()
    get_todas_cursadas.clear()
    get_clases_hoy.clear()
    get_historial_comisiones.clear()
    return True, f"Comisión actualizada a {nuevo_numero}."

def borrar_cursada(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM cursadas WHERE usuario_id = %s AND materia_id = %s;", (usuario_id, materia_id))
        conn.commit()
    get_todas_cursadas.clear()
    get_clases_hoy.clear()

def borrar_cursada_especifica(usuario_id, materia_id, anio_cursada, cuatrimestre):
    """Borra únicamente la cursada puntual (año + cuatrimestre) indicada, sin
    afectar otras cursadas históricas de la misma materia. Se usa al editar
    una cursada cuando el año o el cuatrimestre cambian: como esos campos son
    parte de la UNIQUE constraint de la tabla, guardar_cursada no actualiza la
    fila original (el ON CONFLICT no matchea), sino que inserta una fila
    nueva y deja la vieja huérfana con datos desactualizados. Sin este borrado
    previo, get_todas_cursadas() puede terminar mostrando esa fila vieja como
    si fuera la cursada vigente."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM cursadas
                WHERE usuario_id = %s AND materia_id = %s
                AND anio_cursada = %s AND cuatrimestre = %s;
            """, (usuario_id, materia_id, anio_cursada, cuatrimestre))
        conn.commit()
    get_todas_cursadas.clear()
    get_clases_hoy.clear()

def guardar_tarea(usuario_id, materia_id, numero, descripcion, fecha_vencimiento):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tareas (usuario_id, materia_id, numero, descripcion, fecha_vencimiento)
                VALUES (%s, %s, %s, %s, %s);
            """, (usuario_id, materia_id, numero, descripcion, fecha_vencimiento))
        conn.commit()
    get_tareas_materia.clear()

def actualizar_tarea(tarea_id, descripcion, fecha_vencimiento, completada):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tareas SET descripcion = %s, fecha_vencimiento = %s, completada = %s
                WHERE id = %s;
            """, (descripcion, fecha_vencimiento, completada, tarea_id))
        conn.commit()
    get_tareas_materia.clear()

def borrar_tarea(tarea_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tareas WHERE id = %s;", (tarea_id,))
        conn.commit()
    get_tareas_materia.clear()

# ─── Asistencia ────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_config_cuatrimestre_materia(usuario_id, anio, cuatrimestre):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha_inicio, fecha_fin
                FROM configuracion_cuatrimestre
                WHERE usuario_id = %s AND anio = %s AND cuatrimestre = %s;
            """, (usuario_id, anio, cuatrimestre))
            return cur.fetchone()

@st.cache_data(ttl=60)
def get_faltas_materia(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, fecha, justificada
                FROM asistencias
                WHERE usuario_id = %s AND materia_id = %s
                ORDER BY fecha DESC;
            """, (usuario_id, materia_id))
            return cur.fetchall()

def agregar_falta(usuario_id, materia_id, fecha, justificada=False):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO asistencias (usuario_id, materia_id, fecha, justificada)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (usuario_id, materia_id, fecha)
                DO UPDATE SET justificada = EXCLUDED.justificada;
            """, (usuario_id, materia_id, fecha, justificada))
        conn.commit()
    get_faltas_materia.clear()

def borrar_falta(falta_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM asistencias WHERE id = %s;", (falta_id,))
        conn.commit()
    get_faltas_materia.clear()

def actualizar_falta(falta_id, fecha, justificada):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE asistencias SET fecha = %s, justificada = %s
                WHERE id = %s;
            """, (fecha, justificada, falta_id))
        conn.commit()
    get_faltas_materia.clear()

def calcular_asistencia(usuario_id, materia_id, dias_str, anio_cursada, cuatrimestre, feriados=None,
                         cursada_id=None, fecha_desde_comision=None):
    config = get_config_cuatrimestre_materia(usuario_id, anio_cursada, cuatrimestre)
    if not config:
        return None
    fecha_inicio, fecha_fin = config

    # Si tenemos la cursada y la fecha de inicio de la comisión vigente,
    # sumamos clases por tramo (uno por cada comisión por la que pasó el
    # alumno), en vez de aplicar los días actuales a todo el cuatrimestre.
    if cursada_id and fecha_desde_comision:
        periodos = get_periodos_comision(cursada_id, dias_str, fecha_desde_comision)
        clases_totales = contar_clases_multi_periodo(periodos, fecha_inicio, fecha_fin, feriados)
    else:
        clases_totales = contar_clases_en_rango(dias_str, fecha_inicio, fecha_fin, feriados)

    if clases_totales == 0:
        return None
    faltas = get_faltas_materia(usuario_id, materia_id)
    cantidad_faltas = len(faltas)
    porcentaje = round(((clases_totales - cantidad_faltas) / clases_totales) * 100, 1)
    max_faltas_permitidas = int(clases_totales * 0.25)
    faltas_restantes = max_faltas_permitidas - cantidad_faltas
    return {
        "clases_totales": clases_totales,
        "faltas": cantidad_faltas,
        "porcentaje": porcentaje,
        "faltas_restantes": faltas_restantes,
        "max_faltas_permitidas": max_faltas_permitidas,
        "detalle_faltas": faltas,
    }

def mostrar_asistencia(usuario, mid, dias, anio, cuatri, cursada_id=None, fecha_desde_comision=None):
    st.markdown("---")
    st.markdown("#### 📅 Asistencia")

    # ── Diagnóstico paso a paso (nunca se queda mudo) ─────────────────
    config = get_config_cuatrimestre_materia(usuario["id"], anio, cuatri)
    if not config:
        st.caption(
            f"⚙️ No encontré fechas configuradas para **{cuatri} {anio}**. "
            f"Andá a Inicio → '⚙️ Configurar fechas del cuatrimestre', elegí ese cuatrimestre y ese año, y guardalas."
        )
        return

    feriados_set = {f[1] for f in get_feriados(usuario["id"])}

    fecha_inicio, fecha_fin = config

    if cursada_id and fecha_desde_comision:
        periodos = get_periodos_comision(cursada_id, dias, fecha_desde_comision)
        clases_totales = contar_clases_multi_periodo(periodos, fecha_inicio, fecha_fin, feriados_set)
    else:
        clases_totales = contar_clases_en_rango(dias, fecha_inicio, fecha_fin, feriados_set)

    if clases_totales == 0:
        st.caption(
            f"📅 No pude calcular clases. Días cargados: **'{dias or '—'}'** · "
            f"Rango configurado: {fecha_inicio.strftime('%d/%m/%Y')} → {fecha_fin.strftime('%d/%m/%Y')}. "
            f"Revisá que los días de cursada estén cargados en esta materia (editar cursada → Días)."
        )
        return

    stats = calcular_asistencia(usuario["id"], mid, dias, anio, cuatri, feriados_set, cursada_id, fecha_desde_comision)
    porcentaje = stats["porcentaje"]
    color, negrita = clasificar_asistencia(porcentaje)
    peso = "bold" if negrita else "normal"
    restantes = max(stats["faltas_restantes"], 0)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f"<div style='text-align:center;'><div style='font-size:11px; color:#aaa;'>Asistencia</div>"
            f"<div style='font-size:26px; font-weight:{peso}; color:{color};'>{porcentaje}%</div></div>",
            unsafe_allow_html=True
        )
    with col2:
        st.markdown(
            f"<div style='text-align:center;'><div style='font-size:11px; color:#aaa;'>Faltas usadas</div>"
            f"<div style='font-size:20px; font-weight:bold;'>{stats['faltas']} / {stats['max_faltas_permitidas']}</div></div>",
            unsafe_allow_html=True
        )
    with col3:
        st.markdown(
            f"<div style='text-align:center;'><div style='font-size:11px; color:#aaa;'>Podés faltar</div>"
            f"<div style='font-size:20px; font-weight:{peso}; color:{color};'>{restantes} clase(s) más</div></div>",
            unsafe_allow_html=True
        )

    if porcentaje < 75:
        st.markdown(
            f"<p style='color:{color}; font-weight:bold; text-align:center; margin-top:8px;'>"
            f"🚨 ¡Estás en riesgo de quedar libre por inasistencias!</p>",
            unsafe_allow_html=True
        )
    elif porcentaje < 85:
        st.markdown(
            f"<p style='color:{color}; font-weight:bold; text-align:center; margin-top:8px;'>"
            f"⚠️ Te estás acercando al límite de inasistencias.</p>",
            unsafe_allow_html=True
        )

    with st.expander("📋 Marcar falta / ver faltas registradas"):
        # Contador de reseteo (ítem "formularios deben volver limpios",
        # 02/08/2026): se incrementa después de guardar para que el form se
        # recree con keys nuevas y no quede con la fecha/checkbox tildados.
        falta_key = f"falta_form_key_{mid}"
        if falta_key not in st.session_state:
            st.session_state[falta_key] = 0
        fk = st.session_state[falta_key]

        with st.form(f"form_falta_{mid}_{fk}"):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                fecha_falta = st.date_input("Fecha de la falta", value=date.today(), key=f"fecha_falta_{mid}_{fk}")
            with col_f2:
                justificada = st.checkbox("¿Justificada?", key=f"just_falta_{mid}_{fk}")
            agregar = st.form_submit_button("➕ Marcar falta", use_container_width=True)
        if agregar:
            agregar_falta(usuario["id"], mid, fecha_falta, justificada)
            st.session_state[falta_key] += 1
            st.success("Falta registrada.")
            st.rerun()

        if stats["detalle_faltas"]:
            st.markdown("**Faltas registradas:**")
            for fid, ffecha, fjust in stats["detalle_faltas"]:
                just_text = " · justificada" if fjust else ""
                col_ff1, col_ff2, col_ff3 = st.columns([3, 1, 1])
                with col_ff1:
                    st.markdown(f"📌 {ffecha.strftime('%d/%m/%Y')}{just_text}")
                with col_ff2:
                    if st.button("✏️", key=f"edit_falta_{fid}", use_container_width=True):
                        st.session_state[f"editando_falta_{fid}"] = True
                        st.rerun()
                with col_ff3:
                    if st.button("🗑️", key=f"del_falta_{fid}", use_container_width=True):
                        borrar_falta(fid)
                        st.rerun()

                if st.session_state.get(f"editando_falta_{fid}"):
                    with st.form(f"form_edit_falta_{fid}"):
                        col_ef1, col_ef2 = st.columns(2)
                        with col_ef1:
                            nueva_fecha_falta = st.date_input(
                                "Fecha de la falta", value=ffecha, key=f"nueva_fecha_falta_{fid}"
                            )
                        with col_ef2:
                            nueva_justificada = st.checkbox(
                                "¿Justificada?", value=fjust, key=f"nueva_just_falta_{fid}"
                            )
                        col_gf, col_cf = st.columns(2)
                        with col_gf:
                            guardar_falta_edit = st.form_submit_button("💾 Guardar", use_container_width=True)
                        with col_cf:
                            cancelar_falta_edit = st.form_submit_button("❌ Cancelar", use_container_width=True)
                    if guardar_falta_edit:
                        actualizar_falta(fid, nueva_fecha_falta, nueva_justificada)
                        st.session_state[f"editando_falta_{fid}"] = False
                        st.success("Falta actualizada.")
                        st.rerun()
                    if cancelar_falta_edit:
                        st.session_state[f"editando_falta_{fid}"] = False
                        st.rerun()
        else:
            st.caption("No hay faltas registradas todavía. Por defecto se asume presente en todas las clases.")

def mostrar_gestion_comision(usuario, mid, cid, numero_comision, fecha_desde_comision, turno, dias, horario, link,
                              prof1, email_prof1, prof2, email_prof2):
    """
    Panel de comisión actual + formulario de cambio de comisión + historial
    de comisiones anteriores (ítem #6 de "Cosas por Hacer", 02/08/2026).
    """
    st.markdown("---")
    col_com1, col_com2 = st.columns([3, 1])
    with col_com1:
        comision_texto = numero_comision or "—"
        if fecha_desde_comision:
            comision_texto += f" (desde {fecha_desde_comision.strftime('%d/%m/%Y')})"
        st.caption(f"🔀 Comisión actual: **{comision_texto}**")
    with col_com2:
        if st.button("🔄 Cambiar", key=f"btn_cambiar_com_{mid}", use_container_width=True):
            st.session_state[f"cambiando_comision_{mid}"] = not st.session_state.get(f"cambiando_comision_{mid}", False)
            st.rerun()

    if st.session_state.get(f"cambiando_comision_{mid}"):
        # Contador de reseteo (ítem "formularios deben volver limpios",
        # 02/08/2026): se incrementa al guardar y al cancelar, para que el
        # form vuelva limpio la próxima vez que se abra, en vez de quedar
        # con los datos de un intento anterior.
        cc_key = f"cambiar_comision_form_key_{mid}"
        if cc_key not in st.session_state:
            st.session_state[cc_key] = 0
        fk = st.session_state[cc_key]

        with st.form(f"form_cambiar_comision_{mid}_{fk}"):
            st.markdown("**🔄 Registrar cambio de comisión**")
            col_cc1, col_cc2 = st.columns(2)
            with col_cc1:
                cc_fecha = st.date_input("Fecha del cambio", value=date.today(), key=f"cc_fecha_{mid}_{fk}")
                cc_numero = st.text_input("Nueva comisión (ej: COM V)", key=f"cc_numero_{mid}_{fk}")
                cc_turno = st.selectbox("Turno", TURNOS, index=TURNOS.index(turno) if turno in TURNOS else 0, key=f"cc_turno_{mid}_{fk}")
            with col_cc2:
                cc_horario = st.text_input("Nuevo horario", key=f"cc_horario_{mid}_{fk}")
                cc_link = st.text_input("Nuevo link", value=link or "", key=f"cc_link_{mid}_{fk}")
            cc_dias = st.multiselect("Nuevos días", DIAS, key=f"cc_dias_{mid}_{fk}")
            col_cc3, col_cc4 = st.columns(2)
            with col_cc3:
                cc_prof1 = st.text_input("Profesor/a 1", value=prof1 or "", key=f"cc_prof1_{mid}_{fk}")
                cc_email1 = st.text_input("Email Profesor/a 1", value=email_prof1 or "", key=f"cc_email1_{mid}_{fk}")
            with col_cc4:
                cc_prof2 = st.text_input("Profesor/a 2", value=prof2 or "", key=f"cc_prof2_{mid}_{fk}")
                cc_email2 = st.text_input("Email Profesor/a 2", value=email_prof2 or "", key=f"cc_email2_{mid}_{fk}")
            col_cg, col_cx = st.columns(2)
            with col_cg:
                guardar_cc = st.form_submit_button("💾 Guardar cambio", use_container_width=True)
            with col_cx:
                cancelar_cc = st.form_submit_button("❌ Cancelar", use_container_width=True)

        if guardar_cc:
            if not cc_numero.strip():
                st.error("Ingresá el número de comisión.")
            else:
                cc_horario_norm = normalizar_horario(cc_horario)
                if cc_horario_norm is None:
                    st.error("⏰ Formato de horario no reconocido. Usá HH:MM, ej: 18:30")
                else:
                    ok_cc, msg_cc = cambiar_comision(
                        usuario["id"], mid, cc_fecha, cc_numero.strip(), cc_turno,
                        ", ".join(cc_dias), cc_horario_norm, cc_link,
                        cc_prof1, cc_email1, cc_prof2, cc_email2
                    )
                    if ok_cc:
                        st.session_state[f"cambiando_comision_{mid}"] = False
                        st.session_state[cc_key] += 1
                        st.success(msg_cc)
                        st.rerun()
                    else:
                        st.error(msg_cc)
        if cancelar_cc:
            st.session_state[f"cambiando_comision_{mid}"] = False
            st.session_state[cc_key] += 1
            st.rerun()

    historial_com = get_historial_comisiones(cid)
    if historial_com:
        with st.expander(f"📜 Historial de comisiones ({len(historial_com)})"):
            for hc in historial_com:
                (hid, hnum, hturno, hdias, hhorario, hlink, hprof1, hemail1,
                 hprof2, hemail2, hdesde, hhasta) = hc
                st.caption(
                    f"**{hnum}** — {hdesde.strftime('%d/%m/%Y')} → {hhasta.strftime('%d/%m/%Y')} · "
                    f"{hturno or '—'} · {hdias or '—'} {hhorario or ''}"
                )

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("🗓️ Cursadas")

    clases_hoy = get_clases_hoy(usuario["id"])
    if clases_hoy:
        for clase in clases_hoy:
            mnombre, horario, link, modalidad, turno = clase
            horario_text = f"a las {horario}" if horario else ""
            link_text = f" — [🔗 Acceder]({link})" if link else ""
            st.success(f"📚 Hoy tenés clase de **{mnombre}** {horario_text} ({modalidad}){link_text}")
    else:
        st.info("📭 Hoy no cursás ninguna materia.")

    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs([
        "📖 Cursando actualmente",
        "➕ Registrar Nueva Materia",
        "📌 Tareas",
        "✅ Materias aprobadas",
    ])

    with tab1:
        materias_cursando = get_materias_cursando(usuario["id"], usuario["carrera_id"])
        todas_cursadas = get_todas_cursadas(usuario["id"])
        todos_programas = get_todos_programas_cursada(usuario["id"])

        # ── Exportar asistencia a PDF (ítem de prioridad media-alta, 05/08/2026) ──
        # Se calcula una sola vez acá y se reutiliza tanto para el botón
        # general (todas las cursadas del alumno) como para los botones
        # individuales por materia más abajo, para no repetir la consulta.
        historial_asistencia = calcular_historial_asistencia(usuario["id"])

        if not materias_cursando:
            st.info("No tenés materias marcadas como 'cursando'. Cambiá el estado en Plan de Estudios.")
        else:
            if historial_asistencia:
                nombre_alumno_pdf = get_nombre_usuario(usuario["id"])
                pdf_general = generar_pdf_asistencia(historial_asistencia, nombre_alumno_pdf)
                st.download_button(
                    label="⬇️ Descargar PDF de asistencia (todas las materias)",
                    data=pdf_general,
                    file_name="asistencia_general.pdf",
                    mime="application/pdf",
                    key="pdf_asistencia_general",
                    use_container_width=True
                )
                st.markdown("---")

            for m in materias_cursando:
                mid, mnombre, manio = m
                cursada = todas_cursadas.get(mid)
                programa_link = todos_programas.get(mid)

                with st.expander(f"{NOMBRES_ANIO.get(manio, '')} — {mnombre}"):
                    if cursada:
                        (cid, anio, cuatri, modalidad, dias, horario, link, prof1, email_prof1, prof2,
                         email_prof2, turno, fecha_parcial1, fecha_parcial2, fecha_final,
                         numero_comision, fecha_desde_comision) = cursada
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Año:** {anio}")
                            st.markdown(f"**Cuatrimestre:** {cuatri}")
                            st.markdown(f"**Turno:** {turno or '—'}")
                            st.markdown(f"**Modalidad:** {modalidad}")
                            st.markdown(f"**Días:** {dias or '—'}")
                            st.markdown(f"**Horario:** {horario or '—'}")
                        with col2:
                            if prof1:
                                st.markdown(f"**Profesor/a 1:** {prof1}")
                                if email_prof1:
                                    st.markdown(f"📧 {email_prof1}")
                            if prof2:
                                st.markdown(f"**Profesor/a 2:** {prof2}")
                                if email_prof2:
                                    st.markdown(f"📧 {email_prof2}")
                        if link:
                            st.markdown(f"[🔗 Acceder a la clase]({link})")

                        # ── Fechas de parciales y final ───────────────────
                        st.markdown("**📆 Fechas de evaluación:**")
                        col_fp1, col_fp2, col_ff = st.columns(3)
                        with col_fp1:
                            st.caption(f"1er Parcial: {fecha_parcial1.strftime('%d/%m/%Y') if fecha_parcial1 else '—'}")
                        with col_fp2:
                            st.caption(f"2do Parcial: {fecha_parcial2.strftime('%d/%m/%Y') if fecha_parcial2 else '—'}")
                        with col_ff:
                            st.caption(f"Final: {fecha_final.strftime('%d/%m/%Y') if fecha_final else '—'}")

                        if programa_link:
                            st.markdown("---")
                            col_prog1, col_prog2 = st.columns(2)
                            with col_prog1:
                                st.markdown(f"[📋 Ver programa]({programa_link})")
                            with col_prog2:
                                preview_url = convertir_link_preview(programa_link)
                                if preview_url:
                                    if st.button("👁️ Ver PDF", key=f"pdf_prog_cursada_{mid}", use_container_width=True):
                                        st.session_state[f"viendo_pdf_cursada_{mid}"] = not st.session_state.get(f"viendo_pdf_cursada_{mid}", False)
                                        st.rerun()
                            if st.session_state.get(f"viendo_pdf_cursada_{mid}") and convertir_link_preview(programa_link):
                                st.components.v1.iframe(convertir_link_preview(programa_link), height=500)

                        # ── Sección de asistencia ─────────────────────────
                        mostrar_asistencia(usuario, mid, dias, anio, cuatri, cid, fecha_desde_comision)

                        # ── Exportar a PDF la asistencia de esta materia ──
                        # Reutiliza historial_asistencia (calculado una sola
                        # vez arriba) filtrando por nombre de materia, para
                        # cubrir también el caso de que se haya cursado más
                        # de una vez (varias filas para la misma materia).
                        datos_materia = [d for d in historial_asistencia if d["materia"] == mnombre]
                        if datos_materia:
                            nombre_alumno_pdf = get_nombre_usuario(usuario["id"])
                            pdf_materia = generar_pdf_asistencia(datos_materia, nombre_alumno_pdf, filtro_materia=mnombre)
                            st.download_button(
                                label="⬇️ Descargar PDF de asistencia de esta materia",
                                data=pdf_materia,
                                file_name=f"asistencia_{mnombre.replace(' ', '_')}.pdf",
                                mime="application/pdf",
                                key=f"pdf_asistencia_{mid}",
                                use_container_width=True
                            )

                        # ── Comisión: panel + cambio + historial ──────────
                        mostrar_gestion_comision(
                            usuario, mid, cid, numero_comision, fecha_desde_comision, turno, dias, horario, link,
                            prof1, email_prof1, prof2, email_prof2
                        )

                        st.markdown("---")
                        col_edit, col_borrar = st.columns(2)
                        with col_edit:
                            if st.button("✏️ Editar", key=f"edit_cursada_{mid}", use_container_width=True):
                                st.session_state[f"editando_cursada_{mid}"] = True
                                st.rerun()
                        with col_borrar:
                            key_confirmar = f"confirmar_del_cursada_{mid}"
                            if st.session_state.get(key_confirmar):
                                col_si, col_no = st.columns(2)
                                with col_si:
                                    if st.button("✅ Confirmar", key=f"si_del_cursada_{mid}", use_container_width=True):
                                        borrar_cursada(usuario["id"], mid)
                                        st.session_state[key_confirmar] = False
                                        st.success("Cursada borrada.")
                                        st.rerun()
                                with col_no:
                                    if st.button("❌ Cancelar", key=f"no_del_cursada_{mid}", use_container_width=True):
                                        st.session_state[key_confirmar] = False
                                        st.rerun()
                            else:
                                if st.button("🗑️ Borrar", key=f"borrar_cursada_{mid}", use_container_width=True):
                                    st.session_state[key_confirmar] = True
                                    st.rerun()

                        if st.session_state.get(f"editando_cursada_{mid}"):
                            with st.form(f"form_edit_cursada_{mid}"):
                                col1, col2 = st.columns(2)
                                with col1:
                                    e_anio = st.number_input("Año", min_value=2000, max_value=2100, value=anio)
                                    e_cuatri = st.selectbox("Cuatrimestre", CUATRIMESTRES, index=CUATRIMESTRES.index(cuatri) if cuatri in CUATRIMESTRES else 0)
                                    e_turno = st.selectbox("Turno", TURNOS, index=TURNOS.index(turno) if turno in TURNOS else 0)
                                with col2:
                                    e_modalidad = st.selectbox("Modalidad", MODALIDADES, index=MODALIDADES.index(modalidad) if modalidad in MODALIDADES else 0)
                                    e_horario = st.text_input("Horario", value=horario or "")
                                    e_link = st.text_input("Link", value=link or "")
                                e_dias = st.multiselect("Días", DIAS, default=[d.strip() for d in (dias or "").split(",") if d.strip() in DIAS])
                                e_prof1 = st.text_input("Profesor/a 1", value=prof1 or "")
                                e_email_prof1 = st.text_input("Email Profesor/a 1", value=email_prof1 or "")
                                e_prof2 = st.text_input("Profesor/a 2", value=prof2 or "")
                                e_email_prof2 = st.text_input("Email Profesor/a 2", value=email_prof2 or "")

                                st.markdown("**📆 Fechas de evaluación** _(opcional, se pueden dejar vacías)_")
                                col_ep1, col_ep2, col_ef = st.columns(3)
                                with col_ep1:
                                    e_fecha_parcial1 = st.date_input("1er Parcial", value=fecha_parcial1, key=f"e_fp1_{mid}")
                                with col_ep2:
                                    e_fecha_parcial2 = st.date_input("2do Parcial", value=fecha_parcial2, key=f"e_fp2_{mid}")
                                with col_ef:
                                    e_fecha_final = st.date_input("Final", value=fecha_final, key=f"e_ff_{mid}")

                                col1, col2 = st.columns(2)
                                with col1:
                                    guardar = st.form_submit_button("💾 Guardar", use_container_width=True)
                                with col2:
                                    cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)
                            if guardar:
                                e_horario_norm = normalizar_horario(e_horario)
                                if e_horario_norm is None:
                                    st.error("⏰ Formato de horario no reconocido. Usá HH:MM, ej: 18:30")
                                else:
                                    if e_anio != anio or e_cuatri != cuatri:
                                        # Año o cuatrimestre cambiaron: son parte de la clave única
                                        # de "cursadas", así que el guardado de abajo insertaría una
                                        # fila nueva y dejaría la vieja huérfana con datos desactualizados.
                                        # Hay que borrar la fila original primero (mismo patrón que se
                                        # usa para feriados en home.py).
                                        borrar_cursada_especifica(usuario["id"], mid, anio, cuatri)
                                    guardar_cursada(
                                        usuario["id"], mid, e_anio, e_cuatri, e_modalidad, e_turno,
                                        ", ".join(e_dias), e_horario_norm, e_link, e_prof1, e_email_prof1,
                                        e_prof2, e_email_prof2,
                                        e_fecha_parcial1, e_fecha_parcial2, e_fecha_final,
                                        numero_comision=numero_comision
                                    )
                                    st.session_state[f"editando_cursada_{mid}"] = False
                                    st.success("Cursada actualizada.")
                                    st.rerun()
                            if cancelar:
                                st.session_state[f"editando_cursada_{mid}"] = False
                                st.rerun()
                    else:
                        st.warning("Sin datos de cursada cargados.")
                        if programa_link:
                            st.markdown(f"[📋 Ver programa]({programa_link})")

    with tab2:
        todas = get_todas_materias(usuario["carrera_id"])
        opciones = {f"{NOMBRES_ANIO.get(m[2], '')} — {m[1]}": m[0] for m in todas}

        if "form_cursada_key" not in st.session_state:
            st.session_state.form_cursada_key = 0

        st.markdown("### 📅 Elegí el Año y la Materia")

        # Placeholder "Elegí una materia" como opción por defecto (ítem de
        # prioridad máxima, 27/07/2026), mismo patrón que ya se usa en
        # evaluaciones.py y recursos.py, para que el alumno no guarde una
        # cursada sin haber elegido materia explícitamente.
        opciones_lista = ["Elegí una materia"] + list(opciones.keys())

        fk = st.session_state.form_cursada_key
        with st.form(f"form_cursada_{fk}"):
            materia_label = st.selectbox(
                "📚 Materia (ordenada por año)", opciones_lista, index=0, key=f"cursada_materia_{fk}"
            )
            col1, col2 = st.columns(2)
            with col1:
                anio = st.number_input(
                    "Año de cursada", min_value=2000, max_value=2100, value=datetime.now().year,
                    key=f"cursada_anio_{fk}"
                )
                cuatrimestre = st.selectbox("Cuatrimestre", CUATRIMESTRES, key=f"cursada_cuatri_{fk}")
                turno = st.selectbox("Turno", TURNOS, key=f"cursada_turno_{fk}")
            with col2:
                modalidad = st.selectbox("Modalidad", MODALIDADES, key=f"cursada_modalidad_{fk}")
                horario = st.text_input("Horario (ej: 18:30)", key=f"cursada_horario_{fk}")
                link = st.text_input("Link de clase online", key=f"cursada_link_{fk}")
            col3, col4 = st.columns(2)
            with col3:
                dias_sel = st.multiselect("Días de cursada", DIAS, key=f"cursada_dias_{fk}")
            with col4:
                comision = st.text_input("Comisión (ej: COM V)", value="COM I", key=f"cursada_comision_{fk}")
            col1, col2 = st.columns(2)
            with col1:
                profesor1 = st.text_input("Profesor/a 1", key=f"cursada_prof1_{fk}")
                email_profesor1 = st.text_input("Email Profesor/a 1", key=f"cursada_email1_{fk}")
            with col2:
                profesor2 = st.text_input("Profesor/a 2 (opcional)", key=f"cursada_prof2_{fk}")
                email_profesor2 = st.text_input("Email Profesor/a 2 (opcional)", key=f"cursada_email2_{fk}")

            st.markdown("**📆 Fechas de evaluación** _(opcional, se pueden completar más adelante)_")
            col3, col4, col5 = st.columns(3)
            with col3:
                fecha_parcial1 = st.date_input("1er Parcial", value=None, key=f"cursada_fp1_{fk}")
            with col4:
                fecha_parcial2 = st.date_input("2do Parcial", value=None, key=f"cursada_fp2_{fk}")
            with col5:
                fecha_final = st.date_input("Final", value=None, key=f"cursada_ffinal_{fk}")

            submit = st.form_submit_button("💾 Guardar cursada", use_container_width=True)

        if submit:
            if materia_label == "Elegí una materia":
                st.error("Seleccioná una materia antes de guardar.")
            else:
                horario_norm = normalizar_horario(horario)
                if horario_norm is None:
                    st.error("⏰ Formato de horario no reconocido. Usá HH:MM, ej: 18:30")
                else:
                    materia_id = opciones[materia_label]
                    dias_str = ", ".join(dias_sel) if dias_sel else ""
                    guardar_cursada(
                        usuario["id"], materia_id, anio, cuatrimestre, modalidad, turno, dias_str, horario_norm, link,
                        profesor1, email_profesor1, profesor2, email_profesor2,
                        fecha_parcial1, fecha_parcial2, fecha_final,
                        numero_comision=comision.strip() or "COM I"
                    )
                    st.session_state.form_cursada_key += 1
                    st.success("✅ Cursada guardada correctamente.")
                    st.rerun()

    with tab3:
        st.subheader("📌 Tareas por materia")
        materias_cursando = get_materias_cursando(usuario["id"], usuario["carrera_id"])
        if not materias_cursando:
            st.info("No tenés materias cursando.")
        else:
            opciones_tareas = {f"{NOMBRES_ANIO.get(m[2], '')} — {m[1]}": m[0] for m in materias_cursando}
            materia_tarea_label = st.selectbox("Materia", list(opciones_tareas.keys()), key="sel_tarea")
            materia_tarea_id = opciones_tareas[materia_tarea_label]

            tareas = get_tareas_materia(usuario["id"], materia_tarea_id)
            tareas_dict = {t[1]: t for t in tareas}
            hoy = date.today()

            nums_existentes = sorted(tareas_dict.keys())
            todos_nums = list(range(1, max(nums_existentes) + 2)) if nums_existentes else [1]
            nums_a_mostrar = nums_existentes + [max(todos_nums)]

            for num in nums_existentes:
                tarea = tareas_dict[num]
                with st.expander(f"📌 Tarea {num}", expanded=True):
                    tid, tnum, tdesc, tvenc, tcomp = tarea
                    vencida = tvenc and tvenc < hoy and not tcomp
                    estado_icon = "✅ Completada" if tcomp else ("🔴 Vencida" if vencida else "⏳ Pendiente")
                    st.markdown(f"**{tdesc or 'Sin descripción'}**")
                    st.markdown(f"Vence: {str(tvenc) if tvenc else '—'} — {estado_icon}")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if st.button("✏️ Editar", key=f"edit_tarea_{num}_{materia_tarea_id}", use_container_width=True):
                            st.session_state[f"editando_tarea_{num}_{materia_tarea_id}"] = True
                            st.rerun()
                    with col2:
                        if not tcomp:
                            if st.button("✅ Completar", key=f"comp_tarea_{num}_{materia_tarea_id}", use_container_width=True):
                                actualizar_tarea(tid, tdesc, tvenc, True)
                                st.rerun()
                    with col3:
                        key_confirmar_t = f"confirmar_del_tarea_{tid}"
                        if st.session_state.get(key_confirmar_t):
                            col_si, col_no = st.columns(2)
                            with col_si:
                                if st.button("✅", key=f"si_del_t_{tid}", use_container_width=True):
                                    borrar_tarea(tid)
                                    st.session_state[key_confirmar_t] = False
                                    st.rerun()
                            with col_no:
                                if st.button("❌", key=f"no_del_t_{tid}", use_container_width=True):
                                    st.session_state[key_confirmar_t] = False
                                    st.rerun()
                        else:
                            if st.button("🗑️ Borrar", key=f"borrar_tarea_{num}_{materia_tarea_id}", use_container_width=True):
                                st.session_state[key_confirmar_t] = True
                                st.rerun()

                    if st.session_state.get(f"editando_tarea_{num}_{materia_tarea_id}"):
                        with st.form(f"form_edit_tarea_{num}_{materia_tarea_id}"):
                            nueva_desc = st.text_input("Descripción", value=tdesc or "")
                            nueva_fecha = st.date_input("Fecha de vencimiento", value=tvenc or hoy)
                            nuevo_comp = st.checkbox("Completada", value=tcomp)
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.form_submit_button("💾 Guardar", use_container_width=True):
                                    actualizar_tarea(tid, nueva_desc, nueva_fecha, nuevo_comp)
                                    st.session_state[f"editando_tarea_{num}_{materia_tarea_id}"] = False
                                    st.rerun()
                            with col2:
                                if st.form_submit_button("❌ Cancelar", use_container_width=True):
                                    st.session_state[f"editando_tarea_{num}_{materia_tarea_id}"] = False
                                    st.rerun()

            nuevo_num = (max(nums_existentes) + 1) if nums_existentes else 1
            st.markdown("---")
            with st.expander(f"➕ Agregar Tarea {nuevo_num}", expanded=False):
                key_nueva = f"tarea_nueva_key_{materia_tarea_id}"
                if key_nueva not in st.session_state:
                    st.session_state[key_nueva] = 0
                fk_tarea = st.session_state[key_nueva]
                with st.form(f"form_nueva_tarea_{materia_tarea_id}_{fk_tarea}"):
                    desc = st.text_input(
                        f"Descripción de la Tarea {nuevo_num}",
                        key=f"tarea_nueva_desc_{materia_tarea_id}_{fk_tarea}"
                    )
                    fecha = st.date_input(
                        "Fecha de vencimiento", value=hoy,
                        key=f"tarea_nueva_fecha_{materia_tarea_id}_{fk_tarea}"
                    )
                    if st.form_submit_button("💾 Guardar", use_container_width=True):
                        guardar_tarea(usuario["id"], materia_tarea_id, nuevo_num, desc, fecha)
                        st.session_state[key_nueva] += 1
                        st.rerun()

    with tab4:
        st.subheader("✅ Materias aprobadas")
        st.caption("Materias con estado **aprobada** o **promocionada** que tienen una cursada registrada.")

        aprobadas_raw = get_materias_aprobadas(usuario["id"], usuario["carrera_id"])
        todas_cursadas_ap = get_todas_cursadas(usuario["id"])
        promedios_map = get_promedios_por_materia(usuario["id"])

        # Solo las que además tienen una cursada registrada (respuesta confirmada).
        aprobadas = [a for a in aprobadas_raw if a[0] in todas_cursadas_ap]

        if not aprobadas:
            st.info("Todavía no tenés materias aprobadas o promocionadas con cursada registrada.")
        else:
            por_anio_ap = {}
            for a in aprobadas:
                mid, mnombre, manio, mestado = a
                por_anio_ap.setdefault(manio, []).append(a)

            for manio in sorted(por_anio_ap.keys()):
                st.markdown(f"#### {NOMBRES_ANIO.get(manio, f'Año {manio}')}")

                for mid, mnombre, manio_, mestado in por_anio_ap[manio]:
                    cursada = todas_cursadas_ap[mid]
                    (cid, anio_c, cuatri_c, modalidad, dias, horario, link, prof1, email_prof1, prof2,
                     email_prof2, turno, fecha_parcial1, fecha_parcial2, fecha_final,
                     numero_comision_ap, fecha_desde_comision_ap) = cursada

                    profesores = prof1 or ""
                    if prof2:
                        profesores = f"{profesores} / {prof2}" if profesores else prof2

                    promedio = promedios_map.get(mid)
                    promedio_text = f"{float(promedio):.2f}" if promedio is not None else "Sin notas cargadas"

                    profesor_html = f"<div style='color:#a8e6c1; font-size:13px; margin-top:2px;'>👨‍🏫 {profesores}</div>" if profesores else ""

                    st.markdown(
                        f"<div style='background-color:#123524; border-left:4px solid #2ecc71; "
                        f"padding:12px 18px; border-radius:8px; margin-bottom:10px;'>"
                        f"<span style='color:#2ecc71; font-weight:bold; font-size:16px;'>✅ {mnombre}</span>"
                        f"<div style='color:#ccc; font-size:13px; margin-top:4px;'>"
                        f"{cuatri_c} {anio_c} — {mestado.capitalize()}"
                        f"</div>"
                        f"{profesor_html}"
                        f"<div style='color:#80ffaa; font-weight:bold; font-size:15px; margin-top:6px;'>"
                        f"📊 Promedio: {promedio_text}</div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )

            st.markdown("---")
            st.caption(f"Total: {len(aprobadas)} materia(s) aprobada(s)/promocionada(s) con cursada registrada.")
