# db.py

import os
import re
import csv
import uuid
import zipfile
from io import BytesIO, StringIO
import psycopg
from psycopg import sql as pgsql
from psycopg_pool import ConnectionPool
import bcrypt
from dotenv import load_dotenv
import streamlit as st
from contextlib import contextmanager
from datetime import datetime
from utils import determinar_estado_cuatrimestre

load_dotenv()

# ─── Uso de almacenamiento (Neon) ───────────────────────────────────────────
# Límite de almacenamiento del plan Free de Neon (0.5 GiB). Postgres no tiene
# forma de conocer el límite del plan contratado por SQL, así que queda como
# constante acá — si en algún momento se actualiza el plan de Neon, hay que
# actualizar este valor a mano (ítem "Administración → % de espacio libre en
# Neon", 08/08/2026).
NEON_STORAGE_LIMIT_BYTES = int(0.5 * 1024 * 1024 * 1024)  # 0.5 GiB = 536.870.912 bytes

@st.cache_resource
def get_database_url():
    return os.environ["DATABASE_URL"]

# Mantener compatibilidad con auth.py y db.py setup que usan get_connection()
def get_connection():
    return psycopg.connect(get_database_url())

@st.cache_resource
def get_pool():
    """
    Pool de conexiones reutilizables para las queries de las páginas (pages/*.py).
    check=ConnectionPool.check_connection valida cada conexión antes de entregarla,
    para evitar el problema de que Neon cierre conexiones idle del lado del servidor
    sin que el pool se entere (por eso antes evitábamos un pool tradicional).
    max_idle cierra conexiones ociosas del lado del pool para no acumular conexiones
    que Neon ya dio por muertas.
    """
    return ConnectionPool(
        conninfo=get_database_url(),
        min_size=1,
        max_size=5,
        max_idle=300,
        check=ConnectionPool.check_connection,
        kwargs={"autocommit": False},
    )

@contextmanager
def get_conn():
    """
    Entrega una conexión del pool y la devuelve automáticamente al salir del bloque `with`.
    Mucho más rápido que abrir una conexión nueva por cada query, sin perder la robustez
    frente a que Neon cierre conexiones idle.
    Si Neon está caído o sin crédito, muestra un mensaje amigable en vez de un traceback crudo.
    """
    pool = get_pool()
    try:
        with pool.connection() as conn:
            yield conn
    except psycopg.OperationalError:
        st.error(
            "⚠️ No se pudo conectar a la base de datos. Puede estar temporalmente "
            "inactiva o sin crédito disponible en Neon. Probá de nuevo en unos segundos."
        )
        raise

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS carreras (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            universidad TEXT NOT NULL,
            UNIQUE(nombre, universidad)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nombre TEXT NOT NULL,
            carrera_id INTEGER REFERENCES carreras(id),
            es_admin BOOLEAN DEFAULT FALSE,
            email_institucional TEXT,
            campus_virtual TEXT,
            portal_alumnos TEXT,
            biblioteca_digital TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Número de legajo del alumno: único cuando está cargado, pero admite NULL
    # (Postgres permite múltiples NULL en una columna UNIQUE) para alumnos que
    # todavía no lo tienen asignado ("pendiente").
    cur.execute("""
        ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS legajo TEXT UNIQUE;
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS materias (
            id SERIAL PRIMARY KEY,
            carrera_id INTEGER REFERENCES carreras(id),
            codigo TEXT,
            nombre TEXT NOT NULL,
            anio INTEGER NOT NULL,
            cuatrimestre TEXT NOT NULL,
            final_obligatorio BOOLEAN DEFAULT FALSE,
            es_electiva BOOLEAN DEFAULT FALSE
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS correlatividades (
            id SERIAL PRIMARY KEY,
            materia_id INTEGER REFERENCES materias(id),
            requiere_materia_id INTEGER REFERENCES materias(id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alumno_materias (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            materia_id INTEGER REFERENCES materias(id),
            estado TEXT DEFAULT 'pendiente',
            UNIQUE(usuario_id, materia_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS codigos_invitacion (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE NOT NULL,
            usado BOOLEAN DEFAULT FALSE,
            creado_por INTEGER REFERENCES usuarios(id),
            usado_por INTEGER REFERENCES usuarios(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recursos (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            materia_id INTEGER REFERENCES materias(id),
            nombre TEXT NOT NULL,
            tipo TEXT NOT NULL,
            link TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cursadas (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            materia_id INTEGER REFERENCES materias(id),
            anio_cursada INTEGER NOT NULL,
            cuatrimestre TEXT NOT NULL,
            modalidad TEXT NOT NULL,
            turno TEXT,
            dias TEXT,
            horario TEXT,
            link TEXT,
            profesor1 TEXT,
            email_profesor1 TEXT,
            profesor2 TEXT,
            email_profesor2 TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(usuario_id, materia_id, anio_cursada, cuatrimestre)
        );
    """)

    # Fechas opcionales de 1er parcial, 2do parcial y final para la cursada.
    # Pueden quedar vacías al registrar la cursada y completarse después
    # (ítem 1 de "Cosas por Hacer" — prioridad máxima, 27/07/2026).
    cur.execute("""
        ALTER TABLE cursadas ADD COLUMN IF NOT EXISTS fecha_parcial1 DATE;
    """)
    cur.execute("""
        ALTER TABLE cursadas ADD COLUMN IF NOT EXISTS fecha_parcial2 DATE;
    """)
    cur.execute("""
        ALTER TABLE cursadas ADD COLUMN IF NOT EXISTS fecha_final DATE;
    """)

    # ── Comisiones (ítem #6 de "Cosas por Hacer", 02/08/2026) ──────────────
    # numero_comision + fecha_desde_comision viven directamente en cursadas y
    # representan la comisión VIGENTE (ej. "COM V", desde tal fecha). No se
    # puede estar en dos comisiones a la vez, pero sí cambiar de una a otra
    # a mitad de cuatrimestre: cuando eso pasa, el período anterior se cierra
    # y se archiva en comisiones_historial (ver más abajo), para que el
    # cálculo de asistencia pueda sumar correctamente los días de cursada de
    # cada tramo, aunque hayan sido distintos.
    cur.execute("""
        ALTER TABLE cursadas ADD COLUMN IF NOT EXISTS numero_comision TEXT;
    """)
    cur.execute("""
        ALTER TABLE cursadas ADD COLUMN IF NOT EXISTS fecha_desde_comision DATE;
    """)
    cur.execute("""
        UPDATE cursadas SET numero_comision = 'COM I' WHERE numero_comision IS NULL;
    """)
    cur.execute("""
        UPDATE cursadas SET fecha_desde_comision = COALESCE(created_at::date, make_date(anio_cursada, 1, 1))
        WHERE fecha_desde_comision IS NULL;
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS comisiones_historial (
            id SERIAL PRIMARY KEY,
            cursada_id INTEGER REFERENCES cursadas(id) ON DELETE CASCADE,
            numero_comision TEXT NOT NULL,
            turno TEXT,
            dias TEXT,
            horario TEXT,
            link TEXT,
            profesor1 TEXT,
            email_profesor1 TEXT,
            profesor2 TEXT,
            email_profesor2 TEXT,
            fecha_desde DATE NOT NULL,
            fecha_hasta DATE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS evaluaciones (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            materia_id INTEGER REFERENCES materias(id),
            tipo TEXT NOT NULL,
            descripcion TEXT,
            nota NUMERIC(4,2),
            fecha DATE,
            aprobado BOOLEAN,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tareas (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            materia_id INTEGER REFERENCES materias(id),
            numero INTEGER NOT NULL,
            descripcion TEXT,
            fecha_vencimiento DATE,
            completada BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Recordatorios de tareas por email (ítem prioridad alta, 17/08/2026):
    # marca cuándo se le mandó al alumno el recordatorio de una tarea, para
    # que el script de recordatorios (enviar_recordatorios.py, corrido una
    # vez al día vía GitHub Actions) no le mande el mismo recordatorio más
    # de una vez. NULL = todavía no se mandó recordatorio para esa tarea.
    cur.execute("""
        ALTER TABLE tareas ADD COLUMN IF NOT EXISTS recordatorio_enviado_at TIMESTAMP;
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS asistencias (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            materia_id INTEGER REFERENCES materias(id),
            fecha DATE NOT NULL,
            justificada BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(usuario_id, materia_id, fecha)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS opiniones_profesores (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            materia_id INTEGER REFERENCES materias(id),
            profesor TEXT NOT NULL,
            valoracion TEXT NOT NULL,
            observaciones TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Recomendaciones de profesores hechas "por terceros": a diferencia de
    # opiniones_profesores (privada, un alumno opina de una materia que él
    # mismo cursó), esta es información COMPARTIDA entre todos los alumnos
    # de la carrera, sobre profesores de los que un alumno se enteró por un
    # tercero (no la cursó él mismo). Un mismo profesor puede dictar hasta
    # 5 materias distintas, por eso la relación con materias va en una tabla
    # puente aparte en vez de columnas materia_id_1..5 (ítem "Profesores
    # recomendados por terceros", agregado 29/07/2026).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recomendaciones_terceros (
            id SERIAL PRIMARY KEY,
            apellido TEXT NOT NULL,
            nombre TEXT NOT NULL,
            valoracion TEXT NOT NULL,
            observaciones TEXT,
            cargado_por INTEGER REFERENCES usuarios(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recomendaciones_terceros_materias (
            id SERIAL PRIMARY KEY,
            recomendacion_id INTEGER REFERENCES recomendaciones_terceros(id) ON DELETE CASCADE,
            materia_id INTEGER REFERENCES materias(id),
            UNIQUE(recomendacion_id, materia_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS programas (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            materia_id INTEGER REFERENCES materias(id),
            link TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(usuario_id, materia_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_cuatrimestre (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            anio INTEGER NOT NULL,
            cuatrimestre TEXT NOT NULL,
            fecha_inicio DATE NOT NULL,
            fecha_fin DATE NOT NULL,
            UNIQUE(usuario_id, anio, cuatrimestre)
        );
    """)

    # Feriados / días sin clase configurados por el alumno, para que
    # contar_clases_en_rango() (en cursadas.py y home.py) no los cuente
    # como clase dictada al calcular la asistencia.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feriados (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            fecha DATE NOT NULL,
            descripcion TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(usuario_id, fecha)
        );
    """)

    # Registro de intentos de login fallidos, usado por auth.py para aplicar
    # rate limiting (bloqueo temporal por email tras varios intentos fallidos
    # en una ventana de tiempo). No se guarda si fue exitoso: los éxitos
    # limpian el historial de ese email.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS intentos_login (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_intentos_login_email_fecha
        ON intentos_login (email, created_at);
    """)

    # ── Recuperación de contraseña (ítem prioridad alta, 17/08/2026) ───────
    # Un token de un solo uso por solicitud, con vencimiento corto (1 hora,
    # ver GENERAR_TOKEN_RESET_VENCE_MINUTOS en auth.py). "usado" evita que
    # el mismo link se reutilice una vez ya cambiada la contraseña; el
    # vencimiento evita que un link viejo (por ejemplo reenviado sin
    # querer, o encontrado en un email guardado) siga siendo válido
    # indefinidamente.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER REFERENCES usuarios(id),
            token TEXT UNIQUE NOT NULL,
            usado BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL
        );
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token
        ON password_reset_tokens (token);
    """)

    cur.execute("""
        INSERT INTO carreras (nombre, universidad)
        VALUES ('Licenciatura en Psicología', 'UdeMM')
        ON CONFLICT (nombre, universidad) DO NOTHING;
    """)

    conn.commit()
    cur.close()
    conn.close()

def crear_admin_si_no_existe():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE email = 'fabianbelledi@gmail.com';")
    if not cur.fetchone():
        password_hash = bcrypt.hashpw("Seamist123**".encode(), bcrypt.gensalt()).decode()
        cur.execute("""
            INSERT INTO usuarios (email, password_hash, nombre, carrera_id, es_admin)
            VALUES ('fabianbelledi@gmail.com', %s, 'Admin', 1, TRUE);
        """, (password_hash,))
        conn.commit()
    cur.close()
    conn.close()

# ─── Feriados / días sin clase ──────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_feriados(usuario_id):
    """Devuelve la lista de feriados del alumno como [(id, fecha, descripcion), ...]."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, fecha, descripcion
                FROM feriados
                WHERE usuario_id = %s
                ORDER BY fecha;
            """, (usuario_id,))
            return cur.fetchall()

def agregar_feriado(usuario_id, fecha, descripcion=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO feriados (usuario_id, fecha, descripcion)
                VALUES (%s, %s, %s)
                ON CONFLICT (usuario_id, fecha)
                DO UPDATE SET descripcion = EXCLUDED.descripcion;
            """, (usuario_id, fecha, descripcion))
        conn.commit()
    get_feriados.clear()
    get_home_data_completo.clear()

def borrar_feriado(feriado_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM feriados WHERE id = %s;", (feriado_id,))
        conn.commit()
    get_feriados.clear()
    get_home_data_completo.clear()

# ─── Clases de hoy ──────────────────────────────────────────────────────────
# Antes estaba duplicada, con SQL casi idéntico, en cursadas.py y home.py
# (ítem de prioridad media, "Revisar duplicación de queries entre cursadas.py
# y home.py", 27/07/2026). Se centraliza acá con la versión que incluye
# `turno`, que es la más completa de las dos. Los llamadores que no necesiten
# el turno simplemente ignoran ese valor al desempaquetar la tupla.
#
# NOTA (12/08/2026): pages/home.py ya NO llama a esta función — su propio
# batch (get_home_data_completo, más abajo) trae las clases de hoy con el
# mismo SQL en la misma conexión que el resto de los datos de esa pantalla,
# para no abrir una conexión extra. Esta función se mantiene tal cual porque
# pages/cursadas.py sigue usándola.

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

# ─── Comisiones (historial) ─────────────────────────────────────────────────
# Centralizado acá porque lo usan tanto cursadas.py (formulario de cambio de
# comisión y detalle de asistencia por materia) como home.py (cálculo de
# asistencia multi-período en el dashboard) — mismo criterio que se usó para
# get_clases_hoy (ítem #6 de "Cosas por Hacer", 02/08/2026).

@st.cache_data(ttl=120)
def get_historial_comisiones(cursada_id):
    """
    Períodos CERRADOS de comisión de una cursada (no incluye el vigente,
    que vive en cursadas.numero_comision / cursadas.fecha_desde_comision).
    Devuelve [(id, numero_comision, turno, dias, horario, link,
    profesor1, email_profesor1, profesor2, email_profesor2,
    fecha_desde, fecha_hasta), ...] ordenado por fecha_desde.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, numero_comision, turno, dias, horario, link,
                       profesor1, email_profesor1, profesor2, email_profesor2,
                       fecha_desde, fecha_hasta
                FROM comisiones_historial
                WHERE cursada_id = %s
                ORDER BY fecha_desde;
            """, (cursada_id,))
            return cur.fetchall()

def get_periodos_comision(cursada_id, dias_actual, fecha_desde_actual):
    """
    Arma la lista completa de períodos de comisión de una cursada (los
    cerrados + el vigente), para que utils.contar_clases_multi_periodo()
    pueda sumar las clases dictadas de cada tramo por separado:
    [(dias_str, fecha_desde, fecha_hasta_o_None), ...]
    El último período (comisión vigente) usa fecha_hasta=None, que se
    interpreta como "hasta el fin del cuatrimestre configurado".
    """
    historial = get_historial_comisiones(cursada_id)
    periodos = [(h[3], h[10], h[11]) for h in historial]
    periodos.append((dias_actual, fecha_desde_actual, None))
    return periodos

# ─── Uso de almacenamiento (Neon) ───────────────────────────────────────────
# Usado por la sección "📦 Uso de almacenamiento (Neon)" del panel de
# Administración (ítem nuevo, 08/08/2026). pg_database_size() devuelve el
# tamaño real ocupado por la base en bytes; el % se calcula contra
# NEON_STORAGE_LIMIT_BYTES (definido arriba). Cacheado 5 minutos: el tamaño
# de la base no cambia lo suficientemente rápido como para justificar
# consultarlo en cada rerun de Streamlit.

@st.cache_data(ttl=300)
def get_uso_almacenamiento():
    """Devuelve el tamaño actual de la base de datos, en bytes."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database());")
            return cur.fetchone()[0]

# ─── Batch principal de Home (ítem prioridad alta, latencia de carga,
# 12/08/2026) ────────────────────────────────────────────────────────────
# Antes, cargar Home abría 6 conexiones fijas al pool antes de poder pintar
# nada: stats + configs (antes get_home_data, en home.py), materias
# cursando + notas (antes get_materias_cursando_con_notas, en home.py),
# faltas por materia (antes get_faltas_por_materia, en home.py), feriados
# (antes get_feriados, acá arriba), tareas pendientes (antes
# get_tareas_pendientes, en home.py) y clases de hoy (antes get_clases_hoy,
# acá arriba). Se consolida todo en una sola conexión, mismo criterio que ya
# se usa en get_cursadas_tab_data (cursadas.py) y
# get_estadisticas_asistencia_data (estadisticas.py): en Neon serverless el
# costo real es el round-trip de adquirir/chequear la conexión, no las
# queries en sí — pedirla 1 vez en vez de 6 achica bastante la latencia de
# la pantalla que más se visita.
#
# NOTA: duplica a propósito el SQL de get_feriados y get_clases_hoy (que
# siguen existiendo tal cual, sin cambios, porque pages/cursadas.py las sigue
# usando) en vez de llamarlas, para no abrir una conexión extra por cada una
# — mismo criterio que ya usa get_cursadas_tab_data con sus propias tablas.
#
# Invalidación de caché: todas las funciones que escriben datos que esta
# pantalla muestra (feriados, tareas, faltas, cursadas/comisiones, estado de
# materias, evaluaciones/notas) limpian este caché además del suyo propio.
# Ver agregar_feriado/borrar_feriado más arriba, y en pages/cursadas.py,
# pages/materias.py y pages/evaluaciones.py.

@st.cache_data(ttl=60)
def get_home_data_completo(usuario_id, carrera_id, anio_actual):
    """
    Devuelve todo lo que necesita pages/home.py para pintar la pantalla
    principal, en una sola conexión:
    (total, aprobadas, cursando, regulares, desaprobadas, avance, configs,
     cuatrimestre_para_query, header_cuatrimestre, en_transicion,
     materias_cursando, faltas_map, feriados_set, tareas, clases_hoy)
    """
    hoy = datetime.now()
    dia_semana = ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"][hoy.weekday()]

    with get_conn() as conn:
        with conn.cursor() as cur:
            # ── Stats de avance de carrera ──────────────────────────────
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
            total, aprobadas, cursando, regulares, desaprobadas = cur.fetchone()
            avance = round((aprobadas / total) * 100, 1) if total > 0 else 0

            # ── Configuración de fechas de cuatrimestre ──────────────────
            cur.execute("""
                SELECT anio, cuatrimestre, fecha_inicio, fecha_fin
                FROM configuracion_cuatrimestre
                WHERE usuario_id = %s
                ORDER BY anio DESC, cuatrimestre;
            """, (usuario_id,))
            configs = {(r[0], r[1]): (r[2], r[3]) for r in cur.fetchall()}

            # Cuatrimestre "actual" según las fechas reales configuradas —
            # se resuelve acá adentro (no en home.py) para poder pedir las
            # materias cursando del cuatrimestre correcto en esta misma
            # conexión, sin ida y vuelta extra al pool.
            cuatrimestre_para_query, header_cuatrimestre, en_transicion = determinar_estado_cuatrimestre(
                anio_actual, configs
            )

            # ── Materias cursando + notas ────────────────────────────────
            cur.execute("""
                WITH materias_cursando AS (
                    SELECT
                        m.nombre, m.anio, c.cuatrimestre, c.anio_cursada,
                        c.profesor1, c.dias, c.horario, c.modalidad,
                        m.id AS materia_id, am.usuario_id,
                        c.id AS cursada_id, c.numero_comision, c.fecha_desde_comision
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
                        COUNT(id)                                                             AS total_notas,
                        ROUND(AVG(nota)::numeric, 2)                                          AS promedio,
                        COUNT(id) FILTER (WHERE aprobado = TRUE)                              AS aprobadas,
                        COUNT(id) FILTER (WHERE aprobado = FALSE AND nota IS NOT NULL)         AS desaprobadas,
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
                    mc.nombre, mc.anio, mc.cuatrimestre, mc.anio_cursada,
                    mc.profesor1, mc.dias, mc.horario, mc.modalidad, mc.materia_id,
                    COALESCE(ev.total_notas, 0) AS total_notas,
                    ev.promedio,
                    COALESCE(ev.aprobadas, 0)    AS aprobadas,
                    COALESCE(ev.desaprobadas, 0) AS desaprobadas,
                    ev.detalle_notas,
                    mc.cursada_id, mc.numero_comision, mc.fecha_desde_comision
                FROM materias_cursando mc
                LEFT JOIN evals_usuario ev ON ev.materia_id = mc.materia_id
                ORDER BY mc.anio, mc.nombre;
            """, (usuario_id, anio_actual, cuatrimestre_para_query, usuario_id))
            materias_cursando = cur.fetchall()

            # ── Faltas por materia ───────────────────────────────────────
            cur.execute("""
                SELECT materia_id, COUNT(*)
                FROM asistencias
                WHERE usuario_id = %s
                GROUP BY materia_id;
            """, (usuario_id,))
            faltas_map = {r[0]: r[1] for r in cur.fetchall()}

            # ── Feriados ──────────────────────────────────────────────────
            cur.execute("""
                SELECT id, fecha, descripcion
                FROM feriados
                WHERE usuario_id = %s
                ORDER BY fecha;
            """, (usuario_id,))
            feriados_set = {r[1] for r in cur.fetchall()}

            # ── Tareas pendientes ────────────────────────────────────────
            cur.execute("""
                SELECT t.numero, t.descripcion, t.fecha_vencimiento, m.nombre
                FROM tareas t
                JOIN materias m ON t.materia_id = m.id
                WHERE t.usuario_id = %s AND t.completada = FALSE
                ORDER BY t.fecha_vencimiento ASC NULLS LAST;
            """, (usuario_id,))
            tareas = cur.fetchall()

            # ── Clases de hoy ─────────────────────────────────────────────
            cur.execute("""
                SELECT m.nombre, c.horario, c.link, c.modalidad, c.turno
                FROM cursadas c
                JOIN materias m ON c.materia_id = m.id
                JOIN alumno_materias am ON am.materia_id = m.id AND am.usuario_id = c.usuario_id
                WHERE c.usuario_id = %s
                AND am.estado = 'cursando'
                AND c.dias ILIKE %s;
            """, (usuario_id, f"%{dia_semana}%"))
            clases_hoy = cur.fetchall()

    return (total, aprobadas, cursando, regulares, desaprobadas, avance, configs,
            cuatrimestre_para_query, header_cuatrimestre, en_transicion,
            materias_cursando, faltas_map, feriados_set, tareas, clases_hoy)

# ─── Batch de Plan de Estudios (ítem prioridad alta, latencia de carga,
# 13/08/2026) ────────────────────────────────────────────────────────────
# Antes, pages/materias.py abría 3 conexiones fijas al pool antes de poder
# pintar nada: materias de la carrera (antes get_materias_carrera), estado
# de cada materia para el alumno (antes get_estados_alumno) y correlativas
# de toda la carrera (antes get_correlativas_carrera). Se consolida todo en
# una sola conexión, mismo criterio que get_home_data_completo (arriba) y
# get_cursadas_tab_data (cursadas.py): en Neon serverless el costo real es
# el round-trip de adquirir la conexión, no las queries en sí.
#
# Plan de Estudios es la segunda pantalla más visitada después de Home
# (es el punto de entrada para marcar una materia como cursando o
# aprobada), así que el ahorro de 3→1 conexiones tiene impacto directo en
# la experiencia de uso diario.
#
# Invalidación de caché: actualizar_estado_materia() (única función que
# escribe en alumno_materias) limpia este caché además del suyo propio.

@st.cache_data(ttl=60)
def get_materias_data_completo(usuario_id, carrera_id):
    """
    Devuelve, en una sola conexión, todo lo que necesita pages/materias.py
    para pintar el Plan de Estudios:
    (materias, estados_map, correlativas_map)
    - materias: [(id, nombre, anio, cuatrimestre, final_obligatorio, es_electiva), ...]
    - estados_map: {materia_id: estado} — estado del alumno para cada materia
    - correlativas_map: {materia_id: [(requiere_materia_id, requiere_nombre), ...]}
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            # ── Materias de la carrera ───────────────────────────────────
            cur.execute("""
                SELECT id, nombre, anio, cuatrimestre, final_obligatorio, es_electiva
                FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, cuatrimestre, nombre;
            """, (carrera_id,))
            materias = cur.fetchall()

            # ── Estado del alumno por materia ────────────────────────────
            cur.execute("""
                SELECT materia_id, estado
                FROM alumno_materias
                WHERE usuario_id = %s;
            """, (usuario_id,))
            estados_map = {r[0]: r[1] for r in cur.fetchall()}

            # ── Correlativas de toda la carrera ──────────────────────────
            cur.execute("""
                SELECT co.materia_id, r.id, r.nombre
                FROM correlatividades co
                JOIN materias m ON m.id = co.materia_id
                JOIN materias r ON r.id = co.requiere_materia_id
                WHERE m.carrera_id = %s
                ORDER BY r.anio, r.nombre;
            """, (carrera_id,))
            correlativas_map = {}
            for materia_id, requiere_id, requiere_nombre in cur.fetchall():
                correlativas_map.setdefault(materia_id, []).append((requiere_id, requiere_nombre))

    return materias, estados_map, correlativas_map

# ─── Backup de la base de datos (ítem prioridad alta, 09/08/2026) ──────────
# Dos formatos, ambos generados en Python puro (sin pg_dump, que no está
# garantizado en Streamlit Community Cloud):
#   - SQL: un .sql con INSERTs, restaurable con restaurar_backup_sql() de
#     acá abajo (ítem prioridad alta, 10/08/2026 — restauración por upsert).
#   - CSV: un .zip con un .csv por tabla, para inspeccionar en Excel/Sheets.
# Las dos funciones abren UNA sola conexión y recorren todas las tablas ahí
# adentro (mismo criterio que el resto del proyecto: en Neon serverless el
# costo real es el round-trip de adquirir la conexión, no las queries en sí).
#
# TABLAS_BACKUP está en orden de dependencias (tablas padre antes que hijas)
# para que el .sql se pueda ejecutar de arriba a abajo sin violar foreign
# keys. Se arma a mano en vez de vía introspección del catálogo de Postgres
# para no depender de que el esquema no tenga tablas ajenas al proyecto.
# El mismo orden, invertido, se usa para el borrado en modo espejo de
# restaurar_backup_sql() (hijas antes que padres, para no romper FKs).
TABLAS_BACKUP = [
    "carreras",
    "usuarios",
    "materias",
    "correlatividades",
    "alumno_materias",
    "codigos_invitacion",
    "recursos",
    "cursadas",
    "comisiones_historial",
    "evaluaciones",
    "tareas",
    "asistencias",
    "opiniones_profesores",
    "recomendaciones_terceros",
    "recomendaciones_terceros_materias",
    "programas",
    "configuracion_cuatrimestre",
    "feriados",
    "intentos_login",
]

def _fila_a_insert(tabla, columnas, fila, conn):
    """
    Arma un INSERT INTO ... VALUES (...) ON CONFLICT (id) DO UPDATE ... para
    una fila, escapando los valores de forma segura con psycopg.sql (misma
    librería que usa el resto del proyecto), sin depender de mogrify ni de
    armar el escapeo a mano.

    El ON CONFLICT (id) DO UPDATE (agregado 10/08/2026, ítem "Backup:
    importación/restauración") es lo que permite que restaurar_backup_sql()
    haga un upsert: si el id de la fila ya existe en la base viva, la
    actualiza con los valores del backup; si no existe, la inserta. Todas
    las tablas del proyecto usan "id SERIAL PRIMARY KEY" como primera
    columna, así que este criterio es uniforme en las 19 tablas de
    TABLAS_BACKUP.
    """
    columnas_sql = pgsql.SQL(", ").join(pgsql.Identifier(c) for c in columnas)
    valores_sql = pgsql.SQL(", ").join(pgsql.Literal(v) for v in fila)

    columnas_update = [c for c in columnas if c != "id"]
    if columnas_update:
        update_sql = pgsql.SQL(", ").join(
            pgsql.SQL("{} = EXCLUDED.{}").format(pgsql.Identifier(c), pgsql.Identifier(c))
            for c in columnas_update
        )
        conflicto_sql = pgsql.SQL(" ON CONFLICT (id) DO UPDATE SET {}").format(update_sql)
    else:
        # Caso borde: una tabla con solo la columna "id" no tendría nada que
        # actualizar — no pasa hoy en ninguna de las 19 tablas, pero se deja
        # cubierto por las dudas.
        conflicto_sql = pgsql.SQL(" ON CONFLICT (id) DO NOTHING")

    stmt = pgsql.SQL("INSERT INTO {} ({}) VALUES ({}){};").format(
        pgsql.Identifier(tabla), columnas_sql, valores_sql, conflicto_sql
    )
    return stmt.as_string(conn)

def generar_backup_sql():
    """
    Devuelve bytes de un .sql con un INSERT (upsert por id) por fila de cada
    tabla en TABLAS_BACKUP, envuelto en una transacción (BEGIN/COMMIT).

    Restauración: usar la sección "📥 Restaurar backup" de Administración
    (restaurar_backup_sql() de acá abajo), que sube este mismo archivo y lo
    corre fila por fila. También se puede ejecutar manualmente contra una
    base con el esquema ya creado (init_db()), aunque a mano se pierde el
    reporte de filas que fallaron y el modo espejo.

    Cada fila queda seguida por un comentario marcador con un delimitador
    único generado al vuelo (UUID), del tipo "-- END_STMT_<uuid> id=<id>".
    Este delimitador (no una simple línea en blanco) es lo que le permite a
    restaurar_backup_sql() reconstruir cada INSERT de forma confiable aunque
    algún campo de texto (una observación, una descripción) tenga un salto
    de línea real adentro: partir el archivo por saltos de línea sueltos no
    alcanzaría en ese caso, porque el INSERT ocuparía más de una línea física.
    """
    delimitador = f"END_STMT_{uuid.uuid4().hex}"
    lineas = [
        "-- PsicoNexo — Backup de base de datos",
        f"-- Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "-- Generado en Python con psycopg (no requiere pg_dump).",
        "-- Restaurar desde Administración → 📥 Restaurar backup (upsert por id,",
        "-- no borra nada salvo que actives el modo espejo).",
        f"-- Delimitador interno de restauración: {delimitador}",
        "",
        "BEGIN;",
        "",
    ]
    with get_conn() as conn:
        with conn.cursor() as cur:
            for tabla in TABLAS_BACKUP:
                cur.execute(pgsql.SQL("SELECT * FROM {};").format(pgsql.Identifier(tabla)))
                columnas = [desc[0] for desc in cur.description]
                filas = cur.fetchall()
                lineas.append(f"-- Tabla: {tabla} ({len(filas)} filas)")
                for fila in filas:
                    lineas.append(_fila_a_insert(tabla, columnas, fila, conn))
                    # fila[0] es el id: "id" es siempre la primera columna
                    # declarada en las 19 tablas de TABLAS_BACKUP.
                    lineas.append(f"-- {delimitador} id={fila[0]}")
                lineas.append("")
    lineas.append("COMMIT;")
    contenido = "\n".join(lineas)
    return contenido.encode("utf-8")

def generar_backup_csv_zip():
    """
    Devuelve bytes de un .zip con un archivo <tabla>.csv por cada tabla en
    TABLAS_BACKUP (encabezado con nombres de columna + todas las filas).
    Pensado para inspección en Excel/Sheets, no para restaurar directamente.
    """
    buffer_zip = BytesIO()
    with get_conn() as conn:
        with conn.cursor() as cur:
            with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for tabla in TABLAS_BACKUP:
                    cur.execute(pgsql.SQL("SELECT * FROM {};").format(pgsql.Identifier(tabla)))
                    columnas = [desc[0] for desc in cur.description]
                    filas = cur.fetchall()

                    csv_buffer = StringIO()
                    writer = csv.writer(csv_buffer)
                    writer.writerow(columnas)
                    writer.writerows(filas)
                    zf.writestr(f"{tabla}.csv", csv_buffer.getvalue())
    buffer_zip.seek(0)
    return buffer_zip.getvalue()

# ─── Restauración de backup (ítem prioridad alta, 10/08/2026) ─────────────
# Decisiones de diseño (charladas y confirmadas el 10/08/2026, ver
# PSICO_Mejoras_Pendientes.md):
#   1. Upsert por id, no "vaciar todo antes": una fila del backup cuyo id ya
#      existe en la base viva se ACTUALIZA con los valores del backup; si no
#      existe, se INSERTA. Por defecto no se borra nada que esté en la base
#      viva y no esté en el backup — restaurar un backup viejo no debe poder
#      borrar por accidente algo cargado después.
#   2. Fila por fila, no todo o nada: cada INSERT corre en su propio
#      SAVEPOINT (con conn.transaction(), que psycopg3 anida como SAVEPOINT
#      al estar ya dentro de una transacción abierta). Si una fila falla
#      (típicamente un choque de UNIQUE — email o legajo — con OTRO id), se
#      hace rollback de esa fila puntual y se sigue con las demás, en vez de
#      abortar toda la restauración por un error aislado.
#   3. Modo espejo (opcional, casilla aparte en la UI): además del upsert,
#      borra de cada tabla las filas cuyo id NO aparezca en el backup, para
#      dejar la base exactamente como estaba en el momento en que se generó
#      ese backup. Incluye el caso de una tabla con 0 filas en el backup —
#      ahí se vacía la tabla entera en la base viva. Se recorre
#      TABLAS_BACKUP en orden INVERSO (tablas hijas antes que padres) para
#      no romper foreign keys al borrar.

def _parsear_backup_sql(texto):
    """
    Parsea el contenido de un .sql generado por generar_backup_sql() y
    devuelve una lista de (tabla, id_str, statement_sql), en el mismo orden
    en que aparecen en el archivo. Lanza ValueError si el archivo no tiene
    el delimitador esperado (es decir, no es un backup de esta app).
    """
    m_delim = re.search(r"-- Delimitador interno de restauración:\s*(\S+)", texto)
    if not m_delim:
        raise ValueError(
            "No reconozco este archivo como un backup de PsicoNexo (falta el "
            "delimitador interno de restauración). Subí un .sql generado por "
            "el botón de backup de esta misma app."
        )
    delimitador = m_delim.group(1)
    marcador_re = re.compile(rf"^-- {re.escape(delimitador)} id=(\S+)$")

    filas_parseadas = []
    tabla_actual = None
    buffer_lineas = []
    for linea in texto.split("\n"):
        stripped = linea.strip()

        m_tabla = re.match(r"^-- Tabla:\s*(\w+)", stripped)
        if m_tabla:
            tabla_actual = m_tabla.group(1)
            continue

        m_marca = marcador_re.match(stripped)
        if m_marca:
            if buffer_lineas:
                stmt = "\n".join(buffer_lineas).strip()
                if stmt:
                    filas_parseadas.append((tabla_actual, m_marca.group(1), stmt))
            buffer_lineas = []
            continue

        buffer_lineas.append(linea)

    return filas_parseadas

def restaurar_backup_sql(contenido, modo_espejo=False):
    """
    Restaura un backup generado por generar_backup_sql(). Ver el bloque de
    comentarios de arriba para las tres decisiones de diseño.

    `contenido` puede ser bytes (tal cual entrega st.file_uploader) o str.

    Devuelve:
    {
        "ok_total": int,                          # filas insertadas/actualizadas
        "error_total": int,                        # filas que fallaron
        "errores": [(tabla, id_str, mensaje), ...], # detalle, hasta 50
        "borradas": int,                            # filas borradas (modo espejo)
    }
    """
    texto = contenido.decode("utf-8") if isinstance(contenido, (bytes, bytearray)) else contenido

    filas_parseadas = _parsear_backup_sql(texto)
    if not filas_parseadas:
        return {"ok_total": 0, "error_total": 0, "errores": [], "borradas": 0}

    ok_total = 0
    error_total = 0
    errores = []
    ids_por_tabla = {}

    with get_conn() as conn:
        with conn.cursor() as cur:
            for tabla, id_str, stmt in filas_parseadas:
                ids_por_tabla.setdefault(tabla, set()).add(id_str)
                try:
                    with conn.transaction():
                        cur.execute(stmt)
                    ok_total += 1
                except Exception as e:
                    error_total += 1
                    if len(errores) < 50:
                        errores.append((tabla, id_str, str(e)))

            borradas = 0
            if modo_espejo:
                for tabla in reversed(TABLAS_BACKUP):
                    ids_backup = ids_por_tabla.get(tabla, set())
                    try:
                        ids_int = [int(v) for v in ids_backup]
                    except ValueError:
                        # id no numérico: no debería pasar (todas las tablas
                        # usan SERIAL), pero por seguridad no tocamos esa
                        # tabla en vez de arriesgar un borrado mal dirigido.
                        continue
                    try:
                        with conn.transaction():
                            if ids_int:
                                cur.execute(
                                    pgsql.SQL("DELETE FROM {} WHERE id != ALL(%s);").format(
                                        pgsql.Identifier(tabla)
                                    ),
                                    (ids_int,),
                                )
                            else:
                                # Tabla sin ninguna fila en el backup: el
                                # modo espejo la vacía por completo.
                                cur.execute(pgsql.SQL("DELETE FROM {};").format(pgsql.Identifier(tabla)))
                            borradas += cur.rowcount
                    except Exception as e:
                        error_total += 1
                        if len(errores) < 50:
                            errores.append((tabla, "—", f"Error al borrar filas del modo espejo: {e}"))

        conn.commit()

    get_uso_almacenamiento.clear()
    return {"ok_total": ok_total, "error_total": error_total, "errores": errores, "borradas": borradas}
