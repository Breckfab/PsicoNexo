import bcrypt
import streamlit as st
from db import get_conn
import secrets

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def get_carreras():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre, universidad FROM carreras ORDER BY nombre;")
            return cur.fetchall()

def verificar_codigo(codigo):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM codigos_invitacion WHERE codigo = %s AND usado = FALSE;", (codigo,))
            row = cur.fetchone()
    return row is not None

def marcar_codigo_usado(codigo, usuario_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE codigos_invitacion SET usado = TRUE, usado_por = %s
                WHERE codigo = %s;
            """, (usuario_id, codigo))
        conn.commit()

def register_user(email, password, nombre, carrera_id, codigo):
    if not verificar_codigo(codigo):
        return False, "Código de invitación inválido o ya usado."
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                password_hash = hash_password(password)
                cur.execute(
                    "INSERT INTO usuarios (email, password_hash, nombre, carrera_id) VALUES (%s, %s, %s, %s) RETURNING id;",
                    (email.lower().strip(), password_hash, nombre.strip(), carrera_id)
                )
                usuario_id = cur.fetchone()[0]
                conn.commit()
                marcar_codigo_usado(codigo, usuario_id)
                return True, "Registro exitoso."
            except Exception as e:
                conn.rollback()
                if "unique" in str(e).lower():
                    return False, "Ese email ya está registrado."
                return False, f"Error al registrar: {e}"

def login_user(email, password):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, nombre, carrera_id, es_admin, legajo FROM usuarios WHERE email = %s;",
                (email.lower().strip(),)
            )
            user = cur.fetchone()

    if not user:
        return False, "Email no encontrado.", None
    if not verify_password(password, user[2]):
        return False, "Contraseña incorrecta.", None

    return True, "Login exitoso.", {
        "id": user[0],
        "email": user[1],
        "password_hash": user[2],
        "nombre": user[3],
        "carrera_id": user[4],
        "es_admin": user[5],
        "legajo": user[6]
    }

def logout():
    for key in ["usuario", "pagina"]:
        if key in st.session_state:
            del st.session_state[key]

def generar_codigo(admin_id):
    codigo = secrets.token_hex(4).upper()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO codigos_invitacion (codigo, creado_por) VALUES (%s, %s);",
                (codigo, admin_id)
            )
        conn.commit()
    return codigo

def get_codigos(admin_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.codigo, c.usado, u.nombre as usado_por, c.created_at
                FROM codigos_invitacion c
                LEFT JOIN usuarios u ON c.usado_por = u.id
                WHERE c.creado_por = %s
                ORDER BY c.created_at DESC;
            """, (admin_id,))
            return cur.fetchall()
