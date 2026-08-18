# enviar_recordatorios.py

"""
Script standalone (NO se ejecuta como parte de la app de Streamlit) que
manda por email los recordatorios de tareas próximas a vencer.

Por qué un script aparte: Streamlit Community Cloud no ofrece cron jobs ni
procesos en segundo plano — la app solo "vive" mientras alguien la tiene
abierta en el navegador. Para que el recordatorio llegue igual aunque el
alumno no haya entrado a la app ese día, este script se corre una vez por
día desde GitHub Actions (ver .github/workflows/recordatorios.yml), que sí
tiene su propio scheduler independiente de si la app está abierta o no.

Qué hace:
1. Se conecta directo a la base con psycopg (sin pasar por streamlit, para
   poder correr fuera del contexto de la app — get_conn()/get_pool() de
   db.py usan @st.cache_resource, que requiere runtime de Streamlit).
2. Busca tareas no completadas, con fecha_vencimiento entre hoy y mañana
   inclusive, que todavía no tengan recordatorio_enviado_at cargado.
3. Le manda un email a cada alumno dueño de esas tareas (uno por tarea,
   no agrupado — la mayoría de los alumnos van a tener 0-1 tareas por día
   en esta ventana, así que agrupar no aporta demasiado y complica el
   código).
4. Marca cada tarea avisada con recordatorio_enviado_at = NOW(), para no
   volver a avisar la próxima corrida.

Variables de entorno necesarias (las mismas que ya usa la app + RESEND):
  DATABASE_URL, RESEND_API_KEY, EMAIL_FROM
En GitHub Actions se configuran como Secrets del repo (Settings → Secrets
and variables → Actions), no se suben nunca en texto plano.
"""

import os
import sys
from datetime import date, timedelta

import psycopg

from emails import enviar_email_recordatorio_tarea

VENTANA_DIAS = 1  # avisa tareas que vencen hoy o mañana


def get_connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: falta la variable de entorno DATABASE_URL.")
        sys.exit(1)
    return psycopg.connect(database_url)


def buscar_tareas_a_avisar(conn):
    hoy = date.today()
    limite = hoy + timedelta(days=VENTANA_DIAS)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT t.id, t.numero, t.descripcion, t.fecha_vencimiento,
                   m.nombre AS materia_nombre,
                   u.email, u.nombre AS alumno_nombre
            FROM tareas t
            JOIN materias m ON t.materia_id = m.id
            JOIN usuarios u ON t.usuario_id = u.id
            WHERE t.completada = FALSE
              AND t.fecha_vencimiento BETWEEN %s AND %s
              AND t.recordatorio_enviado_at IS NULL;
        """, (hoy, limite))
        return cur.fetchall()


def marcar_avisada(conn, tarea_id):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tareas SET recordatorio_enviado_at = NOW() WHERE id = %s;",
            (tarea_id,)
        )
    conn.commit()


def main():
    conn = get_connection()
    tareas = buscar_tareas_a_avisar(conn)

    if not tareas:
        print("No hay tareas para avisar hoy.")
        conn.close()
        return

    enviados = 0
    fallidos = 0

    for (tarea_id, numero, descripcion, fecha_venc, materia_nombre,
         email, alumno_nombre) in tareas:
        ok, msg = enviar_email_recordatorio_tarea(
            email, alumno_nombre, materia_nombre, numero, descripcion, fecha_venc
        )
        if ok:
            marcar_avisada(conn, tarea_id)
            enviados += 1
            print(f"✅ Recordatorio enviado — tarea {tarea_id} ({materia_nombre}) a {email}")
        else:
            fallidos += 1
            print(f"❌ Falló el envío — tarea {tarea_id} ({materia_nombre}) a {email}: {msg}")

    conn.close()
    print(f"\nResumen: {enviados} enviado(s), {fallidos} fallido(s).")


if __name__ == "__main__":
    main()
