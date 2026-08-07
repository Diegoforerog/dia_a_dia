"""Enrutador de avisos por persona — Web Push (PWA) + Telegram.

Idea (Fase 2 de Día a día PRO): cada aviso va dirigido a UNA persona y se
entrega por TODOS sus canales: los celulares donde activó las notificaciones
(Web Push) y su chat de Telegram (si lo configuró).

- Web Push usa claves VAPID que se generan una sola vez y se guardan en la
  tabla `configuracion` (clave 'vapid'); se pueden fijar por env
  VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY.
- Cada persona guarda sus `push_subscriptions` (una por dispositivo) y su
  `telegram_chat_id` en personas.json.
- Degradación elegante: si falta pywebpush, el push se desactiva y Telegram
  sigue funcionando; nada tumba el arranque.
"""
import os
import json
import base64

from comun import cargar, guardar

VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:diego.forero@masterescala.co")

try:
    from pywebpush import webpush, WebPushException
    _PUSH_LIB = True
except Exception:
    _PUSH_LIB = False


# ─────────────────────────────────────────────────────────
# Claves VAPID (persistentes)
# ─────────────────────────────────────────────────────────
def _generar_vapid() -> dict:
    """Genera un par de claves VAPID (P-256).
    Devuelve {public: <applicationServerKey base64url>, private_pem: <PEM>}."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    priv = ec.generate_private_key(ec.SECP256R1())
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
    return {"public": public, "private_pem": priv_pem}


def _vapid() -> dict:
    """Devuelve las claves VAPID, generándolas y guardándolas la 1ª vez.
    Prioriza env vars si están completas."""
    env_pub = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    env_priv = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    if env_pub and env_priv:
        return {"public": env_pub, "private_pem": env_priv}
    cfg = cargar("config.json")
    v = cfg.get("vapid") if isinstance(cfg, dict) else None
    if v and v.get("public") and v.get("private_pem"):
        return v
    if not _PUSH_LIB:
        return {}
    try:
        v = _generar_vapid()
        cfg = cargar("config.json")
        cfg["vapid"] = v
        guardar("config.json", cfg)
        print("✓ Avisos: claves VAPID generadas y guardadas")
        return v
    except Exception as e:
        print(f"⚠️  Avisos: no se pudieron generar claves VAPID: {e}")
        return {}


def clave_publica() -> str:
    """La applicationServerKey que necesita el navegador para suscribirse."""
    return (_vapid() or {}).get("public", "")


def push_disponible() -> bool:
    return bool(_PUSH_LIB and clave_publica())


# ─────────────────────────────────────────────────────────
# Personas
# ─────────────────────────────────────────────────────────
def _persona(persona_id: str) -> dict:
    for p in cargar("personas.json").get("personas", []):
        if p.get("id") == persona_id:
            return p
    return {}


def guardar_suscripcion(persona_id: str, subscription: dict) -> bool:
    """Añade (o reemplaza por endpoint) una suscripción Web Push a la persona."""
    data = cargar("personas.json")
    for p in data.get("personas", []):
        if p.get("id") == persona_id:
            subs = p.get("push_subscriptions") or []
            endpoint = subscription.get("endpoint")
            subs = [s for s in subs if s.get("endpoint") != endpoint]
            subs.append(subscription)
            p["push_subscriptions"] = subs
            guardar("personas.json", data)
            return True
    return False


def quitar_suscripcion(persona_id: str, endpoint: str) -> bool:
    data = cargar("personas.json")
    for p in data.get("personas", []):
        if p.get("id") == persona_id:
            p["push_subscriptions"] = [s for s in (p.get("push_subscriptions") or [])
                                       if s.get("endpoint") != endpoint]
            guardar("personas.json", data)
            return True
    return False


# ─────────────────────────────────────────────────────────
# Envío
# ─────────────────────────────────────────────────────────
def _enviar_push(persona: dict, titulo: str, cuerpo: str, url: str = "/", tag: str = "") -> int:
    """Envía a todos los dispositivos de la persona. Limpia suscripciones muertas.
    Devuelve cuántos envíos tuvieron éxito."""
    if not push_disponible():
        return 0
    v = _vapid()
    subs = persona.get("push_subscriptions") or []
    if not subs:
        return 0
    payload = json.dumps({"title": titulo, "body": cuerpo, "url": url, "tag": tag or None})
    ok = 0
    muertas = []
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=v["private_pem"],
                vapid_claims={"sub": VAPID_SUBJECT},
                timeout=10,
            )
            ok += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):   # suscripción expirada/cancelada
                muertas.append(sub.get("endpoint"))
            else:
                print(f"⚠️  Push a {persona.get('nombre')}: {e}")
        except Exception as e:
            print(f"⚠️  Push a {persona.get('nombre')}: {e}")
    for ep in muertas:
        quitar_suscripcion(persona["id"], ep)
    return ok


def _enviar_telegram(chat_id: str, texto: str, parse_mode: str = "Markdown") -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token or not chat_id:
        return False
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
        "text": texto, "parse_mode": parse_mode, "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"❌ Telegram ({chat_id}): {e}")
        return False


def avisar_persona(persona_id: str, titulo: str, cuerpo: str,
                   url: str = "/", tag: str = "", telegram_texto: str = None) -> dict:
    """Envía un aviso a UNA persona por todos sus canales.
    `telegram_texto` permite un formato más rico para Telegram (Markdown);
    si no se da, se usa «*titulo*\\ncuerpo»."""
    persona = _persona(persona_id)
    if not persona:
        return {"push": 0, "telegram": False, "error": "persona no encontrada"}
    push_ok = _enviar_push(persona, titulo, cuerpo, url, tag)
    tg = telegram_texto if telegram_texto is not None else f"*{titulo}*\n{cuerpo}"
    chat = persona.get("telegram_chat_id") or ""
    tg_ok = _enviar_telegram(chat, tg) if chat else False
    return {"push": push_ok, "telegram": tg_ok}


def avisar_todos(titulo: str, cuerpo: str, url: str = "/", tag: str = "") -> dict:
    """Difunde a todas las personas activas (para avisos que no tienen dueño)."""
    res = {}
    for p in cargar("personas.json").get("personas", []):
        if p.get("activo", True):
            res[p["id"]] = avisar_persona(p["id"], titulo, cuerpo, url, tag)
    return res
