# db.py - 20/09/2026

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

    # Links a las carpetas de la carrera en Google Drive y Dropbox (20/09/2026).
    # Un link por servicio, opcionales y editables desde Mi Perfil. Al vivir
    # en la tabla usuarios, el backup SQL/CSV ya los incluye sin tocar
    # TABLAS_BACKUP (generar_backup_* hacen SELECT * de cada tabla).
    cur.execute("""
        ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS link_google_drive TEXT;
    """)
    cur.execute("""
        ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS link_dropbox TEXT;
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

    # ── Rate limiting de recuperación de contraseña (ítem prioridad alta,
    # 28/08/2026) ────────────────────────────────────────────────────────
    # A diferencia de intentos_login, acá se registra CADA pedido de
    # recuperación (exista o no el email), para no delatar con el propio
    # rate limit qué emails están registrados. Ver el comentario completo
    # en auth.py, junto a solicitar_recuperacion().
    cur.execute("""
        CREATE TABLE IF NOT EXISTS intentos_recuperacion (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_intentos_recuperacion_email_fecha
        ON intentos_recuperacion (email, created_at);
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

# ─── Alta del admin inicial (ítem prioridad alta, 23/08/2026) ─────────────
# Antes la contraseña del admin estaba escrita en texto plano acá mismo
# ("Seamist123**"), visible para cualquiera que mire el código en GitHub
# (el repo es público). Ahora se lee desde ADMIN_INITIAL_PASSWORD, una
# variable de entorno / Secret que solo vos ves — el mismo criterio que ya
# se usa para DATABASE_URL, RESEND_API_KEY, etc.
#
# Esta función solo importa la PRIMERA vez que la app corre contra una base
# nueva (mientras no exista el usuario admin). Una vez creado, cambiá la
# contraseña desde tu perfil o directo en la base — ADMIN_INITIAL_PASSWORD
# no se vuelve a usar después de esa primera vez.
def crear_admin_si_no_existe():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE email = 'fabianbelledi@gmail.com';")
    if not cur.fetchone():
        password_inicial = os.environ.get("ADMIN_INITIAL_PASSWORD")
        if not password_inicial:
            # Sin la variable configurada no se crea el admin — mejor eso
            # que insertar una contraseña por defecto predecible en el código.
            print(
                "ADVERTENCIA: falta configurar ADMIN_INITIAL_PASSWORD en las "
                "Secrets. No se creó el usuario admin todavía."
            )
            cur.close()
            conn.close()
            return
        password_hash = bcrypt.hashpw(password_inicial.encode(), bcrypt.gensalt()).decode()
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
@st.cache_data(ttl=120)
def get_historial_comisiones(cursada_id):
    """
    Períodos CERRADOS de comisión de una cursada (no incluye el vigente,
    que vive en cursadas.numero_comision / cursadas.fecha_desde_comision).
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
    cerrados + el vigente).
    """
    historial = get_historial_comisiones(cursada_id)
    periodos = [(h[3], h[10], h[11]) for h in historial]
    periodos.append((dias_actual, fecha_desde_actual, None))
    return periodos

# ─── Uso de almacenamiento (Neon) ───────────────────────────────────────────
@st.cache_data(ttl=300)
def get_uso_almacenamiento():
    """Devuelve el tamaño actual de la base de datos, en bytes."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database());")
            return cur.fetchone()[0]

# ─── Batch principal de Home ────────────────────────────────────────────────
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

            cur.execute("""
                SELECT anio, cuatrimestre, fecha_inicio, fecha_fin
                FROM configuracion_cuatrimestre
                WHERE usuario_id = %s
                ORDER BY anio DESC, cuatrimestre;
            """, (usuario_id,))
            configs = {(r[0], r[1]): (r[2], r[3]) for r in cur.fetchall()}

            cuatrimestre_para_query, header_cuatrimestre, en_transicion = determinar_estado_cuatrimestre(
                anio_actual, configs
            )

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

            cur.execute("""
                SELECT materia_id, COUNT(*)
                FROM asistencias
                WHERE usuario_id = %s
                GROUP BY materia_id;
            """, (usuario_id,))
            faltas_map = {r[0]: r[1] for r in cur.fetchall()}

            cur.execute("""
                SELECT id, fecha, descripcion
                FROM feriados
                WHERE usuario_id = %s
                ORDER BY fecha;
            """, (usuario_id,))
            feriados_set = {r[1] for r in cur.fetchall()}

            cur.execute("""
                SELECT t.numero, t.descripcion, t.fecha_vencimiento, m.nombre
                FROM tareas t
                JOIN materias m ON t.materia_id = m.id
                WHERE t.usuario_id = %s AND t.completada = FALSE
                ORDER BY t.fecha_vencimiento ASC NULLS LAST;
            """, (usuario_id,))
            tareas = cur.fetchall()

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

# ─── Batch de Plan de Estudios ───────────────────────────────────────────────
@st.cache_data(ttl=60)
def get_materias_data_completo(usuario_id, carrera_id):
    """
    Devuelve, en una sola conexión, todo lo que necesita pages/materias.py
    para pintar el Plan de Estudios:
    (materias, estados_map, correlativas_map)
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, anio, cuatrimestre, final_obligatorio, es_electiva
                FROM materias
                WHERE carrera_id = %s
                ORDER BY anio, cuatrimestre, nombre;
            """, (carrera_id,))
            materias = cur.fetchall()

            cur.execute("""
                SELECT materia_id, estado
                FROM alumno_materias
                WHERE usuario_id = %s;
            """, (usuario_id,))
            estados_map = {r[0]: r[1] for r in cur.fetchall()}

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

# ─── Backup de la base de datos ──────────────────────────────────────────────
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
    "intentos_recuperacion",
]

def _fila_a_insert(tabla, columnas, fila, conn):
    """
    Arma un INSERT INTO ... VALUES (...) ON CONFLICT (id) DO UPDATE ... para
    una fila, escapando los valores de forma segura con psycopg.sql.
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
        conflicto_sql = pgsql.SQL(" ON CONFLICT (id) DO NOTHING")

    stmt = pgsql.SQL("INSERT INTO {} ({}) VALUES ({}){};").format(
        pgsql.Identifier(tabla), columnas_sql, valores_sql, conflicto_sql
    )
    return stmt.as_string(conn)

def generar_backup_sql():
    """
    Devuelve bytes de un .sql con un INSERT (upsert por id) por fila de cada
    tabla en TABLAS_BACKUP, envuelto en una transacción (BEGIN/COMMIT).
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
                    lineas.append(f"-- {delimitador} id={fila[0]}")
                lineas.append("")
    lineas.append("COMMIT;")
    contenido = "\n".join(lineas)
    return contenido.encode("utf-8")

def generar_backup_csv_zip():
    """
    Devuelve bytes de un .zip con un archivo <tabla>.csv por cada tabla en
    TABLAS_BACKUP.
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

def _parsear_backup_sql(texto):
    """
    Parsea el contenido de un .sql generado por generar_backup_sql() y
    devuelve una lista de (tabla, id_str, statement_sql).
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
    Restaura un backup generado por generar_backup_sql().
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
                                cur.execute(pgsql.SQL("DELETE FROM {};").format(pgsql.Identifier(tabla)))
                            borradas += cur.rowcount
                    except Exception as e:
                        error_total += 1
                        if len(errores) < 50:
                            errores.append((tabla, "—", f"Error al borrar filas del modo espejo: {e}"))

        conn.commit()

    get_uso_almacenamiento.clear()
    return {"ok_total": ok_total, "error_total": error_total, "errores": errores, "borradas": borradas}
