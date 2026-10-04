# evaluaciones.py - 04.10.2026

import streamlit as st
import psycopg
from db import get_conn, get_home_data_completo
# Cachés de cursadas.py que muestran notas (04/10/2026). cursadas.py no
# importa evaluaciones.py, así que no hay importación circular.
from pages.cursadas import get_cursadas_tab_data, get_promedios_por_materia
from datetime import date
from utils import NOMBRES_ANIO

TIPOS = ["Parcial", "Trabajo Práctico", "Recuperatorio", "Reincorporatorio", "Final"]

# ─── Parciales por número (03/10/2026) ─────────────────────────────────────
# Cada parcial lleva un número (1 o 2) en la columna evaluaciones.numero.
# Solo puede haber una nota por número, por alumno y materia: para cambiarla
# se usa Editar o Borrar. Los demás tipos no usan número.
NOMBRES_PARCIAL = {1: "1er Parcial", 2: "2do Parcial"}

def _nombre_parcial(numero):
    return NOMBRES_PARCIAL.get(numero, "Parcial sin número")

# ─── Promedios separados (29/09/2026) ──────────────────────────────────────
# Antes había un "Promedio general" que mezclaba todas las notas de la
# materia. Ahora son tres promedios independientes, que nunca se juntan:
# Trabajos Prácticos, Parciales y Recuperatorios. Finales y
# Reincorporatorios quedan fuera de los tres. No hace falta ningún cambio
# en la base: se calcula en memoria con las evaluaciones que ya se traen.
GRUPOS_PROMEDIO = [
    ("Trabajo Práctico", "TP"),
    ("Parcial", "Parciales"),
    ("Recuperatorio", "Recuperatorios"),
]

def calcular_promedios_por_grupo(evaluaciones):
    """
    Devuelve {tipo: promedio o None} para cada tipo de GRUPOS_PROMEDIO.
    Solo cuenta notas cargadas (nota no nula). None si no hay ninguna.
    """
    resultado = {}
    for tipo, _etiqueta in GRUPOS_PROMEDIO:
        notas = [float(e[3]) for e in evaluaciones if e[1] == tipo and e[3] is not None]
        resultado[tipo] = (sum(notas) / len(notas)) if notas else None
    return resultado

@st.cache_data(ttl=60)
def get_todas_materias(carrera_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, anio, final_obligatorio
                FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, nombre;
            """, (carrera_id,))
            return cur.fetchall()

@st.cache_data(ttl=60)
def get_evaluaciones(usuario_id, materia_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, tipo, descripcion, nota, fecha, aprobado, numero
                FROM evaluaciones
                WHERE usuario_id = %s AND materia_id = %s
                ORDER BY fecha ASC NULLS LAST, tipo;
            """, (usuario_id, materia_id))
            return cur.fetchall()

def agregar_evaluacion(usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado, numero=None):
    """
    Devuelve (ok: bool, mensaje: str). `numero` solo se usa para parciales
    (1 o 2). Si el índice único de la base rechaza un parcial repetido
    (por ejemplo, dos pestañas guardando a la vez), devuelve ok=False.
    """
    # Redondeo defensivo a 2 decimales: la columna ya es NUMERIC(4,2), pero
    # normalizamos acá también para que la nota que se usa en cálculos en
    # memoria (promedios, etc.) coincida siempre con la que quedó guardada.
    nota = round(float(nota), 2) if nota is not None else None
    if tipo != "Parcial":
        numero = None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO evaluaciones (usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado, numero)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """, (usuario_id, materia_id, tipo, descripcion, nota, fecha, aprobado, numero))
            conn.commit()
    except psycopg.errors.UniqueViolation:
        return False, f"Ya existe una nota del {_nombre_parcial(numero)} para esta materia."
    get_evaluaciones.clear()
    get_home_data_completo.clear()
    get_cursadas_tab_data.clear()
    get_promedios_por_materia.clear()
    return True, "Guardado."

def actualizar_evaluacion(eval_id, descripcion, nota, fecha, aprobado, numero=None, cambia_numero=False):
    """
    Devuelve (ok: bool, mensaje: str). `numero` solo se toca si
    `cambia_numero` es True (se usa para parciales).
    """
    nota = round(float(nota), 2) if nota is not None else None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if cambia_numero:
                    cur.execute("""
                        UPDATE evaluaciones
                        SET descripcion = %s, nota = %s, fecha = %s, aprobado = %s, numero = %s
                        WHERE id = %s;
                    """, (descripcion, nota, fecha, aprobado, numero, eval_id))
                else:
                    cur.execute("""
                        UPDATE evaluaciones
                        SET descripcion = %s, nota = %s, fecha = %s, aprobado = %s
                        WHERE id = %s;
                    """, (descripcion, nota, fecha, aprobado, eval_id))
            conn.commit()
    except psycopg.errors.UniqueViolation:
        return False, f"Ya existe una nota del {_nombre_parcial(numero)} para esta materia."
    get_evaluaciones.clear()
    get_home_data_completo.clear()
    get_cursadas_tab_data.clear()
    get_promedios_por_materia.clear()
    return True, "Evaluación actualizada."

def eliminar_evaluacion(eval_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM evaluaciones WHERE id = %s;", (eval_id,))
        conn.commit()
    get_evaluaciones.clear()
    get_home_data_completo.clear()
    get_cursadas_tab_data.clear()
    get_promedios_por_materia.clear()

def mostrar_promedios_grupos(evaluaciones):
    """
    Banner con los tres promedios independientes (TP, Parciales,
    Recuperatorios). Si un grupo todavía no tiene notas, muestra "—".
    Si ninguno tiene notas, no muestra nada.
    """
    promedios = calcular_promedios_por_grupo(evaluaciones)
    if all(p is None for p in promedios.values()):
        return

    bloques = ""
    for tipo, etiqueta in GRUPOS_PROMEDIO:
        p = promedios[tipo]
        if p is None:
            texto, color = "—", "#888888"
        else:
            texto, color = f"{p:.2f}", ("#2ecc71" if p >= 6 else "#e74c3c")
        bloques += (
            f"<div style='text-align:center; flex:1;'>"
            f"<div style='color:#ccc; font-size:13px;'>{etiqueta}</div>"
            f"<div style='color:{color}; font-size:26px; font-weight:bold;'>{texto}</div>"
            f"</div>"
        )

    st.markdown(
        f"<div style='background-color:#1E1E2E; padding:12px 20px; border-radius:10px; "
        f"display:flex; justify-content:space-between; align-items:center; gap:8px; "
        f"margin-bottom:15px;'>{bloques}</div>",
        unsafe_allow_html=True
    )

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return
    st.title("📝 Notas y Evaluaciones")

    todas = get_todas_materias(usuario["carrera_id"])
    opciones = {f"{NOMBRES_ANIO.get(m[2], '')} — {m[1]}": (m[0], m[3]) for m in todas}

    opciones_lista = ["Elegí una materia"] + list(opciones.keys())
    materia_label = st.selectbox("Seleccioná una materia", opciones_lista, index=0)

    if materia_label == "Elegí una materia":
        st.info("Seleccioná una materia para ver sus notas.")
        return

    materia_id, final_obligatorio = opciones[materia_label]

    st.markdown("---")

    evaluaciones = get_evaluaciones(usuario["id"], materia_id)

    mostrar_promedios_grupos(evaluaciones)

    tabs = st.tabs(["📋 Parciales", "📄 Trabajos Prácticos", "🔄 Recuperatorios", "🔁 Reincorporatorios", "🎓 Final"])
    tipos_tab = ["Parcial", "Trabajo Práctico", "Recuperatorio", "Reincorporatorio", "Final"]

    for tab, tipo in zip(tabs, tipos_tab):
        with tab:
            evals_tipo = [e for e in evaluaciones if e[1] == tipo]
            if tipo == "Parcial":
                # 1er y 2do primero; los que no tienen número, al final.
                evals_tipo.sort(key=lambda e: (e[6] is None, e[6] or 0))
                numeros_ocupados = {e[6]: e[0] for e in evals_tipo if e[6] is not None}
                sin_numero = [e for e in evals_tipo if e[6] is None]

            if evals_tipo:
                notas_tipo = [e[3] for e in evals_tipo if e[3] is not None]
                if notas_tipo:
                    prom_tipo = sum(notas_tipo) / len(notas_tipo)
                    st.markdown(f"**Promedio {tipo}:** `{prom_tipo:.2f}`")

                for e in evals_tipo:
                    eid, etipo, edesc, enota, efecha, eaprobado, enumero = e
                    key_edit = f"editando_eval_{eid}"

                    if st.session_state.get(key_edit):
                        # ── Formulario de edición inline ──────────────────
                        with st.form(f"form_edit_eval_{eid}"):
                            titulo_edit = _nombre_parcial(enumero) if tipo == "Parcial" else (edesc or tipo)
                            st.markdown(f"**✏️ Editando: {titulo_edit}**")
                            nuevo_numero = enumero
                            if tipo == "Parcial":
                                opciones_num = [1, 2] if enumero is not None else [None, 1, 2]
                                nuevo_numero = st.selectbox(
                                    "¿Qué parcial es?",
                                    opciones_num,
                                    index=opciones_num.index(enumero),
                                    format_func=lambda n: NOMBRES_PARCIAL.get(n, "Sin asignar"),
                                    key=f"numero_{eid}"
                                )
                            col1, col2 = st.columns(2)
                            with col1:
                                nueva_desc = st.text_input(
                                    "Descripción",
                                    value=edesc or "",
                                    key=f"desc_{eid}"
                                )
                                nueva_nota = st.number_input(
                                    "Nota",
                                    min_value=0.0, max_value=10.0, step=0.01, format="%.2f",
                                    value=float(enota) if enota is not None else 0.0,
                                    key=f"nota_{eid}"
                                )
                            with col2:
                                nueva_fecha = st.date_input(
                                    "Fecha",
                                    value=efecha if efecha else date.today(),
                                    key=f"fecha_{eid}"
                                )
                                nuevo_aprobado = st.checkbox(
                                    "¿Aprobado?",
                                    value=bool(eaprobado),
                                    key=f"aprobado_{eid}"
                                )
                            col_g, col_c = st.columns(2)
                            with col_g:
                                guardar = st.form_submit_button("💾 Guardar", use_container_width=True)
                            with col_c:
                                cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)

                        if guardar:
                            ocupado_por = numeros_ocupados.get(nuevo_numero) if tipo == "Parcial" else None
                            if tipo == "Parcial" and nuevo_numero is not None and ocupado_por not in (None, eid):
                                st.warning(
                                    f"⚠️ Ya existe una nota del {_nombre_parcial(nuevo_numero)} en esta materia. "
                                    "Editala o borrala desde la lista; no puede haber dos del mismo parcial."
                                )
                            else:
                                ok_ev, msg_ev = actualizar_evaluacion(
                                    eid, nueva_desc, nueva_nota, nueva_fecha, nuevo_aprobado,
                                    numero=nuevo_numero, cambia_numero=(tipo == "Parcial")
                                )
                                if ok_ev:
                                    st.session_state[key_edit] = False
                                    st.success(msg_ev)
                                    st.rerun()
                                else:
                                    st.warning(f"⚠️ {msg_ev}")
                        if cancelar:
                            st.session_state[key_edit] = False
                            st.rerun()

                    else:
                        # ── Vista normal ──────────────────────────────────
                        col1, col2, col3 = st.columns([4, 1, 1])
                        with col1:
                            if tipo == "Parcial":
                                desc_text = _nombre_parcial(enumero) + (f" ({edesc})" if edesc else "")
                            else:
                                desc_text = edesc if edesc else tipo
                            nota_text = f"**{enota:.2f}**" if enota is not None else "Sin nota"
                            fecha_text = str(efecha) if efecha else "Sin fecha"
                            aprobado_icon = "✅" if eaprobado else "❌"
                            st.markdown(f"{aprobado_icon} {desc_text} — Nota: {nota_text} — Fecha: {fecha_text}")
                        with col2:
                            if st.button("✏️ Editar", key=f"btn_edit_{eid}", use_container_width=True):
                                st.session_state[key_edit] = True
                                st.rerun()
                        with col3:
                            key_confirmar = f"confirmar_del_{eid}"
                            if st.session_state.get(key_confirmar):
                                col_si, col_no = st.columns(2)
                                with col_si:
                                    if st.button("✅", key=f"si_del_{eid}", use_container_width=True):
                                        eliminar_evaluacion(eid)
                                        st.session_state[key_confirmar] = False
                                        st.success("Evaluación eliminada.")
                                        st.rerun()
                                with col_no:
                                    if st.button("❌", key=f"no_del_{eid}", use_container_width=True):
                                        st.session_state[key_confirmar] = False
                                        st.rerun()
                            else:
                                if st.button("🗑️", key=f"del_eval_{eid}", use_container_width=True):
                                    st.session_state[key_confirmar] = True
                                    st.rerun()

            else:
                st.info(f"No hay {tipo.lower()}s cargados.")

            if tipo == "Parcial" and sin_numero:
                st.caption(
                    f"ℹ️ Tenés {len(sin_numero)} parcial(es) sin número. Usá ✏️ Editar para indicar "
                    "si es el 1er o el 2do."
                )

            if tipo == "Parcial" and len(numeros_ocupados) >= 2:
                st.warning(
                    "⚠️ Ya existe una nota del 1er Parcial y otra del 2do Parcial en esta materia. "
                    "Para cambiarlas, usá ✏️ Editar o 🗑️ Borrar."
                )
                continue

            with st.expander(f"➕ Agregar {tipo}"):
                if tipo == "Parcial" and numeros_ocupados:
                    ya = ", ".join(NOMBRES_PARCIAL[n] for n in sorted(numeros_ocupados))
                    st.caption(f"Ya cargado: {ya}.")
                # Contador de reseteo (ítem "formularios deben volver
                # limpios", 02/08/2026): se incrementa después de guardar
                # para que el form se recree con keys nuevas y no quede con
                # la descripción/nota recién tipeadas en pantalla.
                eval_key = f"eval_form_key_{tipo}_{materia_id}"
                if eval_key not in st.session_state:
                    st.session_state[eval_key] = 0
                fk = st.session_state[eval_key]

                with st.form(f"form_{tipo.replace(' ', '_')}_{materia_id}_{fk}"):
                    numero_nuevo = None
                    if tipo == "Parcial":
                        numeros_libres = [n for n in (1, 2) if n not in numeros_ocupados]
                        numero_nuevo = st.selectbox(
                            "¿Qué parcial es?", numeros_libres,
                            format_func=lambda n: NOMBRES_PARCIAL[n],
                            key=f"eval_numero_{materia_id}_{fk}"
                        )
                    descripcion = st.text_input(
                        "Descripción (ej: Parcial 1, TP N°2)", key=f"eval_desc_{tipo}_{materia_id}_{fk}"
                    )
                    nota = st.number_input(
                        "Nota", min_value=0.0, max_value=10.0, step=0.01, format="%.2f", value=0.0,
                        key=f"eval_nota_{tipo}_{materia_id}_{fk}"
                    )
                    fecha = st.date_input("Fecha", value=date.today(), key=f"eval_fecha_{tipo}_{materia_id}_{fk}")
                    aprobado = st.checkbox(
                        "¿Aprobado? (marcá si la nota es ≥ 6)", value=False,
                        key=f"eval_aprobado_{tipo}_{materia_id}_{fk}"
                    )
                    submit = st.form_submit_button("💾 Guardar", use_container_width=True)
                if submit:
                    if tipo == "Parcial" and numero_nuevo in numeros_ocupados:
                        st.warning(
                            f"⚠️ Ya existe una nota del {_nombre_parcial(numero_nuevo)} en esta materia. "
                            "Editala o borrala desde la lista."
                        )
                    else:
                        ok_ev, msg_ev = agregar_evaluacion(
                            usuario["id"], materia_id, tipo, descripcion, nota, fecha, aprobado,
                            numero=numero_nuevo
                        )
                        if ok_ev:
                            st.session_state[eval_key] += 1
                            st.success(f"{tipo} guardado.")
                            st.rerun()
                        else:
                            st.warning(f"⚠️ {msg_ev}")


