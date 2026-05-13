import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return psycopg.connect(os.environ["DATABASE_URL"])

def seed():
    conn = get_connection()
    cur = conn.cursor()

    # Obtener carrera_id
    cur.execute("SELECT id FROM carreras WHERE nombre = 'Licenciatura en Psicología' AND universidad = 'UdeMM';")
    row = cur.fetchone()
    if not row:
        print("ERROR: No se encontró la carrera.")
        return
    carrera_id = row[0]

    # Verificar si ya fue cargado
    cur.execute("SELECT COUNT(*) FROM materias WHERE carrera_id = %s;", (carrera_id,))
    count = cur.fetchone()[0]
    if count > 0:
        print(f"Ya hay {count} materias cargadas. Saliendo.")
        return

    # Definición de materias
    # (codigo, nombre, anio, cuatrimestre, final_obligatorio, es_electiva)
    materias = [
        # AÑO 1 - 1er cuatrimestre
        ("H0200", "Psicología General I", 1, "1", False, False),
        ("H0002", "Bases Biológicas y Neurológicas del Comportamiento", 1, "1", False, False),
        ("H0003", "Historia de la Psicología", 1, "1", False, False),
        ("H0202", "Epistemología y Lógica", 1, "1", False, False),
        ("H0203", "Filosofía", 1, "1", False, False),
        ("H0009", "Fundamentos de Sociología", 1, "1", False, False),
        ("H0254", "Inglés I", 1, "1", False, False),
        # AÑO 1 - 2do cuatrimestre
        ("H0201", "Psicología General II", 1, "2", False, False),
        ("H0012", "Neuropsicología", 1, "2", False, False),
        ("H0004", "Teorías Psicológicas Contemporáneas", 1, "2", False, False),
        ("H0204", "Metodología de las Ciencias", 1, "2", False, False),
        ("H0205", "Antropología", 1, "2", False, False),
        ("H0013", "Psicología de la Personalidad", 1, "2", False, False),
        # AÑO 2 - 1er cuatrimestre
        ("H0235", "Fundamentos del Psicoanálisis I", 2, "1", False, False),
        ("H0206", "Psicología del Desarrollo I", 2, "1", False, False),
        ("H0208", "Cultura y Subjetividad", 2, "1", False, False),
        ("H0209", "Lenguaje y Comunicación", 2, "1", False, False),
        ("H0010", "Psicología Social", 2, "1", False, False),
        ("H0237", "Psicopatología I", 2, "1", False, False),
        ("H0255", "Inglés II", 2, "1", False, False),
        # AÑO 2 - 2do cuatrimestre
        ("H0238", "Psicopatología II", 2, "2", True, False),
        ("H0207", "Psicología del Desarrollo II", 2, "2", False, False),
        ("H0236", "Fundamentos del Psicoanálisis II", 2, "2", True, False),
        ("H0020", "Dinámica de Grupos", 2, "2", False, False),
        ("H0015", "Evaluación y Técnicas Psicológicas I", 2, "2", False, False),
        ("H0021", "Psicosociología Educacional", 2, "2", False, False),
        # AÑO 3 - 1er cuatrimestre
        ("H0239", "Psicoanálisis: Escuela Francesa", 3, "1", False, False),
        ("H0018", "Evaluación y Técnicas Psicológicas II", 3, "1", False, False),
        ("H0241", "Abordajes Actuales en Psicopatología", 3, "1", False, False),
        ("H0014", "Técnicas de Abordaje e Intervención en Crisis", 3, "1", False, False),
        ("H0243", "Observación y Práctica Profesional I: Abordaje Socio-educacional", 3, "1", False, False),
        ("H0023", "Psicología Organizacional", 3, "1", False, False),
        (None,    "Materia Electiva I", 3, "1", False, True),
        # AÑO 3 - 2do cuatrimestre
        ("H0240", "Intervenciones en Psicoanálisis", 3, "2", True, False),
        ("H0242", "Modelos y Estrategias de Intervención en Psicopatología", 3, "2", True, False),
        ("H0244", "Observación y Práctica Profesional II: Abordaje Socio-comunitario", 3, "2", False, False),
        ("H0019", "Evaluación y Técnicas Psicológicas III", 3, "2", False, False),
        ("H0022", "Psicología Jurídica", 3, "2", False, False),
        ("H0210", "Ética y Deontología Profesional", 3, "2", False, False),
        # AÑO 4 - 1er cuatrimestre
        ("H0211", "Métodos y Técnicas Psicoterapéuticas I", 4, "1", False, False),
        ("H0029", "Psicología Clínica de Niños y Adolescentes", 4, "1", False, False),
        ("H0213", "Psicología Preventiva y Salud Comunitaria I", 4, "1", False, False),
        ("H0256", "Computación", 4, "1", False, False),
        ("H0035", "Psicoterapia Familiar", 4, "1", False, False),
        ("H0245", "Observación y Práctica Profesional III: Clínica", 4, "1", False, False),
        # AÑO 4 - 2do cuatrimestre
        ("H0246", "Observación y Práctica Profesional IV: Institucional y Jurídica", 4, "2", False, False),
        ("H0232", "Práctica Profesional Supervisada I", 4, "2", True, False),
        ("H0033", "Orientación Vocacional y Ocupacional", 4, "2", False, False),
        ("H0214", "Psicología Preventiva y Salud Comunitaria II", 4, "2", False, False),
        ("H0030", "Psicología Clínica de Adultos", 4, "2", False, False),
        ("H0212", "Métodos y Técnicas Psicoterapéuticas II", 4, "2", False, False),
        # AÑO 5 - Anual
        ("H0257", "Trabajo Integrador Final", 5, "anual", True, False),
        ("H0233", "Práctica Profesional Supervisada II", 5, "anual", True, False),
        (None,    "Materia Electiva II", 5, "anual", False, True),
    ]

    # Insertar materias y guardar mapa nombre->id
    nombre_a_id = {}
    for (codigo, nombre, anio, cuatri, final_oblig, es_electiva) in materias:
        cur.execute(
            """INSERT INTO materias (carrera_id, codigo, nombre, anio, cuatrimestre, final_obligatorio, es_electiva)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;""",
            (carrera_id, codigo, nombre, anio, cuatri, final_oblig, es_electiva)
        )
        materia_id = cur.fetchone()[0]
        nombre_a_id[nombre] = materia_id

    # Definición de correlatividades (materia -> [lista de requisitos])
    correlatividades = {
        "Psicología General II": ["Psicología General I"],
        "Neuropsicología": ["Bases Biológicas y Neurológicas del Comportamiento"],
        "Teorías Psicológicas Contemporáneas": ["Historia de la Psicología"],
        "Metodología de las Ciencias": ["Epistemología y Lógica"],
        "Psicología de la Personalidad": ["Psicología General I"],
        "Fundamentos del Psicoanálisis I": ["Psicología General II", "Psicología de la Personalidad"],
        "Psicología del Desarrollo I": ["Psicología General II"],
        "Cultura y Subjetividad": ["Filosofía"],
        "Lenguaje y Comunicación": ["Psicología General II"],
        "Psicología Social": ["Fundamentos de Sociología"],
        "Psicopatología I": ["Psicología General II", "Psicología de la Personalidad"],
        "Inglés II": ["Inglés I"],
        "Psicopatología II": ["Psicopatología I"],
        "Psicología del Desarrollo II": ["Psicología del Desarrollo I"],
        "Fundamentos del Psicoanálisis II": ["Fundamentos del Psicoanálisis I"],
        "Dinámica de Grupos": ["Fundamentos de Sociología"],
        "Evaluación y Técnicas Psicológicas I": ["Psicología del Desarrollo I"],
        "Psicosociología Educacional": ["Fundamentos de Sociología"],
        "Psicoanálisis: Escuela Francesa": ["Fundamentos del Psicoanálisis II", "Lenguaje y Comunicación"],
        "Evaluación y Técnicas Psicológicas II": ["Evaluación y Técnicas Psicológicas I", "Fundamentos del Psicoanálisis II"],
        "Abordajes Actuales en Psicopatología": ["Psicopatología II"],
        "Técnicas de Abordaje e Intervención en Crisis": ["Psicopatología II"],
        "Observación y Práctica Profesional I: Abordaje Socio-educacional": [
            "Neuropsicología", "Teorías Psicológicas Contemporáneas", "Metodología de las Ciencias",
            "Antropología", "Cultura y Subjetividad", "Psicología Social", "Inglés II",
            "Psicopatología II", "Psicología del Desarrollo II", "Dinámica de Grupos",
            "Evaluación y Técnicas Psicológicas I", "Psicosociología Educacional"
        ],
        "Psicología Organizacional": ["Dinámica de Grupos"],
        "Materia Electiva I": [
            "Neuropsicología", "Teorías Psicológicas Contemporáneas", "Metodología de las Ciencias",
            "Antropología", "Cultura y Subjetividad", "Psicología Social", "Inglés II",
            "Psicopatología II", "Psicología del Desarrollo II", "Dinámica de Grupos",
            "Evaluación y Técnicas Psicológicas I", "Psicosociología Educacional"
        ],
        "Intervenciones en Psicoanálisis": ["Psicoanálisis: Escuela Francesa"],
        "Modelos y Estrategias de Intervención en Psicopatología": ["Abordajes Actuales en Psicopatología"],
        "Observación y Práctica Profesional II: Abordaje Socio-comunitario": ["Observación y Práctica Profesional I: Abordaje Socio-educacional"],
        "Evaluación y Técnicas Psicológicas III": ["Evaluación y Técnicas Psicológicas II"],
        "Psicología Jurídica": ["Fundamentos de Sociología", "Antropología"],
        "Ética y Deontología Profesional": ["Cultura y Subjetividad"],
        "Métodos y Técnicas Psicoterapéuticas I": ["Modelos y Estrategias de Intervención en Psicopatología"],
        "Psicología Clínica de Niños y Adolescentes": ["Psicología del Desarrollo I", "Modelos y Estrategias de Intervención en Psicopatología"],
        "Psicología Preventiva y Salud Comunitaria I": ["Modelos y Estrategias de Intervención en Psicopatología"],
        "Psicoterapia Familiar": ["Modelos y Estrategias de Intervención en Psicopatología", "Dinámica de Grupos"],
        "Observación y Práctica Profesional III: Clínica": ["Observación y Práctica Profesional II: Abordaje Socio-comunitario"],
        "Observación y Práctica Profesional IV: Institucional y Jurídica": ["Observación y Práctica Profesional III: Clínica"],
        "Práctica Profesional Supervisada I": [
            "Técnicas de Abordaje e Intervención en Crisis", "Psicología Organizacional",
            "Intervenciones en Psicoanálisis", "Evaluación y Técnicas Psicológicas III",
            "Psicología Jurídica", "Ética y Deontología Profesional",
            "Métodos y Técnicas Psicoterapéuticas I", "Psicología Clínica de Niños y Adolescentes",
            "Psicología Preventiva y Salud Comunitaria I", "Computación",
            "Psicoterapia Familiar", "Observación y Práctica Profesional III: Clínica"
        ],
        "Orientación Vocacional y Ocupacional": ["Evaluación y Técnicas Psicológicas II"],
        "Psicología Preventiva y Salud Comunitaria II": ["Psicología Preventiva y Salud Comunitaria I"],
        "Psicología Clínica de Adultos": ["Psicología Clínica de Niños y Adolescentes"],
        "Métodos y Técnicas Psicoterapéuticas II": ["Métodos y Técnicas Psicoterapéuticas I"],
        "Trabajo Integrador Final": [
            "Observación y Práctica Profesional IV: Institucional y Jurídica",
            "Práctica Profesional Supervisada I", "Orientación Vocacional y Ocupacional",
            "Psicología Preventiva y Salud Comunitaria II", "Psicología Clínica de Adultos",
            "Métodos y Técnicas Psicoterapéuticas II"
        ],
        "Práctica Profesional Supervisada II": ["Práctica Profesional Supervisada I"],
        "Materia Electiva II": [
            "Técnicas de Abordaje e Intervención en Crisis", "Psicología Organizacional",
            "Intervenciones en Psicoanálisis", "Observación y Práctica Profesional II: Abordaje Socio-comunitario",
            "Evaluación y Técnicas Psicológicas III", "Psicología Jurídica", "Ética y Deontología Profesional"
        ],
    }

    for materia_nombre, requisitos in correlatividades.items():
        materia_id = nombre_a_id.get(materia_nombre)
        if not materia_id:
            print(f"ADVERTENCIA: No se encontró materia '{materia_nombre}'")
            continue
        for req_nombre in requisitos:
            req_id = nombre_a_id.get(req_nombre)
            if not req_id:
                print(f"ADVERTENCIA: No se encontró requisito '{req_nombre}'")
                continue
            cur.execute(
                "INSERT INTO correlatividades (materia_id, requiere_materia_id) VALUES (%s, %s);",
                (materia_id, req_id)
            )

    conn.commit()
    cur.close()
    conn.close()
    print("✅ Materias y correlatividades cargadas correctamente.")

if __name__ == "__main__":
    seed()

