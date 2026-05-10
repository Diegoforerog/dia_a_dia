"""Plan de la mañana con IA (gpt-4o-mini).

Lee tus tareas pendientes + hábitos + eventos del día y genera
una propuesta de plan priorizado que TÚ apruebas.

Uso:
  export OPENAI_API_KEY=tu_clave
  python scripts/plan_manana.py
"""
import os
import json
from datetime import date, datetime
from comun import cargar, cargar_registro_dia, guardar_registro_dia

try:
    from openai import OpenAI
except ImportError:
    print("⚠️  Falta instalar la librería de OpenAI:")
    print("    pip install openai")
    raise SystemExit(1)


def construir_contexto() -> dict:
    empresas = cargar("empresas.json")["empresas"]
    proyectos = cargar("proyectos.json")["proyectos"]
    actividades = cargar("actividades.json")["actividades"]
    habitos_data = cargar("habitos.json")
    config = cargar("config.json")

    pendientes = [a for a in actividades if a["estado"] == "pendiente"]
    habitos_diarios = [h for h in habitos_data["habitos"] if h["activo"] and h["frecuencia"] == "diaria"]

    return {
        "fecha": date.today().isoformat(),
        "dia_semana": datetime.now().strftime("%A"),
        "empresas": empresas,
        "proyectos": proyectos,
        "tareas_pendientes": pendientes,
        "habitos_del_dia": habitos_diarios,
        "config": config
    }


def generar_plan(ctx: dict) -> dict:
    cfg = ctx["config"]
    modelo = cfg["ia"]["modelo"]
    max_tareas = cfg["ia"]["max_tareas_por_dia"]
    tono = cfg["ia"]["tono"]

    sistema = f"""Eres un asistente de productividad para Diego, dropshipper con varias áreas:
empresas/proyectos del usuario, hábitos diarios y eventos.

Tu trabajo: armar un PLAN DEL DÍA realista, en {tono}.

Reglas:
- Máximo {max_tareas} tareas principales.
- Prioriza por: deadline cercano > prioridad alta > proyectos activos.
- Mezcla bloques de negocio (Dropi) con personal/salud para no quemarse.
- Incluye hábitos de la mañana al inicio y los de la noche al final.
- Sugiere horarios concretos (ej: 7:30-8:00).
- Explica brevemente el "porqué" del orden.

Devuelve SOLO JSON con esta estructura:
{{
  "saludo": "frase corta motivadora en español",
  "bloques": [
    {{"hora": "HH:MM", "duracion_min": N, "titulo": "...", "tipo": "tarea|habito|descanso", "id": "id_original o null", "empresa": "nombre", "razon": "por qué ahora"}}
  ],
  "advertencia": "algo importante a no olvidar hoy o cadena vacía",
  "frase_cierre": "cómo medir éxito hoy"
}}"""

    usuario = f"""DATOS DE HOY ({ctx['fecha']}, {ctx['dia_semana']}):

EMPRESAS:
{json.dumps(ctx['empresas'], ensure_ascii=False, indent=2)}

PROYECTOS ACTIVOS:
{json.dumps(ctx['proyectos'], ensure_ascii=False, indent=2)}

TAREAS PENDIENTES ({len(ctx['tareas_pendientes'])}):
{json.dumps(ctx['tareas_pendientes'], ensure_ascii=False, indent=2)}

HÁBITOS DIARIOS:
{json.dumps(ctx['habitos_del_dia'], ensure_ascii=False, indent=2)}

VENTANA DE TRABAJO: {cfg['horarios']['inicio_dia']} - {cfg['horarios']['fin_dia']}

Arma el plan ideal para HOY."""

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


def imprimir_plan(plan: dict, empresas: list) -> None:
    print("\n" + "=" * 60)
    print(f"  ☀️  {plan['saludo']}")
    print("=" * 60)
    color_empresa = {e["nombre"]: e["color"] for e in empresas}

    for b in plan["bloques"]:
        icono = {"tarea": "📌", "habito": "🎯", "descanso": "☕"}.get(b["tipo"], "•")
        print(f"\n  {b['hora']}  {icono}  {b['titulo']}  ({b['duracion_min']} min)")
        if b.get("empresa"):
            print(f"           🏢 {b['empresa']}")
        if b.get("razon"):
            print(f"           💡 {b['razon']}")

    if plan.get("advertencia"):
        print(f"\n  ⚠️  {plan['advertencia']}")
    print(f"\n  🏁 {plan['frase_cierre']}")
    print("\n" + "=" * 60)


def main() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Falta la variable OPENAI_API_KEY")
        print("    export OPENAI_API_KEY=sk-...")
        raise SystemExit(1)

    print("🧠 Generando tu plan del día con IA...")
    ctx = construir_contexto()
    plan = generar_plan(ctx)
    imprimir_plan(plan, ctx["empresas"])

    respuesta = input("\n¿Apruebas este plan? [s/n/editar]: ").strip().lower()
    registro = cargar_registro_dia()

    if respuesta in ("s", "si", "sí", "y", ""):
        registro["plan_generado"] = plan
        registro["aprobado"] = True
        guardar_registro_dia(registro)
        print("\n✅ Plan aprobado y guardado.")
        print(f"   Ver tablero: abre tablero/index.html")
    elif respuesta == "editar":
        registro["plan_generado"] = plan
        registro["aprobado"] = False
        guardar_registro_dia(registro)
        print("\n📝 Plan guardado SIN aprobar. Edita el archivo:")
        print(f"   datos/registros/{registro['fecha']}.json")
    else:
        print("\n❌ Plan descartado. Corre el script de nuevo cuando quieras.")


if __name__ == "__main__":
    main()
