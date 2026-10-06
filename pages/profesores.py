# profesores.py - 06.10.2026

import re
import unicodedata
import streamlit as st
from db import get_conn
from utils import NOMBRES_ANIO

# ─── Valoraciones (categoría "Neutral" agregada 29/09/2026) ────────────────
# La columna opiniones_profesores.valoracion (y la de recomendaciones_terceros)
# es texto libre, así que sumar "Neutral" no necesita migrar nada: las
# opiniones ya cargadas quedan exactamente como estaban.
VALORACIONES = ["Recomendado", "Neutral", "No recomendado"]

# Ícono de cada opinión individual (la que se ve dentro de cada profesor).
ICONOS_VALORACION = {"Recomendado": "✅", "Neutral": "🤷", "No recomendado": "❌"}

# ─── Regla de reputación por profesor (29/09/2026) ──────────────────────────
# Una sola función para las tres tabs (Mis opiniones, Recomendados por
# terceros y Positivos/Negativos/Neutral), para que los íconos nunca se
# contradigan entre sí.
#
# - Las opiniones "Neutral" no suman ni a favor ni en contra.
# - Más "Recomendado" que "No recomendado"  → 👍
# - Más "No recomendado" que "Recomendado"  → 👎
# - Empate, o solo opiniones neutrales      → 🤷
#
# Cambio de comportamiento respecto de antes: un empate entre positivas y
# negativas contaba como 👍; ahora cuenta como 🤷.
def _categoria_reputacion(positivas, negativas):
    if positivas > negativas:
        return "positivo"
    if negativas > positivas:
        return "negativo"
    return "neutral"

ICONOS_REPUTACION = {"positivo": "👍", "negativo": "👎", "neutral": "🤷"}

def _icono_reputacion(valoraciones):
    """Recibe la lista de valoraciones (texto) de un profesor y devuelve 👍, 👎 o 🤷."""
    positivas = sum(1 for v in valoraciones if v == "Recomendado")
    negativas = sum(1 for v in valoraciones if v == "No recomendado")
    return ICONOS_REPUTACION[_categoria_reputacion(positivas, negativas)]

# ─── Batch único de la pantalla (ítem prioridad alta, "Seguir optimizando
# latencia", 14/08/2026) ────────────────────────────────────────────────────
# Antes: 3 conexiones fijas al pool en cada carga (get_todas_materias,
# get_opiniones, get_recomendaciones_terceros). Con st.tabs las tres se
# disparan igual en cada rerun aunque el alumno esté mirando una sola tab
# (Streamlit ejecuta el contenido de las 3 tabs siempre, no solo la visible
# — eso es una limitación del componente en sí, no se resuelve batcheando).
# Lo que sí se puede evitar es que cada una de las 3 queries abra su propia
# conexión al pool: se consolidan acá en una sola conexión, mismo criterio
# que el resto del proyecto (Home, Plan de Estudios, tab "Cursando
# actualmente", Estadísticas) — en Neon serverless el costo real es el
# round-trip de adquirir la conexión, no las queries en sí.
#
# ── Opiniones propias: hasta 3 materias por opinión (ítem pedido
# 27/09/2026) ────────────────────────────────────────────────────────────
# Antes cada fila de opiniones_profesores era una sola materia de un
# profesor. Ahora una misma opinión (una sola valoración/observación) puede
# cubrir hasta 3 materias del mismo profesor, igual que ya funciona
# "Recomendaciones de terceros" con hasta 5. Esto necesitó una tabla puente
# nueva (opiniones_profesores_materias, ver db.py) con migración automática
# de las opiniones viejas. El formato de la tupla `opiniones` cambió: ahora
# `materia_ids`, `materia_nombres` y `materia_anios` son LISTAS (una por
# cada materia de esa opinión), no un solo valor — formato nuevo:
# (id, profesor, valoracion, observaciones, materia_ids, materia_nombres,
# materia_anios). Cualquier código que compare op[1]/op[2] (profesor/
# valoracion) sigue funcionando igual; lo que cambió es el acceso a la
# materia (antes op[4]/op[5]/op[6] eran valores sueltos, ahora son listas).

@st.cache_data(ttl=60)
def get_profesores_data_completo(usuario_id, carrera_id):
    """
    Devuelve, en una sola conexión, todo lo que necesita pages/profesores.py:
    (todas_materias, opiniones, recomendaciones_terceros)
    - todas_materias: [(id, nombre, anio), ...]
    - opiniones: [(id, profesor, valoracion, observaciones, materia_ids,
      materia_nombres, materia_anios), ...] — las tres últimas son listas,
      porque una opinión puede cubrir hasta 3 materias (27/09/2026)
    - recomendaciones_terceros: [(id, apellido, nombre, valoracion, observaciones,
      cargado_por, cargado_por_nombre, materia_ids, materia_nombres, materia_anios), ...]
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # ── Todas las materias de la carrera (para los selectores) ───
            # Versión 7 (06/10/2026): una materia que ya no está vigente en el
            # plan solo aparece si el alumno ya tiene en ella un estado distinto
            # de pendiente, o si ya la usó en una opinión propia o en una
            # recomendación que cargó él (así, al editar, no se pierde esa
            # materia del selector).
            cur.execute("""
                SELECT m.id, m.nombre, m.anio FROM materias m
                WHERE m.carrera_id = %s
                  AND (m.vigente
                       OR EXISTS (SELECT 1 FROM alumno_materias x
                                  WHERE x.materia_id = m.id AND x.usuario_id = %s
                                    AND x.estado <> 'pendiente')
                       OR EXISTS (SELECT 1 FROM opiniones_profesores_materias opm
                                  JOIN opiniones_profesores op ON op.id = opm.opinion_id
                                  WHERE opm.materia_id = m.id AND op.usuario_id = %s)
                       OR EXISTS (SELECT 1 FROM recomendaciones_terceros_materias rtm
                                  JOIN recomendaciones_terceros rt ON rt.id = rtm.recomendacion_id
                                  WHERE rtm.materia_id = m.id AND rt.cargado_por = %s))
                ORDER BY m.anio, m.nombre;
            """, (carrera_id, usuario_id, usuario_id, usuario_id))
            todas_materias = cur.fetchall()

            # ── Opiniones propias del alumno (privadas) ──────────────────
            cur.execute("""
                SELECT op.id, op.profesor, op.valoracion, op.observaciones,
                       ARRAY_AGG(m.id ORDER BY m.anio, m.nombre) AS materia_ids,
                       ARRAY_AGG(m.nombre ORDER BY m.anio, m.nombre) AS materia_nombres,
                       ARRAY_AGG(m.anio ORDER BY m.anio, m.nombre) AS materia_anios
                FROM opiniones_profesores op
                JOIN opiniones_profesores_materias opm ON opm.opinion_id = op.id
                JOIN materias m ON opm.materia_id = m.id
                WHERE op.usuario_id = %s
                GROUP BY op.id, op.profesor, op.valoracion, op.observaciones
                ORDER BY op.profesor;
            """, (usuario_id,))
            opiniones = cur.fetchall()

            # ── Recomendaciones de terceros (compartidas por carrera) ────
            cur.execute("""
                SELECT rt.id, rt.apellido, rt.nombre, rt.valoracion, rt.observaciones,
                       rt.cargado_por, u.nombre AS cargado_por_nombre,
                       ARRAY_AGG(m.id ORDER BY m.anio, m.nombre) AS materia_ids,
                       ARRAY_AGG(m.nombre ORDER BY m.anio, m.nombre) AS materia_nombres,
                       ARRAY_AGG(m.anio ORDER BY m.anio, m.nombre) AS materia_anios
                FROM recomendaciones_terceros rt
                JOIN recomendaciones_terceros_materias rtm ON rtm.recomendacion_id = rt.id
                JOIN materias m ON rtm.materia_id = m.id
                LEFT JOIN usuarios u ON rt.cargado_por = u.id
                WHERE m.carrera_id = %s
                GROUP BY rt.id, rt.apellido, rt.nombre, rt.valoracion, rt.observaciones,
                         rt.cargado_por, u.nombre
                ORDER BY rt.apellido, rt.nombre;
            """, (carrera_id,))
            recomendaciones_terceros = cur.fetchall()

    return todas_materias, opiniones, recomendaciones_terceros

def agregar_opinion(usuario_id, profesor, valoracion, observaciones, materia_ids):
    """
    Devuelve (ok: bool, mensaje: str). Crea una opinión y la asocia a hasta
    3 materias en la tabla puente opiniones_profesores_materias (27/09/2026).
    Mismo manejo de errores que agregar_recomendacion_tercero(): todo en una
    transacción explícita, con rollback garantizado si algo falla a mitad
    del loop de INSERTs.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    INSERT INTO opiniones_profesores (usuario_id, profesor, valoracion, observaciones)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                """, (usuario_id, profesor, valoracion, observaciones))
                opinion_id = cur.fetchone()[0]
                for materia_id in materia_ids:
                    cur.execute("""
                        INSERT INTO opiniones_profesores_materias (opinion_id, materia_id)
                        VALUES (%s, %s)
                        ON CONFLICT (opinion_id, materia_id) DO NOTHING;
                    """, (opinion_id, materia_id))
                conn.commit()
            except Exception as e:
                conn.rollback()
                return False, f"No se pudo guardar la opinión: {e}"
    get_profesores_data_completo.clear()
    return True, "Opinión guardada."

def actualizar_opinion(opinion_id, profesor, valoracion, observaciones, materia_ids):
    """
    Devuelve (ok: bool, mensaje: str). Actualiza profesor/valoración/
    observaciones y reemplaza por completo las materias asociadas (borra
    las viejas y carga las nuevas) — mismo criterio que
    actualizar_recomendacion_tercero(), con rollback garantizado si algo
    falla a mitad de camino.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    UPDATE opiniones_profesores
                    SET profesor = %s, valoracion = %s, observaciones = %s
                    WHERE id = %s;
                """, (profesor, valoracion, observaciones, opinion_id))
                cur.execute("DELETE FROM opiniones_profesores_materias WHERE opinion_id = %s;", (opinion_id,))
                for materia_id in materia_ids:
                    cur.execute("""
                        INSERT INTO opiniones_profesores_materias (opinion_id, materia_id)
                        VALUES (%s, %s)
                        ON CONFLICT (opinion_id, materia_id) DO NOTHING;
                    """, (opinion_id, materia_id))
                conn.commit()
            except Exception as e:
                conn.rollback()
                return False, f"No se pudo actualizar la opinión: {e}"
    get_profesores_data_completo.clear()
    return True, "Opinión actualizada."

def eliminar_opinion(opinion_id):
    # Las filas de opiniones_profesores_materias se borran solas por el
    # ON DELETE CASCADE de la tabla puente (ver db.py).
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM opiniones_profesores WHERE id = %s;", (opinion_id,))
        conn.commit()
    get_profesores_data_completo.clear()

# ─── Profesores recomendados por terceros ───────────────────────────────────
# A diferencia de opiniones_profesores (privada, un alumno opina de una
# materia que él mismo cursó), esta sección es COMPARTIDA entre todos los
# alumnos de la carrera: sirve para cargar profesores de los que un alumno
# se enteró por un tercero, sin haber cursado él mismo con ellos. Un mismo
# profesor puede dictar hasta 5 materias, guardadas en la tabla puente
# recomendaciones_terceros_materias. Solo quien cargó una recomendación
# puede editarla o borrarla (agregado 29/07/2026).
#
# ── Manejo de errores en operaciones multi-INSERT (ítem prioridad media,
# 26/09/2026) ────────────────────────────────────────────────────────────
# Antes, agregar_recomendacion_tercero() y actualizar_recomendacion_tercero()
# hacían un INSERT/UPDATE seguido de un loop de INSERTs sin try/except
# propio: si un materia_id resultaba inválido (o cualquier otro error de
# datos) a mitad del loop, el error se propagaba crudo a Streamlit en vez
# de mostrar un mensaje entendible. get_conn() ya cubre el caso de que Neon
# esté caído, pero no errores de datos.
#
# Ahora las dos funciones devuelven (ok: bool, mensaje: str) y envuelven
# todo el bloque en un try/except con rollback explícito — mismo patrón
# que ya usa register_user() en auth.py — así que un error a mitad de
# camino no deja una recomendación a medio cargar (sin materias asociadas,
# por ejemplo) y el alumno ve un mensaje claro en vez de un traceback.

def agregar_recomendacion_tercero(usuario_id, apellido, nombre, valoracion, observaciones, materia_ids):
    """
    Devuelve (ok: bool, mensaje: str). Ver comentario arriba sobre el
    manejo de errores en operaciones multi-INSERT (26/09/2026).
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    INSERT INTO recomendaciones_terceros (apellido, nombre, valoracion, observaciones, cargado_por)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                """, (apellido, nombre, valoracion, observaciones, usuario_id))
                recomendacion_id = cur.fetchone()[0]
                for materia_id in materia_ids:
                    cur.execute("""
                        INSERT INTO recomendaciones_terceros_materias (recomendacion_id, materia_id)
                        VALUES (%s, %s)
                        ON CONFLICT (recomendacion_id, materia_id) DO NOTHING;
                    """, (recomendacion_id, materia_id))
                conn.commit()
            except Exception as e:
                conn.rollback()
                return False, f"No se pudo guardar la recomendación: {e}"
    get_profesores_data_completo.clear()
    return True, "Recomendación guardada."

def actualizar_recomendacion_tercero(recomendacion_id, apellido, nombre, valoracion, observaciones, materia_ids):
    """
    Devuelve (ok: bool, mensaje: str). Mismo criterio que
    agregar_recomendacion_tercero() (ver comentario arriba): el UPDATE, el
    DELETE de materias viejas y el loop de INSERTs nuevos corren en una
    sola transacción explícita, con rollback garantizado si algo falla a
    mitad de camino.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    UPDATE recomendaciones_terceros
                    SET apellido = %s, nombre = %s, valoracion = %s, observaciones = %s
                    WHERE id = %s;
                """, (apellido, nombre, valoracion, observaciones, recomendacion_id))
                cur.execute("DELETE FROM recomendaciones_terceros_materias WHERE recomendacion_id = %s;", (recomendacion_id,))
                for materia_id in materia_ids:
                    cur.execute("""
                        INSERT INTO recomendaciones_terceros_materias (recomendacion_id, materia_id)
                        VALUES (%s, %s)
                        ON CONFLICT (recomendacion_id, materia_id) DO NOTHING;
                    """, (recomendacion_id, materia_id))
                conn.commit()
            except Exception as e:
                conn.rollback()
                return False, f"No se pudo actualizar la recomendación: {e}"
    get_profesores_data_completo.clear()
    return True, "Recomendación actualizada."

def eliminar_recomendacion_tercero(recomendacion_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM recomendaciones_terceros WHERE id = %s;", (recomendacion_id,))
        conn.commit()
    get_profesores_data_completo.clear()

# ─── Listados "Positivos", "Negativos" y "Neutral" (24/09/2026, Neutral
# agregado 29/09/2026) ───────────────────────────────────────────────────────
# Agrupa a todos los profesores por 👍 / 👎 / 🤷 sumando tus opiniones propias
# (opiniones_profesores) y las recomendaciones de terceros, sin importar
# quién hizo el comentario. NO abre ninguna consulta nueva: trabaja sobre
# los datos que ya trae get_profesores_data_completo(), así que no suma
# latencia y se actualiza solo cuando esas funciones limpian el caché.
#
# Criterio: ver _categoria_reputacion() más arriba (las neutrales no suman
# ni a favor ni en contra; el empate y el "solo neutrales" van a 🤷). Esto
# cuenta opiniones, no materias — una opinión que cubre 3 materias suma 1
# sola vez.
#
# Unión de nombres: en tus opiniones el profesor es un solo texto libre y en
# las de terceros van apellido y nombre por separado. Para reconocer al
# mismo profesor se comparan los nombres sin tildes, sin mayúsculas, sin
# signos y sin importar el orden ("Pérez, Juan" = "Juan Pérez"). Variantes
# como "J. Pérez" o con segundo nombre se leen como profesores distintos.

def _sin_tildes_minusculas(texto):
    descompuesto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn").lower()

def _clave_profesor(texto):
    limpio = re.sub(r"[^\w\s]", " ", _sin_tildes_minusculas(texto))
    return " ".join(sorted(limpio.split()))

def agrupar_por_reputacion(opiniones, recomendaciones):
    """
    Devuelve (positivos, negativos, neutrales): tres listas de nombres para
    mostrar, ordenadas alfabéticamente.
    """
    profesores = {}

    # Primero las de terceros, para que el nombre a mostrar quede como
    # "Apellido, Nombre" cuando el profesor aparece en ambos orígenes.
    for r in recomendaciones:
        apellido, nombre, valoracion = r[1], r[2], r[3]
        clave = _clave_profesor(f"{apellido} {nombre}")
        if not clave:
            continue
        datos = profesores.setdefault(
            clave, {"nombre": f"{apellido.strip()}, {nombre.strip()}", "pos": 0, "neg": 0}
        )
        if valoracion == "Recomendado":
            datos["pos"] += 1
        elif valoracion == "No recomendado":
            datos["neg"] += 1

    for op in opiniones:
        profesor, valoracion = op[1], op[2]
        clave = _clave_profesor(profesor)
        if not clave:
            continue
        datos = profesores.setdefault(clave, {"nombre": profesor.strip(), "pos": 0, "neg": 0})
        if valoracion == "Recomendado":
            datos["pos"] += 1
        elif valoracion == "No recomendado":
            datos["neg"] += 1

    positivos, negativos, neutrales = [], [], []
    for d in profesores.values():
        categoria = _categoria_reputacion(d["pos"], d["neg"])
        if categoria == "positivo":
            positivos.append(d["nombre"])
        elif categoria == "negativo":
            negativos.append(d["nombre"])
        else:
            neutrales.append(d["nombre"])

    positivos.sort(key=_sin_tildes_minusculas)
    negativos.sort(key=_sin_tildes_minusculas)
    neutrales.sort(key=_sin_tildes_minusculas)
    return positivos, negativos, neutrales

def _texto_materias(materia_nombres, materia_anios):
    """Arma 'Año — Materia, Año — Materia, ...' a partir de las listas de la opinión."""
    return ", ".join(
        f"{NOMBRES_ANIO.get(anio, f'Año {anio}')} — {nombre}"
        for nombre, anio in zip(materia_nombres, materia_anios)
    )

def mostrar(usuario):
    if not usuario:
        st.switch_page("app.py")
        return

    st.title("⭐ Opiniones de Profesores")
    st.caption("Tus opiniones son privadas y solo las ves vos.")

    # ── Batch único de la pantalla (ítem prioridad alta, latencia de carga,
    # 14/08/2026): antes eran 3 conexiones fijas al pool (todas_materias,
    # opiniones, recomendaciones_terceros). Ahora es 1 sola — ver
    # get_profesores_data_completo más arriba.
    todas, opiniones_todas, recomendaciones = get_profesores_data_completo(
        usuario["id"], usuario["carrera_id"]
    )
    opciones = {f"{NOMBRES_ANIO.get(m[2], '')} — {m[1]}": m[0] for m in todas}
    # Lista con placeholder "—" para los selectores de "hasta 3 materias"
    # (27/09/2026): ninguno de los 3 campos es obligatorio individualmente,
    # solo hace falta completar al menos uno.
    opciones_multi_lista = ["—"] + list(opciones.keys())

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📋 Mis opiniones",
        "➕ Agregar opinión",
        "🗣️ Profesores recomendados por terceros",
        "👍 Positivos",
        "👎 Negativos",
        "🤷 Neutral",
        "🔄 Cambio de Opiniones",
    ])

    with tab1:
        opiniones = opiniones_todas

        if not opiniones:
            st.info("Todavía no cargaste ninguna opinión.")
        else:
            filtro = st.radio(
                "Filtrar por valoración",
                ["Todas"] + VALORACIONES,
                horizontal=True
            )

            if filtro != "Todas":
                opiniones = [o for o in opiniones if o[2] == filtro]

            if not opiniones:
                st.info("No hay opiniones con ese filtro.")
            else:
                por_profesor = {}
                for op in opiniones:
                    profesor = op[1]
                    por_profesor.setdefault(profesor, []).append(op)

                for profesor, ops in por_profesor.items():
                    icono_prof = _icono_reputacion([o[2] for o in ops])
                    total_materias = sum(len(o[4]) for o in ops)

                    with st.expander(f"{icono_prof} {profesor} ({total_materias} materia{'s' if total_materias != 1 else ''})"):
                        for op in ops:
                            oid, _, valoracion, observaciones, materia_ids, materia_nombres, materia_anios = op
                            key_edit_op = f"editando_opinion_{oid}"
                            materias_texto = _texto_materias(materia_nombres, materia_anios)

                            if st.session_state.get(key_edit_op):
                                # ── Formulario de edición inline (27/09/2026: ahora
                                # tiene profesor + hasta 3 materias + valoración +
                                # observaciones, los mismos cuatro tipos de campo que
                                # "➕ Agregar opinión". Antes solo se podía tocar
                                # valoración/observaciones desde acá. ──────────────
                                with st.form(f"form_edit_opinion_{oid}"):
                                    st.markdown(f"**✏️ Editando opinión — {profesor}**")
                                    nuevo_profesor = st.text_input(
                                        "Nombre del profesor/a", value=profesor, key=f"edit_profesor_{oid}"
                                    )
                                    st.markdown("**Materias que dicta** _(hasta 3, completá al menos una)_")
                                    e_materias_labels = []
                                    for i in range(3):
                                        default_label = "—"
                                        if i < len(materia_ids):
                                            for lbl, mid_opt in opciones.items():
                                                if mid_opt == materia_ids[i]:
                                                    default_label = lbl
                                                    break
                                        idx_default = (
                                            opciones_multi_lista.index(default_label)
                                            if default_label in opciones_multi_lista else 0
                                        )
                                        e_materias_labels.append(
                                            st.selectbox(
                                                f"Materia {i + 1}", opciones_multi_lista,
                                                index=idx_default, key=f"edit_materia_{i}_{oid}"
                                            )
                                        )
                                    nueva_valoracion = st.radio(
                                        "Valoración", VALORACIONES,
                                        index=VALORACIONES.index(valoracion) if valoracion in VALORACIONES else 0,
                                        horizontal=True,
                                        key=f"edit_val_{oid}"
                                    )
                                    nuevas_obs = st.text_area(
                                        "Observaciones (opcional)",
                                        value=observaciones or "",
                                        height=100,
                                        key=f"edit_obs_{oid}"
                                    )
                                    col_go, col_co = st.columns(2)
                                    with col_go:
                                        guardar_op_edit = st.form_submit_button("💾 Guardar", use_container_width=True)
                                    with col_co:
                                        cancelar_op_edit = st.form_submit_button("❌ Cancelar", use_container_width=True)

                                if guardar_op_edit:
                                    nuevas_materia_ids = []
                                    for lbl in e_materias_labels:
                                        if lbl != "—" and opciones[lbl] not in nuevas_materia_ids:
                                            nuevas_materia_ids.append(opciones[lbl])
                                    if not nuevo_profesor.strip():
                                        st.error("Ingresá el nombre del profesor/a.")
                                    elif not nuevas_materia_ids:
                                        st.error("Seleccioná al menos una materia.")
                                    else:
                                        # No permitir que este profesor quede con dos
                                        # opiniones distintas cubriendo la misma materia.
                                        otras_materias_ids = set()
                                        for o in ops:
                                            if o[0] != oid:
                                                otras_materias_ids.update(o[4])
                                        conflicto = set(nuevas_materia_ids) & otras_materias_ids
                                        if conflicto:
                                            st.error("Ya tenés otra opinión cargada para ese profesor en una de esas materias.")
                                        else:
                                            ok, msg = actualizar_opinion(
                                                oid, nuevo_profesor.strip(), nueva_valoracion,
                                                nuevas_obs.strip(), nuevas_materia_ids
                                            )
                                            if ok:
                                                st.session_state[key_edit_op] = False
                                                st.success(msg)
                                                st.rerun()
                                            else:
                                                st.error(f"⚠️ {msg}")
                                if cancelar_op_edit:
                                    st.session_state[key_edit_op] = False
                                    st.rerun()

                            else:
                                icono_val = ICONOS_VALORACION.get(valoracion, "❔")

                                col1, col2, col3 = st.columns([5, 1, 1])
                                with col1:
                                    st.markdown(f"{icono_val} **{valoracion}** — {materias_texto}")
                                    if observaciones:
                                        st.caption(f"💬 {observaciones}")
                                with col2:
                                    if st.button("✏️", key=f"edit_op_{oid}", use_container_width=True):
                                        st.session_state[key_edit_op] = True
                                        st.rerun()
                                with col3:
                                    if st.button("🗑️", key=f"del_op_{oid}", use_container_width=True):
                                        eliminar_opinion(oid)
                                        st.rerun()

                        st.markdown("---")

    with tab2:
        if "form_opinion_key" not in st.session_state:
            st.session_state.form_opinion_key = 0
        fk = st.session_state.form_opinion_key

        # Cada widget lleva su propia key atada al contador de reseteo `fk`
        # (mismo patrón que feriados/faltas/comisiones/evaluaciones/recursos,
        # ítem "formularios deben volver limpios", 02/08/2026). Sin esto, el
        # form_opinion_key igual cambia el nombre del st.form, pero los
        # widgets de adentro conservan lo tipeado porque no tenían key propia.
        with st.form(f"form_opinion_{fk}"):
            profesor = st.text_input("Nombre del profesor/a", key=f"opinion_profesor_{fk}")
            st.markdown("**Materias que dicta** _(hasta 3, completá al menos una)_")
            materias_labels = []
            for i in range(3):
                materias_labels.append(
                    st.selectbox(f"Materia {i + 1}", opciones_multi_lista, index=0, key=f"opinion_materia_{i}_{fk}")
                )
            valoracion = st.radio(
                "Valoración", VALORACIONES, horizontal=True, key=f"opinion_valoracion_{fk}"
            )
            observaciones = st.text_area(
                "Observaciones (opcional)", height=100, key=f"opinion_obs_{fk}"
            )
            submit = st.form_submit_button("💾 Guardar opinión", use_container_width=True)

        if submit:
            materia_ids_sel = []
            for lbl in materias_labels:
                if lbl != "—" and opciones[lbl] not in materia_ids_sel:
                    materia_ids_sel.append(opciones[lbl])
            if not profesor:
                st.error("Ingresá el nombre del profesor/a.")
            elif not materia_ids_sel:
                st.error("Seleccioná al menos una materia.")
            else:
                # No permitir cargar una opinión nueva que pise una materia
                # que ese mismo profesor ya tiene cubierta en otra opinión.
                materias_ya_usadas = set()
                for op in opiniones_todas:
                    if op[1] == profesor.strip():
                        materias_ya_usadas.update(op[4])
                conflicto = set(materia_ids_sel) & materias_ya_usadas
                if conflicto:
                    st.error(
                        "Ya tenés una opinión cargada para ese profesor en una de esas "
                        "materias. Corregila desde '📋 Mis opiniones'."
                    )
                else:
                    ok, msg = agregar_opinion(
                        usuario["id"], profesor.strip(), valoracion, observaciones.strip(), materia_ids_sel
                    )
                    if ok:
                        st.session_state.form_opinion_key += 1
                        st.success(f"✅ {msg}")
                        st.rerun()
                    else:
                        st.error(f"⚠️ {msg}")

    with tab3:
        st.caption(
            "Recomendaciones **compartidas con todos los alumnos**, sobre profesores de los "
            "que te enteraste por un tercero (no cursaste vos mismo/a con ellos)."
        )

        opciones_mat = opciones
        opciones_mat_lista = ["—"] + list(opciones_mat.keys())

        if "form_terceros_key" not in st.session_state:
            st.session_state.form_terceros_key = 0
        fk_t = st.session_state.form_terceros_key

        # Cada widget con key atada a `fk_t` (mismo patrón que el resto de
        # los formularios "que deben volver limpios", 02/08/2026 / 04/08/2026).
        with st.expander("➕ Cargar recomendación de un tercero"):
            with st.form(f"form_terceros_{fk_t}"):
                col_ap, col_no = st.columns(2)
                with col_ap:
                    t_apellido = st.text_input("Apellido del profesor/a", key=f"terceros_apellido_{fk_t}")
                with col_no:
                    t_nombre = st.text_input("Nombre del profesor/a", key=f"terceros_nombre_{fk_t}")

                t_valoracion = st.radio(
                    "Valoración", VALORACIONES, horizontal=True, key=f"terceros_valoracion_{fk_t}"
                )

                st.markdown("**Materias que dicta** _(hasta 5, completá al menos una)_")
                t_materias_labels = []
                for i in range(5):
                    t_materias_labels.append(
                        st.selectbox(
                            f"Materia {i + 1}", opciones_mat_lista, index=0,
                            key=f"terceros_materia_{i}_{fk_t}"
                        )
                    )

                t_observaciones = st.text_area(
                    "Observaciones (opcional)", height=100, key=f"terceros_obs_{fk_t}"
                )
                submit_terceros = st.form_submit_button("💾 Guardar recomendación", use_container_width=True)

            if submit_terceros:
                materia_ids_sel = [opciones_mat[lbl] for lbl in t_materias_labels if lbl != "—"]
                if not t_apellido.strip() or not t_nombre.strip():
                    st.error("Completá apellido y nombre del profesor/a.")
                elif not materia_ids_sel:
                    st.error("Seleccioná al menos una materia.")
                else:
                    ok_t, msg_t = agregar_recomendacion_tercero(
                        usuario["id"], t_apellido.strip(), t_nombre.strip(),
                        t_valoracion, t_observaciones.strip(), materia_ids_sel
                    )
                    if ok_t:
                        st.session_state.form_terceros_key += 1
                        st.success("✅ Recomendación guardada. Ya la pueden ver todos los alumnos.")
                        st.rerun()
                    else:
                        st.error(f"⚠️ {msg_t}")

        st.markdown("---")

        if not recomendaciones:
            st.info("Todavía no hay recomendaciones de terceros cargadas.")
        else:
            # Agrupar por profesor (apellido + nombre, sin importar mayúsculas/
            # espacios) para que si dos alumnos distintos cargan al mismo
            # profesor por separado, aparezca combinado en un solo bloque.
            por_profesor_t = {}
            for r in recomendaciones:
                r_apellido, r_nombre = r[1], r[2]
                clave = (r_apellido.strip().lower(), r_nombre.strip().lower())
                if clave not in por_profesor_t:
                    por_profesor_t[clave] = {"apellido": r_apellido, "nombre": r_nombre, "entradas": []}
                por_profesor_t[clave]["entradas"].append(r)

            for clave, grupo in por_profesor_t.items():
                entradas = grupo["entradas"]
                icono_prof_t = _icono_reputacion([e[3] for e in entradas])

                materias_combinadas = set()
                for e in entradas:
                    for mn in e[8]:
                        materias_combinadas.add(mn)

                titulo_expander = f"{icono_prof_t} {grupo['apellido']}, {grupo['nombre']} — {', '.join(sorted(materias_combinadas))}"

                with st.expander(titulo_expander):
                    for e in entradas:
                        (eid, e_apellido, e_nombre, e_val, e_obs, e_cargado_por,
                         e_cargado_por_nombre, e_mat_ids, e_mat_nombres, e_mat_anios) = e

                        key_edit_t = f"editando_terceros_{eid}"
                        es_propia = usuario["id"] == e_cargado_por

                        if es_propia and st.session_state.get(key_edit_t):
                            # ── Formulario de edición inline (solo el dueño llega acá) ──
                            with st.form(f"form_edit_terceros_{eid}"):
                                ec_apellido = st.text_input("Apellido del profesor/a", value=e_apellido, key=f"e_ap_{eid}")
                                ec_nombre = st.text_input("Nombre del profesor/a", value=e_nombre, key=f"e_no_{eid}")
                                ec_valoracion = st.radio(
                                    "Valoración", VALORACIONES,
                                    index=VALORACIONES.index(e_val) if e_val in VALORACIONES else 0,
                                    horizontal=True, key=f"e_val_{eid}"
                                )

                                st.markdown("**Materias que dicta** _(hasta 5)_")
                                materia_ids_actuales = list(e_mat_ids)
                                ec_materias_labels = []
                                for i in range(5):
                                    default_label = "—"
                                    if i < len(materia_ids_actuales):
                                        for lbl, mid_opt in opciones_mat.items():
                                            if mid_opt == materia_ids_actuales[i]:
                                                default_label = lbl
                                                break
                                    idx_default = opciones_mat_lista.index(default_label) if default_label in opciones_mat_lista else 0
                                    ec_materias_labels.append(
                                        st.selectbox(f"Materia {i + 1}", opciones_mat_lista, index=idx_default, key=f"e_mat_{i}_{eid}")
                                    )

                                ec_observaciones = st.text_area("Observaciones (opcional)", value=e_obs or "", height=100, key=f"e_obs_{eid}")

                                col_ge, col_ce = st.columns(2)
                                with col_ge:
                                    guardar_t_edit = st.form_submit_button("💾 Guardar", use_container_width=True)
                                with col_ce:
                                    cancelar_t_edit = st.form_submit_button("❌ Cancelar", use_container_width=True)

                            if guardar_t_edit:
                                materia_ids_edit_sel = [opciones_mat[lbl] for lbl in ec_materias_labels if lbl != "—"]
                                if not ec_apellido.strip() or not ec_nombre.strip():
                                    st.error("Completá apellido y nombre del profesor/a.")
                                elif not materia_ids_edit_sel:
                                    st.error("Seleccioná al menos una materia.")
                                else:
                                    ok_te, msg_te = actualizar_recomendacion_tercero(
                                        eid, ec_apellido.strip(), ec_nombre.strip(),
                                        ec_valoracion, ec_observaciones.strip(), materia_ids_edit_sel
                                    )
                                    if ok_te:
                                        st.session_state[key_edit_t] = False
                                        st.success(msg_te)
                                        st.rerun()
                                    else:
                                        st.error(f"⚠️ {msg_te}")
                            if cancelar_t_edit:
                                st.session_state[key_edit_t] = False
                                st.rerun()

                        else:
                            icono_val_t = ICONOS_VALORACION.get(e_val, "❔")
                            materias_texto = ", ".join(e_mat_nombres)

                            if es_propia:
                                col1, col2, col3 = st.columns([5, 1, 1])
                                with col1:
                                    st.markdown(f"{icono_val_t} **{e_val}** — {materias_texto}")
                                    if e_obs:
                                        st.caption(f"💬 {e_obs}")
                                    st.caption("Cargado por: vos")
                                with col2:
                                    if st.button("✏️", key=f"edit_terceros_{eid}", use_container_width=True):
                                        st.session_state[key_edit_t] = True
                                        st.rerun()
                                with col3:
                                    if st.button("🗑️", key=f"del_terceros_{eid}", use_container_width=True):
                                        eliminar_recomendacion_tercero(eid)
                                        st.rerun()
                            else:
                                st.markdown(f"{icono_val_t} **{e_val}** — {materias_texto}")
                                if e_obs:
                                    st.caption(f"💬 {e_obs}")
                                st.caption(f"Cargado por: {e_cargado_por_nombre or 'otro alumno'}")

                        st.markdown("---")

    # ── Tabs "Positivos", "Negativos" y "Neutral" (24/09/2026, Neutral
    # 29/09/2026) ─────────────────────────────────────────────────────────
    # Se calculan en memoria con los datos que ya trajo el batch de arriba,
    # sin ninguna consulta nueva. Ver agrupar_por_reputacion().
    positivos, negativos, neutrales = agrupar_por_reputacion(opiniones_todas, recomendaciones)

    with tab4:
        if not positivos:
            st.info("Todavía no hay profesores con reputación positiva.")
        else:
            st.caption(f"{len(positivos)} profesor(es) con 👍")
            for nombre_prof in positivos:
                st.markdown(f"👍 {nombre_prof}")

    with tab5:
        if not negativos:
            st.info("Todavía no hay profesores con reputación negativa.")
        else:
            st.caption(f"{len(negativos)} profesor(es) con 👎")
            for nombre_prof in negativos:
                st.markdown(f"👎 {nombre_prof}")

    with tab6:
        if not neutrales:
            st.info("Todavía no hay profesores con reputación neutral.")
        else:
            st.caption(f"{len(neutrales)} profesor(es) con 🤷")
            for nombre_prof in neutrales:
                st.markdown(f"🤷 {nombre_prof}")

    # ── Tab "Cambio de Opiniones" (26/09/2026, actualizada 27/09/2026) ─────
    # Pantalla dedicada para corregir a un profesor de punta a punta: elegís
    # el profesor, ves todas las opiniones (bloques de hasta 3 materias) que
    # le cargaste, y para cada una podés cambiar profesor/materias/
    # valoración/observaciones o borrarla. Abajo hay un formulario para
    # cargarle una opinión NUEVA al mismo profesor, con las materias que
    # todavía no tiene cubiertas.
    #
    # No abre ninguna consulta nueva: trabaja sobre opiniones_todas, que ya
    # trajo el batch de arriba.
    with tab7:
        st.caption(
            "Elegí un profesor para cargarle una opinión nueva (hasta 3 materias), o para "
            "cambiarle el profesor, las materias, la valoración o las observaciones a una "
            "opinión ya cargada."
        )

        if not opiniones_todas:
            st.info("Todavía no cargaste ninguna opinión.")
        else:
            profesores_propios = sorted(
                set(op[1] for op in opiniones_todas), key=_sin_tildes_minusculas
            )
            profesor_sel = st.selectbox(
                "Profesor/a", profesores_propios, key="cambio_op_profesor_sel"
            )

            opiniones_prof = [op for op in opiniones_todas if op[1] == profesor_sel]
            materias_ya_ids = set()
            for op in opiniones_prof:
                materias_ya_ids.update(op[4])

            st.markdown(f"**Opiniones cargadas para {profesor_sel}:**")
            for op in opiniones_prof:
                oid, _, valoracion, observaciones, materia_ids, materia_nombres, materia_anios = op
                materias_texto = _texto_materias(materia_nombres, materia_anios)

                with st.expander(f"{materias_texto} — {valoracion}"):
                    with st.form(f"form_cambio_op_{oid}"):
                        ec_profesor = st.text_input(
                            "Profesor/a", value=profesor_sel, key=f"cambio_op_profesor_{oid}"
                        )
                        st.markdown("**Materias que dicta** _(hasta 3)_")
                        ec_materias_labels = []
                        for i in range(3):
                            default_label = "—"
                            if i < len(materia_ids):
                                for lbl, mid_opt in opciones.items():
                                    if mid_opt == materia_ids[i]:
                                        default_label = lbl
                                        break
                            idx_default = (
                                opciones_multi_lista.index(default_label)
                                if default_label in opciones_multi_lista else 0
                            )
                            ec_materias_labels.append(
                                st.selectbox(
                                    f"Materia {i + 1}", opciones_multi_lista,
                                    index=idx_default, key=f"cambio_op_materia_{i}_{oid}"
                                )
                            )
                        nueva_valoracion = st.radio(
                            "Valoración", VALORACIONES,
                            index=VALORACIONES.index(valoracion) if valoracion in VALORACIONES else 0,
                            horizontal=True, key=f"cambio_op_val_{oid}"
                        )
                        nuevas_obs = st.text_area(
                            "Observaciones (opcional)", value=observaciones or "",
                            height=100, key=f"cambio_op_obs_{oid}"
                        )
                        col_g, col_b = st.columns(2)
                        with col_g:
                            guardar_cambio = st.form_submit_button("💾 Guardar cambios", use_container_width=True)
                        with col_b:
                            borrar_cambio = st.form_submit_button("🗑️ Borrar esta opinión", use_container_width=True)

                    if guardar_cambio:
                        nuevas_materia_ids = []
                        for lbl in ec_materias_labels:
                            if lbl != "—" and opciones[lbl] not in nuevas_materia_ids:
                                nuevas_materia_ids.append(opciones[lbl])
                        if not ec_profesor.strip():
                            st.error("Ingresá el nombre del profesor/a.")
                        elif not nuevas_materia_ids:
                            st.error("Seleccioná al menos una materia.")
                        else:
                            otras_materias_ids = set()
                            for o in opiniones_prof:
                                if o[0] != oid:
                                    otras_materias_ids.update(o[4])
                            conflicto = set(nuevas_materia_ids) & otras_materias_ids
                            if conflicto:
                                st.error("Ese profesor ya tiene otra opinión cargada para una de esas materias.")
                            else:
                                ok, msg = actualizar_opinion(
                                    oid, ec_profesor.strip(), nueva_valoracion,
                                    nuevas_obs.strip(), nuevas_materia_ids
                                )
                                if ok:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(f"⚠️ {msg}")
                    if borrar_cambio:
                        eliminar_opinion(oid)
                        st.success("Opinión borrada.")
                        st.rerun()

            st.markdown("---")
            st.markdown(f"**➕ Agregar opinión nueva para {profesor_sel}**")

            opciones_disponibles = {
                lbl: mid for lbl, mid in opciones.items() if mid not in materias_ya_ids
            }

            if not opciones_disponibles:
                st.caption("Ya cargaste todas las materias disponibles para este profesor.")
            else:
                if "form_cambio_nueva_key" not in st.session_state:
                    st.session_state.form_cambio_nueva_key = 0
                fkc = st.session_state.form_cambio_nueva_key

                opciones_disp_multi_lista = ["—"] + list(opciones_disponibles.keys())

                with st.form(f"form_cambio_nueva_materia_{fkc}"):
                    st.markdown("**Materias que dicta** _(hasta 3, completá al menos una)_")
                    nuevas_labels = []
                    for i in range(3):
                        nuevas_labels.append(
                            st.selectbox(
                                f"Materia {i + 1}", opciones_disp_multi_lista,
                                index=0, key=f"cambio_nueva_materia_{i}_{fkc}"
                            )
                        )
                    valoracion_add = st.radio(
                        "Valoración", VALORACIONES, horizontal=True, key=f"cambio_nueva_val_{fkc}"
                    )
                    obs_add = st.text_area(
                        "Observaciones (opcional)", height=100, key=f"cambio_nueva_obs_{fkc}"
                    )
                    submit_add = st.form_submit_button("💾 Agregar opinión", use_container_width=True)

                if submit_add:
                    materia_ids_add = []
                    for lbl in nuevas_labels:
                        if lbl != "—" and opciones_disponibles[lbl] not in materia_ids_add:
                            materia_ids_add.append(opciones_disponibles[lbl])
                    if not materia_ids_add:
                        st.error("Seleccioná al menos una materia.")
                    else:
                        ok, msg = agregar_opinion(
                            usuario["id"], profesor_sel, valoracion_add, obs_add.strip(), materia_ids_add
                        )
                        if ok:
                            st.session_state.form_cambio_nueva_key += 1
                            st.success(f"✅ {msg}")
                            st.rerun()
                        else:
                            st.error(f"⚠️ {msg}")
