import streamlit as st
from db import (
    get_conn, get_feriados, agregar_feriado, borrar_feriado,
    get_periodos_comision, get_home_data_completo,
)
from datetime import datetime, date, timedelta
from utils import (
    DIA_INDEX, contar_clases_en_rango, contar_clases_multi_periodo,
    clasificar_asistencia, determinar_estado_cuatrimestre,
)

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
    get_home_data_completo.clear()

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

def calcular_estado_cursada(cuatrimestre):
    mes = datetime.now().month
    if cuatrimestre == "Anual":
        return "En curso" if 3 <= mes <= 11 else "Finalizada"
    elif cuatrimestre == "1° Cuatrimestre":
        return "En curso" if 3 <= mes <= 7 else "Finalizada"
    elif cuatrimestre == "2° Cuatrimestre":
        return "En curso" if 8 <= mes <= 12 else "Finalizada"
    return "En curso"

# ─── Alertas de vencimiento ────────────────────────────────────────────────────

def mostrar_alertas_vencimiento(tareas):
    """Muestra banners de alerta para tareas vencidas o próximas a vencer (≤ 3 días)."""
    if not tareas:
        return

    hoy = date.today()
    limite = hoy + timedelta(days=3)

    vencidas   = [(t) for t in tareas if t[2] and t[2] < hoy]
    proximas   = [(t) for t in tareas if t[2] and hoy <= t[2] <= limite]

    if not vencidas and not proximas:
        return

    if vencidas:
        with st.container():
            msgs = []
            for t in vencidas:
                tnum, tdesc, tvenc, mnom = t
                msgs.append(f"**Tarea {tnum}** de *{mnom}* — venció el {tvenc.strftime('%d/%m')}")
            st.error(
                "🔴 **Tareas vencidas:**\n\n" + "\n\n".join(f"• {m}" for m in msgs),
                icon="⚠️"
            )

    if proximas:
        with st.container():
            msgs = []
            for t in proximas:
                tnum, tdesc, tvenc, mnom = t
                dias_restantes = (tvenc - hoy).days
                if dias_restantes == 0:
                    cuando = "**hoy**"
                elif dias_restantes == 1:
                    cuando = "**mañana**"
                else:
                    cuando = f"en **{dias_restantes} días** ({tvenc.strftime('%d/%m')})"
                msgs.append(f"**Tarea {tnum}** de *{mnom}* — vence {cuando}")
            st.warning(
                "⏰ **Tareas por vencer:**\n\n" + "\n\n".join(f"• {m}" for m in msgs),
                icon="📅"
            )

# ─── Alerta de asistencia ──────────────────────────────────────────────────────
# Banner al tope de Home (mismo patrón que mostrar_alertas_vencimiento) que
# lista TODAS las materias cursando con % de asistencia por debajo de 85%,
# usando el mismo umbral que clasificar_asistencia() en el resto del sistema.
# Se separa en dos niveles: 🚨 riesgo real de quedar libre (<75%) y
# ⚠️ acercándose al límite (75%-85%), para que el alumno vea de un vistazo
# cuántas faltas usó, cuántas tiene permitidas, y cuántas le quedan
# disponibles antes de superar el 25% de inasistencias permitido.
#
# El cálculo suma clases por período de comisión (ítem #6, 02/08/2026): si
# el alumno cambió de comisión a mitad de cuatrimestre, cada tramo cuenta
# sus propios días de cursada dentro de sus propias fechas, en vez de
# aplicar los días actuales a todo el rango.

def mostrar_alerta_asistencia(materias_cursando, todas_configs, faltas_map, feriados_set):
    if not materias_cursando:
        return

    en_riesgo = []
    acercandose = []

    for m in materias_cursando:
        (mnombre, manio, mcuatri, manio_cursada, mprofesor,
         mdias, mhorario, mmodalidad, mid, total_notas,
         promedio, aprobadas_ev, desaprobadas_ev, detalle_notas,
         cursada_id, numero_comision, fecha_desde_comision) = m

        config = todas_configs.get((manio_cursada, mcuatri))
        if not config:
            continue

        fecha_ini, fecha_fin = config
        if cursada_id and fecha_desde_comision:
            periodos = get_periodos_comision(cursada_id, mdias, fecha_desde_comision)
            clases_totales = contar_clases_multi_periodo(periodos, fecha_ini, fecha_fin, feriados_set)
        else:
            clases_totales = contar_clases_en_rango(mdias, fecha_ini, fecha_fin, feriados_set)
        if clases_totales == 0:
            continue

        faltas_mat = faltas_map.get(mid, 0)
        porcentaje = round(((clases_totales - faltas_mat) / clases_totales) * 100, 1)
        max_faltas = int(clases_totales * 0.25)
        restantes = max(max_faltas - faltas_mat, 0)

        if porcentaje >= 85:
            continue

        info = (mnombre, porcentaje, faltas_mat, max_faltas, restantes)
        if porcentaje < 75:
            en_riesgo.append(info)
        else:
            acercandose.append(info)

    if not en_riesgo and not acercandose:
        return

    if en_riesgo:
        with st.container():
            msgs = []
            for mnombre, porcentaje, faltas_mat, max_faltas, restantes in en_riesgo:
                msgs.append(
                    f"**{mnombre}** — {porcentaje}% de asistencia · {faltas_mat}/{max_faltas} faltas usadas · "
                    f"podés faltar **{restantes}** clase(s) más"
                )
            st.error(
                "🚨 **Riesgo de quedar libre por inasistencias:**\n\n" + "\n\n".join(f"• {m}" for m in msgs),
                icon="🚨"
            )

    if acercandose:
        with st.container():
            msgs = []
            for mnombre, porcentaje, faltas_mat, max_faltas, restantes in acercandose:
                msgs.append(
                    f"**{mnombre}** — {porcentaje}% de asistencia · {faltas_mat}/{max_faltas} faltas usadas · "
                    f"podés faltar **{restantes}** clase(s) más"
                )
            st.warning(
                "⚠️ **Te estás acercando al límite de faltas:**\n\n" + "\n\n".join(f"• {m}" for m in msgs),
                icon="⚠️"
            )

# ─── Panel de configuración de fechas ─────────────────────────────────────────

def mostrar_config_fechas(usuario_id, anio_actual, cuatrimestre_actual, todas_configs):
    config_actual = todas_configs.get((anio_actual, cuatrimestre_actual))

    # Contador de reseteo (ítem "formularios deben volver limpios", 02/08/2026):
    # se incrementa después de guardar para que el form se recree con keys
    # nuevas y no quede con los valores recién tipeados pegados en pantalla.
    if "config_cuatri_form_key" not in st.session_state:
        st.session_state.config_cuatri_form_key = 0

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

        fk = st.session_state.config_cuatri_form_key
        with st.form(f"form_config_cuatrimestre_{fk}"):
            col1, col2, col3 = st.columns(3)
            with col1:
                anio_cfg = st.number_input("Año", min_value=2020, max_value=2040,
                                           value=anio_actual, key=f"cfg_anio_{fk}")
            with col2:
                fecha_ini = st.date_input("Fecha de inicio",
                                          value=config_existente[0] if config_existente else def_ini,
                                          key=f"cfg_ini_{fk}")
            with col3:
                fecha_fin = st.date_input("Fecha de fin",
                                          value=config_existente[1] if config_existente else def_fin,
                                          key=f"cfg_fin_{fk}")

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
                st.session_state.config_cuatri_form_key += 1
                st.success(f"✅ Fechas guardadas: {fecha_ini.strftime('%d/%m/%Y')} → {fecha_fin.strftime('%d/%m/%Y')}")
                st.rerun()

        if todas_configs:
            st.markdown("**Configuraciones guardadas:**")
            for (anio_c, cuatri_c), (fi, ff) in sorted(todas_configs.items(), reverse=True):
                key_edit_cfg = f"editando_config_{anio_c}_{cuatri_c}"

                if st.session_state.get(key_edit_cfg):
                    # ── Formulario de edición inline ──────────────────
                    with st.form(f"form_edit_config_{anio_c}_{cuatri_c}"):
                        st.markdown(f"**✏️ Editando: {cuatri_c} {anio_c}**")
                        col_e1, col_e2 = st.columns(2)
                        with col_e1:
                            nueva_fi = st.date_input(
                                "Fecha de inicio", value=fi, key=f"edit_fi_{anio_c}_{cuatri_c}"
                            )
                        with col_e2:
                            nueva_ff = st.date_input(
                                "Fecha de fin", value=ff, key=f"edit_ff_{anio_c}_{cuatri_c}"
                            )
                        col_ge, col_ce = st.columns(2)
                        with col_ge:
                            guardar_cfg_edit = st.form_submit_button("💾 Guardar", use_container_width=True)
                        with col_ce:
                            cancelar_cfg_edit = st.form_submit_button("❌ Cancelar", use_container_width=True)

                    if guardar_cfg_edit:
                        if nueva_ff <= nueva_fi:
                            st.error("La fecha de fin debe ser posterior a la de inicio.")
                        else:
                            guardar_config_cuatrimestre(usuario_id, anio_c, cuatri_c, nueva_fi, nueva_ff)
                            st.session_state[key_edit_cfg] = False
                            st.success(f"✅ {cuatri_c} {anio_c} actualizado: {nueva_fi.strftime('%d/%m/%Y')} → {nueva_ff.strftime('%d/%m/%Y')}")
                            st.rerun()
                    if cancelar_cfg_edit:
                        st.session_state[key_edit_cfg] = False
                        st.rerun()
                else:
                    col_cfg1, col_cfg2 = st.columns([4, 1])
                    with col_cfg1:
                        st.caption(f"📅 {cuatri_c} {anio_c}: {fi.strftime('%d/%m/%Y')} → {ff.strftime('%d/%m/%Y')}")
                    with col_cfg2:
                        if st.button("✏️ Editar", key=f"btn_edit_cfg_{anio_c}_{cuatri_c}", use_container_width=True):
                            st.session_state[key_edit_cfg] = True
                            st.rerun()

# ─── Panel de feriados / días sin clase ───────────────────────────────────────

def mostrar_config_feriados(usuario_id):
    """Permite cargar y borrar fechas que no cuentan como clase dictada
    (feriados, paros, suspensiones puntuales) al calcular la asistencia."""
    feriados = get_feriados(usuario_id)

    # Contador de reseteo (ítem "formularios deben volver limpios", 02/08/2026):
    # se incrementa después de guardar para que el form se recree con keys
    # nuevas y no quede con la fecha/descripción recién tipeadas en pantalla.
    if "feriado_form_key" not in st.session_state:
        st.session_state.feriado_form_key = 0

    with st.expander("🗓️ Feriados / días sin clase", expanded=False):
        st.caption(
            "Cargá acá las fechas que no se dictaron clase (feriados, paros, suspensiones). "
            "No se van a contar como clase al calcular tu % de asistencia."
        )

        fk = st.session_state.feriado_form_key
        with st.form(f"form_nuevo_feriado_{fk}"):
            col1, col2 = st.columns([1, 2])
            with col1:
                fecha_feriado = st.date_input("Fecha", value=date.today(), key=f"nuevo_feriado_fecha_{fk}")
            with col2:
                desc_feriado = st.text_input("Descripción (opcional)", key=f"nuevo_feriado_desc_{fk}")
            agregar = st.form_submit_button("➕ Agregar", use_container_width=True)

        if agregar:
            agregar_feriado(usuario_id, fecha_feriado, desc_feriado.strip() or None)
            st.session_state.feriado_form_key += 1
            st.success("Feriado agregado.")
            st.rerun()

        if feriados:
            st.markdown("**Feriados cargados:**")
            for fid, ffecha, fdesc in feriados:
                key_edit_fer = f"editando_feriado_{fid}"

                if st.session_state.get(key_edit_fer):
                    # ── Formulario de edición inline ──────────────────
                    with st.form(f"form_edit_feriado_{fid}"):
                        col_ef1, col_ef2 = st.columns([1, 2])
                        with col_ef1:
                            nueva_fecha_fer = st.date_input(
                                "Fecha", value=ffecha, key=f"edit_fecha_feriado_{fid}"
                            )
                        with col_ef2:
                            nueva_desc_fer = st.text_input(
                                "Descripción (opcional)", value=fdesc or "", key=f"edit_desc_feriado_{fid}"
                            )
                        col_gf, col_cf = st.columns(2)
                        with col_gf:
                            guardar_fer_edit = st.form_submit_button("💾 Guardar", use_container_width=True)
                        with col_cf:
                            cancelar_fer_edit = st.form_submit_button("❌ Cancelar", use_container_width=True)

                    if guardar_fer_edit:
                        desc_final = nueva_desc_fer.strip() or None
                        if nueva_fecha_fer != ffecha:
                            # La fecha es parte de la clave única: borrar y recrear.
                            borrar_feriado(fid)
                        agregar_feriado(usuario_id, nueva_fecha_fer, desc_final)
                        st.session_state[key_edit_fer] = False
                        st.success("Feriado actualizado.")
                        st.rerun()
                    if cancelar_fer_edit:
                        st.session_state[key_edit_fer] = False
                        st.rerun()
                else:
                    col_f1, col_f2, col_f3 = st.columns([4, 1, 1])
                    with col_f1:
                        desc_text = f" — {fdesc}" if fdesc else ""
                        st.markdown(f"📌 {ffecha.strftime('%d/%m/%Y')}{desc_text}")
                    with col_f2:
                        if st.button("✏️", key=f"edit_feriado_{fid}", use_container_width=True):
                            st.session_state[key_edit_fer] = True
                            st.rerun()
                    with col_f3:
                        if st.button("🗑️", key=f"del_feriado_{fid}", use_container_width=True):
                            borrar_feriado(fid)
                            st.rerun()
        else:
            st.caption("No cargaste feriados todavía.")

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

def mostrar_chip_asistencia(mdias, manio_cursada, mcuatri, mid, todas_configs, faltas_map, feriados_set=None,
                             cursada_id=None, fecha_desde_comision=None):
    config_asist = todas_configs.get((manio_cursada, mcuatri))
    if not config_asist:
        st.caption(
            f"⚙️ No encontré fechas configuradas para **{mcuatri} {manio_cursada}** para calcular asistencia. "
            f"Configuralas arriba en '⚙️ Configurar fechas del cuatrimestre'."
        )
        return

    fecha_ini_a, fecha_fin_a = config_asist
    if cursada_id and fecha_desde_comision:
        periodos = get_periodos_comision(cursada_id, mdias, fecha_desde_comision)
        clases_totales = contar_clases_multi_periodo(periodos, fecha_ini_a, fecha_fin_a, feriados_set)
    else:
        clases_totales = contar_clases_en_rango(mdias, fecha_ini_a, fecha_fin_a, feriados_set)
    if clases_totales == 0:
        st.caption(
            f"📅 No pude calcular la asistencia. Días cargados: **'{mdias or '—'}'** · "
            f"Rango: {fecha_ini_a.strftime('%d/%m/%Y')} → {fecha_fin_a.strftime('%d/%m/%Y')}. "
            f"Revisá los días de cursada en Cursadas → Editar."
        )
        return

    faltas_mat = faltas_map.get(mid, 0)
    porcentaje_asist = round(((clases_totales - faltas_mat) / clases_totales) * 100, 1)
    max_faltas = int(clases_totales * 0.25)
    restantes = max(max_faltas - faltas_mat, 0)
    color_a, negrita_a = clasificar_asistencia(porcentaje_asist)
    peso_a = "bold" if negrita_a else "normal"

    st.markdown(
        f"<div style='margin-top:6px; font-size:12px;'>"
        f"📅 Asistencia: <span style='color:{color_a}; font-weight:{peso_a};'>{porcentaje_asist}%</span>"
        f" — Podés faltar <span style='color:{color_a}; font-weight:{peso_a};'>{restantes}</span> clase(s) más"
        f" ({faltas_mat}/{max_faltas} usadas)"
        f"</div>",
        unsafe_allow_html=True
    )

    if porcentaje_asist < 85:
        alerta_txt = "🚨 ¡Riesgo de quedar libre por inasistencias!" if porcentaje_asist < 75 else "⚠️ Te estás acercando al límite de faltas."
        st.markdown(
            f"<div style='color:{color_a}; font-weight:bold; font-size:12px; margin-top:2px;'>{alerta_txt}</div>",
            unsafe_allow_html=True
        )

# ─── Vista principal ───────────────────────────────────────────────────────────

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("🧠 PsicoNexo")
    st.markdown(f"### Bienvenido/a, {usuario['nombre'].split()[0]} 👋")

    mes_actual = datetime.now().month
    anio_actual = datetime.now().year if mes_actual >= 3 else datetime.now().year - 1

    # ── Batch único de toda la pantalla (ítem prioridad alta, latencia de
    # carga, 12/08/2026): antes eran 6 conexiones fijas al pool (stats,
    # configs, materias cursando + notas, faltas, feriados, tareas y
    # clases de hoy). Ahora es 1 sola — ver get_home_data_completo en db.py.
    (total, aprobadas, cursando, regulares, desaprobadas, avance, todas_configs,
     cuatrimestre_para_query, header_cuatrimestre, en_transicion,
     materias_cursando, faltas_map, feriados_set, tareas, clases_hoy) = get_home_data_completo(
        usuario["id"], usuario["carrera_id"], anio_actual
    )

    # Tareas y asistencia — alertas arriba del todo
    mostrar_alertas_vencimiento(tareas)
    mostrar_alerta_asistencia(materias_cursando, todas_configs, faltas_map, feriados_set)

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

    mostrar_config_fechas(usuario["id"], anio_actual, cuatrimestre_para_query, todas_configs)
    mostrar_config_feriados(usuario["id"])

    st.markdown("---")

    if en_transicion:
        st.markdown("### 📚 Cursando")
        st.info(f"⏸️ **{header_cuatrimestre}**")
    else:
        st.markdown(f"### 📚 Cursando — {header_cuatrimestre}")

    if not materias_cursando:
        st.info("No tenés materias registradas para este cuatrimestre.")
    else:
        for m in materias_cursando:
            (mnombre, manio, mcuatri, manio_cursada, mprofesor,
             mdias, mhorario, mmodalidad, mid, total_notas,
             promedio, aprobadas_ev, desaprobadas_ev, detalle_notas,
             cursada_id, numero_comision, fecha_desde_comision) = m

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
                    if numero_comision:
                        st.caption(f"🔀 {numero_comision}")
                with col_b:
                    st.markdown(
                        f"<div style='text-align:right;'>"
                        f"<span style='background:{badge_color}; color:white; "
                        f"padding:3px 10px; border-radius:12px; font-size:12px;'>"
                        f"{estado}</span></div>",
                        unsafe_allow_html=True
                    )

                mostrar_barra_cuatrimestre(mcuatri, manio_cursada, todas_configs)
                mostrar_chip_asistencia(
                    mdias, manio_cursada, mcuatri, mid, todas_configs, faltas_map, feriados_set,
                    cursada_id, fecha_desde_comision
                )

                st.markdown("**Notas cargadas:**")
                if total_notas and int(total_notas) > 0:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        color_prom = "#2ecc71" if promedio and promedio >= 6 else "#e74c3c"
                        promedio_text = f"{float(promedio):.2f}" if promedio is not None else "—"
                        st.markdown(
                            f"<div style='text-align:center;'>"
                            f"<div style='font-size:11px; color:#aaa;'>Promedio</div>"
                            f"<div style='font-size:24px; font-weight:bold; color:{color_prom};'>"
                            f"{promedio_text}</div></div>",
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
        if tareas:
            hoy = date.today()
            for t in tareas:
                tnum, tdesc, tvenc, mnom = t
                vencida = tvenc and tvenc < hoy
                proxima = tvenc and hoy <= tvenc <= hoy + timedelta(days=3)
                if vencida:
                    icono = "🔴"
                elif proxima:
                    icono = "⚠️"
                else:
                    icono = "⏳"
                venc_text = str(tvenc) if tvenc else "Sin fecha"
                st.markdown(f"{icono} **Tarea {tnum}** — {mnom}")
                st.caption(f"{tdesc or 'Sin descripción'} — Vence: {venc_text}")
        else:
            st.info("No tenés tareas pendientes.")
