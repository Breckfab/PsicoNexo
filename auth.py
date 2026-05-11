import bcrypt
import streamlit as st
from db import get_connection

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def get_carreras():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nombre, universidad FROM carreras ORDER BY nombre;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def register_user(email, password, nombre, carrera_id):
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

def login_user(email, password):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, password_hash, nombre, carrera_id FROM usuarios WHERE email = %s;",
        (email.lower().strip(),)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    if not user:
        return False, "Email no encontrado.", None
    if not verify_password(password, user[2]):
        return False, "Contraseña incorrecta.", None

    return True, "Login exitoso.", {
        "id": user[0],
        "email": user[1],
        "password_hash": user[2],
        "nombre": user[3],
        "carrera_id": user[4]
    }

def logout():
    for key in ["usuario", "pagina"]:
        if key in st.session_state:
            del st.session_state[key]
