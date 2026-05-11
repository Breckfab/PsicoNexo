import os
import psycopg
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
            universidad TEXT NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nombre TEXT NOT NULL,
            carrera_id INTEGER REFERENCES carreras(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        INSERT INTO carreras (nombre, universidad)
        VALUES ('Licenciatura en Psicología', 'UdeMM')
        ON CONFLICT DO NOTHING;
    """)

    conn.commit()
    cur.close()
    conn.close()
