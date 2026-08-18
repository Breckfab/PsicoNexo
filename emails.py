# emails.py

import os
import requests

# ─── Envío de emails vía Resend (ítem prioridad alta, 17/08/2026) ──────────
# Se eligió Resend por sobre SendGrid/SMTP de Gmail: API HTTP simple (no
# requiere SDK aparte, alcanza con `requests`, que ya es dependencia de
# otras librerías del proyecto), 3.000 emails/mes gratis (de sobra para uso
# personal) y no depende de habilitar "apps menos seguras" ni app passwords
# como sí exige Gmail SMTP.
#
# Variables de entorno necesarias (agregar en .env / en las Secrets de
# Streamlit Community Cloud):
#   RESEND_API_KEY = la API key generada en resend.com/api-keys
#   EMAIL_FROM     = remitente verificado, ej. "PsicoNexo <no-reply@tudominio.com>"
#                    Si todavía no verificaste un dominio propio en Resend,
#                    se puede usar el remitente de pruebas de Resend
#                    ("onboarding@resend.dev"), pero ese solo entrega a la
#                    casilla con la que te registraste en Resend — para
#                    mandarle emails a cualquier alumno hace falta verificar
#                    un dominio propio (gratis, se hace agregando registros
#                    DNS TXT/MX en el proveedor del dominio).

RESEND_API_URL = "https://api.resend.com/emails"


def _get_config():
    api_key = os.environ.get("RESEND_API_KEY")
    remitente = os.environ.get("EMAIL_FROM", "PsicoNexo <onboarding@resend.dev>")
    return api_key, remitente


def enviar_email(destinatario, asunto, html):
    """
    Envía un email vía la API HTTP de Resend.

    Devuelve (ok: bool, mensaje: str). No lanza excepciones hacia el
    llamador: cualquier error de red, de configuración o de la API de
    Resend se traduce a un mensaje legible, para que auth.py pueda decidir
    qué mostrarle al alumno sin tener que envolver cada llamada en un
    try/except propio.
    """
    api_key, remitente = _get_config()

    if not api_key:
        return False, (
            "No se pudo enviar el email: falta configurar RESEND_API_KEY "
            "en las variables de entorno."
        )

    try:
        respuesta = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": remitente,
                "to": [destinatario],
                "subject": asunto,
                "html": html,
            },
            timeout=10,
        )
    except requests.RequestException as e:
        return False, f"No se pudo conectar con Resend: {e}"

    if respuesta.status_code in (200, 201):
        return True, "Email enviado."

    return False, f"Resend devolvió un error ({respuesta.status_code}): {respuesta.text}"


def _layout_email(titulo, cuerpo_html, boton_texto=None, boton_link=None):
    """
    Envuelve el contenido de un email en un layout HTML simple con la
    identidad visual de PsicoNexo (violeta #7B2FBE, mismo tono que el resto
    de la app), para no tener que repetir el mismo bloque de estilos en
    cada función que arma un email distinto.
    """
    boton_html = ""
    if boton_texto and boton_link:
        boton_html = f"""
            <div style="text-align:center; margin:28px 0;">
                <a href="{boton_link}"
                   style="background-color:#7B2FBE; color:#ffffff; text-decoration:none;
                          padding:12px 28px; border-radius:8px; font-weight:bold;
                          font-size:15px; display:inline-block;">
                    {boton_texto}
                </a>
            </div>
        """

    return f"""
    <div style="font-family: Arial, sans-serif; max-width:480px; margin:0 auto;
                background-color:#1E1E2E; border-radius:12px; padding:32px 28px;
                color:#e0e0e0;">
        <div style="text-align:center; margin-bottom:20px;">
            <span style="font-size:24px; font-weight:bold; color:#ffffff;">🧠 PsicoNexo</span>
        </div>
        <h2 style="color:#ffffff; font-size:18px; margin-bottom:16px;">{titulo}</h2>
        <div style="font-size:14px; line-height:1.6; color:#cccccc;">
            {cuerpo_html}
        </div>
        {boton_html}
        <p style="font-size:12px; color:#888888; margin-top:28px; text-align:center;">
            Sistema para estudiantes de Psicología — PsicoNexo
        </p>
    </div>
    """


def enviar_email_recuperacion(destinatario, nombre, link_reset):
    """
    Arma y envía el email de recuperación de contraseña. El link ya viene
    armado desde auth.py (incluye el token como query param).
    """
    cuerpo = f"""
        <p>Hola {nombre},</p>
        <p>Recibimos una solicitud para restablecer tu contraseña en PsicoNexo.
        Si vos la pediste, tocá el botón de abajo para elegir una nueva.</p>
        <p>Este link vence en <strong>1 hora</strong>. Si no lo usás antes,
        vas a tener que pedir uno nuevo.</p>
        <p>Si no fuiste vos quien pidió esto, podés ignorar este email
        tranquilamente — tu contraseña no se va a modificar.</p>
    """
    html = _layout_email(
        "🔑 Recuperación de contraseña",
        cuerpo,
        boton_texto="Restablecer contraseña",
        boton_link=link_reset,
    )
    return enviar_email(destinatario, "PsicoNexo — Recuperación de contraseña", html)


def enviar_email_recordatorio_tarea(destinatario, nombre, materia_nombre, numero, descripcion, fecha_vencimiento):
    """
    Arma y envía el email de recordatorio de una tarea próxima a vencer.
    Usado por el script de recordatorios (ver comentario en auth.py /
    Mejoras Pendientes sobre cómo se dispara este envío).
    """
    desc_texto = descripcion or "Sin descripción"
    cuerpo = f"""
        <p>Hola {nombre},</p>
        <p>Te recordamos que tenés una tarea próxima a vencer:</p>
        <div style="background-color:#2a2a3e; border-radius:8px; padding:14px 18px; margin:16px 0;">
            <p style="margin:0 0 6px 0;"><strong>Materia:</strong> {materia_nombre}</p>
            <p style="margin:0 0 6px 0;"><strong>Tarea {numero}:</strong> {desc_texto}</p>
            <p style="margin:0; color:#e74c3c;"><strong>Vence:</strong> {fecha_vencimiento.strftime('%d/%m/%Y')}</p>
        </div>
        <p>Entrá a PsicoNexo para marcarla como completada o revisar el detalle.</p>
    """
    html = _layout_email("📌 Recordatorio de tarea", cuerpo)
    return enviar_email(
        destinatario, f"PsicoNexo — Recordatorio: {materia_nombre} vence pronto", html
    )
