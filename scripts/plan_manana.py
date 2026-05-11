"""Plan del día con IA (gpt-4o-mini) — soporta cualquier fecha.

Considera:
  • Eventos del calendario (iCal) — bloques que NO se pueden tocar
  • Horario laboral configurado por día de la semana
  • Hábitos del día (filtrados por dias_especificos si aplica)
  • Tareas pendientes ordenadas por prioridad + deadline
  • Espacios libres calculados automáticamente

Uso:
  python scripts/plan_manana.py                # hoy
  python scripts/plan_manana.py 2026-05-15     # día específico
"""
import os
import sys
import json
from datetime import date, datetime, timedelta
from comun import cargar, cargar_registro_dia, guardar_registro_dia

try:
    from openai import OpenAI
except ImportError:
    print("⚠️  Falta instalar la librería de OpenAI: pip install openai")
    raise SystemExit(1)


DIAS_ES = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo']


def _leer_eventos_dia(fecha: date) -> list:
    """Lee eventos iCal para una fecha específica."""
    try:
        from icalendar import Calendar
        import recurring_ical_events
        import urllib.request
    except ImportError:
        return []

    cals_data = cargar("calendarios.json")
    cals = [c for c in cals_data.get("calendarios_gmail", [])
            if c.get("activo") and c.get("ical_url")]
    if not cals:
        return []

    inicio = datetime.combine(fecha, datetime.min.time())
    fin = datetime.combine(fecha, datetime.max.time())

    eventos = []
    for cal in cals:
        try:
            req = urllib.request.Request(cal["ical_url"], headers={"User-Agent": "Organizador/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                ics = r.read()
            ical = Calendar.from_ical(ics)
            ocs = recurring_ical_events.of(ical).between(inicio, fin)
            for ev in ocs:
                start = ev.get("DTSTART").dt if ev.get("DTSTART") else None
                end = ev.get("DTEND").dt if ev.get("DTEND") else start
                if not start or not hasattr(start, "hour"):
                    continue
                eventos.append({
                    "titulo": str(ev.get("SUMMARY", "(sin título)")),
                    "inicio": start.strftime("%H:%M"),
                    "fin": end.strftime("%H:%M") if end else start.strftime("%H:%M"),
                    "calendario": cal.get("nombre_para_mostrar")
                })
        except Exception:
            pass

    eventos.sort(key=lambda e: e["inicio"])
    return eventos


def _horario_laboral(fecha: date) -> dict:
    """Horario laboral del día (según ISO weekday). Lee de config.horario_laboral o usa default."""
    iso_dow = str(fecha.isoweekday())
    default = {
        "1": {"activo": True,  "inicio": "08:00", "fin": "18:00"},
        "2": {"activo": True,  "inicio": "08:00", "fin": "18:00"},
        "3": {"activo": True,  "inicio": "08:00", "fin": "18:00"},
        "4": {"activo": True,  "inicio": "08:00", "fin": "18:00"},
        "5": {"activo": True,  "inicio": "08:00", "fin": "18:00"},
        "6": {"activo": False, "inicio": "09:00", "fin": "13:00"},
        "7": {"activo": False, "inicio": "00:00", "fin": "00:00"}
    }
    config = cargar("config.json")
    hl = config.get("horario_laboral") if isinstance(config, dict) else None
    if isinstance(hl, dict) and iso_dow in hl and isinstance(hl[iso_dow], dict):
        return hl[iso_dow]
    return default[iso_dow]


def _calcular_libres(fecha: date, horario: dict, eventos: list) -> list:
    """Calcula gaps entre eventos dentro del horario laboral."""
    if not horario.get("activo"):
        return []
    try:
        ih, im = map(int, horario["inicio"].split(":"))
        fh, fm = map(int, horario["fin"].split(":"))
    except Exception:
        return []
    ini = ih * 60 + im
    fin = fh * 60 + fm

    # convertir eventos a minutos en el día y truncar a la ventana
    bloqueados = []
    for e in eventos:
        try:
            eh, em = map(int, e["inicio"].split(":"))
            fh2, fm2 = map(int, e["fin"].split(":"))
            es = max(eh*60+em, ini)
            ef = min(fh2*60+fm2, fin)
            if ef > es:
                bloqueados.append((es, ef))
        except Exception:
            pass
    bloqueados.sort()

    libres = []
    cursor = ini
    for s, f in bloqueados:
        if s - cursor >= 15:  # min gap 15 min
            libres.append({
                "inicio": f"{cursor//60:02d}:{cursor%60:02d}",
                "fin":    f"{s//60:02d}:{s%60:02d}",
                "duracion_min": s - cursor
            })
        cursor = max(cursor, f)
    if fin - cursor >= 15:
        libres.append({
            "inicio": f"{cursor//60:02d}:{cursor%60:02d}",
            "fin":    f"{fin//60:02d}:{fin%60:02d}",
            "duracion_min": fin - cursor
        })
    return libres


def _filtrar_habitos_dia(habitos: list, fecha: date) -> list:
    """Devuelve solo hábitos que aplican en esa fecha."""
    iso_dow = fecha.isoweekday()  # 1..7
    out = []
    for h in habitos:
        if not h.get("activo"): continue
        if h.get("tipo") == "malo": continue  # los malos no se programan
        freq = h.get("frecuencia", "diaria")
        if freq == "diaria":
            out.append(h)
        elif freq == "dias_especificos":
            if iso_dow in (h.get("dias") or []):
                out.append(h)
    return out


def construir_contexto(fecha=None) -> dict:
    """Construye contexto enriquecido para la IA."""
    if fecha is None:
        fecha = date.today()
    elif isinstance(fecha, str):
        fecha = date.fromisoformat(fecha)

    clientes = cargar("clientes.json").get("clientes", cargar("clientes.json").get("empresas", []))
    proyectos = cargar("proyectos.json")["proyectos"]
    actividades = cargar("actividades.json")["actividades"]
    habitos_data = cargar("habitos.json")
    config = cargar("config.json")

    pendientes = [a for a in actividades if a.get("estado") == "pendiente"]
    # Priorizar: deadline cercano > prioridad alta > resto
    def _peso(t):
        prio = {"alta": 0, "media": 1, "baja": 2}.get(t.get("prioridad","media"), 3)
        dl = t.get("deadline") or "9"
        return (prio, dl)
    pendientes.sort(key=_peso)

    habitos_dia = _filtrar_habitos_dia(habitos_data.get("habitos", []), fecha)
    eventos = _leer_eventos_dia(fecha)
    horario = _horario_laboral(fecha)
    libres = _calcular_libres(fecha, horario, eventos)

    return {
        "fecha": fecha.isoformat(),
        "dia_semana": DIAS_ES[fecha.weekday()],
        "clientes": clientes,
        "proyectos": proyectos,
        "tareas_pendientes": pendientes[:10],  # top 10
        "habitos_del_dia": habitos_dia,
        "eventos_calendario": eventos,
        "horario_laboral": horario,
        "espacios_libres": libres,
        "config": config
    }


def generar_plan(ctx: dict) -> dict:
    cfg = ctx["config"]
    modelo = (cfg.get("ia") or {}).get("modelo", "gpt-4o-mini")
    max_tareas = (cfg.get("ia") or {}).get("max_tareas_por_dia", 8)
    tono = (cfg.get("ia") or {}).get("tono", "directo, motivador, en español")

    horario = ctx["horario_laboral"]
    if not horario.get("activo"):
        ventana_txt = f"Día NO laboral ({horario.get('inicio','-')}-{horario.get('fin','-')})"
    else:
        ventana_txt = f"{horario['inicio']} a {horario['fin']}"

    sistema = f"""Eres el asistente de productividad de Diego, dropshipper colombiano.

Tu trabajo: armar un PLAN DEL DÍA realista para la fecha objetivo, en {tono}.

REGLAS DURAS:
1. Los EVENTOS del calendario son INTOCABLES. Programa todo alrededor de ellos.
2. Respeta el horario laboral: no programes nada fuera de la ventana.
3. Encaja las tareas en los espacios libres reales (que te paso abajo).
4. Hábitos de la mañana → al inicio del día. Hábitos de noche → al final.
5. No sobrecargues: máximo {max_tareas} tareas principales.
6. Mezcla negocio y personal/salud para no quemarse.
7. Si hay tareas urgentes (deadline = hoy o prioridad alta), van primero.
8. Si NO hay tareas pendientes, llena con hábitos + descansos cortos.
9. Si el día NO es laboral, sugiere ritual ligero (hábitos de salud, descanso).

Devuelve SOLO JSON con esta estructura:
{{
  "saludo": "frase corta motivadora",
  "bloques": [
    {{"hora": "HH:MM", "duracion_min": N, "titulo": "...",
      "tipo": "tarea|habito|evento|descanso",
      "id": "id_original o null",
      "cliente": "nombre del cliente (opcional)",
      "razon": "por qué este bloque ahora (1 frase corta)"}}
  ],
  "advertencia": "algo importante a no olvidar (o cadena vacía)",
  "frase_cierre": "cómo medir éxito hoy"
}}"""

    usuario = f"""FECHA OBJETIVO: {ctx['fecha']} ({ctx['dia_semana']})

VENTANA DE TRABAJO: {ventana_txt}

EVENTOS DEL CALENDARIO (intocables, ya bloqueados):
{json.dumps(ctx['eventos_calendario'], ensure_ascii=False, indent=2)}

ESPACIOS LIBRES dentro de la ventana laboral (úsalos para programar tareas):
{json.dumps(ctx['espacios_libres'], ensure_ascii=False, indent=2)}

HÁBITOS QUE APLICAN ESE DÍA ({len(ctx['habitos_del_dia'])}):
{json.dumps(ctx['habitos_del_dia'], ensure_ascii=False, indent=2)}

TAREAS PENDIENTES ordenadas por prioridad/deadline ({len(ctx['tareas_pendientes'])}):
{json.dumps(ctx['tareas_pendientes'], ensure_ascii=False, indent=2)}

CLIENTES:
{json.dumps(ctx['clientes'], ensure_ascii=False, indent=2)}

Arma el plan ideal. Cada bloque DEBE caber en un espacio libre (o ser un evento ya existente listado para contexto)."""

    cliente = OpenAI()
    respuesta = cliente.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": sistema},
            {"role": "user", "content": usuario}
        ],
        response_format={"type": "json_object"},
        temperature=0.4
    )
    return json.loads(respuesta.choices[0].message.content)


def imprimir_plan(plan: dict, clientes: list) -> None:
    print("\n" + "=" * 60)
    print(f"  ☀️  {plan.get('saludo','')}")
    print("=" * 60)
    for b in plan.get("bloques", []):
        icono = {"tarea": "📌", "habito": "🎯", "evento": "📅", "descanso": "☕"}.get(b.get("tipo"), "•")
        print(f"\n  {b.get('hora','')}  {icono}  {b.get('titulo','')}  ({b.get('duracion_min',0)} min)")
        if b.get("cliente"): print(f"           🏢 {b['cliente']}")
        if b.get("razon"):   print(f"           💡 {b['razon']}")
    if plan.get("advertencia"): print(f"\n  ⚠️  {plan['advertencia']}")
    if plan.get("frase_cierre"): print(f"\n  🏁 {plan['frase_cierre']}")
    print("\n" + "=" * 60)


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Falta OPENAI_API_KEY"); raise SystemExit(1)

    fecha_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if fecha_arg:
        try:
            fecha = date.fromisoformat(fecha_arg)
        except ValueError:
            print(f"❌ Fecha inválida: {fecha_arg} (usa YYYY-MM-DD)"); raise SystemExit(1)
    else:
        fecha = date.today()

    print(f"🧠 Generando plan para {fecha.isoformat()} ({DIAS_ES[fecha.weekday()]})...")
    ctx = construir_contexto(fecha)
    plan = generar_plan(ctx)
    imprimir_plan(plan, ctx["clientes"])

    if fecha == date.today():
        respuesta = input("\n¿Apruebas este plan? [s/n]: ").strip().lower()
        registro = cargar_registro_dia()
        if respuesta in ("s","si","sí","y",""):
            registro["plan_generado"] = plan
            registro["aprobado"] = True
            guardar_registro_dia(registro)
            print("\n✅ Plan aprobado y guardado.")


if __name__ == "__main__":
    main()
