"""Scheduler interno — dispara recordatorios y avisos de eventos al momento EXACTO.
Reemplaza los cron de n8n que polleaban cada 5 minutos.

Diseño:
  • APScheduler con persistencia en PostgreSQL (sobrevive reinicios)
  • 1 job por recordatorio, programado a su fecha_hora exacta
  • 1 job por evento iCal próximo (10 min antes del inicio)
  • Sync iCal cada hora para descubrir eventos nuevos
  • Envía Telegram directo (sin pasar por n8n)
"""
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, date
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

# Timezone — preferir zoneinfo (Python 3.9+), fallback a pytz
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Bogota")
except ImportError:
    import pytz
    TZ = pytz.timezone("America/Bogota")

import db as _db  # módulo local
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─────────────────────────────────────────────────────────
# Inicialización del scheduler
# ─────────────────────────────────────────────────────────
def _build_db_url() -> str:
    h = os.environ["DB_HOST"]
    p = os.environ.get("DB_PORT", "5432")
    u = os.environ["DB_USER"]
    pw = urllib.parse.quote(os.environ["DB_PASSWORD"], safe="")
    n = os.environ["DB_NAME"]
    return f"postgresql+psycopg2://{u}:{pw}@{h}:{p}/{n}"

import urllib.parse
_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            jobstores={"default": SQLAlchemyJobStore(
                url=_build_db_url(),
                tablename="apscheduler_jobs"
            )},
            executors={"default": ThreadPoolExecutor(4)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
            timezone=TZ
        )
    return _scheduler


def _asegurar_tabla_eventos_conocidos():
    """Crea la tabla eventos_conocidos si no existe."""
    try:
        _db.execute("""
            CREATE TABLE IF NOT EXISTS eventos_conocidos (
                uid TEXT NOT NULL,
                inicio TIMESTAMPTZ NOT NULL,
                titulo TEXT,
                fin TIMESTAMPTZ,
                calendario TEXT,
                cliente TEXT,
                ubicacion TEXT,
                organizador TEXT,
                html_link TEXT,
                meet_link TEXT,
                visto_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (uid, inicio)
            )
        """)
    except Exception as e:
        print(f"⚠️  No se pudo crear tabla eventos_conocidos: {e}")


def iniciar():
    """Llamar UNA VEZ al boot de la API."""
    s = get_scheduler()
    if s.running:
        return
    s.start()
    _asegurar_tabla_eventos_conocidos()
    # Job recurrente: sincroniza eventos cada 30 min (antes 1h)
    # Más frecuente para detectar reuniones recién agendadas
    s.add_job(
        sincronizar_eventos_calendario,
        "interval", minutes=30,
        id="_sync_ical_horario",
        replace_existing=True,
        next_run_time=datetime.now(TZ) + timedelta(seconds=30)  # corre en 30 seg al boot
    )
    # Re-programar recordatorios pendientes (por si hubo restart)
    reprogramar_recordatorios_pendientes()
    print("⚙️  Scheduler iniciado · jobs:", len(s.get_jobs()))


# ─────────────────────────────────────────────────────────
# Telegram envío directo
# ─────────────────────────────────────────────────────────
def telegram_send(texto: str, parse_mode: str = "Markdown") -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️  Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({
        "chat_id": int(CHAT_ID),
        "text": texto,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False


# ─────────────────────────────────────────────────────────
# RECORDATORIOS
# ─────────────────────────────────────────────────────────
def programar_recordatorio(rec_id: str, fecha_hora):
    """Programa un job único para un recordatorio."""
    s = get_scheduler()
    if isinstance(fecha_hora, str):
        fecha_hora = datetime.fromisoformat(fecha_hora.replace("Z", "+00:00"))
    s.add_job(
        disparar_recordatorio,
        "date",
        run_date=fecha_hora,
        args=[rec_id],
        id=f"rec_{rec_id}",
        replace_existing=True
    )
    print(f"🔔 Programado recordatorio {rec_id} para {fecha_hora}")


def cancelar_recordatorio(rec_id: str):
    s = get_scheduler()
    try:
        s.remove_job(f"rec_{rec_id}")
    except Exception:
        pass


def disparar_recordatorio(rec_id: str):
    """Dispara cuando llega la hora. Envía Telegram y maneja repetición."""
    rows = _db.query(
        "SELECT * FROM recordatorios WHERE id=%s AND NOT enviado AND activo",
        (rec_id,)
    )
    if not rows:
        return
    r = rows[0]
    fh = r["fecha_hora"]
    hora = fh.astimezone(TZ).strftime("%H:%M") if fh else ""
    texto = f"🔔 *{r['titulo']}*"
    if r.get("mensaje"):
        texto += f"\n\n{r['mensaje']}"
    if hora:
        texto += f"\n\n_⏰ {hora}_"
    if r.get("repetir") and r["repetir"] != "no":
        texto += f"\n_🔁 se repite {r['repetir']}_"

    telegram_send(texto)
    _db.execute(
        "UPDATE recordatorios SET enviado=TRUE, enviado_at=NOW() WHERE id=%s",
        (rec_id,)
    )

    # Repetición
    if r.get("repetir") and r["repetir"] != "no":
        delta = {
            "diario":   timedelta(days=1),
            "semanal":  timedelta(weeks=1),
            "mensual":  timedelta(days=30),
            "anual":    timedelta(days=365)
        }.get(r["repetir"])
        if delta:
            from secrets import token_hex
            nuevo_id = f"rec_{datetime.now().strftime('%Y%m%d%H%M%S')}_{token_hex(3)}"
            siguiente = fh + delta
            _db.execute("""
                INSERT INTO recordatorios (id, titulo, mensaje, fecha_hora, repetir, cliente_id, enviado, activo)
                VALUES (%s,%s,%s,%s,%s,%s,FALSE,TRUE)
            """, (nuevo_id, r["titulo"], r.get("mensaje",""), siguiente, r["repetir"], r.get("cliente_id")))
            programar_recordatorio(nuevo_id, siguiente)


def reprogramar_recordatorios_pendientes():
    """Al boot, re-engancha todos los recordatorios futuros pendientes."""
    try:
        rows = _db.query(
            "SELECT id, fecha_hora FROM recordatorios "
            "WHERE NOT enviado AND activo AND fecha_hora > NOW()"
        )
        for r in rows:
            programar_recordatorio(r["id"], r["fecha_hora"])
        print(f"🔁 Re-programados {len(rows)} recordatorios pendientes")
    except Exception as e:
        print(f"⚠️  No se pudo reprogramar recordatorios: {e}")


# ─────────────────────────────────────────────────────────
# AVISO 10 MIN ANTES DE EVENTOS DE CALENDARIO
# ─────────────────────────────────────────────────────────
def sincronizar_eventos_calendario():
    """Lee iCal + OAuth de todos los calendarios activos. Para cada evento que arranca
    en las próximas 24h, programa un job a -10 min de su inicio."""
    try:
        from icalendar import Calendar
        import recurring_ical_events
    except ImportError:
        print("⚠️  Falta librería icalendar / recurring_ical_events")
        return

    from comun import cargar
    todos = [c for c in cargar("calendarios.json").get("calendarios_gmail", []) if c.get("activo")]
    cals = [c for c in todos if c.get("ical_url")]
    cals_oauth = [c for c in todos if not c.get("ical_url")]

    ahora = datetime.now(TZ)
    # Ventana de DETECCIÓN: 7 días (para descubrir reuniones recién agendadas)
    hasta_deteccion = ahora + timedelta(days=7)
    # Ventana de AVISOS -10 min: solo próximas 24h
    limite_aviso = ahora + timedelta(hours=24)
    hasta = limite_aviso  # mantenemos var para código iCal legacy
    clientes = {c["id"]: c for c in cargar("clientes.json").get("clientes", [])}
    nuevos = 0
    # Detectar si es la PRIMERA sync de esta tabla (no notificar todo de golpe)
    es_primer_sync = False
    try:
        rows = _db.query("SELECT COUNT(*)::int AS n FROM eventos_conocidos")
        es_primer_sync = (rows[0]["n"] == 0) if rows else True
    except Exception:
        es_primer_sync = True
    notificados_nuevos = 0
    # Dedupe entre calendarios: el mismo evento puede aparecer en varios calendarios
    # del usuario (un evento compartido se ve desde @gmail y desde @nextgen al mismo
    # tiempo). Usamos iCalUID + inicio como clave estable para programar UNA SOLA vez.
    yapuestos = set()  # set de (icaluid_normalizado, inicio_iso)

    def _norm_uid(u: str) -> str:
        if not u:
            return ""
        # Quita sufijos @google.com / @resource.calendar.google.com para que matche
        return u.split("@")[0]

    # PROTECCIÓN 1: limpiar TODOS los avisos ev_* antes de reprogramar.
    # Si un evento fue movido/cancelado, su job viejo se borra acá y NO se reprograma
    # (porque ya no aparece en events.list para las próximas 24h).
    try:
        s = get_scheduler()
        borrados = 0
        for j in s.get_jobs():
            if j.id.startswith("ev_"):
                try:
                    s.remove_job(j.id)
                    borrados += 1
                except Exception:
                    pass
        if borrados:
            print(f"🧹 Sync: borrados {borrados} avisos viejos antes de reprogramar")
    except Exception as e:
        print(f"⚠️  No se pudieron limpiar jobs viejos: {e}")

    # ─── Calendarios OAuth (Google API) ───
    if cals_oauth:
        try:
            from pathlib import Path as _Path
            token_path = _Path(__file__).resolve().parent.parent / "integraciones" / "token.json"
            if token_path.exists():
                from google.oauth2.credentials import Credentials
                from google.auth.transport.requests import Request as GRequest
                from googleapiclient.discovery import build
                SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
                if creds.expired and creds.refresh_token:
                    creds.refresh(GRequest())
                    token_path.write_text(creds.to_json())
                servicio = build("calendar", "v3", credentials=creds)
                for cal in cals_oauth:
                    try:
                        r = servicio.events().list(
                            calendarId=cal["email"],
                            timeMin=ahora.isoformat(),
                            timeMax=hasta_deteccion.isoformat(),  # 7 días para detectar eventos nuevos
                            singleEvents=True,
                            orderBy="startTime",
                            maxResults=500
                        ).execute()
                        cli = clientes.get(cal.get("cliente_asociado"), {})
                        for ev in r.get("items", []):
                            # iCalUID es estable entre calendarios; id es por-calendario
                            uid_raw = ev.get("iCalUID") or ev.get("id", "")
                            uid = _norm_uid(uid_raw)
                            start_v = ev.get("start", {}).get("dateTime")
                            end_v   = ev.get("end",   {}).get("dateTime")
                            if not start_v:
                                continue
                            try:
                                start = datetime.fromisoformat(start_v.replace("Z", "+00:00"))
                                end   = datetime.fromisoformat(end_v.replace("Z", "+00:00")) if end_v else None
                            except Exception:
                                continue
                            dedupe_key = (uid, start.isoformat())
                            if dedupe_key in yapuestos:
                                continue
                            yapuestos.add(dedupe_key)
                            # Link de Meet (puede venir como hangoutLink o conferenceData)
                            meet_link = ev.get("hangoutLink", "")
                            if not meet_link:
                                cd = ev.get("conferenceData", {}) or {}
                                for ep_entry in (cd.get("entryPoints") or []):
                                    if ep_entry.get("entryPointType") == "video":
                                        meet_link = ep_entry.get("uri", "")
                                        break
                            org = ev.get("organizer", {}) or {}
                            organizador = org.get("displayName") or org.get("email", "")
                            # ¿Evento NUEVO? Si no lo conocíamos, lo registramos y notificamos
                            try:
                                existe = _db.query(
                                    "SELECT 1 FROM eventos_conocidos WHERE uid=%s AND inicio=%s",
                                    (uid, start)
                                )
                                if not existe:
                                    _db.execute("""
                                        INSERT INTO eventos_conocidos
                                          (uid, inicio, titulo, fin, calendario, cliente, ubicacion, organizador, html_link, meet_link)
                                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                        ON CONFLICT (uid, inicio) DO NOTHING
                                    """, (uid, start,
                                          ev.get("summary", "(sin título)"),
                                          end,
                                          cal.get("nombre_para_mostrar"),
                                          cli.get("nombre", ""),
                                          ev.get("location", ""),
                                          organizador,
                                          ev.get("htmlLink", ""),
                                          meet_link))
                                    if not es_primer_sync:
                                        _notificar_evento_nuevo({
                                            "titulo": ev.get("summary", "(sin título)"),
                                            "inicio": start,
                                            "fin": end,
                                            "calendario": cal.get("nombre_para_mostrar"),
                                            "cliente": cli.get("nombre", ""),
                                            "ubicacion": ev.get("location", ""),
                                            "organizador": organizador,
                                            "html_link": ev.get("htmlLink", ""),
                                            "meet_link": meet_link
                                        })
                                        notificados_nuevos += 1
                            except Exception as e:
                                print(f"⚠️  No se pudo trackear evento conocido: {e}")
                            # Programar aviso -10 min sólo si está dentro de las próximas 24h
                            if start > limite_aviso:
                                continue
                            aviso_at = start - timedelta(minutes=10)
                            if aviso_at <= ahora:
                                continue
                            if _db.query("SELECT 1 FROM eventos_avisados WHERE evento_uid=%s AND inicio=%s AND tipo_aviso='pre_10min'",
                                          (uid, start)):
                                continue
                            payload = {
                                "uid": uid,
                                "titulo": ev.get("summary", "(sin título)"),
                                "inicio_iso": start.isoformat(),
                                "fin_iso": end.isoformat() if end else None,
                                "ubicacion": ev.get("location", ""),
                                "calendario": cal.get("nombre_para_mostrar"),
                                "cliente": cli.get("nombre", ""),
                                "html_link": ev.get("htmlLink", ""),
                                "meet_link": meet_link
                            }
                            job_id = f"ev_{uid}_{int(start.timestamp())}"
                            get_scheduler().add_job(
                                avisar_evento,
                                "date",
                                run_date=aviso_at,
                                args=[payload],
                                id=job_id,
                                replace_existing=True
                            )
                            nuevos += 1
                    except Exception as e:
                        print(f"⚠️  Sync OAuth error {cal.get('email','?')}: {e}")
        except Exception as e:
            print(f"⚠️  Sync OAuth global error: {e}")

    # ─── Calendarios iCal (legacy) ───
    for cal in cals:
        try:
            req = urllib.request.Request(cal["ical_url"], headers={"User-Agent": "Organizador/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                ics = r.read()
            ical = Calendar.from_ical(ics)
            ocs = recurring_ical_events.of(ical).between(ahora, hasta)
            for ev in ocs:
                start = ev.get("DTSTART").dt if ev.get("DTSTART") else None
                end = ev.get("DTEND").dt if ev.get("DTEND") else start
                uid = str(ev.get("UID", ""))
                if not start or not hasattr(start, "hour"):
                    continue
                if start.tzinfo is None:
                    start = start.replace(tzinfo=TZ)
                if end and end.tzinfo is None:
                    end = end.replace(tzinfo=TZ)

                aviso_at = start - timedelta(minutes=10)
                if aviso_at <= ahora:
                    continue  # ya pasó la ventana de aviso

                # ID único por evento+inicio para no duplicar
                job_id = f"ev_{uid}_{int(start.timestamp())}"
                # ¿ya está programado o ya avisado?
                if _db.query("SELECT 1 FROM eventos_avisados WHERE evento_uid=%s AND inicio=%s AND tipo_aviso='pre_10min'",
                              (uid, start)):
                    continue

                cli = clientes.get(cal.get("cliente_asociado"), {})
                payload = {
                    "uid": uid,
                    "titulo": str(ev.get("SUMMARY", "(sin título)")),
                    "inicio_iso": start.isoformat(),
                    "fin_iso": end.isoformat() if end else None,
                    "ubicacion": str(ev.get("LOCATION", "")),
                    "calendario": cal.get("nombre_para_mostrar"),
                    "cliente": cli.get("nombre", "")
                }
                s = get_scheduler()
                s.add_job(
                    avisar_evento,
                    "date",
                    run_date=aviso_at,
                    args=[payload],
                    id=job_id,
                    replace_existing=True
                )
                nuevos += 1
        except Exception as e:
            print(f"⚠️  Sync iCal error {cal.get('email','?')}: {e}")
    if nuevos or notificados_nuevos or es_primer_sync:
        marca = " (primer sync — registrando sin notificar)" if es_primer_sync else ""
        print(f"📅 Sync: programados {nuevos} avisos -10min · {notificados_nuevos} eventos nuevos notificados a Telegram{marca}")


def _notificar_evento_nuevo(info: dict):
    """Envía a Telegram el aviso de un evento recién agendado."""
    try:
        DIAS_ES = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
        MESES_ES = ["","ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
        inicio = info["inicio"]
        inicio_local = inicio.astimezone(TZ)
        fin_local = info.get("fin").astimezone(TZ) if info.get("fin") else None
        dia = DIAS_ES[inicio_local.weekday()].capitalize()
        fecha = f"{dia} {inicio_local.day} {MESES_ES[inicio_local.month]}"
        hora = inicio_local.strftime("%H:%M")
        rango = hora
        if fin_local:
            rango += f" – {fin_local.strftime('%H:%M')}"
        texto = f"📅 *Nueva reunión agendada*\n\n*{info['titulo']}*\n\n🕐 {fecha} · {rango}"
        if info.get("cliente"):
            texto += f"\n🏢 {info['cliente']}"
        elif info.get("calendario"):
            texto += f"\n📅 {info['calendario']}"
        if info.get("organizador"):
            texto += f"\n👤 Por: {info['organizador']}"
        if info.get("ubicacion"):
            texto += f"\n📍 {info['ubicacion']}"
        if info.get("meet_link"):
            texto += f"\n\n🎥 [Unirse al Meet]({info['meet_link']})"
        if info.get("html_link"):
            texto += f"\n📖 [Ver en Calendar]({info['html_link']})"
        telegram_send(texto)
    except Exception as e:
        print(f"⚠️  Error notificando evento nuevo: {e}")


def _evento_sigue_vigente(payload: dict, inicio: datetime) -> bool:
    """Verifica con Google API que el evento aún existe a esa hora.
    Devuelve True si sigue vigente o si NO se puede verificar (failsafe = avisa).
    Devuelve False sólo cuando Google confirma que el evento ya no está ahí."""
    uid = payload.get("uid", "").strip()
    if not uid:
        return True  # sin uid, no podemos verificar — mejor avisar
    try:
        from pathlib import Path as _Path
        token_path = _Path(__file__).resolve().parent.parent / "integraciones" / "token.json"
        if not token_path.exists():
            return True
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GRequest
        from googleapiclient.discovery import build
        SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(GRequest())
            token_path.write_text(creds.to_json())
        servicio = build("calendar", "v3", credentials=creds)
        from comun import cargar
        cals = [c for c in cargar("calendarios.json").get("calendarios_gmail", [])
                if c.get("activo") and not c.get("ical_url")]
        t_min = (inicio - timedelta(minutes=2)).isoformat()
        t_max = (inicio + timedelta(minutes=2)).isoformat()
        # Probar las 2 formas del iCalUID porque Google las maneja distinto
        candidatos = [uid]
        if "@" not in uid:
            candidatos.append(uid + "@google.com")
        for cal in cals:
            for c_uid in candidatos:
                try:
                    r = servicio.events().list(
                        calendarId=cal["email"],
                        iCalUID=c_uid,
                        timeMin=t_min,
                        timeMax=t_max,
                        singleEvents=True
                    ).execute()
                    for ev in r.get("items", []):
                        ev_start = ev.get("start", {}).get("dateTime", "")
                        if not ev_start:
                            continue
                        try:
                            ev_start_dt = datetime.fromisoformat(ev_start.replace("Z", "+00:00"))
                        except Exception:
                            continue
                        # Si el start coincide en menos de 60 seg → es el mismo
                        if abs((ev_start_dt - inicio).total_seconds()) < 60:
                            return True
                except Exception:
                    continue
        # No se encontró el evento a esa hora en ningún calendario
        return False
    except Exception as e:
        print(f"⚠️  No se pudo verificar vigencia del evento: {e}")
        return True  # failsafe: ante duda, enviar


def avisar_evento(payload: dict):
    """Dispara 10 min antes de un evento. Envía Telegram y marca como avisado."""
    inicio = datetime.fromisoformat(payload["inicio_iso"])
    ahora = datetime.now(TZ)
    # PROTECCIÓN 2: verificar que el evento aún existe en Google antes de avisar
    if not _evento_sigue_vigente(payload, inicio):
        print(f"⏭️  Evento '{payload.get('titulo')}' movido/cancelado — no envío aviso")
        return
    min_restantes = max(0, int((inicio - ahora).total_seconds() / 60))

    hora_ini = inicio.astimezone(TZ).strftime("%H:%M")
    hora_fin = ""
    if payload.get("fin_iso"):
        try:
            fin = datetime.fromisoformat(payload["fin_iso"])
            hora_fin = fin.astimezone(TZ).strftime("%H:%M")
        except Exception:
            pass

    texto = f"⏰ *En {min_restantes} min: {payload['titulo']}*"
    texto += f"\n\n🕐 {hora_ini}"
    if hora_fin:
        texto += f" – {hora_fin}"
    if payload.get("cliente"):
        texto += f"\n🏢 {payload['cliente']}"
    elif payload.get("calendario"):
        texto += f"\n📅 {payload['calendario']}"
    if payload.get("ubicacion"):
        texto += f"\n📍 {payload['ubicacion']}"
    if payload.get("meet_link"):
        texto += f"\n\n🎥 [Unirse al Meet]({payload['meet_link']})"
    if payload.get("html_link"):
        texto += f"\n📖 [Ver evento en Calendar]({payload['html_link']})"

    telegram_send(texto)
    try:
        _db.execute(
            "INSERT INTO eventos_avisados (evento_uid, inicio, tipo_aviso) VALUES (%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (payload["uid"], inicio, "pre_10min")
        )
    except Exception as e:
        print(f"⚠️  No se pudo marcar avisado: {e}")
