"""Envía tu plan del día por Telegram.

Setup:
  Ver integraciones/README_telegram.md

Uso:
  python scripts/enviar_telegram.py
"""
import urllib.request
import urllib.parse
import json
from datetime import date
from comun import cargar, cargar_registro_dia


def construir_mensaje(plan: dict, fecha: str) -> str:
    if not plan:
        return f"No hay plan generado para {fecha}."
    lineas = [f"*☀️ Plan del día — {fecha}*", "", plan.get("saludo", ""), ""]
    for b in plan.get("bloques", []):
        icono = {"tarea": "📌", "habito": "🎯", "descanso": "☕"}.get(b.get("tipo", ""), "•")
        lineas.append(f"`{b.get('hora','')}` {icono} *{b.get('titulo','')}*")
        if b.get("empresa"):
            lineas.append(f"     _{b['empresa']} · {b.get('duracion_min',0)} min_")
        if b.get("razon"):
            lineas.append(f"     💡 {b['razon']}")
        lineas.append("")
    if plan.get("advertencia"):
        lineas.append(f"⚠️ {plan['advertencia']}")
    if plan.get("frase_cierre"):
        lineas.append(f"\n🏁 _{plan['frase_cierre']}_")
    return "\n".join(lineas)


def main() -> None:
    config = cargar("config.json")["telegram"]
    if not config["bot_token"] or not config["chat_id"]:
        print("⚠️  Configura bot_token y chat_id en datos/config.json")
        print("    Ver integraciones/README_telegram.md")
        raise SystemExit(1)

    hoy = date.today().isoformat()
    registro = cargar_registro_dia(hoy)
    plan = registro.get("plan_generado")
    mensaje = construir_mensaje(plan, hoy)

    url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
    datos = urllib.parse.urlencode({
        "chat_id": config["chat_id"],
        "text": mensaje,
        "parse_mode": "Markdown"
    }).encode()

    with urllib.request.urlopen(url, data=datos) as r:
        resultado = json.loads(r.read())
        if resultado.get("ok"):
            print("✅ Plan enviado por Telegram")
        else:
            print(f"❌ Error: {resultado}")


if __name__ == "__main__":
    main()
