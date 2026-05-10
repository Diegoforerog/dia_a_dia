"""CLI rápido para agregar tareas, proyectos, hábitos o empresas.

Uso:
  python scripts/agregar.py tarea
  python scripts/agregar.py proyecto
  python scripts/agregar.py habito
  python scripts/agregar.py empresa
"""
import sys
from datetime import datetime
from comun import cargar, guardar, nuevo_id


def pedir(texto: str, default: str = "") -> str:
    sufijo = f" [{default}]" if default else ""
    respuesta = input(f"{texto}{sufijo}: ").strip()
    return respuesta or default


def listar_opciones(items: list, etiqueta: str = "nombre") -> None:
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item.get(etiqueta, item.get('id', '?'))}")


def elegir(items: list, mensaje: str, etiqueta: str = "nombre") -> dict:
    listar_opciones(items, etiqueta)
    while True:
        try:
            idx = int(input(f"{mensaje} (1-{len(items)}): ")) - 1
            if 0 <= idx < len(items):
                return items[idx]
        except ValueError:
            pass
        print("  Opción inválida.")


def agregar_tarea() -> None:
    empresas = cargar("empresas.json")["empresas"]
    proyectos_data = cargar("proyectos.json")
    proyectos = proyectos_data["proyectos"]
    actividades_data = cargar("actividades.json")

    print("\n📌 NUEVA TAREA")
    print("\n¿A qué empresa pertenece?")
    empresa = elegir(empresas, "Empresa")

    proyectos_empresa = [p for p in proyectos if p["empresa_id"] == empresa["id"]]
    if proyectos_empresa:
        print(f"\n¿Proyecto dentro de {empresa['nombre']}?")
        print("  0. (Sin proyecto / general)")
        listar_opciones(proyectos_empresa)
        idx = input(f"Proyecto (0-{len(proyectos_empresa)}): ").strip()
        proyecto_id = proyectos_empresa[int(idx) - 1]["id"] if idx and idx != "0" else None
    else:
        proyecto_id = None

    titulo = pedir("\nTítulo de la tarea")
    prioridad = pedir("Prioridad (alta/media/baja)", "media")
    duracion = pedir("Duración estimada en minutos", "30")
    deadline = pedir("Deadline YYYY-MM-DD (vacío = sin fecha)")
    notas = pedir("Notas (opcional)")

    nueva = {
        "id": nuevo_id("tarea"),
        "empresa_id": empresa["id"],
        "proyecto_id": proyecto_id,
        "titulo": titulo,
        "prioridad": prioridad,
        "duracion_min": int(duracion),
        "deadline": deadline or None,
        "notas": notas,
        "estado": "pendiente",
        "creada": datetime.now().isoformat()
    }
    actividades_data["actividades"].append(nueva)
    guardar("actividades.json", actividades_data)
    print(f"\n✅ Tarea agregada: {titulo}")


def agregar_proyecto() -> None:
    empresas = cargar("empresas.json")["empresas"]
    proyectos_data = cargar("proyectos.json")

    print("\n🗂️  NUEVO PROYECTO")
    print("\n¿A qué empresa pertenece?")
    empresa = elegir(empresas, "Empresa")

    nombre = pedir("Nombre del proyecto")
    prioridad = pedir("Prioridad (alta/media/baja)", "media")
    deadline = pedir("Deadline YYYY-MM-DD (opcional)")
    descripcion = pedir("Descripción breve")

    nuevo = {
        "id": nuevo_id("proy"),
        "empresa_id": empresa["id"],
        "nombre": nombre,
        "estado": "activo",
        "prioridad": prioridad,
        "deadline": deadline or None,
        "descripcion": descripcion
    }
    proyectos_data["proyectos"].append(nuevo)
    guardar("proyectos.json", proyectos_data)
    print(f"\n✅ Proyecto agregado: {nombre}")


def agregar_habito() -> None:
    habitos_data = cargar("habitos.json")
    categorias = habitos_data["categorias"]

    print("\n🎯 NUEVO HÁBITO")
    print("\n¿Qué categoría?")
    cat = elegir(categorias, "Categoría")

    nombre = pedir("Nombre del hábito")
    frecuencia = pedir("Frecuencia (diaria/semanal)", "diaria")
    horario = pedir("Horario sugerido (mañana/tarde/noche/todo el día)", "mañana")
    duracion = pedir("Duración en minutos", "15")

    nuevo = {
        "id": nuevo_id("hab"),
        "categoria_id": cat["id"],
        "nombre": nombre,
        "frecuencia": frecuencia,
        "horario_sugerido": horario,
        "duracion_min": int(duracion),
        "activo": True,
        "racha_actual": 0,
        "mejor_racha": 0
    }
    habitos_data["habitos"].append(nuevo)
    guardar("habitos.json", habitos_data)
    print(f"\n✅ Hábito agregado: {nombre}")


def agregar_empresa() -> None:
    empresas_data = cargar("empresas.json")
    print("\n🏢 NUEVA EMPRESA / ÁREA")
    nombre = pedir("Nombre")
    descripcion = pedir("Descripción breve")
    color = pedir("Color hex (ej: #FF6B35)", "#888888")

    nueva = {
        "id": nombre.lower().replace(" ", "_")[:30],
        "nombre": nombre,
        "color": color,
        "descripcion": descripcion,
        "activo": True
    }
    empresas_data["empresas"].append(nueva)
    guardar("empresas.json", empresas_data)
    print(f"\n✅ Empresa agregada: {nombre}")


COMANDOS = {
    "tarea": agregar_tarea,
    "proyecto": agregar_proyecto,
    "habito": agregar_habito,
    "empresa": agregar_empresa,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMANDOS:
        print("Uso: python scripts/agregar.py [tarea|proyecto|habito|empresa]")
        sys.exit(1)
    COMANDOS[sys.argv[1]]()


if __name__ == "__main__":
    main()
