"""Genera un resumen del día de mañana y lo envía por Telegram.

Combina:
  • Eventos del calendario conectado (iCal)
  • Tareas pendientes con deadline mañana o sin deadline
  • Hábitos diarios sugeridos
  • Resumen narrativo generado por IA (gpt-4o-mini)

Uso:
  python3 scripts/resumen_manana.py
"""
import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import date, timedelta, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
from comun import cargar, cargar_env
cargar_env()

API_URL = "http://localhost:5050/api"
API_TOKEN = os.environ.get("ORGANIZADOR_TOKEN", "")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")


def get(ruta):
    """GET al API local con auth."""
    req = urllib.request.Request(
        API_URL + ruta,
        headers={"X-API-Token": API_TOKEN}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def telegram_send(texto, parse_mode="HTML"):
    """Envía mensaje al bot."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": int(CHAT_ID),
        "text": texto,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def generar_resumen_ia(datos):
    """Pide a gpt-4o-mini un resumen narrativo del día de mañana."""
    try:
        from openai import OpenAI
    except ImportError:
        return None

    cliente = OpenAI(api_key=OPENAI_KEY)
    sistema = """Eres el asistente personal de Diego, dropshipper colombiano. Te llamas Día a día.
Tu tarea: armar un RESUMEN breve y motivador de su día de mañana, en español, tono cercano y directo.

Reglas:
- Saluda mencionando el día de la semana de mañana.
- Si hay eventos del calendario, menciónalos en orden cronológico con su hora.
- Si hay tareas pendientes prioritarias, sugiere cuáles atacar primero.
- Si hay hábitos de la mañana, recuérdale arrancar con esos.
- Cierra con UNA frase corta motivadora (no cliché).
- Máximo 8-10 líneas. Conciso, directo, útil.
- NO inventes datos. Si no hay eventos, dilo natural."""

    usuario = f"""DATOS DE MAÑANA ({datos['fecha']}, {datos['dia_semana']}):

EVENTOS DEL CALENDARIO ({len(datos['eventos'])}):
{json.dumps(datos['eventos'], ensure_ascii=False, indent=2)}

TAREAS PENDIENTES (todas, ordenadas por prioridad):
{json.dumps(datos['tareas'], ensure_ascii=False, indent=2)}

HÁBITOS DIARIOS QUE TOCAN MAÑANA:
{json.dumps(datos['habitos'], ensure_ascii=False, indent=2)}

Arma el resumen para enviar por Telegram."""

    r = cliente.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": sistema},
            {"role": "user", "content": usuario}
        ],
        temperature=0.7,
    )
    return r.choices[0].message.content.strip()


def main():
    if not all([BOT_TOKEN, CHAT_ID, OPENAI_KEY]):
        print("❌ Faltan variables: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPENAI_API_KEY")
        sys.exit(1)

    manana = date.today() + timedelta(days=1)
    dias = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
    nombre_dia = dias[manana.weekday()]

    print(f"📅 Armando resumen para mañana: {nombre_dia} {manana.isoformat()}")

    # 1. eventos del calendario mañana
    eventos = []
    try:
        ev_raw = get(f"/calendarios/eventos_rango?desde={manana.isoformat()}&hasta={manana.isoformat()}")
        eventos = sorted([
            {
                "hora": e["start"][11:16] if not e.get("allDay") else "todo el día",
                "titulo": e["title"],
                "calendario": e.get("extendedProps", {}).get("calendario", ""),
                "ubicacion": e.get("extendedProps", {}).get("ubicacion", "")
            }
            for e in ev_raw if not e.get("title", "").startswith("⚠️")
        ], key=lambda x: x["hora"])
        print(f"  ✓ {len(eventos)} eventos")
    except Exception as e:
        print(f"  ⚠️  No se pudieron leer eventos: {e}")

    # 2. tareas pendientes
    tareas = []
    try:
        clientes = {c["id"]: c["nombre"] for c in get("/clientes")["clientes"]}
        t_raw = get("/tareas?estado=pendiente")
        for t in t_raw.get("actividades", []):
            tareas.append({
                "titulo": t["titulo"],
                "cliente": clientes.get(t.get("cliente_id"), "—"),
                "prioridad": t.get("prioridad", "media"),
                "deadline": t.get("deadline"),
                "duracion_min": t.get("duracion_min", 30)
            })
        # priorizar: alta > media > baja, deadline más cercano primero
        prio_orden = {"alta": 0, "media": 1, "baja": 2}
        tareas.sort(key=lambda x: (prio_orden.get(x["prioridad"], 3), x.get("deadline") or "9"))
        tareas = tareas[:8]
        print(f"  ✓ {len(tareas)} tareas pendientes (top 8)")
    except Exception as e:
        print(f"  ⚠️  No se pudieron leer tareas: {e}")

    # 3. hábitos diarios
    habitos = []
    try:
        h_raw = get("/habitos")
        cats = {c["id"]: c for c in h_raw.get("categorias", [])}
        for h in h_raw.get("habitos", []):
            if not h.get("activo"):
                continue
            if h.get("frecuencia") != "diaria":
                continue
            cat = cats.get(h.get("categoria_id"), {"nombre":"—","icono":"•"})
            habitos.append({
                "nombre": h["nombre"],
                "categoria": cat["nombre"],
                "horario_sugerido": h.get("horario_sugerido","mañana"),
                "duracion_min": h.get("duracion_min", 15)
            })
        print(f"  ✓ {len(habitos)} hábitos diarios")
    except Exception as e:
        print(f"  ⚠️  No se pudieron leer hábitos: {e}")

    # 4. IA arma el resumen
    datos = {
        "fecha": manana.isoformat(),
        "dia_semana": nombre_dia,
        "eventos": eventos,
        "tareas": tareas,
        "habitos": habitos
    }

    print("\n🧠 Generando resumen con gpt-4o-mini...")
    resumen_ia = generar_resumen_ia(datos)
    if not resumen_ia:
        print("❌ Falló la IA")
        sys.exit(1)

    print("\n--- Resumen IA ---")
    print(resumen_ia)
    print("--- fin ---\n")

    # 5. mensaje formateado para Telegram con sección estructurada
    cabecera = f"🌅 <b>Resumen para mañana — {nombre_dia.capitalize()} {manana.day}</b>\n\n"
    cuerpo = resumen_ia + "\n"

    detalle = ""
    if eventos:
        detalle += "\n📅 <b>Eventos del calendario</b>\n"
        for e in eventos:
            ubi = f" · 📍 {e['ubicacion']}" if e['ubicacion'] else ""
            detalle += f"<code>{e['hora']}</code>  {e['titulo']}{ubi}\n"

    if tareas:
        detalle += "\n📌 <b>Tareas pendientes</b>\n"
        for t in tareas[:5]:
            emoji = {"alta":"🔴","media":"🟡","baja":"⚪"}.get(t["prioridad"], "•")
            dl = f" · 📆 {t['deadline']}" if t.get("deadline") else ""
            detalle += f"{emoji} {t['titulo']} <i>· {t['cliente']}</i>{dl}\n"

    if habitos:
        manana_habs = [h for h in habitos if h["horario_sugerido"] == "mañana"]
        if manana_habs:
            detalle += "\n🌅 <b>Para la mañana</b>\n"
            for h in manana_habs:
                detalle += f"• {h['nombre']} <i>({h['duracion_min']} min)</i>\n"

    detalle += f"\n💬 Responde con tareas nuevas: <i>/tarea cliente | titulo</i>"

    mensaje = cabecera + cuerpo + detalle

    # 6. enviar
    print("📤 Enviando a Telegram...")
    r = telegram_send(mensaje)
    if r.get("ok"):
        print(f"✅ Mensaje enviado (id={r['result']['message_id']})")
    else:
        print(f"❌ Error: {r}")


if __name__ == "__main__":
    main()
