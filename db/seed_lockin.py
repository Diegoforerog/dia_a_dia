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
            return {"ok": True, "code": r.status, "data": json.loads(r.read() or "null")}
    except urllib.error.HTTPError as e:
        print(f"   ⚠️  {method} {ruta} → {e.code} {e.read()[:200]}")
        return {"ok": False, "code": e.code, "data": None}
    except urllib.error.URLError as e:
        print(f"   ⚠️  {method} {ruta} → sin conexión: {e.reason}")
        return {"ok": False, "code": 0, "data": None}


def main():
    print(f"→ Servidor: {BASE}  {'(DRY RUN)' if DRY else ''}")
    _probar_conexion()

    # 0. Leer el plan ANTES de borrar (en local el borrado vacía este mismo archivo)
    nuevos = json.loads((RAIZ / "datos" / "habitos.json").read_text())["habitos"]
    if not nuevos:
        print("✋ datos/habitos.json está vacío. Regenéralo antes de sincronizar.")
        sys.exit(1)

    # 1. Borrar hábitos existentes
    r = api("GET", "/habitos")
    if not r["ok"]:
        print("✋ No pude LEER los hábitos (token inválido o sin permiso). Nada que hacer.")
        sys.exit(1)
    viejos = (r["data"] or {}).get("habitos", [])
    print(f"\n1) Hábitos actuales en el servidor: {len(viejos)}")
    del_ok = del_fail = 0
    for h in viejos:
        if DRY:
            print(f"   − borraría: {h.get('nombre')}")
        else:
            res = api("DELETE", f"/habitos/{h['id']}")
            if res["ok"]: del_ok += 1
            else: del_fail += 1
    if not DRY:
        print(f"   Borrados: {del_ok} ok, {del_fail} fallidos")

    # 2. Crear los nuevos (leídos en el paso 0)
    print(f"\n2) Creando {len(nuevos)} hábitos del Lock In:")
    new_ok = new_fail = 0
    for h in nuevos:
        body = {k: h[k] for k in ("id", "categoria_id", "nombre", "frecuencia", "horario_sugerido",
                                  "duracion_min", "dias", "tipo", "alcance", "persona_id") if k in h}
        if DRY:
            print(f"   + crearía: {h['nombre']}  ({h.get('horario_sugerido','')})")
        else:
            res = api("POST", "/habitos", body)
            if res["ok"]: new_ok += 1
            else: new_fail += 1
    if not DRY:
        print(f"   Creados: {new_ok} ok, {new_fail} fallidos")

    # 3. Curso Daniel Habif (opcional — no bloquea el resto)
    cursos_resp = api("GET", "/cursos")
    if not cursos_resp["ok"]:
        print("\n3) No pude leer /cursos (permisos o versión desplegada distinta).")
        print("   No pasa nada: agrega el curso a mano en la app → Aprender → «+ Nuevo curso»:")
        print("     Nombre: Curso Daniel Habif  ·  Persona: Diego  ·  min/día: 60")
    else:
        cursos = (cursos_resp["data"] or {}).get("cursos", [])
        if any("daniel habif" in (c.get("nombre", "").lower()) for c in cursos):
            print("\n3) Curso 'Daniel Habif' ya existe — no se duplica.")
        else:
            print("\n3) Agregando curso 'Curso Daniel Habif' (Diego)")
            if not DRY:
                api("POST", "/cursos", {"nombre": "Curso Daniel Habif", "emoji": "🎤",
                                        "persona_id": "persona_diego", "min_dia": 60,
                                        "recompensa": "Crecimiento personal"})

    # 4. Verificación final: qué quedó realmente en el servidor
    if not DRY:
        fin = api("GET", "/habitos")
        habs = (fin["data"] or {}).get("habitos", []) if fin["ok"] else []
        print(f"\n4) VERIFICACIÓN — el servidor ahora tiene {len(habs)} hábitos:")
        pareja = [h for h in habs if (h.get('alcance') or 'pareja') == 'pareja']
        print(f"   • De pareja (compartidos): {len(pareja)}")
        for h in habs[:40]:
            quien = 'pareja' if (h.get('alcance') or 'pareja') == 'pareja' else (h.get('persona_id') or '?')
            print(f"     - {h.get('nombre')}  [{quien}]")
        if len(habs) == len(nuevos):
            print("\n✅ Sincronización correcta: coincide con el plan del Lock In.")
        else:
            print(f"\n⚠️  Se esperaban {len(nuevos)} y hay {len(habs)}. Revisa los errores de arriba.")
    else:
        print("\n(DRY RUN — no se cambió nada)")


if __name__ == "__main__":
    main()
