import os
import psycopg
import bcrypt
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return psycopg.connect(os.environ["DATABASE_URL"])

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
            created_at TIMESTAMP DEFAULT NOW()
        );
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
