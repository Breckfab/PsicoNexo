"""
Constantes y funciones compartidas entre los distintos módulos de pages/.

Antes de este archivo, varias de estas definiciones estaban duplicadas
(a veces con leves variantes) en cursadas.py, home.py, materias.py,
evaluaciones.py, historial.py, profesores.py, recursos.py y estadisticas.py.
Centralizarlas acá evita que una corrección futura (por ejemplo, agregar un
6° año a la carrera) haya que replicarla en ocho lugares distintos.

No se modificó ningún comportamiento al migrar este contenido: los valores
y la lógica son exactamente los mismos que ya estaban en uso.
"""

from datetime import date, timedelta
import logging

# ─── Logging centralizado ───────────────────────────────────────────────────
# Antes, varios "except:" en el código atrapaban cualquier error y devolvían
# None en silencio (por ejemplo al convertir links de Drive/Dropbox), sin dejar
# rastro de qué falló ni por qué. Con este logger, esos casos quedan
# registrados (visibles en los logs de Streamlit Cloud) en vez de desaparecer.
logger = logging.getLogger("psiconexo")
if not logger.handlers:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

# ─── Nombres de año de carrera ─────────────────────────────────────────────
NOMBRES_ANIO = {1: "1° Año", 2: "2° Año", 3: "3° Año", 4: "4° Año", 5: "5° Año"}

# ─── Índice de día de la semana (usado para calcular asistencia) ──────────
DIA_INDEX = {"Lunes": 0, "Martes": 1, "Miércoles": 2, "Jueves": 3, "Viernes": 4, "Sábado": 5, "Domingo": 6}

# ─── Orden y texto corto de cuatrimestre ───────────────────────────────────
ORDEN_CUATRI = {"1° Cuatrimestre": 1, "2° Cuatrimestre": 2, "Anual": 3,
                "1": 1, "2": 2, "anual": 3}

CUATRI_TEXTO = {
    "1": "1° Cuat.",
    "2": "2° Cuat.",
    "anual": "Anual",
    "1° Cuatrimestre": "1° Cuat.",
    "2° Cuatrimestre": "2° Cuat.",
    "Anual": "Anual",
}

# ─── Iconos de estado de materia ───────────────────────────────────────────
# (incluye "pendiente" — el uso en historial.py, que antes no lo tenía,
# no se ve afectado porque siempre se accede con .get(estado, "⬜"))
COLORES = {
    "pendiente": "⬜",
    "cursando": "🟡",
    "regular": "🟠",
    "promocionada": "🟢",
    "aprobada": "🟢",
    "desaprobada": "🔴",
}


def determinar_estado_cuatrimestre(anio_actual, todas_configs):
    """
    Determina en qué cuatrimestre está el alumno en base a las FECHAS REALES
    configuradas por él (⚙️ Configurar fechas del cuatrimestre), en vez de un
    rango fijo de meses.

    Esto evita el bug de mostrar "1° Cuatrimestre" cuando en realidad ya
    terminó (por ejemplo, porque el alumno aprobó todo antes de la fecha de
    fin) y el 2° Cuatrimestre todavía no arrancó.

    Movida acá desde pages/home.py (ítem "Consolidar Home en una sola
    conexión", 12/08/2026): es una función pura (no toca la base), y
    db.py la necesita para resolver get_home_data_completo() sin tener
    que importar pages/home.py (lo que generaría un import circular, ya
    que home.py importa de db.py).

    Devuelve una tupla:
    - cuatrimestre_para_query: "1° Cuatrimestre" o "2° Cuatrimestre", el que
      se usa para buscar las materias que el alumno está cursando.
    - header_texto: texto a mostrar en el encabezado de la sección "Cursando".
    - en_transicion: True si estamos en un período sin cuatrimestre activo
      (uno finalizado y el otro sin empezar, o el año ya finalizado), para
      poder mostrar un mensaje distinto en vez del encabezado normal.
    """
    hoy = date.today()
    config_1 = todas_configs.get((anio_actual, "1° Cuatrimestre"))
    config_2 = todas_configs.get((anio_actual, "2° Cuatrimestre"))

    cuatri_1_finalizado = config_1 is not None and hoy > config_1[1]
    cuatri_2_no_empezo = config_2 is None or hoy < config_2[0]
    cuatri_2_finalizado = config_2 is not None and hoy > config_2[1]
    cuatri_2_en_curso = config_2 is not None and config_2[0] <= hoy <= config_2[1]
    cuatri_1_en_curso = config_1 is not None and config_1[0] <= hoy <= config_1[1]

    if cuatri_1_finalizado and cuatri_2_no_empezo:
        return (
            "2° Cuatrimestre",
            "PRIMER CUATRIMESTRE FINALIZADO — SEGUNDO CUATRIMESTRE NO HA COMENZADO AÚN",
            True,
        )

    if cuatri_2_finalizado:
        return (
            "2° Cuatrimestre",
            f"AÑO {anio_actual} FINALIZADO",
            True,
        )

    if cuatri_2_en_curso:
        return "2° Cuatrimestre", f"2° Cuatrimestre {anio_actual}", False

    if cuatri_1_en_curso:
        return "1° Cuatrimestre", f"1° Cuatrimestre {anio_actual}", False

    # Sin fechas configuradas todavía para ninguno de los dos: fallback al
    # heurístico anterior por mes, para no dejar al alumno sin nada mientras
    # carga las fechas por primera vez.
    mes = hoy.month
    cuatri_fallback = "1° Cuatrimestre" if 3 <= mes <= 7 else "2° Cuatrimestre"
    return cuatri_fallback, f"{cuatri_fallback} {anio_actual}", False


def contar_clases_en_rango(dias_str, fecha_inicio, fecha_fin, feriados=None):
    """Cuenta cuántas veces caen los días de cursada dentro del rango de fechas.
    `feriados`, si se pasa, es un set/conjunto de fechas (date) que se descuentan
    del conteo aunque coincidan con un día de cursada."""
    if not dias_str or not fecha_inicio or not fecha_fin or fecha_fin < fecha_inicio:
        return 0
    dias_lista = [d.strip() for d in dias_str.split(",") if d.strip()]
    indices = {DIA_INDEX[d] for d in dias_lista if d in DIA_INDEX}
    if not indices:
        return 0
    feriados = feriados or set()
    total = 0
    fecha = fecha_inicio
    while fecha <= fecha_fin:
        if fecha.weekday() in indices and fecha not in feriados:
            total += 1
        fecha += timedelta(days=1)
    return total


def contar_clases_multi_periodo(periodos, fecha_inicio_cuatri, fecha_fin_cuatri, feriados=None):
    """
    Suma las clases dictadas a lo largo de varios períodos de una misma
    cursada (uno por cada comisión por la que pasó el alumno), recortando
    cada período al rango real del cuatrimestre configurado.

    `periodos` es una lista de tuplas (dias_str, fecha_desde, fecha_hasta),
    donde fecha_hasta puede ser None para indicar "la comisión vigente"
    (se recorta con fecha_fin_cuatri). Se usa para que un cambio de
    comisión a mitad de cuatrimestre (ítem #6, 02/08/2026) no rompa el
    cálculo de asistencia: cada tramo cuenta sus propios días de cursada
    dentro de sus propias fechas, en vez de aplicar los días actuales a
    todo el cuatrimestre.
    """
    if not fecha_inicio_cuatri or not fecha_fin_cuatri:
        return 0
    total = 0
    for dias_str, p_desde, p_hasta in periodos:
        desde = max(p_desde, fecha_inicio_cuatri) if p_desde else fecha_inicio_cuatri
        hasta = min(p_hasta, fecha_fin_cuatri) if p_hasta else fecha_fin_cuatri
        if hasta < desde:
            continue
        total += contar_clases_en_rango(dias_str, desde, hasta, feriados)
    return total


def clasificar_asistencia(porcentaje):
    """Devuelve (color, negrita) según qué tan cerca está el alumno del límite del 75%."""
    if porcentaje >= 85:
        return "#2ecc71", False
    elif porcentaje >= 75:
        return "#f0c000", True
    else:
        return "#e74c3c", True


# ─── Conversión de links a vista previa (Drive / Dropbox) ──────────────────
# Esta función estaba duplicada de forma idéntica en cursadas.py (como
# convertir_link_drive, solo con el caso de Drive), materias.py y recursos.py
# (con Drive + Dropbox). Se centraliza acá para evitar que una corrección
# futura tenga que replicarse en los tres lugares, y además se reemplaza el
# "except: return None" silencioso por un log de advertencia: antes, si un
# link tenía un formato inesperado, la función fallaba en silencio y el
# usuario solo veía que no aparecía el botón de "Ver PDF", sin ninguna pista
# de qué había pasado.
def convertir_link_preview(link):
    """
    Intenta convertir un link de Google Drive o Dropbox a una URL de vista
    previa embebible. Devuelve None si el link no es de ninguno de esos
    servicios, o si tiene un formato inesperado que no se pudo interpretar
    (en ese caso, queda un warning en el log con el detalle del error).
    """
    if not link:
        return None

    if "drive.google.com" in link and "/file/d/" in link:
        try:
            file_id = link.split("/file/d/")[1].split("/")[0]
            return f"https://drive.google.com/file/d/{file_id}/preview"
        except Exception as e:
            logger.warning(f"No se pudo convertir link de Drive a preview: {link!r} — {e}")
            return None

    if "dropbox.com" in link:
        try:
            url = link.split("?")[0]
            return f"{url}?raw=1"
        except Exception as e:
            logger.warning(f"No se pudo convertir link de Dropbox a preview: {link!r} — {e}")
            return None

    return None
