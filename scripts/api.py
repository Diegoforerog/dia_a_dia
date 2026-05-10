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

INTEGRACIONES = RAIZ / "integraciones"
INTEGRACIONES.mkdir(exist_ok=True)
GOOGLE_CRED = INTEGRACIONES / "credentials.json"
GOOGLE_TOKEN = INTEGRACIONES / "token.json"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5050/api/oauth/google/callback")

# Permite OAuth sobre HTTP en local (sin TLS)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

app = Flask(__name__, static_folder=str(RAIZ / "tablero"), static_url_path="/tablero")
CORS(app)

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
    return jsonify({"ok": True})


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
        "mejor_racha": 0
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

        # racha calculada desde "cumplidos" (más confiable que el campo guardado)
        racha = 0
        d = hoy
        while d.isoformat() in completados:
            racha += 1
            d -= timedelta(days=1)
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
        flow.fetch_token(code=code)
        creds = flow.credentials
        GOOGLE_TOKEN.write_text(creds.to_json())
        return _pagina_resultado(True, "Conexión exitosa con Google Calendar")
    except Exception as e:
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


@app.route("/api/oauth/google/disconnect", methods=["POST"])
@requiere_auth
def oauth_disconnect():
    """Elimina el token (no las credentials)."""
    if GOOGLE_TOKEN.exists():
        GOOGLE_TOKEN.unlink()
    return jsonify({"ok": True})


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
    cals = [c for c in cargar("calendarios.json")["calendarios_gmail"]
            if c.get("activo") and c.get("ical_url")]

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


@app.route("/api/plan/generar", methods=["POST"])
@requiere_auth
def generar_plan_endpoint():
    """Llama al planificador IA y guarda el plan del día."""
    try:
        from plan_manana import construir_contexto, generar_plan
    except ImportError as e:
        return jsonify({"error": f"Falta módulo: {e}"}), 500

    if not os.getenv("OPENAI_API_KEY"):
        return jsonify({"error": "Falta OPENAI_API_KEY"}), 500

    ctx = construir_contexto()
    plan = generar_plan(ctx)
    registro = cargar_registro_dia()
    registro["plan_generado"] = plan
    registro["aprobado"] = request.json.get("auto_aprobar", False) if request.is_json else False
    guardar_registro_dia(registro)
    return jsonify({"plan": plan, "fecha": registro["fecha"]})


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


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    print(f"🚀 API en http://localhost:{port}")
    print(f"   Token de seguridad: {API_TOKEN}")
    print(f"   Tablero: http://localhost:{port}/")
    print(f"   Health: http://localhost:{port}/api/health")
    app.run(host="0.0.0.0", port=port, debug=False)
