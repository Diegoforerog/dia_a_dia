"""Ritual de cierre del día (estilo Sunsama).

- Muestra qué cumpliste hoy
- Actualiza rachas de hábitos
- Mueve tareas no hechas a mañana
- Pide reflexión corta

Uso:
  python scripts/cierre_noche.py
"""
from datetime import date, timedelta
from comun import cargar, cargar_registro_dia, guardar_registro_dia, guardar


def main() -> None:
    hoy = date.today().isoformat()
    ayer = (date.today() - timedelta(days=1)).isoformat()
    registro = cargar_registro_dia(hoy)
    actividades_data = cargar("actividades.json")
    habitos_data = cargar("habitos.json")

    completadas = registro["tareas_completadas"]
    cumplidos = registro["habitos_cumplidos"]

    print("\n" + "=" * 60)
    print(f"  🌙  CIERRE DEL DÍA — {hoy}")
    print("=" * 60)

    print(f"\n  ✅ Tareas cumplidas: {len(completadas)}")
    for t in actividades_data["actividades"]:
        if t["id"] in completadas:
            print(f"     • {t['titulo']}")

    print(f"\n  🎯 Hábitos cumplidos: {len(cumplidos)}/{len([h for h in habitos_data['habitos'] if h['activo']])}")

    # Actualizar rachas
    registro_ayer = cargar_registro_dia(ayer)
    ayer_cumplidos = set(registro_ayer.get("habitos_cumplidos", []))

    for h in habitos_data["habitos"]:
        if not h["activo"]:
            continue
        if h["id"] in cumplidos:
            if h["id"] in ayer_cumplidos:
                h["racha_actual"] += 1
            else:
                h["racha_actual"] = 1
            if h["racha_actual"] > h["mejor_racha"]:
                h["mejor_racha"] = h["racha_actual"]
            estado = f"🔥 racha: {h['racha_actual']}"
        else:
            if h["racha_actual"] > 0:
                estado = f"💔 racha rota (era {h['racha_actual']})"
            else:
                estado = "⚪️ no hecho"
            h["racha_actual"] = 0
        print(f"     • {h['nombre']} → {estado}")

    guardar("habitos.json", habitos_data)

    # Mover pendientes a mañana
    no_hechas = [
        a for a in actividades_data["actividades"]
        if a["estado"] == "pendiente" and a["id"] not in completadas
    ]
    if no_hechas:
        print(f"\n  ⏭️  Tareas que no se hicieron hoy ({len(no_hechas)}):")
        for a in no_hechas:
            print(f"     • {a['titulo']}")
        respuesta = input("\n¿Mover automáticamente a mañana? [s/n]: ").strip().lower()
        if respuesta in ("s", "si", ""):
            print("  ↪️  Quedarán visibles mañana automáticamente (siguen pendientes).")

    # Reflexión
    print("\n  ✍️  Reflexión rápida (puedes saltar con Enter):")
    notas = input("     ¿Qué aprendiste o qué fue lo mejor de hoy? > ").strip()
    if notas:
        registro["notas"] = notas

    registro["cerrado"] = True
    guardar_registro_dia(registro)

    pct_habitos = len(cumplidos) / max(1, len([h for h in habitos_data["habitos"] if h["activo"]])) * 100
    print(f"\n  📊 Cumplimiento de hábitos: {pct_habitos:.0f}%")
    print("\n  💤 Buen descanso. Mañana otra vez.\n")


if __name__ == "__main__":
    main()
