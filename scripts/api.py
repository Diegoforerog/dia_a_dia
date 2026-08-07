"""API local que expone todos los datos del organizador.

n8n (VPS) la consume vía Cloudflare Tunnel.
El tablero local también la usa.

Requisitos:
  pip install flask flask-cors

Uso:
  python scripts/api.py
  → API en http://localhost:5050
"""
import os
import json
from datetime import date, datetime
from flask import Flask, jsonify, request, send_from_directory, redirect
from flask_cors import CORS
from comun import (
    cargar, guardar, cargar_registro_dia, guardar_registro_dia,
    nuevo_id, RAIZ, DATOS
)
import db as _db

# Aprovisionamiento automático de la BD (activar con BOOTSTRAP_DB=1).
# Crea la base + esquema si no existen e importa datos de un PG viejo
# (MIGRAR_DESDE_HOST) la primera vez. Idempotente. DEBE correr antes
# del scheduler para que las tablas ya existan.
try:
    import bootstrap_db as _bootstrap
    _bootstrap.ejecutar()
except Exception as _e:
    print(f"⚠️  Bootstrap DB: {_e}")

# Scheduler interno (reemplaza polling crons de n8n)
try:
    import scheduler as _sched
    _SCHED_OK = True
except Exception as _e:
    print(f"⚠️  Scheduler no disponible: {_e}")
    _sched = None
    _SCHED_OK = False

INTEGRACIONES = RAIZ / "integraciones"
INTEGRACIONES.mkdir(exist_ok=True)
GOOGLE_CRED = INTEGRACIONES / "credentials.json"
GOOGLE_TOKEN = INTEGRACIONES / "token.json"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5050/api/oauth/google/callback")

# Permite OAuth sobre HTTP en local (sin TLS)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
# Google a veces devuelve scopes extra (openid, email) — esto evita que oauthlib lance error
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Persistencia: si las env vars GOOGLE_CREDENTIALS_JSON / GOOGLE_TOKEN_JSON existen,
# escribir los archivos correspondientes al boot. Útil en containers efímeros (easypanel).
_gcred_env = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
if _gcred_env and not GOOGLE_CRED.exists():
    try:
        import json as _json
        _json.loads(_gcred_env)  # validar
        GOOGLE_CRED.write_text(_gcred_env)
        print("✓ credentials.json escrito desde GOOGLE_CREDENTIALS_JSON")
    except Exception as _e:
        print(f"⚠️  GOOGLE_CREDENTIALS_JSON inválido: {_e}")

_gtoken_env = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
if _gtoken_env and not GOOGLE_TOKEN.exists():
    try:
        import json as _json
        _json.loads(_gtoken_env)  # validar
        GOOGLE_TOKEN.write_text(_gtoken_env)
        print("✓ token.json escrito desde GOOGLE_TOKEN_JSON")
    except Exception as _e:
        print(f"⚠️  GOOGLE_TOKEN_JSON inválido: {_e}")

app = Flask(__name__, static_folder=str(RAIZ / "tablero"), static_url_path="/tablero")
CORS(app)

# Arrancar scheduler en el boot del app (no en cada worker — solo el 1ro)
if _SCHED_OK and os.environ.get("WERKZEUG_RUN_MAIN") != "false":
    try:
        _sched.iniciar()
    except Exception as _e:
        print(f"⚠️  No se pudo iniciar scheduler: {_e}")

# Token simple de seguridad para que n8n se autentique
API_TOKEN = os.getenv("ORGANIZADOR_TOKEN", "cambia-este-token-en-config")


def autorizado(req) -> bool:
    """Acepta token via header X-API-Token o query param ?token=."""
    token = req.headers.get("X-API-Token") or req.args.get("token")
    return token == API_TOKEN


def requiere_auth(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not autorizado(request):
            return jsonify({"error": "No autorizado"}), 401
        return f(*args, **kwargs)
    return wrapper


# ============ CLIENTES ============

@app.route("/api/clientes", methods=["GET"])
@app.route("/api/empresas", methods=["GET"])  # alias retro-compat
@requiere_auth
def get_clientes():
    data = cargar("clientes.json")
    # Mantener key "empresas" como alias en la misma respuesta para retro-compat
    data["empresas"] = data["clientes"]
    return jsonify(data)


@app.route("/api/clientes", methods=["POST"])
@app.route("/api/empresas", methods=["POST"])  # alias retro-compat
@requiere_auth
def post_cliente():
    body = request.get_json()
    data = cargar("clientes.json")
    nuevo = {
        "id": body.get("id") or body["nombre"].lower().replace(" ", "_")[:30],
        "nombre": body["nombre"],
        "color": body.get("color", "#888888"),
        "descripcion": body.get("descripcion", ""),
        "activo": body.get("activo", True)
    }
    data["clientes"].append(nuevo)
    guardar("clientes.json", data)
    return jsonify(nuevo), 201


@app.route("/api/clientes/<cid>", methods=["PUT"])
@app.route("/api/empresas/<cid>", methods=["PUT"])  # alias
@requiere_auth
def put_cliente(cid):
    body = request.get_json()
    data = cargar("clientes.json")
    for c in data["clientes"]:
        if c["id"] == cid:
            c.update({k: v for k, v in body.items() if k != "id"})
            guardar("clientes.json", data)
            return jsonify(c)
    return jsonify({"error": "Cliente no encontrado"}), 404


@app.route("/api/clientes/<cid>", methods=["DELETE"])
@app.route("/api/empresas/<cid>", methods=["DELETE"])  # alias
@requiere_auth
def delete_cliente(cid):
    data = cargar("clientes.json")
    data["clientes"] = [c for c in data["clientes"] if c["id"] != cid]
    guardar("clientes.json", data)
    return jsonify({"ok": True})


# ============ PROYECTOS ============

@app.route("/api/proyectos", methods=["GET"])
@requiere_auth
def get_proyectos():
    return jsonify(cargar("proyectos.json"))


@app.route("/api/proyectos", methods=["POST"])
@requiere_auth
def post_proyecto():
    body = request.get_json()
    data = cargar("proyectos.json")
    nuevo = {
        "id": body.get("id") or nuevo_id("proy"),
        "cliente_id": body.get("cliente_id") or body.get("empresa_id"),
        "nombre": body["nombre"],
        "estado": body.get("estado", "activo"),
        "prioridad": body.get("prioridad", "media"),
        "deadline": body.get("deadline"),
        "descripcion": body.get("descripcion", "")
    }
    data["proyectos"].append(nuevo)
    guardar("proyectos.json", data)
    return jsonify(nuevo), 201


@app.route("/api/proyectos/<pid>", methods=["PUT"])
@requiere_auth
def put_proyecto(pid):
    body = request.get_json()
    data = cargar("proyectos.json")
    for p in data["proyectos"]:
        if p["id"] == pid:
            p.update({k: v for k, v in body.items() if k != "id"})
            guardar("proyectos.json", data)
            return jsonify(p)
    return jsonify({"error": "Proyecto no encontrado"}), 404


@app.route("/api/proyectos/<pid>", methods=["DELETE"])
@requiere_auth
def delete_proyecto(pid):
    data = cargar("proyectos.json")
    data["proyectos"] = [p for p in data["proyectos"] if p["id"] != pid]
    guardar("proyectos.json", data)
    # Cascada: limpiar épicas e historias del proyecto (JSON es la fuente de verdad)
    ep = cargar("epicas.json")
    if ep.get("epicas"):
        ep["epicas"] = [e for e in ep["epicas"] if e.get("proyecto_id") != pid]
        guardar("epicas.json", ep)
    hi = cargar("historias.json")
    if hi.get("historias"):
        hi["historias"] = [h for h in hi["historias"] if h.get("proyecto_id") != pid]
        guardar("historias.json", hi)
    return jsonify({"ok": True})


# ============ PERSONAS (Fase 0 — pareja) ============

PERSONAS_SEMILLA = [
    {"id": "persona_diego",  "nombre": "Diego",  "color": "#2563EB", "emoji": "🧭",
     "activo": True, "telegram_chat_id": "", "push_subscriptions": [], "orden": 0},
    {"id": "persona_esposa", "nombre": "Esposa", "color": "#B0578D", "emoji": "🌸",
     "activo": True, "telegram_chat_id": "", "push_subscriptions": [], "orden": 1},
]


def _asegurar_personas() -> dict:
    """Devuelve personas.json; si está vacío, siembra a Diego + Esposa (renombrables)."""
    data = cargar("personas.json")
    if not data.get("personas"):
        data = {"personas": [dict(p) for p in PERSONAS_SEMILLA]}
        guardar("personas.json", data)
    return data


@app.route("/api/personas", methods=["GET"])
@requiere_auth
def get_personas():
    return jsonify(_asegurar_personas())


@app.route("/api/personas", methods=["POST"])
@requiere_auth
def post_persona():
    body = request.get_json()
    data = _asegurar_personas()
    nueva = {
        "id": body.get("id") or nuevo_id("persona"),
        "nombre": body["nombre"],
        "color": body.get("color", "#2563EB"),
        "emoji": body.get("emoji", ""),
        "activo": True,
        "telegram_chat_id": body.get("telegram_chat_id", ""),
        "push_subscriptions": [],
        "orden": len(data["personas"]),
    }
    data["personas"].append(nueva)
    guardar("personas.json", data)
    return jsonify(nueva), 201


@app.route("/api/personas/<pid>", methods=["PUT"])
@requiere_auth
def put_persona(pid):
    body = request.get_json()
    data = _asegurar_personas()
    for p in data["personas"]:
        if p["id"] == pid:
            # push_subscriptions se maneja solo por los endpoints de push
            p.update({k: v for k, v in body.items() if k not in ("id", "push_subscriptions")})
            guardar("personas.json", data)
            # No devolver las suscripciones (ruido/privacidad)
            salida = {k: v for k, v in p.items() if k != "push_subscriptions"}
            return jsonify(salida)
    return jsonify({"error": "Persona no encontrada"}), 404


# ============ AVISOS / WEB PUSH (Fase 2) ============

@app.route("/api/push/clave-publica", methods=["GET"])
def push_clave_publica():
    """applicationServerKey (VAPID) para que el navegador se suscriba.
    Público: no expone secretos, solo la clave pública."""
    try:
        import avisos
        return jsonify({"clave": avisos.clave_publica(), "disponible": avisos.push_disponible()})
    except Exception as e:
        return jsonify({"clave": "", "disponible": False, "error": str(e)})


@app.route("/api/push/suscribir", methods=["POST"])
@requiere_auth
def push_suscribir():
    body = request.get_json() or {}
    persona_id = body.get("persona_id")
    sub = body.get("subscription")
    if not persona_id or not sub or not sub.get("endpoint"):
        return jsonify({"error": "Falta persona_id o subscription"}), 400
    import avisos
    if avisos.guardar_suscripcion(persona_id, sub):
        return jsonify({"ok": True})
    return jsonify({"error": "Persona no encontrada"}), 404


@app.route("/api/push/desuscribir", methods=["POST"])
@requiere_auth
def push_desuscribir():
    body = request.get_json() or {}
    persona_id = body.get("persona_id")
    endpoint = body.get("endpoint")
    if not persona_id or not endpoint:
        return jsonify({"error": "Falta persona_id o endpoint"}), 400
    import avisos
    avisos.quitar_suscripcion(persona_id, endpoint)
    return jsonify({"ok": True})


@app.route("/api/push/prueba", methods=["POST"])
@requiere_auth
def push_prueba():
    """Envía un aviso de prueba a la persona por todos sus canales."""
    body = request.get_json() or {}
    persona_id = body.get("persona_id")
    if not persona_id:
        return jsonify({"error": "Falta persona_id"}), 400
    import avisos
    persona = avisos._persona(persona_id)
    nombre = persona.get("nombre", "")
    res = avisos.avisar_persona(
        persona_id,
        "Día a día",
        f"¡Hola {nombre}! Tus avisos están funcionando 🎉",
        url="/",
        tag="prueba",
    )
    return jsonify({"ok": True, "resultado": res})


# ============ ÉPICAS (Fase 1 — fases de un proyecto) ============

@app.route("/api/epicas", methods=["GET"])
@requiere_auth
def get_epicas():
    proyecto_id = request.args.get("proyecto_id")
    data = cargar("epicas.json")
    items = data.get("epicas", [])
    if proyecto_id:
        items = [e for e in items if e.get("proyecto_id") == proyecto_id]
    return jsonify({"epicas": items})


@app.route("/api/epicas", methods=["POST"])
@requiere_auth
def post_epica():
    body = request.get_json()
    data = cargar("epicas.json")
    data.setdefault("epicas", [])
    nueva = {
        "id": body.get("id") or nuevo_id("epica"),
        "proyecto_id": body["proyecto_id"],
        "titulo": body["titulo"],
        "descripcion": body.get("descripcion", ""),
        "prioridad": body.get("prioridad", "media"),
        "estado": body.get("estado", "abierta"),
        "orden": len(data["epicas"]),
    }
    data["epicas"].append(nueva)
    guardar("epicas.json", data)
    return jsonify(nueva), 201


@app.route("/api/epicas/<eid>", methods=["PUT"])
@requiere_auth
def put_epica(eid):
    body = request.get_json()
    data = cargar("epicas.json")
    for e in data.get("epicas", []):
        if e["id"] == eid:
            e.update({k: v for k, v in body.items() if k != "id"})
            guardar("epicas.json", data)
            return jsonify(e)
    return jsonify({"error": "Épica no encontrada"}), 404


@app.route("/api/epicas/<eid>", methods=["DELETE"])
@requiere_auth
def delete_epica(eid):
    data = cargar("epicas.json")
    data["epicas"] = [e for e in data.get("epicas", []) if e["id"] != eid]
    guardar("epicas.json", data)
    # Las historias de esa épica quedan sin épica (no se borran)
    hi = cargar("historias.json")
    cambio = False
    for h in hi.get("historias", []):
        if h.get("epica_id") == eid:
            h["epica_id"] = None
            cambio = True
    if cambio:
        guardar("historias.json", hi)
    return jsonify({"ok": True})


# ============ HISTORIAS (Fase 1 — tarjetas del canvas) ============

ESTADOS_HISTORIA = ["backlog", "planeado", "en_progreso", "qa", "bloqueado", "hecho"]


@app.route("/api/historias", methods=["GET"])
@requiere_auth
def get_historias():
    proyecto_id = request.args.get("proyecto_id")
    data = cargar("historias.json")
    items = data.get("historias", [])
    if proyecto_id:
        items = [h for h in items if h.get("proyecto_id") == proyecto_id]
    return jsonify({"historias": items})


@app.route("/api/historias", methods=["POST"])
@requiere_auth
def post_historia():
    body = request.get_json()
    data = cargar("historias.json")
    data.setdefault("historias", [])
    nueva = {
        "id": body.get("id") or nuevo_id("hist"),
        "proyecto_id": body["proyecto_id"],
        "epica_id": body.get("epica_id"),
        "titulo": body["titulo"],
        "descripcion": body.get("descripcion", ""),
        "responsable_id": body.get("responsable_id"),
        "prioridad": body.get("prioridad", "media"),
        "estado": body.get("estado", "backlog"),
        "etiquetas": body.get("etiquetas", []),
        "estimacion_horas": body.get("estimacion_horas"),
        "fecha_objetivo": body.get("fecha_objetivo"),
        "motivo_bloqueo": "",
        "criterios": body.get("criterios", []),
        "subtareas": body.get("subtareas", []),
        "origen": body.get("origen", ""),
        "orden": len(data["historias"]),
        "creada": datetime.now().isoformat(),
        "completada_en": None,
    }
    if nueva["estado"] not in ESTADOS_HISTORIA:
        nueva["estado"] = "backlog"
    data["historias"].append(nueva)
    guardar("historias.json", data)
    return jsonify(nueva), 201


@app.route("/api/historias/<hid>", methods=["PUT"])
@requiere_auth
def put_historia(hid):
    body = request.get_json()
    data = cargar("historias.json")
    for h in data.get("historias", []):
        if h["id"] == hid:
            estado_antes = h.get("estado")
            h.update({k: v for k, v in body.items() if k != "id"})
            if h.get("estado") not in ESTADOS_HISTORIA:
                h["estado"] = estado_antes or "backlog"
            # Reglas de transición automáticas
            if h["estado"] == "hecho" and estado_antes != "hecho":
                h["completada_en"] = datetime.now().isoformat()
            elif h["estado"] != "hecho":
                h["completada_en"] = None
            if h["estado"] != "bloqueado":
                h["motivo_bloqueo"] = ""
            guardar("historias.json", data)
            return jsonify(h)
    return jsonify({"error": "Historia no encontrada"}), 404


@app.route("/api/historias/<hid>", methods=["DELETE"])
@requiere_auth
def delete_historia(hid):
    data = cargar("historias.json")
    data["historias"] = [h for h in data.get("historias", []) if h["id"] != hid]
    guardar("historias.json", data)
    return jsonify({"ok": True})


def _migrar_actividades_a_historias():
    """Semilla única: convierte las actividades existentes en historias del canvas.
    Idempotente (marca origen 'actividad:<id>'). No borra las actividades:
    el plan diario las sigue usando hasta la Fase 5."""
    hi = cargar("historias.json")
    hi.setdefault("historias", [])
    ya_migradas = {h.get("origen") for h in hi["historias"] if h.get("origen")}
    acts = cargar("actividades.json").get("actividades", [])
    mapa_estado = {"pendiente": "backlog", "en_progreso": "en_progreso",
                   "completada": "hecho", "descartada": None}
    nuevas = 0
    for a in acts:
        origen = f"actividad:{a['id']}"
        if origen in ya_migradas:
            continue
        if not a.get("proyecto_id"):
            continue  # el canvas exige proyecto; queda como tarea del día
        estado = mapa_estado.get(a.get("estado", "pendiente"), "backlog")
        if estado is None:
            continue
        hi["historias"].append({
            "id": nuevo_id("hist"),
            "proyecto_id": a.get("proyecto_id"),
            "epica_id": None,
            "titulo": a.get("titulo", "Sin título"),
            "descripcion": a.get("notas", ""),
            "responsable_id": "persona_diego",
            "prioridad": a.get("prioridad", "media"),
            "estado": estado,
            "etiquetas": [],
            "estimacion_horas": round((a.get("duracion_min") or 30) / 60, 2),
            "fecha_objetivo": a.get("deadline"),
            "motivo_bloqueo": "",
            "criterios": [],
            "subtareas": [],
            "origen": origen,
            "orden": len(hi["historias"]),
            "creada": a.get("creada") or datetime.now().isoformat(),
            "completada_en": a.get("completada_en"),
        })
        nuevas += 1
    if nuevas:
        guardar("historias.json", hi)
        print(f"✓ Migración SCRUM: {nuevas} actividad(es) convertidas en historias")
    return nuevas


# ============ ACTIVIDADES (tareas) ============

@app.route("/api/tareas", methods=["GET"])
@requiere_auth
def get_tareas():
    estado = request.args.get("estado")
    data = cargar("actividades.json")
    items = data["actividades"]
    if estado:
        items = [t for t in items if t["estado"] == estado]
    return jsonify({"actividades": items})


@app.route("/api/tareas", methods=["POST"])
@requiere_auth
def post_tarea():
    body = request.get_json()
    data = cargar("actividades.json")
    nueva = {
        "id": body.get("id") or nuevo_id("tarea"),
        "cliente_id": body.get("cliente_id") or body.get("empresa_id"),
        "proyecto_id": body.get("proyecto_id"),
        "titulo": body["titulo"],
        "prioridad": body.get("prioridad", "media"),
        "duracion_min": body.get("duracion_min", 30),
        "deadline": body.get("deadline"),
        "notas": body.get("notas", ""),
        "estado": "pendiente",
        "creada": datetime.now().isoformat()
    }
    data["actividades"].append(nueva)
    guardar("actividades.json", data)
    return jsonify(nueva), 201


@app.route("/api/tareas/<tid>", methods=["PUT"])
@requiere_auth
def put_tarea(tid):
    body = request.get_json()
    data = cargar("actividades.json")
    for t in data["actividades"]:
        if t["id"] == tid:
            t.update({k: v for k, v in body.items() if k != "id"})
            guardar("actividades.json", data)
            return jsonify(t)
    return jsonify({"error": "Tarea no encontrada"}), 404


@app.route("/api/tareas/<tid>/cumplir", methods=["POST"])
@requiere_auth
def cumplir_tarea(tid):
    """Marca como cumplida + actualiza registro del día."""
    data = cargar("actividades.json")
    encontrada = None
    for t in data["actividades"]:
        if t["id"] == tid:
            t["estado"] = "completada"
            t["completada_en"] = datetime.now().isoformat()
            encontrada = t
            break
    if not encontrada:
        return jsonify({"error": "Tarea no encontrada"}), 404
    guardar("actividades.json", data)

    registro = cargar_registro_dia()
    if tid not in registro["tareas_completadas"]:
        registro["tareas_completadas"].append(tid)
    guardar_registro_dia(registro)
    return jsonify(encontrada)


# ============ HÁBITOS ============

@app.route("/api/habitos", methods=["GET"])
@requiere_auth
def get_habitos():
    return jsonify(cargar("habitos.json"))


@app.route("/api/habitos", methods=["POST"])
@requiere_auth
def post_habito():
    body = request.get_json()
    data = cargar("habitos.json")
    nuevo = {
        "id": body.get("id") or nuevo_id("hab"),
        "categoria_id": body["categoria_id"],
        "nombre": body["nombre"],
        "frecuencia": body.get("frecuencia", "diaria"),
        "horario_sugerido": body.get("horario_sugerido", "mañana"),
        "duracion_min": body.get("duracion_min", 15),
        "activo": True,
        "racha_actual": 0,
        "mejor_racha": 0,
        "dias": body.get("dias"),  # int[] 1-7 (ISO) o None
        "tipo": body.get("tipo", "bueno")  # 'bueno' (cumplir) o 'malo' (evitar)
    }
    data["habitos"].append(nuevo)
    guardar("habitos.json", data)
    return jsonify(nuevo), 201


@app.route("/api/habitos/<hid>", methods=["PUT"])
@requiere_auth
def put_habito(hid):
    body = request.get_json()
    data = cargar("habitos.json")
    for h in data["habitos"]:
        if h["id"] == hid:
            h.update({k: v for k, v in body.items() if k != "id"})
            guardar("habitos.json", data)
            return jsonify(h)
    return jsonify({"error": "Hábito no encontrado"}), 404


@app.route("/api/habitos/<hid>/cumplir", methods=["POST"])
@requiere_auth
def cumplir_habito(hid):
    """Marca como cumplido HOY."""
    registro = cargar_registro_dia()
    if hid not in registro["habitos_cumplidos"]:
        registro["habitos_cumplidos"].append(hid)
    guardar_registro_dia(registro)
    return jsonify({"ok": True, "habito_id": hid, "fecha": registro["fecha"]})


@app.route("/api/habitos/<hid>", methods=["DELETE"])
@requiere_auth
def delete_habito(hid):
    data = cargar("habitos.json")
    data["habitos"] = [h for h in data["habitos"] if h["id"] != hid]
    guardar("habitos.json", data)
    return jsonify({"ok": True})


# ============ AVISO 10 MIN ANTES DE EVENTOS DE CALENDARIO ============

@app.route("/api/eventos/avisar_proximos", methods=["POST", "GET"])
@requiere_auth
def avisar_proximos_eventos():
    """Devuelve eventos del calendario que arrancan en los próximos 15 min
    y aún no se han avisado. Los marca como avisados al devolver.

    Diseñado para correr cada 5 min desde n8n."""
    from datetime import timedelta, timezone as _tz

    if not _db.db_disponible():
        return jsonify({"eventos": [], "error": "DB no disponible"}), 500

    try:
        from icalendar import Calendar
        import recurring_ical_events
        import urllib.request as urlreq
    except ImportError:
        return jsonify({"error": "Falta librería icalendar / recurring_ical_events"}), 500

    minutos_antes = int(request.args.get("minutos", 10))
    ventana_minutos = int(request.args.get("ventana", 15))  # lookahead

    ahora = datetime.now().astimezone()
    desde = ahora
    hasta = ahora + timedelta(minutes=ventana_minutos)

    clientes = {c["id"]: c for c in cargar("clientes.json").get("clientes", [])}
    cals = [c for c in cargar("calendarios.json")["calendarios_gmail"]
            if c.get("activo") and c.get("ical_url")]

    # 1. Leer eventos de los calendarios en la ventana
    proximos = []
    for cal in cals:
        try:
            req = urlreq.Request(cal["ical_url"], headers={"User-Agent": "Organizador/1.0"})
            with urlreq.urlopen(req, timeout=15) as r:
                ics = r.read()
            ical = Calendar.from_ical(ics)
            # Pedimos una ventana algo amplia para no perder eventos en el borde
            ocs = recurring_ical_events.of(ical).between(
                ahora - timedelta(minutes=5), hasta + timedelta(minutes=5))
            for ev in ocs:
                start = ev.get("DTSTART").dt if ev.get("DTSTART") else None
                end = ev.get("DTEND").dt if ev.get("DTEND") else start
                uid = str(ev.get("UID", ""))
                if not start or not hasattr(start, "hour"):
                    continue  # all-day no aplica
                # Normalizar a aware
                if start.tzinfo is None:
                    start = start.replace(tzinfo=ahora.tzinfo)
                if end and end.tzinfo is None:
                    end = end.replace(tzinfo=ahora.tzinfo)
                # ¿Cae dentro de [desde, hasta]?
                if desde <= start <= hasta:
                    cli = clientes.get(cal.get("cliente_asociado"), {})
                    proximos.append({
                        "uid": uid,
                        "titulo": str(ev.get("SUMMARY", "(sin título)")),
                        "inicio": start,
                        "fin": end,
                        "ubicacion": str(ev.get("LOCATION", "")),
                        "calendario": cal.get("nombre_para_mostrar"),
                        "cliente": cli.get("nombre", ""),
                        "color": cal.get("color", "#4A4D7A")
                    })
        except Exception as e:
            print(f"⚠️  Error leyendo {cal.get('email','?')}: {e}")

    # 2. Filtrar los ya avisados (consulta tabla)
    ya_avisados = set()
    if proximos:
        ids = [(p["uid"], p["inicio"]) for p in proximos]
        # Consulta una sola vez
        for uid, ini in ids:
            existing = _db.query(
                "SELECT 1 FROM eventos_avisados WHERE evento_uid=%s AND inicio=%s AND tipo_aviso='pre_10min'",
                (uid, ini))
            if existing:
                ya_avisados.add((uid, ini.isoformat()))

    nuevos = [p for p in proximos if (p["uid"], p["inicio"].isoformat()) not in ya_avisados]

    # 3. Marcar como avisados los nuevos
    for p in nuevos:
        try:
            _db.execute(
                "INSERT INTO eventos_avisados (evento_uid, inicio, tipo_aviso) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (p["uid"], p["inicio"], "pre_10min"))
        except Exception as e:
            print(f"⚠️  Error guardando aviso: {e}")

    # 4. Devolver
    salida = []
    for p in nuevos:
        delta = p["inicio"] - ahora
        min_restantes = max(0, int(delta.total_seconds() / 60))
        salida.append({
            "uid": p["uid"],
            "titulo": p["titulo"],
            "inicio": p["inicio"].isoformat(),
            "fin": p["fin"].isoformat() if p["fin"] else None,
            "hora_inicio": p["inicio"].strftime("%H:%M"),
            "hora_fin": p["fin"].strftime("%H:%M") if p["fin"] else None,
            "minutos_restantes": min_restantes,
            "ubicacion": p["ubicacion"],
            "calendario": p["calendario"],
            "cliente": p["cliente"],
            "color": p["color"]
        })
    return jsonify({"eventos": salida, "total": len(salida), "ventana_minutos": ventana_minutos})


# ============ SESIÓN DEL BOT (estado entre mensajes) ============

@app.route("/api/bot/sesion/<int:chat_id>", methods=["GET"])
@requiere_auth
def get_sesion(chat_id):
    if not _db.db_disponible():
        return jsonify({"sesion": None})
    rows = _db.query("SELECT flujo, paso, datos FROM sesiones_bot WHERE chat_id=%s", (chat_id,))
    if rows:
        s = rows[0]
        return jsonify({"sesion": {"flujo": s["flujo"], "paso": s["paso"], "datos": s["datos"]}})
    return jsonify({"sesion": None})


@app.route("/api/bot/sesion/<int:chat_id>", methods=["POST"])
@requiere_auth
def set_sesion(chat_id):
    body = request.get_json() or {}
    if not _db.db_disponible():
        return jsonify({"error": "DB no disponible"}), 500
    from psycopg2.extras import Json
    _db.execute("""
        INSERT INTO sesiones_bot (chat_id, flujo, paso, datos)
        VALUES (%s,%s,%s,%s)
        ON CONFLICT (chat_id) DO UPDATE SET
          flujo=EXCLUDED.flujo, paso=EXCLUDED.paso,
          datos=EXCLUDED.datos, actualizado=NOW()
    """, (chat_id, body.get("flujo",""), body.get("paso",""), Json(body.get("datos", {}))))
    return jsonify({"ok": True})


@app.route("/api/bot/sesion/<int:chat_id>", methods=["DELETE"])
@requiere_auth
def del_sesion(chat_id):
    if _db.db_disponible():
        _db.execute("DELETE FROM sesiones_bot WHERE chat_id=%s", (chat_id,))
    return jsonify({"ok": True})


# ============ HORARIO DE SUEÑO (global) ============

SUENO_DEFAULT = {"despertar": "06:00", "dormir": "23:00"}


def _cargar_horario_sueno():
    config = cargar("config.json")
    s = config.get("horario_sueno") if isinstance(config, dict) else None
    if not isinstance(s, dict):
        return dict(SUENO_DEFAULT)
    return {
        "despertar": s.get("despertar", SUENO_DEFAULT["despertar"]),
        "dormir":    s.get("dormir",    SUENO_DEFAULT["dormir"])
    }


@app.route("/api/horario-sueno", methods=["GET"])
@requiere_auth
def get_horario_sueno():
    return jsonify(_cargar_horario_sueno())


@app.route("/api/horario-sueno", methods=["PUT"])
@requiere_auth
def put_horario_sueno():
    body = request.get_json() or {}
    config = cargar("config.json")
    config["horario_sueno"] = {
        "despertar": body.get("despertar", SUENO_DEFAULT["despertar"]),
        "dormir":    body.get("dormir",    SUENO_DEFAULT["dormir"])
    }
    guardar("config.json", config)
    return jsonify({"ok": True, "horario_sueno": _cargar_horario_sueno()})


# ============ HORARIO LABORAL POR DÍA ============

HORARIO_DEFAULT = {
    "1": {"activo": True,  "inicio": "08:00", "fin": "18:00"},  # Lun
    "2": {"activo": True,  "inicio": "08:00", "fin": "18:00"},  # Mar
    "3": {"activo": True,  "inicio": "08:00", "fin": "18:00"},  # Mié
    "4": {"activo": True,  "inicio": "08:00", "fin": "18:00"},  # Jue
    "5": {"activo": True,  "inicio": "08:00", "fin": "18:00"},  # Vie
    "6": {"activo": False, "inicio": "09:00", "fin": "13:00"},  # Sáb
    "7": {"activo": False, "inicio": "00:00", "fin": "00:00"}   # Dom
}


def _cargar_horario_laboral():
    config = cargar("config.json")
    hl = config.get("horario_laboral") if isinstance(config, dict) else None
    if not isinstance(hl, dict) or not hl:
        return dict(HORARIO_DEFAULT)
    # Asegurar las 7 claves
    out = dict(HORARIO_DEFAULT)
    for k in ["1","2","3","4","5","6","7"]:
        if k in hl and isinstance(hl[k], dict):
            out[k] = {
                "activo": bool(hl[k].get("activo", False)),
                "inicio": hl[k].get("inicio", out[k]["inicio"]),
                "fin":    hl[k].get("fin",    out[k]["fin"])
            }
    return out


@app.route("/api/horario-laboral", methods=["GET"])
@requiere_auth
def get_horario_laboral():
    return jsonify(_cargar_horario_laboral())


@app.route("/api/horario-laboral", methods=["PUT"])
@requiere_auth
def put_horario_laboral():
    body = request.get_json() or {}
    # Validación mínima
    if not isinstance(body, dict):
        return jsonify({"error": "body debe ser dict {1..7: {...}}"}), 400
    config = cargar("config.json")
    config["horario_laboral"] = body
    guardar("config.json", config)
    return jsonify({"ok": True, "horario_laboral": _cargar_horario_laboral()})


# ============ ESPACIOS LIBRES EN LA AGENDA ============

@app.route("/api/agenda/libres", methods=["GET"])
@requiere_auth
def agenda_libres():
    """Calcula los espacios libres en un día dado, leyendo iCal y considerando
    la ventana de trabajo (horarios.inicio_dia / fin_dia de config).

    Query: ?fecha=YYYY-MM-DD&min_gap_min=15
    """
    from datetime import timedelta

    fecha_str = request.args.get("fecha")
    if not fecha_str:
        return jsonify({"error": "Falta param 'fecha' (YYYY-MM-DD)"}), 400
    try:
        fecha = date.fromisoformat(fecha_str)
    except ValueError:
        return jsonify({"error": "Fecha inválida"}), 400

    min_gap = int(request.args.get("min_gap_min", 15))

    # Horario laboral según el día de la semana (ISO: 1=Lun..7=Dom)
    iso_dow = str(fecha.isoweekday())
    horario_lab = _cargar_horario_laboral()
    hoy_lab = horario_lab.get(iso_dow, HORARIO_DEFAULT[iso_dow])

    if not hoy_lab.get("activo"):
        return jsonify({
            "fecha": fecha_str,
            "no_laboral": True,
            "mensaje": "Día no laboral según tu configuración",
            "espacios_libres": [],
            "eventos": [],
            "total_libre_min": 0,
            "total_ocupado_min": 0
        })

    inicio_dia = hoy_lab.get("inicio", "08:00")
    fin_dia = hoy_lab.get("fin", "18:00")
    try:
        ih, im = map(int, inicio_dia.split(":"))
        fh, fm = map(int, fin_dia.split(":"))
    except Exception:
        ih, im, fh, fm = 8, 0, 18, 0

    # TZ Colombia
    from datetime import timezone
    tz = timezone(timedelta(hours=-5))
    ventana_inicio = datetime.combine(fecha, datetime.min.time()).replace(hour=ih, minute=im, tzinfo=tz)
    ventana_fin = datetime.combine(fecha, datetime.min.time()).replace(hour=fh, minute=fm, tzinfo=tz)

    # Cargar eventos del día con expansión RRULE
    try:
        from icalendar import Calendar
        import recurring_ical_events
        import urllib.request as urlreq
    except ImportError:
        return jsonify({"error": "Falta librería icalendar / recurring_ical_events"}), 500

    cals = [c for c in cargar("calendarios.json")["calendarios_gmail"]
            if c.get("activo") and c.get("ical_url")]

    eventos = []
    for cal in cals:
        try:
            req = urlreq.Request(cal["ical_url"], headers={"User-Agent": "Organizador/1.0"})
            with urlreq.urlopen(req, timeout=15) as r:
                ics = r.read()
            ical = Calendar.from_ical(ics)
            ocs = recurring_ical_events.of(ical).between(
                ventana_inicio - timedelta(hours=2),
                ventana_fin + timedelta(hours=2))
            for ev in ocs:
                start = ev.get("DTSTART").dt if ev.get("DTSTART") else None
                end = ev.get("DTEND").dt if ev.get("DTEND") else start
                if not start or not hasattr(start, "hour"):
                    continue  # all-day no bloquea
                if start.tzinfo is None:
                    start = start.replace(tzinfo=tz)
                if end and end.tzinfo is None:
                    end = end.replace(tzinfo=tz)
                # Solo eventos que solapan con la ventana de trabajo
                if end <= ventana_inicio or start >= ventana_fin:
                    continue
                eventos.append({
                    "titulo": str(ev.get("SUMMARY", "(sin título)")),
                    "inicio": max(start, ventana_inicio),
                    "fin": min(end, ventana_fin),
                    "calendario": cal.get("nombre_para_mostrar")
                })
        except Exception:
            pass

    eventos.sort(key=lambda e: e["inicio"])

    # Calcular gaps entre eventos
    libres = []
    cursor = ventana_inicio
    for ev in eventos:
        gap_min = int((ev["inicio"] - cursor).total_seconds() / 60)
        if gap_min >= min_gap:
            libres.append({
                "inicio": cursor.isoformat(),
                "fin": ev["inicio"].isoformat(),
                "duracion_min": gap_min
            })
        if ev["fin"] > cursor:
            cursor = ev["fin"]
    # Gap final
    gap_final = int((ventana_fin - cursor).total_seconds() / 60)
    if gap_final >= min_gap:
        libres.append({
            "inicio": cursor.isoformat(),
            "fin": ventana_fin.isoformat(),
            "duracion_min": gap_final
        })

    total_libre = sum(l["duracion_min"] for l in libres)
    total_ocupado = int((ventana_fin - ventana_inicio).total_seconds() / 60) - total_libre

    return jsonify({
        "fecha": fecha_str,
        "ventana_inicio": ventana_inicio.isoformat(),
        "ventana_fin": ventana_fin.isoformat(),
        "min_gap_min": min_gap,
        "eventos": [{
            "titulo": e["titulo"],
            "inicio": e["inicio"].isoformat(),
            "fin": e["fin"].isoformat(),
            "calendario": e["calendario"]
        } for e in eventos],
        "espacios_libres": libres,
        "total_libre_min": total_libre,
        "total_ocupado_min": total_ocupado
    })


# ============ REUNIONES (check disponibilidad + link Google Calendar) ============

def _parse_iso(s):
    """Parsea ISO con o sin TZ. Si no tiene TZ, asume Colombia (-05:00)."""
    if not s: return None
    if 'T' not in s:
        s = s + 'T00:00:00-05:00'
    elif '+' not in s and 'Z' not in s and s.count('-') < 3:
        s = s + '-05:00'
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


@app.route("/api/reunion/proponer", methods=["POST"])
@requiere_auth
def proponer_reunion():
    """Recibe propuesta de reunión, chequea conflictos contra calendarios iCal,
    devuelve link de Google Calendar deeplink para crear con 1 click."""
    from datetime import timedelta
    import urllib.parse

    body = request.get_json() or {}
    titulo = (body.get("titulo") or "").strip()
    fecha_hora = body.get("fecha_hora")  # ISO con TZ
    duracion_min = int(body.get("duracion_min") or 60)
    invitados = body.get("invitados") or []  # lista de strings
    descripcion = (body.get("descripcion") or "").strip()
    ubicacion = (body.get("ubicacion") or "").strip()

    if not titulo or not fecha_hora:
        return jsonify({"error": "Faltan campos: titulo o fecha_hora"}), 400

    inicio = _parse_iso(fecha_hora)
    if not inicio:
        return jsonify({"error": "Fecha/hora inválida (usa ISO)"}), 400
    fin = inicio + timedelta(minutes=duracion_min)

    # Limpiar invitados (quitar vacíos, validar @)
    inv_clean = [e.strip() for e in invitados if "@" in str(e)]

    # === Chequear conflictos contra iCal ===
    conflictos = []
    try:
        from icalendar import Calendar
        import recurring_ical_events
        import urllib.request as urlreq

        cals = [c for c in cargar("calendarios.json")["calendarios_gmail"]
                if c.get("activo") and c.get("ical_url")]

        # Ampliar rango ±1 día para cubrir eventos que crucen medianoche
        rango_desde = inicio - timedelta(hours=12)
        rango_hasta = fin + timedelta(hours=12)

        for cal in cals:
            try:
                req = urlreq.Request(cal["ical_url"], headers={"User-Agent": "Organizador/1.0"})
                with urlreq.urlopen(req, timeout=15) as r:
                    ics = r.read()
                ical = Calendar.from_ical(ics)
                ocs = recurring_ical_events.of(ical).between(rango_desde, rango_hasta)
                for ev in ocs:
                    e_start = ev.get("DTSTART").dt if ev.get("DTSTART") else None
                    e_end = ev.get("DTEND").dt if ev.get("DTEND") else e_start
                    if not e_start: continue
                    # normalizar a datetime con TZ
                    if not hasattr(e_start, "hour"):
                        continue  # all-day no consideramos como conflicto duro
                    if not hasattr(e_start, "tzinfo") or e_start.tzinfo is None:
                        e_start = e_start.replace(tzinfo=inicio.tzinfo)
                    if not hasattr(e_end, "tzinfo") or e_end.tzinfo is None:
                        e_end = e_end.replace(tzinfo=inicio.tzinfo)
                    # Overlap check: [inicio,fin) vs [e_start,e_end)
                    if e_start < fin and e_end > inicio:
                        conflictos.append({
                            "titulo": str(ev.get("SUMMARY", "(sin título)")),
                            "calendario": cal["nombre_para_mostrar"],
                            "inicio": e_start.isoformat(),
                            "fin": e_end.isoformat()
                        })
            except Exception:
                pass
    except ImportError:
        pass

    # === Construir Google Calendar deeplink ===
    def _gcal_dt(d):
        """Format UTC para Google Calendar deeplink."""
        if d.tzinfo:
            d_utc = d.astimezone()  # convertir a TZ local del server (Bogotá)
            return d_utc.strftime("%Y%m%dT%H%M%S")
        return d.strftime("%Y%m%dT%H%M%S")

    gcal_params = {
        "action": "TEMPLATE",
        "text": titulo,
        "dates": f"{_gcal_dt(inicio)}/{_gcal_dt(fin)}",
        "ctz": "America/Bogota"
    }
    if descripcion:
        gcal_params["details"] = descripcion
    if ubicacion:
        gcal_params["location"] = ubicacion
    if inv_clean:
        gcal_params["add"] = ",".join(inv_clean)

    gcal_url = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(gcal_params)

    # Mensaje de status
    if conflictos:
        msg = f"⚠️ Tienes {len(conflictos)} conflicto{'s' if len(conflictos)!=1 else ''} en ese horario"
    else:
        msg = "✅ Horario disponible"

    return jsonify({
        "ok": True,
        "titulo": titulo,
        "inicio": inicio.isoformat(),
        "fin": fin.isoformat(),
        "duracion_min": duracion_min,
        "invitados": inv_clean,
        "conflictos": conflictos,
        "disponible": len(conflictos) == 0,
        "mensaje": msg,
        "google_calendar_url": gcal_url
    })


# ============ RECORDATORIOS ============

@app.route("/api/recordatorios", methods=["GET"])
@requiere_auth
def get_recordatorios():
    return jsonify(cargar("recordatorios.json"))


@app.route("/api/recordatorios", methods=["POST"])
@requiere_auth
def post_recordatorio():
    body = request.get_json()
    data = cargar("recordatorios.json")
    nuevo = {
        "id": body.get("id") or nuevo_id("rec"),
        "titulo": body["titulo"],
        "mensaje": body.get("mensaje", ""),
        "fecha_hora": body["fecha_hora"],
        "repetir": body.get("repetir", "no"),
        "cliente_id": body.get("cliente_id"),
        "enviado": False,
        "enviado_at": None,
        "activo": True
    }
    data["recordatorios"].append(nuevo)
    guardar("recordatorios.json", data)
    # Programar en el scheduler — dispara EXACTO a su hora
    if _SCHED_OK:
        try:
            _sched.programar_recordatorio(nuevo["id"], nuevo["fecha_hora"])
        except Exception as e:
            print(f"⚠️  No se pudo programar recordatorio: {e}")
    return jsonify(nuevo), 201


@app.route("/api/recordatorios/<rid>", methods=["PUT"])
@requiere_auth
def put_recordatorio(rid):
    body = request.get_json()
    data = cargar("recordatorios.json")
    for r in data["recordatorios"]:
        if r["id"] == rid:
            r.update({k: v for k, v in body.items() if k != "id"})
            guardar("recordatorios.json", data)
            # Re-programar si cambió la fecha
            if _SCHED_OK and "fecha_hora" in body:
                try:
                    _sched.programar_recordatorio(rid, r["fecha_hora"])
                except Exception as e:
                    print(f"⚠️  No se pudo re-programar: {e}")
            return jsonify(r)
    return jsonify({"error": "Recordatorio no encontrado"}), 404


@app.route("/api/recordatorios/<rid>", methods=["DELETE"])
@requiere_auth
def delete_recordatorio(rid):
    data = cargar("recordatorios.json")
    data["recordatorios"] = [r for r in data["recordatorios"] if r["id"] != rid]
    guardar("recordatorios.json", data)
    if _SCHED_OK:
        try:
            _sched.cancelar_recordatorio(rid)
        except Exception:
            pass
    return jsonify({"ok": True})


@app.route("/api/recordatorios/disparar", methods=["POST", "GET"])
@requiere_auth
def disparar_recordatorios():
    """Devuelve recordatorios que YA pasaron pero no se han enviado.
    Marca los devueltos como enviados. Genera próxima ocurrencia si repite."""
    from datetime import timedelta
    if not _db.db_disponible():
        return jsonify({"recordatorios": [], "error": "DB no disponible"}), 500

    ahora = datetime.now()
    pendientes = _db.query("""
        SELECT id, titulo, mensaje, fecha_hora, repetir, cliente_id
        FROM recordatorios
        WHERE NOT enviado AND activo AND fecha_hora <= %s
        ORDER BY fecha_hora ASC
        LIMIT 20
    """, (ahora,))

    salida = []
    for r in pendientes:
        salida.append({
            "id": r["id"], "titulo": r["titulo"], "mensaje": r["mensaje"],
            "fecha_hora": r["fecha_hora"].isoformat() if hasattr(r["fecha_hora"],'isoformat') else str(r["fecha_hora"]),
            "repetir": r["repetir"], "cliente_id": r["cliente_id"]
        })
        # marcar enviado
        _db.execute("UPDATE recordatorios SET enviado=TRUE, enviado_at=%s WHERE id=%s",
                    (ahora, r["id"]))
        # si repite, crear el siguiente
        if r["repetir"] != "no":
            base = r["fecha_hora"]
            if hasattr(base, "isoformat"):
                pass
            else:
                base = datetime.fromisoformat(str(base))
            delta = {
                "diario":   timedelta(days=1),
                "semanal":  timedelta(weeks=1),
                "mensual":  timedelta(days=30),  # aproximado
                "anual":    timedelta(days=365)
            }.get(r["repetir"])
            if delta:
                nuevo_dt = base + delta
                _db.execute("""
                    INSERT INTO recordatorios (id, titulo, mensaje, fecha_hora, repetir, cliente_id, enviado, activo)
                    VALUES (%s,%s,%s,%s,%s,%s,FALSE,TRUE)
                """, (nuevo_id("rec"), r["titulo"], r["mensaje"], nuevo_dt, r["repetir"], r["cliente_id"]))
    return jsonify({"recordatorios": salida, "total": len(salida)})


# ============ MÉTRICAS / PROGRESO ============

_LOGROS_HABITO = [
    ("primera_marca",     "Primera marca",     "Marcaste un hábito por primera vez", 1),
    ("racha_semana",      "Semana completa",   "7 días seguidos",                    7),
    ("racha_quincena",    "Dos semanas",       "14 días seguidos",                  14),
    ("racha_mes",         "Mes consistente",   "30 días seguidos",                  30),
    ("racha_trimestre",   "Trimestre",         "90 días seguidos",                  90),
    ("racha_anual",       "Un año",            "365 días seguidos",                365),
]

_LOGROS_PROYECTO = [
    ("primer_completado", "Primer proyecto cerrado", "Completaste tu primer proyecto", 1),
    ("cinco_completados", "Cinco proyectos",         "5 proyectos completados",         5),
    ("diez_completados",  "Veterano",                "10 proyectos completados",       10),
    ("a_tiempo",          "Puntual",                 "Cerraste un proyecto antes del deadline", 1),
]


@app.route("/api/metricas/habitos", methods=["GET"])
@requiere_auth
def metricas_habitos():
    """Devuelve métricas detalladas por hábito + agregadas."""
    from datetime import timedelta
    habitos_data = cargar("habitos.json")
    cats = {c["id"]: c for c in habitos_data.get("categorias", [])}
    activos = [h for h in habitos_data.get("habitos", []) if h.get("activo")]

    hoy = date.today()
    inicio_30 = hoy - timedelta(days=29)
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    # Cargar todos los registros de los últimos 365 días en memoria
    cumplidos_por_habito = {}
    if hasattr(_db := __import__('db'), 'db_disponible') and _db.db_disponible():
        try:
            rows = _db.query(
                "SELECT habito_id, fecha FROM habitos_registros WHERE fecha >= %s",
                ((hoy - timedelta(days=365)).isoformat(),)
            )
            for r in rows:
                cumplidos_por_habito.setdefault(r["habito_id"], set()).add(str(r["fecha"]))
        except Exception:
            pass

    # Fallback: leer JSON
    if not cumplidos_por_habito:
        from comun import REGISTROS
        if REGISTROS.exists():
            for f in REGISTROS.glob("*.json"):
                try:
                    reg = json.loads(f.read_text())
                    for hid in reg.get("habitos_cumplidos", []):
                        cumplidos_por_habito.setdefault(hid, set()).add(reg["fecha"])
                except Exception:
                    pass

    out_habitos = []
    total_cumplidos_hoy = 0
    mejor_racha_global = 0

    for h in activos:
        completados = cumplidos_por_habito.get(h["id"], set())
        cat = cats.get(h.get("categoria_id"), {"nombre": "—", "icono": "•", "color": "#888"})

        # últimos 30 días con flag de cumplido
        ultimos_30 = []
        for i in range(30):
            d = inicio_30 + timedelta(days=i)
            ultimos_30.append({"fecha": d.isoformat(), "cumplido": d.isoformat() in completados})

        # semanas (últimas 12)
        semanas = []
        for w in range(12):
            ws = hoy - timedelta(days=hoy.weekday() + 7*w)
            we = ws + timedelta(days=6)
            cnt = sum(1 for d in (ws + timedelta(n) for n in range(7))
                      if d.isoformat() in completados and d <= hoy)
            total_dias = min(7, (hoy - ws).days + 1)
            semanas.append({
                "semana_inicio": ws.isoformat(),
                "cumplidos": cnt,
                "total": total_dias,
                "pct": round(cnt / max(1, total_dias) * 100)
            })
        semanas.reverse()

        # mes actual
        dias_mes = (hoy - inicio_mes).days + 1
        cumplidos_mes = sum(1 for d in completados if d >= inicio_mes.isoformat() and d <= hoy.isoformat())
        cumplidos_semana = sum(1 for d in completados if d >= inicio_semana.isoformat() and d <= hoy.isoformat())

        # Racha — depende del tipo de hábito
        tipo = h.get("tipo", "bueno")
        racha = 0
        if tipo == "bueno":
            # Días consecutivos cumplidos hasta hoy
            d = hoy
            while d.isoformat() in completados:
                racha += 1
                d -= timedelta(days=1)
        else:  # malo
            # Días consecutivos SIN caer (hoy hacia atrás)
            d = hoy
            limite = 365  # safety
            while d.isoformat() not in completados and limite > 0:
                racha += 1
                d -= timedelta(days=1)
                limite -= 1
        mejor_racha = max(h.get("mejor_racha", 0), racha)
        mejor_racha_global = max(mejor_racha_global, mejor_racha)

        if hoy.isoformat() in completados:
            total_cumplidos_hoy += 1

        # logros
        total_marcas = len(completados)
        logros = []
        for lid, titulo, desc, umbral in _LOGROS_HABITO:
            if lid == "primera_marca":
                desbloqueado = total_marcas >= 1
            else:
                desbloqueado = mejor_racha >= umbral
            logros.append({"id": lid, "titulo": titulo, "descripcion": desc,
                           "umbral": umbral, "desbloqueado": desbloqueado})

        out_habitos.append({
            "id": h["id"],
            "nombre": h["nombre"],
            "categoria": cat["nombre"],
            "icono": cat.get("icono", "•"),
            "color": cat.get("color", "#888"),
            "tipo": tipo,
            "racha_actual": racha,
            "mejor_racha": mejor_racha,
            "total_marcas": total_marcas,
            "ultimos_30_dias": ultimos_30,
            "semanas": semanas,
            "este_mes": {"cumplidos": cumplidos_mes, "total": dias_mes,
                         "pct": round(cumplidos_mes / max(1, dias_mes) * 100)},
            "esta_semana": {"cumplidos": cumplidos_semana, "total": min(7, (hoy - inicio_semana).days + 1),
                            "pct": round(cumplidos_semana / max(1, min(7, (hoy - inicio_semana).days + 1)) * 100)},
            "logros": logros
        })

    return jsonify({
        "habitos": out_habitos,
        "totales": {
            "habitos_activos": len(activos),
            "cumplidos_hoy": total_cumplidos_hoy,
            "mejor_racha_global": mejor_racha_global,
            "logros_desbloqueados": sum(1 for h in out_habitos for l in h["logros"] if l["desbloqueado"])
        }
    })


@app.route("/api/metricas/proyectos", methods=["GET"])
@requiere_auth
def metricas_proyectos():
    """Devuelve métricas por proyecto + agregadas."""
    from datetime import timedelta
    clientes = cargar("clientes.json").get("clientes", [])
    cmap = {c["id"]: c for c in clientes}
    proyectos = cargar("proyectos.json").get("proyectos", [])
    actividades = cargar("actividades.json").get("actividades", [])

    hoy = date.today()
    inicio_30 = hoy - timedelta(days=29)

    # Tareas completadas por día (últimos 30 días)
    completadas_por_dia = {(inicio_30 + timedelta(n)).isoformat(): 0 for n in range(30)}
    for a in actividades:
        if a.get("estado") == "completada" and a.get("completada_en"):
            try:
                f = str(a["completada_en"])[:10]
                if f in completadas_por_dia:
                    completadas_por_dia[f] += 1
            except Exception:
                pass

    # Por proyecto: contar tareas totales y completadas
    proyectos_metricas = []
    completados_total = 0
    a_tiempo = False
    for p in proyectos:
        tareas_p = [a for a in actividades if a.get("proyecto_id") == p["id"]]
        completadas = sum(1 for a in tareas_p if a.get("estado") == "completada")
        total = len(tareas_p)
        cli = cmap.get(p.get("cliente_id"), {"nombre": "—", "color": "#888"})
        dias_rest = None
        if p.get("deadline"):
            try:
                deadline = date.fromisoformat(str(p["deadline"]))
                dias_rest = (deadline - hoy).days
            except Exception:
                pass

        if p.get("estado") == "completado":
            completados_total += 1
            if p.get("deadline") and dias_rest is not None and dias_rest >= 0:
                a_tiempo = True

        ultima_act = None
        for a in tareas_p:
            ts = a.get("completada_en") or a.get("creada")
            if ts and (not ultima_act or str(ts) > str(ultima_act)):
                ultima_act = ts

        proyectos_metricas.append({
            "id": p["id"],
            "nombre": p["nombre"],
            "cliente": cli["nombre"],
            "color": cli.get("color", "#888"),
            "estado": p.get("estado", "activo"),
            "prioridad": p.get("prioridad", "media"),
            "tareas_totales": total,
            "tareas_completadas": completadas,
            "pct_progreso": round(completadas / max(1, total) * 100) if total else 0,
            "deadline": str(p["deadline"]) if p.get("deadline") else None,
            "dias_restantes": dias_rest,
            "ultima_actividad": str(ultima_act)[:10] if ultima_act else None
        })

    # Distribución por estado
    por_estado = {"activo": 0, "pausado": 0, "completado": 0, "archivado": 0}
    for p in proyectos:
        e = p.get("estado", "activo")
        por_estado[e] = por_estado.get(e, 0) + 1

    # Tareas completadas por cliente (últimos 30 días)
    por_cliente_30d = {}
    for a in actividades:
        if a.get("estado") == "completada" and a.get("completada_en"):
            f = str(a["completada_en"])[:10]
            if f >= inicio_30.isoformat():
                cid = a.get("cliente_id")
                por_cliente_30d[cid] = por_cliente_30d.get(cid, 0) + 1
    completadas_por_cliente = [
        {"cliente_id": cid, "nombre": cmap.get(cid, {}).get("nombre", "—"),
         "color": cmap.get(cid, {}).get("color", "#888"), "tareas": n}
        for cid, n in sorted(por_cliente_30d.items(), key=lambda x: -x[1])
    ]

    # Logros
    logros = []
    for lid, titulo, desc, umbral in _LOGROS_PROYECTO:
        if lid == "a_tiempo":
            desbloqueado = a_tiempo
        else:
            desbloqueado = completados_total >= umbral
        logros.append({"id": lid, "titulo": titulo, "descripcion": desc,
                       "umbral": umbral, "desbloqueado": desbloqueado})

    return jsonify({
        "proyectos": proyectos_metricas,
        "totales": {
            "proyectos_total": len(proyectos),
            "proyectos_activos": por_estado.get("activo", 0),
            "proyectos_completados": completados_total,
            "tareas_completadas_30d": sum(completadas_por_dia.values()),
            "tareas_pendientes": sum(1 for a in actividades if a.get("estado") == "pendiente")
        },
        "completadas_por_dia": [{"fecha": f, "n": n} for f, n in completadas_por_dia.items()],
        "completadas_por_cliente": completadas_por_cliente,
        "por_estado": por_estado,
        "logros": logros
    })


# ============ CALENDARIOS GMAIL ============

@app.route("/api/calendarios", methods=["GET"])
@requiere_auth
def get_calendarios():
    return jsonify(cargar("calendarios.json"))


@app.route("/api/calendarios", methods=["POST"])
@requiere_auth
def post_calendario():
    body = request.get_json()
    data = cargar("calendarios.json")
    nombre = body.get("nombre_para_mostrar") or body.get("email", "calendario").split("@")[0]
    nuevo = {
        "id": body.get("id") or nuevo_id("cal"),
        "email": body.get("email", ""),
        "ical_url": body.get("ical_url", ""),
        "nombre_para_mostrar": nombre,
        "cliente_asociado": body.get("cliente_asociado") or body.get("empresa_asociada"),
        "persona_id": body.get("persona_id"),
        "color": body.get("color", "#4ECDC4"),
        "activo": body.get("activo", True)
    }
    data["calendarios_gmail"].append(nuevo)
    guardar("calendarios.json", data)
    return jsonify(nuevo), 201


@app.route("/api/calendarios/<cid>", methods=["PUT"])
@requiere_auth
def put_calendario(cid):
    body = request.get_json()
    data = cargar("calendarios.json")
    for c in data["calendarios_gmail"]:
        if c["id"] == cid:
            c.update({k: v for k, v in body.items() if k != "id"})
            guardar("calendarios.json", data)
            return jsonify(c)
    return jsonify({"error": "Calendario no encontrado"}), 404


@app.route("/api/calendarios/<cid>", methods=["DELETE"])
@requiere_auth
def delete_calendario(cid):
    data = cargar("calendarios.json")
    data["calendarios_gmail"] = [c for c in data["calendarios_gmail"] if c["id"] != cid]
    guardar("calendarios.json", data)
    return jsonify({"ok": True})


@app.route("/api/calendarios/estado_oauth", methods=["GET"])
@requiere_auth
def estado_oauth():
    """Indica si ya está conectado con Google."""
    return jsonify({
        "credentials_json": GOOGLE_CRED.exists(),
        "token_json": GOOGLE_TOKEN.exists(),
        "listo_para_usar": GOOGLE_CRED.exists() and GOOGLE_TOKEN.exists(),
        "redirect_uri_esperado": GOOGLE_REDIRECT_URI
    })


# ============ OAUTH GOOGLE (flujo desde la web) ============

@app.route("/api/oauth/google/credentials", methods=["POST"])
@requiere_auth
def subir_credentials():
    """Recibe el contenido de credentials.json (descargado de Google Cloud) y lo guarda."""
    body = request.get_json()
    contenido = body.get("contenido")
    if not contenido:
        return jsonify({"error": "Falta 'contenido' con el JSON de Google"}), 400
    try:
        data = json.loads(contenido) if isinstance(contenido, str) else contenido
    except json.JSONDecodeError as e:
        return jsonify({"error": f"JSON inválido: {e}"}), 400

    # Validación mínima del formato esperado
    if not (data.get("installed") or data.get("web")):
        return jsonify({"error": "El JSON no parece de Google OAuth. Debe contener 'installed' o 'web'."}), 400

    GOOGLE_CRED.write_text(json.dumps(data, indent=2))
    return jsonify({"ok": True, "ruta": str(GOOGLE_CRED)})


@app.route("/api/oauth/google/start", methods=["GET"])
def oauth_start():
    """Devuelve la URL de autorización de Google. NO requiere auth (es flujo público)."""
    if not GOOGLE_CRED.exists():
        return jsonify({"error": "Falta credentials.json. Súbelo primero."}), 400
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return jsonify({"error": "Falta instalar: pip install google-auth-oauthlib"}), 500

    flow = Flow.from_client_secrets_file(
        str(GOOGLE_CRED),
        scopes=GOOGLE_SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true"
    )
    (INTEGRACIONES / ".oauth_state").write_text(state)
    if getattr(flow, "code_verifier", None):
        (INTEGRACIONES / ".oauth_code_verifier").write_text(flow.code_verifier)
    return jsonify({"auth_url": auth_url, "state": state})


@app.route("/api/oauth/google/callback", methods=["GET"])
def oauth_callback():
    """Google redirige aquí con el código. Lo intercambiamos por token.json."""
    code = request.args.get("code")
    error = request.args.get("error")
    if error:
        return _pagina_resultado(False, f"Google devolvió error: {error}")
    if not code:
        return _pagina_resultado(False, "No llegó el código de autorización")

    if not GOOGLE_CRED.exists():
        return _pagina_resultado(False, "Falta credentials.json")

    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return _pagina_resultado(False, "Librería google-auth-oauthlib no instalada")

    try:
        flow = Flow.from_client_secrets_file(
            str(GOOGLE_CRED),
            scopes=GOOGLE_SCOPES,
            redirect_uri=GOOGLE_REDIRECT_URI
        )
        verifier_path = INTEGRACIONES / ".oauth_code_verifier"
        if verifier_path.exists():
            flow.code_verifier = verifier_path.read_text().strip()
        flow.fetch_token(code=code)
        creds = flow.credentials
        GOOGLE_TOKEN.write_text(creds.to_json())
        return _pagina_resultado(True, "Conexión exitosa con Google Calendar")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return _pagina_resultado(False, f"Error al obtener token: {e}")


def _pagina_resultado(ok: bool, mensaje: str) -> str:
    color = "#10b981" if ok else "#ef4444"
    icono = "✅" if ok else "❌"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{'Conectado' if ok else 'Error'}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #0f1115; color: #e8eaf0;
    display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .card {{ background: #181b22; border: 1px solid #2a2f3a; border-radius: 14px;
    padding: 32px 40px; max-width: 480px; text-align: center; }}
  h1 {{ color: {color}; margin-top: 0; }}
  a {{ color: #a78bfa; text-decoration: none; }}
</style></head>
<body><div class="card">
  <h1>{icono} {'Conectado' if ok else 'Algo falló'}</h1>
  <p>{mensaje}</p>
  <p><a href="/tablero/admin.html">← Volver al admin</a></p>
  <script>setTimeout(() => window.location.href = '/tablero/admin.html', 2500);</script>
</div></body></html>"""


@app.route("/api/oauth/google/export_token", methods=["GET"])
@requiere_auth
def export_token():
    """Devuelve el contenido de token.json. SOLO para que el admin lo guarde
    como variable de entorno GOOGLE_TOKEN_JSON y sobreviva reinicios."""
    if not GOOGLE_TOKEN.exists():
        return jsonify({"error": "No hay token.json. Hacé OAuth primero."}), 404
    try:
        return jsonify({"ok": True, "contenido": GOOGLE_TOKEN.read_text()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/oauth/google/export_credentials", methods=["GET"])
@requiere_auth
def export_credentials():
    """Devuelve el contenido de credentials.json. SOLO para que el admin lo
    guarde como variable de entorno GOOGLE_CREDENTIALS_JSON."""
    if not GOOGLE_CRED.exists():
        return jsonify({"error": "No hay credentials.json"}), 404
    try:
        return jsonify({"ok": True, "contenido": GOOGLE_CRED.read_text()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/oauth/google/disconnect", methods=["POST"])
@requiere_auth
def oauth_disconnect():
    """Elimina el token (no las credentials)."""
    if GOOGLE_TOKEN.exists():
        GOOGLE_TOKEN.unlink()
    return jsonify({"ok": True})


_PALETA_GOOGLE_CACHE = {"paleta": None, "ts": 0}


def _google_creds():
    """Devuelve credenciales Google refrescadas, o None si no hay OAuth."""
    if not GOOGLE_TOKEN.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GRequest
    except ImportError:
        return None
    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        GOOGLE_TOKEN.write_text(creds.to_json())
    return creds


def _obtener_paleta_google(creds):
    """Devuelve dict {'event': {id: hex}, 'calendar': {id: hex}}. Cachea 1h."""
    import time as _time
    if _PALETA_GOOGLE_CACHE["paleta"] and (_time.time() - _PALETA_GOOGLE_CACHE["ts"] < 3600):
        return _PALETA_GOOGLE_CACHE["paleta"]
    try:
        from googleapiclient.discovery import build
        servicio = build("calendar", "v3", credentials=creds)
        colors = servicio.colors().get().execute()
        paleta = {
            "event":    {k: v.get("background", "#888888") for k, v in colors.get("event", {}).items()},
            "calendar": {k: v.get("background", "#888888") for k, v in colors.get("calendar", {}).items()}
        }
        _PALETA_GOOGLE_CACHE["paleta"] = paleta
        _PALETA_GOOGLE_CACHE["ts"] = _time.time()
        return paleta
    except Exception:
        return {"event": {}, "calendar": {}}


@app.route("/api/calendarios/sync_google", methods=["POST"])
@requiere_auth
def sync_google():
    """Sincroniza la lista local con los calendarios visibles en Google.
    Agrega los que faltan (match por email/id de Google). No borra ni desactiva."""
    creds = _google_creds()
    if not creds:
        return jsonify({"error": "No conectado con Google. Conecta OAuth primero."}), 400
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return jsonify({"error": "Falta librería google-api-python-client"}), 500

    try:
        servicio = build("calendar", "v3", credentials=creds)
        cals_google = servicio.calendarList().list().execute().get("items", [])
    except Exception as e:
        return jsonify({"error": f"Error consultando Google: {e}"}), 500

    data = cargar("calendarios.json")
    if "calendarios_gmail" not in data:
        data["calendarios_gmail"] = []
    emails_existentes = {(c.get("email") or "").lower() for c in data["calendarios_gmail"] if c.get("email")}

    # Cliente "personal" como default; si no existe, el primero activo
    try:
        clientes = cargar("clientes.json").get("clientes", [])
        cliente_default = next(
            (c["id"] for c in clientes if c["id"] == "personal" and c.get("activo")),
            next((c["id"] for c in clientes if c.get("activo")), None)
        )
    except Exception:
        cliente_default = None

    agregados = []
    for cg in cals_google:
        gid = cg["id"]
        if gid.lower() in emails_existentes:
            continue
        # Saltar calendarios "festivos" de Google (ruido) — el usuario los puede activar manual si quiere
        if gid.endswith("@group.v.calendar.google.com") and "holiday" in gid.lower():
            continue
        nuevo = {
            "id": nuevo_id("cal"),
            "email": gid,
            "ical_url": "",
            "nombre_para_mostrar": cg.get("summary", gid)[:80],
            "cliente_asociado": cliente_default,
            "color": cg.get("backgroundColor", "#888888"),
            "activo": True
        }
        data["calendarios_gmail"].append(nuevo)
        emails_existentes.add(gid.lower())
        agregados.append(nuevo)

    if agregados:
        guardar("calendarios.json", data)

    return jsonify({
        "ok": True,
        "agregados": agregados,
        "total_agregados": len(agregados),
        "total_google": len(cals_google),
        "total_local": len(data["calendarios_gmail"])
    })


@app.route("/api/calendarios/paleta_google", methods=["GET"])
@requiere_auth
def paleta_google():
    """Devuelve la paleta oficial de colores de Google Calendar."""
    creds = _google_creds()
    if not creds:
        return jsonify({"event": {}, "calendar": {}})
    return jsonify(_obtener_paleta_google(creds))


@app.route("/api/calendarios/google_list", methods=["GET"])
@requiere_auth
def listar_calendarios_google():
    """Lista los calendarios disponibles en la cuenta Google autorizada."""
    if not GOOGLE_TOKEN.exists():
        return jsonify({"error": "No autorizado con Google. Conecta primero."}), 400
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GRequest
        from googleapiclient.discovery import build
    except ImportError:
        return jsonify({"error": "Falta librería google-api-python-client"}), 500

    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        GOOGLE_TOKEN.write_text(creds.to_json())

    servicio = build("calendar", "v3", credentials=creds)
    r = servicio.calendarList().list().execute()
    cals = [{
        "id": c["id"],
        "summary": c.get("summary", c["id"]),
        "primary": c.get("primary", False),
        "backgroundColor": c.get("backgroundColor", "#888888")
    } for c in r.get("items", [])]
    return jsonify({"calendarios": cals})


@app.route("/api/calendarios/eventos_hoy", methods=["GET"])
@requiere_auth
def eventos_hoy_google():
    """Devuelve los eventos de hoy de TODOS los calendarios activos."""
    if not GOOGLE_TOKEN.exists():
        return jsonify({"eventos": [], "mensaje": "No conectado con Google"}), 200
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GRequest
        from googleapiclient.discovery import build
        from datetime import time, timezone
    except ImportError:
        return jsonify({"error": "Falta librería"}), 500

    creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(GRequest())
        GOOGLE_TOKEN.write_text(creds.to_json())

    servicio = build("calendar", "v3", credentials=creds)
    cals_activos = [c for c in cargar("calendarios.json")["calendarios_gmail"] if c.get("activo")]

    inicio = datetime.combine(date.today(), datetime.min.time()).astimezone()
    fin = datetime.combine(date.today(), datetime.max.time()).astimezone()

    eventos = []
    for cal in cals_activos:
        try:
            r = servicio.events().list(
                calendarId=cal["email"],
                timeMin=inicio.isoformat(),
                timeMax=fin.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            for ev in r.get("items", []):
                eventos.append({
                    "calendario": cal["nombre_para_mostrar"],
                    "cliente_id": cal.get("cliente_asociado"),
                    "color": cal.get("color"),
                    "titulo": ev.get("summary", "(sin título)"),
                    "inicio": ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date"),
                    "fin": ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date"),
                    "ubicacion": ev.get("location", "")
                })
        except Exception as e:
            eventos.append({"error": str(e), "calendario": cal["email"]})
    return jsonify({"eventos": eventos, "total": len(eventos)})


# ============ EVENTOS DESDE iCAL (recomendado) ============

@app.route("/api/calendarios/eventos_rango", methods=["GET"])
@requiere_auth
def eventos_rango():
    """Devuelve eventos en un rango de fechas con expansión de RRULE.
    Query: ?desde=YYYY-MM-DD&hasta=YYYY-MM-DD
    Formato compatible con FullCalendar.js"""
    from datetime import timedelta
    try:
        from icalendar import Calendar
        import recurring_ical_events
        import urllib.request
    except ImportError as e:
        return jsonify({"error": f"Falta librería: {e}"}), 500

    desde_str = request.args.get("desde")
    hasta_str = request.args.get("hasta")

    try:
        if desde_str:
            desde = datetime.fromisoformat(desde_str)
        else:
            desde = datetime.combine(date.today() - timedelta(days=7), datetime.min.time())
        if hasta_str:
            hasta = datetime.fromisoformat(hasta_str)
            # si vino solo fecha (sin hora), tomar el día completo hasta 23:59:59
            if len(hasta_str) == 10:
                hasta = hasta.replace(hour=23, minute=59, second=59)
        else:
            hasta = datetime.combine(date.today() + timedelta(days=60), datetime.max.time())
    except ValueError:
        return jsonify({"error": "Formato de fecha inválido (usa YYYY-MM-DD)"}), 400

    clientes = {c["id"]: c for c in cargar("clientes.json").get("clientes", [])}
    todos_cals = [c for c in cargar("calendarios.json")["calendarios_gmail"] if c.get("activo")]
    cals = [c for c in todos_cals if c.get("ical_url")]
    cals_oauth = [c for c in todos_cals if not c.get("ical_url")]

    eventos = []
    for cal in cals:
        try:
            req = urllib.request.Request(cal["ical_url"], headers={"User-Agent": "Organizador/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                ics = r.read()
            ical = Calendar.from_ical(ics)
            ocurrencias = recurring_ical_events.of(ical).between(desde, hasta)
            cli = clientes.get(cal.get("cliente_asociado"), {"nombre": cal.get("nombre_para_mostrar")})
            color = cal.get("color", "#4A4D7A")
            for ev in ocurrencias:
                start = ev.get("DTSTART").dt if ev.get("DTSTART") else None
                end = ev.get("DTEND").dt if ev.get("DTEND") else start
                if start is None:
                    continue
                all_day = not hasattr(start, "hour")
                eventos.append({
                    "id": str(ev.get("UID", "")) + "_" + (str(start) if not all_day else start.isoformat()),
                    "title": str(ev.get("SUMMARY", "(sin título)")),
                    "start": start.isoformat() if hasattr(start, "isoformat") else str(start),
                    "end": end.isoformat() if hasattr(end, "isoformat") else str(end),
                    "allDay": all_day,
                    "backgroundColor": color,
                    "borderColor": color,
                    "textColor": "#FFFFFF",
                    "extendedProps": {
                        "calendario": cal.get("nombre_para_mostrar"),
                        "calendario_id": cal["id"],
                        "cliente": cli.get("nombre"),
                        "color_cliente": cli.get("color"),
                        "ubicacion": str(ev.get("LOCATION", "")),
                        "descripcion": str(ev.get("DESCRIPTION", ""))[:300]
                    }
                })
        except Exception as e:
            eventos.append({
                "id": f"error_{cal['id']}",
                "title": f"⚠️ Error leyendo {cal.get('nombre_para_mostrar')}",
                "start": desde.isoformat(),
                "allDay": True,
                "backgroundColor": "#A8392F",
                "borderColor": "#A8392F",
                "extendedProps": {"error": str(e)}
            })

    if cals_oauth:
        creds = _google_creds()
        if creds:
            try:
                from googleapiclient.discovery import build
                paleta = _obtener_paleta_google(creds)
                servicio = build("calendar", "v3", credentials=creds)
                t_min = desde.isoformat() if desde.tzinfo else desde.astimezone().isoformat()
                t_max = hasta.isoformat() if hasta.tzinfo else hasta.astimezone().isoformat()
                for cal in cals_oauth:
                    try:
                        r = servicio.events().list(
                            calendarId=cal["email"],
                            timeMin=t_min,
                            timeMax=t_max,
                            singleEvents=True,
                            orderBy="startTime",
                            maxResults=500
                        ).execute()
                        cli = clientes.get(cal.get("cliente_asociado"), {"nombre": cal.get("nombre_para_mostrar")})
                        color_cal = cal.get("color", "#4A4D7A")
                        for ev in r.get("items", []):
                            start_obj = ev.get("start", {})
                            end_obj = ev.get("end", {})
                            start_v = start_obj.get("dateTime") or start_obj.get("date")
                            end_v   = end_obj.get("dateTime")   or end_obj.get("date")
                            if not start_v:
                                continue
                            all_day = "date" in start_obj and "dateTime" not in start_obj
                            color_id = ev.get("colorId")
                            color_evt = paleta["event"].get(color_id) if color_id else None
                            color_final = color_evt or color_cal
                            # Asistentes (lista de invitados + estado de respuesta)
                            attendees = []
                            for a in (ev.get("attendees") or []):
                                attendees.append({
                                    "email": a.get("email", ""),
                                    "nombre": a.get("displayName") or a.get("email", "").split("@")[0],
                                    "respuesta": a.get("responseStatus", "needsAction"),
                                    "es_organizador": a.get("organizer", False),
                                    "es_yo": a.get("self", False)
                                })
                            # Organizador (si no está en attendees)
                            organizador = ev.get("organizer", {}) or {}
                            # Links: web de Google Calendar + Meet
                            html_link = ev.get("htmlLink", "")
                            meet_link = ev.get("hangoutLink", "")
                            if not meet_link:
                                # algunos eventos usan conferenceData
                                cd = ev.get("conferenceData", {}) or {}
                                for ep_entry in (cd.get("entryPoints") or []):
                                    if ep_entry.get("entryPointType") == "video":
                                        meet_link = ep_entry.get("uri", "")
                                        break
                            eventos.append({
                                "id": ev.get("id"),
                                "title": ev.get("summary", "(sin título)"),
                                "start": start_v,
                                "end": end_v,
                                "allDay": all_day,
                                "backgroundColor": color_final,
                                "borderColor": color_final,
                                "textColor": "#FFFFFF",
                                "extendedProps": {
                                    "calendario": cal.get("nombre_para_mostrar"),
                                    "calendario_id": cal["id"],
                                    "calendario_email": cal["email"],
                                    "cliente": cli.get("nombre"),
                                    "color_cliente": cli.get("color"),
                                    "color_calendario": color_cal,
                                    "color_evento_propio": color_evt,
                                    "ubicacion": ev.get("location", ""),
                                    "descripcion": (ev.get("description") or "")[:500],
                                    "asistentes": attendees,
                                    "organizador_email": organizador.get("email", ""),
                                    "organizador_nombre": organizador.get("displayName") or organizador.get("email", ""),
                                    "html_link": html_link,
                                    "meet_link": meet_link
                                }
                            })
                    except Exception as e:
                        eventos.append({
                            "id": f"error_{cal['id']}",
                            "title": f"⚠️ Error leyendo {cal.get('nombre_para_mostrar')}",
                            "start": desde.isoformat(),
                            "allDay": True,
                            "backgroundColor": "#A8392F",
                            "borderColor": "#A8392F",
                            "extendedProps": {"error": str(e)}
                        })
            except Exception as e:
                eventos.append({
                    "id": "error_oauth",
                    "title": f"⚠️ Error OAuth: {e}",
                    "start": desde.isoformat(),
                    "allDay": True,
                    "backgroundColor": "#A8392F",
                    "borderColor": "#A8392F",
                    "extendedProps": {"error": str(e)}
                })

    return jsonify(eventos)


@app.route("/api/calendarios/eventos_ical", methods=["GET"])
@requiere_auth
def eventos_ical():
    """Lee eventos de hoy desde TODAS las URLs iCal activas. Sin OAuth, sin Google Cloud."""
    try:
        from icalendar import Calendar
        import urllib.request
        from datetime import time
    except ImportError:
        return jsonify({"error": "Falta: pip install icalendar"}), 500

    cals = [c for c in cargar("calendarios.json")["calendarios_gmail"]
            if c.get("activo") and c.get("ical_url")]

    inicio = datetime.combine(date.today(), datetime.min.time())
    fin = datetime.combine(date.today(), datetime.max.time())

    eventos = []
    for cal in cals:
        try:
            req = urllib.request.Request(cal["ical_url"], headers={"User-Agent": "Organizador/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                ics = r.read()
            ical = Calendar.from_ical(ics)
            for componente in ical.walk("VEVENT"):
                dtstart = componente.get("dtstart").dt
                dtend = componente.get("dtend").dt if componente.get("dtend") else dtstart
                # normalizar a datetime sin tz para comparar
                if hasattr(dtstart, "date"):
                    dt_compare = dtstart.replace(tzinfo=None) if dtstart.tzinfo else dtstart
                else:
                    dt_compare = datetime.combine(dtstart, datetime.min.time())
                if not (inicio <= dt_compare <= fin):
                    continue
                eventos.append({
                    "calendario": cal["nombre_para_mostrar"],
                    "cliente_id": cal.get("cliente_asociado"),
                    "color": cal.get("color"),
                    "titulo": str(componente.get("summary", "(sin título)")),
                    "inicio": dtstart.isoformat() if hasattr(dtstart, "isoformat") else str(dtstart),
                    "fin": dtend.isoformat() if hasattr(dtend, "isoformat") else str(dtend),
                    "ubicacion": str(componente.get("location", "")),
                    "descripcion": str(componente.get("description", ""))[:200]
                })
        except Exception as e:
            eventos.append({"error": str(e), "calendario": cal["nombre_para_mostrar"]})

    eventos.sort(key=lambda e: e.get("inicio", "") if "error" not in e else "")
    return jsonify({"eventos": eventos, "total": len([e for e in eventos if "error" not in e])})


@app.route("/api/calendarios/probar_ical", methods=["POST"])
@requiere_auth
def probar_ical():
    """Prueba una URL iCal sin guardarla. Devuelve cuántos eventos tiene + nombre del calendario."""
    body = request.get_json()
    url = body.get("ical_url", "").strip()
    if not url:
        return jsonify({"error": "Falta ical_url"}), 400
    try:
        from icalendar import Calendar
        import urllib.request
    except ImportError:
        return jsonify({"error": "Falta: pip install icalendar"}), 500

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Organizador/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ics = r.read()
        ical = Calendar.from_ical(ics)
        eventos = list(ical.walk("VEVENT"))
        nombre = str(ical.get("X-WR-CALNAME", "Calendario"))
        return jsonify({
            "ok": True,
            "nombre_detectado": nombre,
            "total_eventos": len(eventos)
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ============ PLAN DEL DÍA ============

@app.route("/api/plan/hoy", methods=["GET"])
@requiere_auth
def get_plan_hoy():
    registro = cargar_registro_dia()
    return jsonify(registro)


@app.route("/api/plan/semana", methods=["POST"])
@requiere_auth
def generar_plan_semana():
    """IA organiza la semana del lunes al domingo con tema por día.

    Body: { "inicio": "YYYY-MM-DD" (lunes opcional, default lunes de hoy) }"""
    from datetime import timedelta
    try:
        from plan_manana import _leer_eventos_dia, _horario_laboral, _horario_sueno, _filtrar_habitos_dia, DIAS_ES
        from openai import OpenAI
    except ImportError as e:
        return jsonify({"error": f"Falta módulo: {e}"}), 500

    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "Falta OPENAI_API_KEY"}), 500

    body = request.get_json() or {}
    inicio_str = body.get("inicio")
    if inicio_str:
        try:
            inicio = date.fromisoformat(inicio_str)
        except ValueError:
            return jsonify({"error": "fecha inválida"}), 400
    else:
        h = date.today()
        # lunes ISO (1=Lun)
        inicio = h - timedelta(days=h.isoweekday() - 1)

    fin = inicio + timedelta(days=6)
    habitos_data = cargar("habitos.json")
    tareas = [a for a in cargar("actividades.json").get("actividades", []) if a.get("estado") == "pendiente"]

    dias_data = []
    for i in range(7):
        d = inicio + timedelta(days=i)
        habs = _filtrar_habitos_dia(habitos_data.get("habitos", []), d)
        evs = _leer_eventos_dia(d)
        lab = _horario_laboral(d)
        dias_data.append({
            "fecha": d.isoformat(),
            "dia": DIAS_ES[d.weekday()],
            "laboral": lab.get("activo", False),
            "ventana_laboral": f"{lab.get('inicio','—')}-{lab.get('fin','—')}" if lab.get("activo") else "no laboral",
            "eventos": evs,
            "habitos": [{"nombre": h["nombre"], "horario": h.get("horario_sugerido","mañana")} for h in habs],
            "tareas_con_deadline": [t for t in tareas if t.get("deadline") == d.isoformat()]
        })
    sueno = _horario_sueno()

    sistema = f"""Eres el coach de productividad de Diego. Vas a organizar SU SEMANA del {inicio.isoformat()} al {fin.isoformat()} para que sea más productivo.

Despierta {sueno['despertar']} · Duerme {sueno['dormir']}.

Tu trabajo: identificar el TEMA PRINCIPAL de la semana, el foco de cada día, y los big rocks (cosas críticas que NO se pueden mover).

REGLAS:
1. Respeta días no laborales (descanso o ritual ligero).
2. Distribuye las tareas con deadline en los días apropiados.
3. Agrupa esfuerzos similares (ej: 'lunes y martes = ads', 'miércoles = creativos').
4. Da un foco claro por día — qué hacer si solo pudiera hacer UNA cosa ese día.
5. Marca los big_rocks: 3-5 cosas críticas de la semana.

Devuelve SOLO JSON:
{{
  "tema_semana": "frase corta — el foco principal",
  "dias": [
    {{"fecha": "YYYY-MM-DD", "dia": "lunes",
      "foco": "una frase con el foco del día",
      "objetivos": ["objetivo 1", "objetivo 2"],
      "alerta": "evento o tarea crítica del día (o vacío)"}}
  ],
  "big_rocks": ["3 a 5 puntos críticos de la semana"],
  "recomendaciones": ["consejos para ser más productivo esta semana"],
  "frase_motivadora": "una frase de cierre"
}}"""

    usuario = f"""DATOS DE LA SEMANA:
Sueño: despertar {sueno['despertar']} · dormir {sueno['dormir']}

DÍAS:
{json.dumps(dias_data, ensure_ascii=False, indent=2)}

TAREAS TOTAL PENDIENTES (priorizadas):
{json.dumps(sorted(tareas, key=lambda t: ({'alta':0,'media':1,'baja':2}.get(t.get('prioridad','media'),3), t.get('deadline') or '9'))[:15], ensure_ascii=False, indent=2)}

Organiza esta semana para máxima productividad."""

    cliente = OpenAI()
    resp = cliente.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"system","content":sistema},{"role":"user","content":usuario}],
        response_format={"type":"json_object"},
        temperature=0.4
    )
    plan = json.loads(resp.choices[0].message.content)
    return jsonify({"plan": plan, "inicio": inicio.isoformat(), "fin": fin.isoformat()})


@app.route("/api/plan/mes", methods=["POST"])
@requiere_auth
def generar_plan_mes():
    """IA da visión del mes: tema por semana + métricas + recomendaciones."""
    from datetime import timedelta
    from calendar import monthrange
    try:
        from plan_manana import _leer_eventos_dia, DIAS_ES
        from openai import OpenAI
    except ImportError as e:
        return jsonify({"error": f"Falta módulo: {e}"}), 500

    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "Falta OPENAI_API_KEY"}), 500

    body = request.get_json() or {}
    año = body.get("año") or date.today().year
    mes = body.get("mes") or date.today().month
    año = int(año); mes = int(mes)
    dias_mes = monthrange(año, mes)[1]
    primer_dia = date(año, mes, 1)
    ultimo_dia = date(año, mes, dias_mes)

    # Contar eventos por semana del mes
    eventos_por_semana = {}
    for d in (primer_dia + timedelta(n) for n in range(dias_mes)):
        # número de semana ISO dentro del mes (aproximado)
        semana_inicio = d - timedelta(days=d.isoweekday() - 1)
        key = semana_inicio.isoformat()
        evs = _leer_eventos_dia(d)
        eventos_por_semana.setdefault(key, []).extend(evs)

    tareas_pendientes = [a for a in cargar("actividades.json").get("actividades", []) if a.get("estado") == "pendiente"]
    tareas_con_dl_mes = [t for t in tareas_pendientes if t.get("deadline") and primer_dia.isoformat() <= str(t["deadline"]) <= ultimo_dia.isoformat()]
    proyectos = cargar("proyectos.json").get("proyectos", [])

    sistema = """Eres el coach de productividad de Diego. Vas a darle una VISIÓN DE ALTO NIVEL del mes para que sepa hacia dónde apuntar.

Tu trabajo: identificar el tema del mes, organizar las 4-5 semanas con un foco cada una, y dar recomendaciones para que sea productivo.

Devuelve SOLO JSON:
{
  "tema_mes": "frase corta — el norte del mes",
  "semanas": [
    {"inicio": "YYYY-MM-DD", "fin": "YYYY-MM-DD",
     "etiqueta": "Semana 1 (1-7 mayo)",
     "tema": "foco principal de la semana",
     "objetivos": ["3 cosas concretas para esa semana"]}
  ],
  "metricas": {
    "eventos_totales": N,
    "tareas_con_deadline_este_mes": N,
    "proyectos_activos": N
  },
  "recomendaciones": ["consejos para ser más productivo este mes"],
  "advertencias": ["fechas críticas, deadlines fuertes"],
  "frase_cierre": "frase motivadora"
}"""

    usuario = f"""MES OBJETIVO: {primer_dia.isoformat()} a {ultimo_dia.isoformat()}

EVENTOS POR SEMANA:
{json.dumps({k: [{'titulo':e['titulo'],'inicio':e['inicio']} for e in v[:10]] for k,v in eventos_por_semana.items()}, ensure_ascii=False, indent=2)}

TAREAS CON DEADLINE ESTE MES:
{json.dumps(tareas_con_dl_mes, ensure_ascii=False, indent=2)}

PROYECTOS ACTIVOS:
{json.dumps([p for p in proyectos if p.get('estado')=='activo'], ensure_ascii=False, indent=2)}

Dame la visión del mes."""

    cliente = OpenAI()
    resp = cliente.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"system","content":sistema},{"role":"user","content":usuario}],
        response_format={"type":"json_object"},
        temperature=0.4
    )
    plan = json.loads(resp.choices[0].message.content)
    return jsonify({"plan": plan, "mes": mes, "año": año})


@app.route("/api/plan/generar", methods=["POST"])
@requiere_auth
def generar_plan_endpoint():
    """Llama al planificador IA y guarda el plan del día.

    Body opcional: { "fecha": "YYYY-MM-DD", "auto_aprobar": bool }
    Si no se pasa fecha → hoy."""
    try:
        from plan_manana import construir_contexto, generar_plan
    except ImportError as e:
        return jsonify({"error": f"Falta módulo: {e}"}), 500

    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "Falta OPENAI_API_KEY"}), 500

    body = request.get_json() or {}
    fecha_str = body.get("fecha")
    fecha = None
    if fecha_str:
        try:
            fecha = date.fromisoformat(fecha_str)
        except ValueError:
            return jsonify({"error": f"Fecha inválida: {fecha_str}"}), 400

    ctx = construir_contexto(fecha)
    plan = generar_plan(ctx)

    # Guardar en planes_diarios SOLO si la fecha es hoy o futura
    registro = cargar_registro_dia(ctx["fecha"])
    registro["plan_generado"] = plan
    registro["aprobado"] = bool(body.get("auto_aprobar", False))
    registro["fecha"] = ctx["fecha"]
    guardar_registro_dia(registro)

    return jsonify({
        "plan": plan,
        "fecha": ctx["fecha"],
        "dia_semana": ctx["dia_semana"],
        "eventos_considerados": len(ctx["eventos_calendario"]),
        "espacios_libres": len(ctx["espacios_libres"]),
        "habitos_aplicables": len(ctx["habitos_del_dia"]),
        "tareas_consideradas": len(ctx["tareas_pendientes"])
    })


# ============ RESUMEN GENERAL (útil para Telegram /menu) ============

@app.route("/api/resumen", methods=["GET"])
@requiere_auth
def get_resumen():
    """Todo lo importante en una sola llamada."""
    empresas = cargar("empresas.json")["empresas"]
    proyectos = cargar("proyectos.json")["proyectos"]
    tareas = cargar("actividades.json")["actividades"]
    habitos_data = cargar("habitos.json")
    registro = cargar_registro_dia()

    pendientes = [t for t in tareas if t["estado"] == "pendiente"]
    habitos_activos = [h for h in habitos_data["habitos"] if h["activo"]]
    cumplidos_hoy = registro["habitos_cumplidos"]

    return jsonify({
        "fecha": registro["fecha"],
        "empresas": len(empresas),
        "proyectos_activos": len([p for p in proyectos if p["estado"] == "activo"]),
        "tareas_pendientes": len(pendientes),
        "habitos_hoy": {
            "total": len(habitos_activos),
            "cumplidos": len(cumplidos_hoy),
            "pct": round(len(cumplidos_hoy) / max(1, len(habitos_activos)) * 100)
        },
        "plan_generado": registro.get("plan_generado") is not None,
        "dia_cerrado": registro.get("cerrado", False)
    })


# ============ HEALTH ============

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "fecha": date.today().isoformat()})


@app.route("/api/scheduler/test_resumen_matutino", methods=["POST"])
@requiere_auth
def test_resumen_matutino():
    """Dispara el resumen matutino ahora mismo (forzando, ignora si ya se envió)."""
    if not _SCHED_OK:
        return jsonify({"error": "Scheduler no disponible"}), 500
    try:
        _sched.enviar_resumen_matutino(forzar=True)
        return jsonify({"ok": True, "mensaje": "Resumen enviado a Telegram"})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/scheduler/estado_resumen", methods=["GET"])
@requiere_auth
def estado_resumen_diario():
    """Devuelve los últimos 7 días: ¿se envió el resumen? ¿a qué hora?"""
    try:
        from comun import _USAR_DB
        if not _USAR_DB:
            return jsonify({"error": "DB no disponible"}), 500
        import db as _bd
        rows = _bd.query("""
            SELECT fecha, enviado_at, eventos_count, tareas_count, habitos_count, intentos
            FROM resumen_diario_enviado
            ORDER BY fecha DESC
            LIMIT 7
        """)
        return jsonify({
            "ultimos_7_dias": [
                {
                    "fecha": str(r["fecha"]),
                    "enviado_at": r["enviado_at"].isoformat() if r.get("enviado_at") else None,
                    "eventos": r["eventos_count"],
                    "tareas": r["tareas_count"],
                    "habitos": r["habitos_count"],
                    "intentos": r["intentos"]
                } for r in rows
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scheduler/diag", methods=["GET", "POST"])
@requiere_auth
def scheduler_diag():
    """Diagnóstico del scheduler. Reintenta arranque si está caído."""
    out = {"sched_ok": _SCHED_OK, "ahora": datetime.now().isoformat()}
    if not _SCHED_OK:
        out["error"] = "Módulo scheduler no se pudo importar al boot"
        # intentar import ahora
        try:
            import scheduler as _s
            out["import_retry"] = "ok"
            try:
                _s.iniciar()
                out["start_retry"] = "ok"
            except Exception as e:
                out["start_retry"] = str(e)
        except Exception as e:
            out["import_retry"] = str(e)
        return jsonify(out)

    try:
        s = _sched.get_scheduler()
        out["running"] = s.running
        if not s.running:
            try:
                _sched.iniciar()
                out["start_retry"] = "ok"
                s = _sched.get_scheduler()
                out["running"] = s.running
            except Exception as e:
                out["start_error"] = str(e)
        # POST: si el body trae {"accion": "resync_eventos"}, borra jobs ev_* y resincroniza
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            accion = body.get("accion") or request.args.get("accion")
            if accion == "resync_eventos":
                borrados = 0
                for j in s.get_jobs():
                    if j.id.startswith("ev_"):
                        try:
                            s.remove_job(j.id)
                            borrados += 1
                        except Exception:
                            pass
                out["jobs_borrados"] = borrados
                try:
                    _sched.sincronizar_eventos_calendario()
                    out["resync"] = "ok"
                except Exception as e:
                    out["resync_error"] = str(e)
        jobs = s.get_jobs()
        out["jobs_count"] = len(jobs)
        out["jobs"] = [{
            "id": j.id,
            "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
            "func": str(j.func_ref) if hasattr(j, 'func_ref') else str(j.func)
        } for j in jobs[:30]]
    except Exception as e:
        out["scheduler_error"] = str(e)
    return jsonify(out)


# ============ DIAGNÓSTICO DE BASE DE DATOS ============

@app.route("/api/db/diag", methods=["GET"])
@requiere_auth
def db_diag():
    """Estado real de la conexión a Postgres: qué tablas ve y cuántas filas.
    Para diagnosticar cuándo la app está sirviendo JSON de respaldo."""
    out = {
        "db_disponible": _db.db_disponible(),
        "db_host": os.getenv("DB_HOST", ""),
        "db_name": os.getenv("DB_NAME", ""),
        "tablas": {},
        "errores": [],
    }
    if out["db_disponible"]:
        for tabla in ["clientes", "proyectos", "actividades", "habitos", "habito_categorias",
                      "calendarios", "personas", "epicas", "historias", "recordatorios",
                      "configuracion", "eventos_conocidos"]:
            try:
                rows = _db.query(f"SELECT COUNT(*)::int AS n FROM organizador.{tabla}")
                out["tablas"][tabla] = rows[0]["n"]
            except Exception as e:
                out["errores"].append(f"{tabla}: {str(e).splitlines()[0]}")
    # ¿cargar() está usando DB o JSON?
    try:
        import comun as _comun
        out["usar_db_flag"] = getattr(_comun, "_USAR_DB", None)
    except Exception as e:
        out["errores"].append(f"comun: {e}")
    # Traza del bootstrap de este boot
    try:
        out["bootstrap_traza"] = getattr(_bootstrap, "TRAZA", [])
    except Exception:
        out["bootstrap_traza"] = ["(módulo bootstrap no cargado)"]
    return jsonify(out)


# ============ TOKEN AUTO (solo localhost) ============

@app.route("/api/local-token", methods=["GET"])
def local_token():
    """Devuelve el token SOLO si la petición viene de localhost.
    Permite que admin.html cargue el token automáticamente sin pedírselo al usuario."""
    if request.remote_addr not in ("127.0.0.1", "::1", "localhost"):
        return jsonify({"error": "Solo accesible desde localhost"}), 403
    return jsonify({"token": API_TOKEN})


# ============ TABLERO ESTÁTICO ============

@app.route("/")
def root():
    return send_from_directory(str(RAIZ / "tablero"), "index.html")


# ============ SEMILLA PRO (Fase 0+1): personas + migración de actividades ============
# Idempotente; corre en cada boot (local y gunicorn) sin efectos si ya está hecho.
try:
    _asegurar_personas()
    _migrar_actividades_a_historias()
except Exception as _e:
    print(f"⚠️  Semilla SCRUM no aplicada: {_e}")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    print(f"🚀 API en http://localhost:{port}")
    print(f"   Token de seguridad: {API_TOKEN}")
    print(f"   Tablero: http://localhost:{port}/")
    print(f"   Health: http://localhost:{port}/api/health")
    app.run(host="0.0.0.0", port=port, debug=False)
