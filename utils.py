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

from datetime import timedelta

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


def clasificar_asistencia(porcentaje):
    """Devuelve (color, negrita) según qué tan cerca está el alumno del límite del 75%."""
    if porcentaje >= 85:
        return "#2ecc71", False
    elif porcentaje >= 75:
        return "#f0c000", True
    else:
        return "#e74c3c", True
