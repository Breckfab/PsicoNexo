import bcrypt
import streamlit as st
from db import get_connection

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def get_carreras():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nombre, universidad FROM carreras ORDER BY nombre;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def register_user(email: str, password: str, nombre: str, carrera_id: int) -> tuple[bool, str]:
    conn = get_connection()
    cur = conn.cursor()
    try:
        password_hash = hash_password(password)
        cur.execute(
            "INSERT INTO usuarios (email, password_hash, nombre, carrera_id) VALUES (%s, %s, %s, %s);",
            (email.lower().strip(), password_hash, nombre.strip(), carrera_id)
        )
        conn.commit()
        return True, "Registro exitoso."
    except Exception as e:
        conn.rollback()
        if "unique" in str(e).lower():
            return False, "Ese email ya está registrado."
        return False, f"Error al registrar: {e}"
    finally:
        cur.close()
        conn.close()

def login_user(email: str, password: str) -> tuple[bool, str, dict | None]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, password_hash, nombre, carrera_id FROM usuarios WHERE email =
