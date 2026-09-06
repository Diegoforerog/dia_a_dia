#!/usr/bin/env python3
"""
Sincroniza los hábitos del plan "The Great Lock In" con el servidor
(sirve para producción con base de datos O local con JSON: siempre pasa
por la API, que persiste donde corresponda).

Qué hace:
  1. Borra TODOS los hábitos existentes en el servidor.
  2. Crea los 28 hábitos definidos en datos/habitos.json.
  3. Agrega el curso "Curso Daniel Habif" a la sección de Cursos (si no existe).

Uso:
  BASE_URL="https://TU-DOMINIO" API_TOKEN="tu-token" python db/seed_lockin.py
  # o local:
  BASE_URL="http://localhost:5050" API_TOKEN="organizador-diego-token-2026-cambia-en-prod" python db/seed_lockin.py

El token es el mismo que usa el tablero (X-API-Token). En local lo da /api/local-token.
Agrega --dry-run para ver qué haría sin cambiar nada.
"""
import json, os, sys, urllib.request, urllib.error
from pathlib import Path

BASE = os.environ.get("BASE_URL", "http://localhost:5050").rstrip("/")
TOKEN = os.environ.get("API_TOKEN", "")
DRY = "--dry-run" in sys.argv
RAIZ = Path(__file__).resolve().parent.parent

if not TOKEN:
    print("✋ Falta API_TOKEN. Ej: API_TOKEN=... BASE_URL=... python db/seed_lockin.py")
    sys.exit(1)

if "TU-DOMINIO" in BASE or "tu-dominio" in BASE:
    print(f"✋ BASE_URL sigue con el texto de ejemplo ({BASE}).")
    print("   Reemplázalo por el dominio real donde abres la app en el teléfono, p.ej.:")
    print('   BASE_URL="https://miapp.midominio.com" API_TOKEN="..." python3 db/seed_lockin.py --dry-run')
    sys.exit(1)


def _probar_conexion():
    """Falla temprano con un mensaje claro si la URL/red no responde."""
    try:
        req = urllib.request.Request(BASE + "/api/health", method="GET")
        urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError:
        pass  # responde algo → el host existe, seguimos
    except urllib.error.URLError as e:
        print(f"✋ No pude conectar a {BASE}")
        print(f"   Motivo: {e.reason}")
        print("   Revisa que el dominio esté bien escrito (con https://) y que la app esté arriba.")
        sys.exit(1)


def api(method, ruta, body=None):
    url = BASE + "/api" + ruta
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-API-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        print(f"   ⚠️  {method} {ruta} → {e.code} {e.read()[:200]}")
        return None
    except urllib.error.URLError as e:
        print(f"   ⚠️  {method} {ruta} → sin conexión: {e.reason}")
        return None


def main():
    print(f"→ Servidor: {BASE}  {'(DRY RUN)' if DRY else ''}")
    _probar_conexion()

    # 1. Borrar hábitos existentes
    actuales = api("GET", "/habitos") or {}
    viejos = actuales.get("habitos", [])
    print(f"\n1) Hábitos actuales en el servidor: {len(viejos)}")
    for h in viejos:
        print(f"   − borrar: {h.get('nombre')}")
        if not DRY:
            api("DELETE", f"/habitos/{h['id']}")

    # 2. Crear los nuevos
    nuevos = json.loads((RAIZ / "datos" / "habitos.json").read_text())["habitos"]
    print(f"\n2) Creando {len(nuevos)} hábitos del Lock In:")
    for h in nuevos:
        body = {k: h[k] for k in ("id", "categoria_id", "nombre", "frecuencia", "horario_sugerido",
                                  "duracion_min", "dias", "tipo", "alcance", "persona_id") if k in h}
        print(f"   + {h['nombre']}  ({h.get('horario_sugerido','')})")
        if not DRY:
            api("POST", "/habitos", body)

    # 3. Curso Daniel Habif
    cursos = (api("GET", "/cursos") or {}).get("cursos", [])
    if any("daniel habif" in (c.get("nombre", "").lower()) for c in cursos):
        print("\n3) Curso 'Daniel Habif' ya existe — no se duplica.")
    else:
        print("\n3) Agregando curso 'Curso Daniel Habif' (Diego)")
        if not DRY:
            api("POST", "/cursos", {"nombre": "Curso Daniel Habif", "emoji": "🎤",
                                    "persona_id": "persona_diego", "min_dia": 60,
                                    "recompensa": "Crecimiento personal"})

    print("\n✅ Listo." if not DRY else "\n(DRY RUN — no se cambió nada)")


if __name__ == "__main__":
    main()
