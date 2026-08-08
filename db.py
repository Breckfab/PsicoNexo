import os
import psycopg
from psycopg_pool import ConnectionPool
import bcrypt
from dotenv import load_dotenv
import streamlit as st
from contextlib import contextmanager
from datetime import datetime

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

def borrar_feriado(feriado_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM feriados WHERE id = %s;", (feriado_id,))
        conn.commit()
    get_feriados.clear()

# ─── Clases de hoy ──────────────────────────────────────────────────────────
# Antes estaba duplicada, con SQL casi idéntico, en cursadas.py y home.py
# (ítem de prioridad media, "Revisar duplicación de queries entre cursadas.py
# y home.py", 27/07/2026). Se centraliza acá con la versión que incluye
# `turno`, que es la más completa de las dos. Los llamadores que no necesiten
# el turno simplemente ignoran ese valor al desempaquetar la tupla.

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
