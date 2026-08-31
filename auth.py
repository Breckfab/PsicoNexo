# auth.py - 31/08/2026

import bcrypt
import streamlit as st
from db import get_conn
import secrets
from datetime import datetime, timedelta
from emails import enviar_email_recuperacion

# ─── Rate limiting de login ─────────────────────────────────────────────────
MAX_INTENTOS_FALLIDOS = 5
VENTANA_MINUTOS = 15

# ─── Recuperación de contraseña (ítem prioridad alta, 17/08/2026) ──────────
TOKEN_RESET_VENCE_MINUTOS = 60

# ─── Rate limiting de recuperación de contraseña (ítem prioridad alta,
# 28/08/2026) ────────────────────────────────────────────────────────────
# A diferencia del login (que solo cuenta intentos FALLIDOS — el éxito limpia
# el historial), acá no existe un "intento fallido": cada pedido de
# recuperación se registra siempre, exista o no el email en la base. Si solo
# contáramos los pedidos de emails que sí existen, el propio rate limit se
# podría usar para averiguar qué emails están registrados (pedir varias veces
# seguidas y ver si el sistema corta o no). Por eso el conteo es incondicional.
#
# Límite un poco más laxo que el de login (5 en vez de un número menor):
# acá no hay contraseña que se pueda tipear mal, así que no hace falta ser
# tan estricto, y de paso no molesta mientras se está probando el sistema.
MAX_INTENTOS_RECUPERACION = 5
VENTANA_MINUTOS_RECUPERACION = 15

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
    """
    Chequeo de solo lectura, ya sin uso dentro de register_user() desde el
    fix de la condición de carrera (31/08/2026) — se deja disponible por si
    en el futuro hace falta validar un código sin consumirlo (por ejemplo,
    un botón de "invalidar código" en el panel de Admin).
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM codigos_invitacion WHERE codigo = %s AND usado = FALSE;", (codigo,))
            row = cur.fetchone()
    return row is not None

def marcar_codigo_usado(codigo, usuario_id):
    """
    Igual que verificar_codigo(): ya no la usa register_user() (ver comentario
    ahí), se deja disponible para otros posibles llamadores futuros. OJO: a
    diferencia del UPDATE atómico de register_user(), esta versión NO chequea
    `usado = FALSE` en el WHERE, así que no sirve como candado de concurrencia
    por sí sola.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE codigos_invitacion SET usado = TRUE, usado_por = %s
                WHERE codigo = %s;
            """, (usuario_id, codigo))
        conn.commit()

# ─── Registro de usuario (fix condición de carrera, 31/08/2026) ────────────
# Antes: verificar_codigo() → INSERT usuarios → marcar_codigo_usado(), en 3
# pasos separados (3 conexiones/transacciones distintas). Si dos registros
# con el mismo código llegaban casi en simultáneo, los dos podían pasar la
# verificación antes de que cualquiera de los dos marcara el código como
# usado, y terminaban ambos registrados con el mismo código de invitación.
#
# Ahora: todo corre en una sola conexión y una sola transacción. El INSERT
# del usuario va primero (necesitamos el usuario_id para guardarlo en
# usado_por), y el candado de concurrencia real es el UPDATE de más abajo:
#
#   UPDATE codigos_invitacion SET usado = TRUE, usado_por = %s
#   WHERE codigo = %s AND usado = FALSE
#   RETURNING id;
#
# Postgres bloquea la fila del código durante ese UPDATE. Si dos registros
# llegan en simultáneo con el mismo código, uno de los dos gana la carrera y
# el otro, cuando le toca correr su propio UPDATE, ya encuentra la fila con
# usado = TRUE — su WHERE no matchea ninguna fila, RETURNING no devuelve
# nada, y se interpreta como "código inválido o ya usado". Se hace rollback
# de toda la transacción (incluyendo el INSERT del usuario, que también
# queda deshecho), así que no se puede quedar un usuario creado sin un
# código válido detrás.
def register_user(email, password, nombre, carrera_id, codigo):
    codigo_norm = codigo.strip()
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                password_hash = hash_password(password)
                cur.execute(
                    "INSERT INTO usuarios (email, password_hash, nombre, carrera_id) VALUES (%s, %s, %s, %s) RETURNING id;",
                    (email.lower().strip(), password_hash, nombre.strip(), carrera_id)
                )
                usuario_id = cur.fetchone()[0]

                cur.execute("""
                    UPDATE codigos_invitacion
                    SET usado = TRUE, usado_por = %s
                    WHERE codigo = %s AND usado = FALSE
                    RETURNING id;
                """, (usuario_id, codigo_norm))
                fila_codigo = cur.fetchone()

                if not fila_codigo:
                    # El código no existe, o alguien más lo consumió en el
                    # instante entre que este alumno lo tipeó y confirmó el
                    # formulario. Se deshace todo, incluido el INSERT del
                    # usuario de más arriba.
                    conn.rollback()
                    return False, "Código de invitación inválido o ya usado."

                conn.commit()
                return True, "Registro exitoso."
            except Exception as e:
                conn.rollback()
                if "unique" in str(e).lower():
                    return False, "Ese email ya está registrado."
                return False, f"Error al registrar: {e}"

# ─── Rate limiting: helpers (login) ─────────────────────────────────────────

def _contar_intentos_fallidos_recientes(email):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM intentos_login
                WHERE email = %s AND created_at > NOW() - make_interval(mins => %s);
            """, (email, VENTANA_MINUTOS))
            return cur.fetchone()[0]

def _registrar_intento_fallido(email):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO intentos_login (email) VALUES (%s);", (email,))
        conn.commit()

def _limpiar_intentos_fallidos(email):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM intentos_login WHERE email = %s;", (email,))
        conn.commit()

def login_user(email, password):
    email_norm = email.lower().strip()

    intentos = _contar_intentos_fallidos_recientes(email_norm)
    if intentos >= MAX_INTENTOS_FALLIDOS:
        return False, (
            f"Demasiados intentos fallidos. Por seguridad, esperá unos minutos "
            f"antes de volver a intentar."
        ), None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, password_hash, nombre, carrera_id, es_admin, legajo FROM usuarios WHERE email = %s;",
                (email_norm,)
            )
            user = cur.fetchone()

    if not user:
        _registrar_intento_fallido(email_norm)
        return False, "Email no encontrado.", None
    if not verify_password(password, user[2]):
        _registrar_intento_fallido(email_norm)
        return False, "Contraseña incorrecta.", None

    _limpiar_intentos_fallidos(email_norm)
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

# ─── Rate limiting: helpers (recuperación de contraseña, 28/08/2026) ───────

def _contar_intentos_recuperacion_recientes(email):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM intentos_recuperacion
                WHERE email = %s AND created_at > NOW() - make_interval(mins => %s);
            """, (email, VENTANA_MINUTOS_RECUPERACION))
            return cur.fetchone()[0]

def _registrar_intento_recuperacion(email):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO intentos_recuperacion (email) VALUES (%s);", (email,))
        conn.commit()

# ─── Recuperación de contraseña (ítem prioridad alta, 17/08/2026) ──────────
# Flujo: el alumno pide recuperación con su email → se genera un token de un
# solo uso con vencimiento de 1 hora → se manda por email (vía Resend, ver
# emails.py) un link a la app con el token como query param
# (?reset_token=...) → app.py detecta ese query param y muestra el
# formulario de nueva contraseña → al confirmar, se valida el token acá y
# se actualiza el hash.
#
# Deliberadamente NO se le informa al usuario si el email existe o no en la
# base (mensaje siempre igual, "Si el email existe..."), para no filtrar
# qué emails están registrados en el sistema a quien esté probando.

def solicitar_recuperacion(email, base_url):
    """
    Genera un token de recuperación para `email` (si existe un usuario con
    ese email) y le manda el link de reseteo por email. `base_url` es la
    URL pública de la app (ej. "https://psiconexo.streamlit.app"), para
    armar el link completo.

    Devuelve siempre (True, mensaje_generico) salvo error real al mandar el
    email de un usuario que sí existe, o que se haya cortado por rate limit
    — así no se filtra si el email está registrado o no.

    Rate limiting (ítem prioridad alta, 28/08/2026): el conteo de intentos
    es INCONDICIONAL, se registra tanto si el email existe como si no. Si
    solo contáramos los pedidos de emails existentes, el propio rate limit
    serviría para deducir qué emails están registrados (pedir varias veces
    seguidas y ver si el sistema corta o no).
    """
    email_norm = email.lower().strip()
    mensaje_generico = (
        "Si el email está registrado, te mandamos un link para restablecer "
        "tu contraseña. Revisá tu bandeja de entrada (y la carpeta de spam)."
    )

    intentos = _contar_intentos_recuperacion_recientes(email_norm)
    if intentos >= MAX_INTENTOS_RECUPERACION:
        # Mismo mensaje genérico de siempre — no delatamos que se cortó por
        # rate limit, para no darle a un atacante una señal distinta según
        # si el email existe o no.
        return True, mensaje_generico

    _registrar_intento_recuperacion(email_norm)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM usuarios WHERE email = %s;", (email_norm,))
            user = cur.fetchone()

    if not user:
        # No existe el usuario: devolvemos el mismo mensaje genérico, sin
        # generar token ni mandar nada, para no filtrar qué emails existen.
        return True, mensaje_generico

    usuario_id, nombre = user
    token = secrets.token_urlsafe(32)
    expira = datetime.now() + timedelta(minutes=TOKEN_RESET_VENCE_MINUTOS)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO password_reset_tokens (usuario_id, token, expires_at)
                VALUES (%s, %s, %s);
            """, (usuario_id, token, expira))
        conn.commit()

    link_reset = f"{base_url.rstrip('/')}/?reset_token={token}"
    ok_envio, msg_envio = enviar_email_recuperacion(email_norm, nombre, link_reset)

    if not ok_envio:
        # El token ya quedó guardado en la base igual (no hace daño), pero
        # avisamos del error real de envío en vez del mensaje genérico, para
        # que quede claro que algo falló del lado del proveedor de email
        # (útil sobre todo en desarrollo, mientras se prueba la integración).
        return False, f"No se pudo enviar el email de recuperación: {msg_envio}"

    return True, mensaje_generico

def verificar_token_reset(token):
    """
    Devuelve (usuario_id, nombre) si el token es válido (existe, no usado,
    no vencido), o None si no lo es.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.usuario_id, u.nombre
                FROM password_reset_tokens p
                JOIN usuarios u ON u.id = p.usuario_id
                WHERE p.token = %s AND p.usado = FALSE AND p.expires_at > NOW();
            """, (token,))
            row = cur.fetchone()
    return row

def resetear_password(token, nueva_password):
    """
    Valida el token y, si es válido, actualiza la contraseña del usuario y
    marca el token como usado (para que no se pueda reutilizar el mismo
    link). Devuelve (ok: bool, mensaje: str).
    """
    datos = verificar_token_reset(token)
    if not datos:
        return False, "Este link ya no es válido. Puede haber vencido o ya haber sido usado — pedí uno nuevo."

    usuario_id, _nombre = datos
    password_hash = hash_password(nueva_password)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE usuarios SET password_hash = %s WHERE id = %s;",
                (password_hash, usuario_id)
            )
            cur.execute(
                "UPDATE password_reset_tokens SET usado = TRUE WHERE token = %s;",
                (token,)
            )
        conn.commit()

    return True, "Contraseña actualizada correctamente. Ya podés iniciar sesión."
