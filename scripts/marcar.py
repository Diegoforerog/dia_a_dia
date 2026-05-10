"""Marcar tareas hechas o hábitos cumplidos en el registro del día.

Uso:
  python scripts/marcar.py
"""
from datetime import date
from comun import cargar, cargar_registro_dia, guardar_registro_dia, guardar


def main() -> None:
    hoy = date.today().isoformat()
    registro = cargar_registro_dia(hoy)
    actividades_data = cargar("actividades.json")
    habitos_data = cargar("habitos.json")

    pendientes = [a for a in actividades_data["actividades"] if a["estado"] == "pendiente"]
    habitos = [h for h in habitos_data["habitos"] if h["activo"]]

    print(f"\n📅 Registro del {hoy}\n")
    print("=" * 50)
    print("\n📌 TAREAS PENDIENTES")
    for i, t in enumerate(pendientes, 1):
        marca = "✅" if t["id"] in registro["tareas_completadas"] else "⬜"
        print(f"  {marca} {i}. {t['titulo']} ({t['prioridad']})")

    print("\n🎯 HÁBITOS DE HOY")
    for i, h in enumerate(habitos, 1):
        marca = "✅" if h["id"] in registro["habitos_cumplidos"] else "⬜"
        cat = next((c['icono'] for c in habitos_data['categorias'] if c['id'] == h['categoria_id']), "")
        print(f"  {marca} {i}. {cat} {h['nombre']}")

    print("\n" + "=" * 50)
    print("\nEscribe qué quieres marcar:")
    print("  t1, t2... → marcar/desmarcar tarea")
    print("  h1, h2... → marcar/desmarcar hábito")
    print("  fin → guardar y salir")

    while True:
        cmd = input("\n> ").strip().lower()
        if cmd in ("fin", "q", "salir", ""):
            break
        try:
            tipo = cmd[0]
            idx = int(cmd[1:]) - 1
            if tipo == "t" and 0 <= idx < len(pendientes):
                tid = pendientes[idx]["id"]
                if tid in registro["tareas_completadas"]:
                    registro["tareas_completadas"].remove(tid)
                    print(f"  ⬜ Desmarcada: {pendientes[idx]['titulo']}")
                else:
                    registro["tareas_completadas"].append(tid)
                    print(f"  ✅ Marcada: {pendientes[idx]['titulo']}")
            elif tipo == "h" and 0 <= idx < len(habitos):
                hid = habitos[idx]["id"]
                if hid in registro["habitos_cumplidos"]:
                    registro["habitos_cumplidos"].remove(hid)
                    print(f"  ⬜ Desmarcado: {habitos[idx]['nombre']}")
                else:
                    registro["habitos_cumplidos"].append(hid)
                    print(f"  ✅ Cumplido: {habitos[idx]['nombre']}")
            else:
                print("  Índice fuera de rango.")
        except (ValueError, IndexError):
            print("  Formato inválido. Usa t1, h2, etc.")

    guardar_registro_dia(registro)
    print(f"\n💾 Registro guardado en datos/registros/{hoy}.json")


if __name__ == "__main__":
    main()
