import os
import psycopg
from psycopg_pool import ConnectionPool
import bcrypt
from dotenv import load_dotenv
import streamlit as st
from contextlib import contextmanager

load_dotenv()

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
