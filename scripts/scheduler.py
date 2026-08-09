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


def _asegurar_tabla_resumen_diario():
    """Tabla para idempotencia: garantiza que el resumen se envíe EXACTAMENTE
    una vez por día, sobreviviendo reinicios del container."""
    try:
        _db.execute("""
            CREATE TABLE IF NOT EXISTS resumen_diario_enviado (
                fecha DATE PRIMARY KEY,
                enviado_at TIMESTAMPTZ DEFAULT NOW(),
                eventos_count INT DEFAULT 0,
                tareas_count INT DEFAULT 0,
                habitos_count INT DEFAULT 0,
                intentos INT DEFAULT 1
            )
        """)
    except Exception as e:
        print(f"⚠️  No se pudo crear tabla resumen_diario_enviado: {e}")


def iniciar():
    """Llamar UNA VEZ al boot de la API."""
    s = get_scheduler()
    if s.running:
        return
    s.start()
    _asegurar_tabla_eventos_conocidos()
    _asegurar_tabla_resumen_diario()
    # Job recurrente: sincroniza eventos cada 30 min (antes 1h)
    s.add_job(
        sincronizar_eventos_calendario,
        "interval", minutes=30,
        id="_sync_ical_horario",
        replace_existing=True,
        next_run_time=datetime.now(TZ) + timedelta(seconds=30)
    )
    # Resumen matutino: cada día a la hora de despertar configurada
    _programar_resumen_matutino()
    # RECOVERY: si ya pasó la hora de despertar HOY y no se envió → enviar
    _intentar_resumen_si_falta()
    # Avisos inteligentes (cocinar, hábitos, sprint, mercado): escaneo cada 15 min
    _asegurar_tabla_avisos_intel()
    s.add_job(
        revisar_avisos_inteligentes,
        "interval", minutes=15,
        id="_avisos_inteligentes",
        replace_existing=True,
        next_run_time=datetime.now(TZ) + timedelta(seconds=90)
    )
    # Resumen dominical de pareja: domingos 7:30pm (tolera hasta 2h de atraso)
    try:
        from apscheduler.triggers.cron import CronTrigger as _Cron
        s.add_job(
            enviar_resumen_dominical,
            _Cron(day_of_week="sun", hour=19, minute=30, timezone=TZ),
            id="_resumen_dominical",
            replace_existing=True,
            misfire_grace_time=7200
        )
    except Exception as e:
        print(f"⚠️  No se pudo programar resumen dominical: {e}")
    # Re-programar recordatorios pendientes
    reprogramar_recordatorios_pendientes()
    print("⚙️  Scheduler iniciado · jobs:", len(s.get_jobs()))


def _programar_resumen_matutino():
    """Lee config.horario_sueno.despertar y programa el resumen diario a esa hora.
    misfire_grace_time alto: si el sistema estaba caído cuando tocaba, lo dispara
    hasta 1h después de su hora teórica."""
    try:
        from apscheduler.triggers.cron import CronTrigger
        from comun import cargar
        cfg = cargar("config.json")
        sueno = cfg.get("horario_sueno") if isinstance(cfg, dict) else None
        despertar = (sueno or {}).get("despertar", "06:00")
        hora, minuto = map(int, despertar.split(":"))
        s = get_scheduler()
        s.add_job(
            enviar_resumen_matutino,
            CronTrigger(hour=hora, minute=minuto, timezone=TZ),
            id="_resumen_matutino",
            replace_existing=True,
            misfire_grace_time=3600  # tolera hasta 1h de atraso
        )
        print(f"☀️  Resumen matutino programado para las {despertar} (misfire grace 1h)")
    except Exception as e:
        print(f"⚠️  No se pudo programar resumen matutino: {e}")


def _intentar_resumen_si_falta():
    """Al boot: si ya pasó la hora de despertar HOY y NO se envió resumen →
    enviarlo ahora. Cubre el caso de easypanel reiniciando el container
    justo a la hora teórica."""
    try:
        from comun import cargar
        cfg = cargar("config.json")
        sueno = cfg.get("horario_sueno") if isinstance(cfg, dict) else None
        despertar = (sueno or {}).get("despertar", "06:00")
        hora, minuto = map(int, despertar.split(":"))
        ahora = datetime.now(TZ)
        hora_hoy = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        if ahora < hora_hoy:
            return  # aún no es hora, el cron lo manejará
        rows = _db.query("SELECT 1 FROM resumen_diario_enviado WHERE fecha=%s", (ahora.date(),))
        if rows:
            return  # ya se envió hoy
        # Demora 60s para no interferir con el arranque y para que la DB termine de levantarse
        print(f"☀️  Recovery: resumen de hoy aún no enviado, ejecutando en 60s...")
        get_scheduler().add_job(
            enviar_resumen_matutino,
            "date",
            run_date=ahora + timedelta(seconds=60),
            id="_resumen_recovery",
            replace_existing=True
        )
    except Exception as e:
        print(f"⚠️  Recovery resumen: {e}")


# ─────────────────────────────────────────────────────────
# Enrutador de avisos por persona (Fase 2)
# ─────────────────────────────────────────────────────────
def _enrutar(persona_id, titulo, cuerpo, url="/", tag="", telegram_texto=None):
    """Envía un aviso al dueño (persona) por Web Push + su Telegram.
    Si no hay persona (calendario sin dueño), cae al Telegram global de siempre."""
    if persona_id:
        try:
            import avisos
            return avisos.avisar_persona(persona_id, titulo, cuerpo, url=url,
                                         tag=tag, telegram_texto=telegram_texto)
        except Exception as e:
            print(f"⚠️  Enrutador avisos: {e}")
    # Sin dueño → comportamiento clásico (Telegram global)
    telegram_send(telegram_texto if telegram_texto is not None else f"*{titulo}*\n{cuerpo}")
    return {"push": 0, "telegram": True, "fallback": True}


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


def _repetir_etiqueta(rep: str) -> str:
    """'dias:1,3,5' → 'L,X,V'; el resto se muestra tal cual."""
    if not rep or rep == "no":
        return ""
    if rep.startswith("dias:"):
        letras = {1: "L", 2: "M", 3: "X", 4: "J", 5: "V", 6: "S", 7: "D"}
        try:
            return "los " + ",".join(letras[int(x)] for x in rep.split(":", 1)[1].split(",") if x.strip())
        except (ValueError, KeyError):
            return "días específicos"
    return rep


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
        texto += f"\n_🔁 se repite {_repetir_etiqueta(r['repetir'])}_"

    cuerpo = r["titulo"] + (f" · {hora}" if hora else "")
    _enrutar(r.get("persona_id"), "Recordatorio", cuerpo,
             url="/", tag=f"rec_{rec_id}", telegram_texto=texto)
    _db.execute(
        "UPDATE recordatorios SET enviado=TRUE, enviado_at=NOW() WHERE id=%s",
        (rec_id,)
    )

    # Repetición
    if r.get("repetir") and r["repetir"] != "no":
        rep = r["repetir"]
        siguiente = None
        if rep.startswith("dias:"):
            # Días específicos (ISO 1-7): buscar el próximo día marcado
            try:
                dias_sel = {int(x) for x in rep.split(":", 1)[1].split(",") if x.strip()}
            except ValueError:
                dias_sel = set()
            if dias_sel:
                cand = fh + timedelta(days=1)
                for _ in range(7):
                    if cand.astimezone(TZ).isoweekday() in dias_sel:
                        siguiente = cand
                        break
                    cand += timedelta(days=1)
        else:
            delta = {
                "diario":   timedelta(days=1),
                "semanal":  timedelta(weeks=1),
                "mensual":  timedelta(days=30),
                "anual":    timedelta(days=365)
            }.get(rep)
            if delta:
                siguiente = fh + delta
        if siguiente:
            from secrets import token_hex
            nuevo_id = f"rec_{datetime.now().strftime('%Y%m%d%H%M%S')}_{token_hex(3)}"
            _db.execute("""
                INSERT INTO recordatorios (id, titulo, mensaje, fecha_hora, repetir, cliente_id, persona_id, enviado, activo)
                VALUES (%s,%s,%s,%s,%s,%s,%s,FALSE,TRUE)
            """, (nuevo_id, r["titulo"], r.get("mensaje",""), siguiente, rep,
                  r.get("cliente_id"), r.get("persona_id")))
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
                            # Detección de "evento NUEVO" — solo notifica la
                            # PRIMERA vez que vemos un UID, no las siguientes
                            # instancias del mismo evento recurrente.
                            try:
                                # ¿Hemos visto ANTES este UID (con cualquier inicio)?
                                uid_ya_visto = _db.query(
                                    "SELECT 1 FROM eventos_conocidos WHERE uid=%s LIMIT 1",
                                    (uid,)
                                )
                                # ¿Hemos visto esta instancia específica (uid, inicio)?
                                instancia_existe = _db.query(
                                    "SELECT 1 FROM eventos_conocidos WHERE uid=%s AND inicio=%s",
                                    (uid, start)
                                )
                                if not instancia_existe:
                                    # Registrar siempre la instancia (para tracking)
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
                                    # Notificar SOLO si el UID era totalmente nuevo
                                    # (alguien te invitó por primera vez a este evento)
                                    if not uid_ya_visto and not es_primer_sync:
                                        _notificar_evento_nuevo({
                                            "titulo": ev.get("summary", "(sin título)"),
                                            "inicio": start,
                                            "fin": end,
                                            "calendario": cal.get("nombre_para_mostrar"),
                                            "cliente": cli.get("nombre", ""),
                                            "persona_id": cal.get("persona_id"),
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
                                "persona_id": cal.get("persona_id"),
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
                    "cliente": cli.get("nombre", ""),
                    "persona_id": cal.get("persona_id")
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


def _asegurar_tabla_resumen_persona():
    try:
        _db.execute("""
            CREATE TABLE IF NOT EXISTS resumen_persona_enviado (
                fecha DATE NOT NULL, persona_id TEXT NOT NULL,
                enviado_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (fecha, persona_id))""")
    except Exception as e:
        print(f"⚠️  tabla resumen_persona_enviado: {e}")


def _habitos_de_hoy(ahora, persona_id=None):
    """Hábitos activos que tocan hoy. Si se da persona_id: sus personales + los
    de pareja. Sin persona: todos (comportamiento clásico)."""
    from comun import cargar
    try:
        habs_data = cargar("habitos.json")
        cats = {c["id"]: c for c in habs_data.get("categorias", [])}
        dia_iso = ahora.isoweekday()
        salida = []
        for h in habs_data.get("habitos", []):
            if not h.get("activo", True):
                continue
            dias = h.get("dias")
            if dias and isinstance(dias, list) and dia_iso not in dias:
                continue
            if persona_id:
                alcance = h.get("alcance", "pareja")
                if alcance == "personal" and h.get("persona_id") != persona_id:
                    continue
            cat = cats.get(h.get("categoria_id"), {})
            salida.append({"id": h.get("id"),
                           "nombre": h.get("nombre", "(sin nombre)"),
                           "icono": cat.get("icono") or h.get("icono") or "•"})
        return salida
    except Exception as e:
        print(f"⚠️  Resumen: hábitos: {e}")
        return []


def _comida_de_hoy(ahora):
    """Devuelve {desayuno, almuerzo, cena} del menú de la semana para hoy (o {})."""
    from comun import cargar
    try:
        y, w, dow = ahora.isocalendar()   # dow: 1=lunes..7=domingo
        semana = f"{y}-W{w:02d}"
        dias_nom = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        nombre_dia = dias_nom[dow - 1]
        fila = next((m for m in cargar("menus.json").get("menus", []) if m.get("semana") == semana), None)
        return ((fila or {}).get("dias", {}) or {}).get(nombre_dia, {}) or {}
    except Exception as e:
        print(f"⚠️  Resumen: comida: {e}")
        return {}


# ─────────────────────────────────────────────────────────
# Avisos inteligentes (Fase 5): cocinar, hábitos, sprint, mercado
# ─────────────────────────────────────────────────────────
def _asegurar_tabla_avisos_intel():
    try:
        _db.execute("""
            CREATE TABLE IF NOT EXISTS avisos_intel_enviados (
                fecha DATE NOT NULL, persona_id TEXT NOT NULL, tipo TEXT NOT NULL,
                enviado_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (fecha, persona_id, tipo))""")
    except Exception as e:
        print(f"⚠️  tabla avisos_intel_enviados: {e}")


def _marcar_aviso_intel(fecha, persona_id, tipo) -> bool:
    """Registra el envío de hoy; devuelve True SOLO la primera vez (dedup atómico)."""
    try:
        res = _db.query(
            "INSERT INTO avisos_intel_enviados (fecha, persona_id, tipo) "
            "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING 1",
            (fecha, persona_id, tipo))
        return bool(res)
    except Exception as e:
        print(f"⚠️  marcar aviso intel: {e}")
        return False


def revisar_avisos_inteligentes():
    """Escaneo periódico (~15 min). Cada aviso se manda una sola vez al día
    gracias al marcador. Respeta los toggles en config.avisos_inteligentes."""
    from comun import cargar, cargar_registro_dia
    try:
        cfg = cargar("config.json")
        tog = (cfg.get("avisos_inteligentes") or {}) if isinstance(cfg, dict) else {}
        def on(k):
            return tog.get(k, True)   # por defecto: encendidos
        ahora = datetime.now(TZ)
        hoy = ahora.date()
        hm = ahora.hour * 60 + ahora.minute
        dow = ahora.isoweekday()   # 1=lunes .. 7=domingo
        personas = [p for p in cargar("personas.json").get("personas", []) if p.get("activo", True)]
        configuradas = [p for p in personas if p.get("telegram_chat_id") or p.get("push_subscriptions")]
        import avisos

        # 1) Hora de cocinar — almuerzo 11:00–12:30, cena 18:00–19:30
        if on("cocinar"):
            comida = _comida_de_hoy(ahora)
            for momento, ini, fin in [("almuerzo", 11*60, 12*60+30), ("cena", 18*60, 19*60+30)]:
                plato = (comida or {}).get(momento)
                if plato and ini <= hm < fin and _marcar_aviso_intel(hoy, "_todos", f"cocinar_{momento}"):
                    avisos.avisar_todos(
                        "🍳 Hora de cocinar",
                        f"Toca preparar {plato} ({momento}). ¡Buen provecho! 💛",
                        url="/tablero/comidas.html", tag="cocinar")

        # 2) Faltan cosas en el mercado — sábado 8:00–12:00
        if on("mercado") and dow == 6 and 8*60 <= hm < 12*60:
            pend = [m for m in cargar("lista_mercado.json").get("lista_mercado", []) if not m.get("comprado")]
            if pend and _marcar_aviso_intel(hoy, "_todos", "mercado"):
                avisos.avisar_todos(
                    "🛒 Lista de mercado",
                    f"Tienen {len(pend)} cosa(s) por comprar este fin. ¿Van al mercado?",
                    url="/tablero/mercado.html", tag="mercado")

        # 3) Meta de sprint sin avance — miércoles 9:00–21:00
        if on("sprint") and dow == 3 and 9*60 <= hm < 21*60:
            y, w, _ = ahora.isocalendar(); semana = f"{y}-W{w:02d}"
            fila = next((s for s in cargar("sprints.json").get("sprints", []) if s.get("semana") == semana), None)
            metas = (fila or {}).get("metas", []) if fila else []
            if metas and sum(1 for m in metas if m.get("hecha")) == 0 and _marcar_aviso_intel(hoy, "_todos", "sprint"):
                avisos.avisar_todos(
                    "🎯 Su sprint de la semana",
                    f"Mitad de semana y aún ninguna de sus {len(metas)} meta(s) está cumplida. ¡Ánimo, juntos! 🔥",
                    url="/tablero/sprint.html", tag="sprint")

        # 4) Se acabó algo de la despensa — media mañana 9:30–12:00
        if on("despensa") and 9*60+30 <= hm < 12*60:
            agotados = [d.get("item") for d in cargar("despensa.json").get("despensa", [])
                        if d.get("estado") == "agotado" and d.get("item")]
            if agotados and _marcar_aviso_intel(hoy, "_todos", "despensa"):
                lista = ", ".join(agotados[:5]) + ("…" if len(agotados) > 5 else "")
                avisos.avisar_todos(
                    "🧺 Se acabó en la despensa",
                    f"Sin: {lista}. Dale a «Armar de esta semana» en el mercado para reponerlo.",
                    url="/tablero/mercado.html", tag="despensa")

        # 5) Actividades por vencer — mañana 8:00–11:00, por persona
        if on("vencimientos") and 8*60 <= hm < 11*60:
            historias = cargar("historias.json").get("historias", [])
            manana = (hoy + timedelta(days=1)).isoformat()
            hoy_iso = hoy.isoformat()
            for p in configuradas:
                por_vencer = [h for h in historias
                              if h.get("estado") not in ("hecho",)
                              and h.get("responsable_id") in (p["id"], "ambos")
                              and h.get("fecha_objetivo") in (hoy_iso, manana)]
                if por_vencer and _marcar_aviso_intel(hoy, p["id"], "vencimientos"):
                    lista = ", ".join(h.get("titulo", "") for h in por_vencer[:3])
                    _enrutar(p["id"], "⏰ Por vencer",
                             f"{len(por_vencer)} tarea(s) vencen hoy o mañana: {lista}"
                             f"{'…' if len(por_vencer) > 3 else ''}",
                             url="/tablero/proyectos.html", tag="vencimientos")

        # 6) Te toca estudiar — tarde 18:00–21:00, por persona
        if on("estudio") and 18*60 <= hm < 21*60:
            cursos = [c for c in cargar("cursos.json").get("cursos", [])
                      if c.get("estado") != "terminado"]
            hoy_iso = hoy.isoformat()
            for p in configuradas:
                pendientes_est = []
                for c in cursos:
                    if c.get("persona_id") not in (p["id"], "ambos"):
                        continue
                    estudio_hoy = any(str(h.get("fecha"))[:10] == hoy_iso and h.get("persona_id") == p["id"]
                                      for h in (c.get("historial") or []))
                    if not estudio_hoy:
                        pendientes_est.append(c)
                if pendientes_est and _marcar_aviso_intel(hoy, p["id"], "estudio"):
                    c0 = pendientes_est[0]
                    racha = c0.get("racha") or 0
                    extra = f" — llevas {racha} día(s) de racha 🔥" if racha >= 2 else ""
                    _enrutar(p["id"], "🎓 Te toca estudiar",
                             f"{c0.get('emoji','📚')} {c0['nombre']}: {c0.get('min_dia',20)} min de hoy{extra}",
                             url="/tablero/aprender.html", tag="estudio")

        # 7) Hábito sin marcar — noche 20:00–22:00, por persona
        if on("habitos") and 20*60 <= hm < 22*60:
            cumplidos = set(cargar_registro_dia().get("habitos_cumplidos", []))
            for p in configuradas:
                pendientes = [h for h in _habitos_de_hoy(ahora, p["id"]) if h.get("id") and h["id"] not in cumplidos]
                if pendientes and _marcar_aviso_intel(hoy, p["id"], "habitos"):
                    lista = ", ".join(h["nombre"] for h in pendientes[:3])
                    _enrutar(p["id"], "✅ Hábitos de hoy",
                             f"Te queda(n) {len(pendientes)} por marcar: {lista}{'…' if len(pendientes) > 3 else ''}",
                             url="/", tag="habitos")
    except Exception as e:
        print(f"⚠️  revisar_avisos_inteligentes: {e}")


# ─────────────────────────────────────────────────────────
# Resumen dominical de pareja (domingo ~7:30pm)
# ─────────────────────────────────────────────────────────
def enviar_resumen_dominical(forzar: bool = False):
    """Cada domingo en la noche: cómo les fue la semana como pareja
    (sprint, estudio, hábitos, gastos, mercado) + arranque de la nueva."""
    from comun import cargar, cargar_registro_dia
    try:
        cfg = cargar("config.json")
        tog = (cfg.get("avisos_inteligentes") or {}) if isinstance(cfg, dict) else {}
        if not tog.get("resumen_semanal", True) and not forzar:
            return
        ahora = datetime.now(TZ)
        hoy = ahora.date()
        if not forzar and not _marcar_aviso_intel(hoy, "_todos", "resumen_semanal"):
            return  # ya se envió este domingo

        y, w, _ = hoy.isocalendar()
        semana = f"{y}-W{w:02d}"
        personas = {p["id"]: p for p in cargar("personas.json").get("personas", [])
                    if p.get("activo", True)}
        nom = lambda pid: (personas.get(pid, {}).get("nombre") or pid).split(" ")[0]
        partes = ["💞 *Resumen de su semana*"]

        # 🎯 Sprint
        fila = next((s for s in cargar("sprints.json").get("sprints", [])
                     if s.get("semana") == semana), None)
        if fila and (fila.get("lema") or fila.get("metas")):
            metas = fila.get("metas") or []
            hechas = sum(1 for m in metas if m.get("hecha"))
            lema = fila.get("lema") or "sin foco"
            cierre = "semana cerrada ✓" if fila.get("cerrado") else "¡ciérrenla en el Sprint!"
            partes.append(f"🎯 «{lema}»: {hechas}/{len(metas)} metas · {cierre}")

        # 🎓 Estudio + reto
        mins = {}
        for c in cargar("cursos.json").get("cursos", []):
            for h in (c.get("historial") or []):
                try:
                    f = date.fromisoformat(str(h.get("fecha"))[:10])
                except (TypeError, ValueError):
                    continue
                fy, fw, _ = f.isocalendar()
                if f"{fy}-W{fw:02d}" == semana and h.get("persona_id"):
                    mins[h["persona_id"]] = mins.get(h["persona_id"], 0) + int(h.get("minutos") or 0)
        if mins:
            detalle = " · ".join(f"{nom(pid)} {m} min" for pid, m in mins.items())
            reto = cfg.get("reto_aprender") or {}
            total = sum(mins.values())
            extra = ""
            if reto.get("modo", "coop") == "coop":
                meta = int(reto.get("meta_min") or 300)
                extra = " — ¡reto cumplido! 🤝" if total >= meta else f" — quedaron a {meta - total} min de la meta"
            elif reto.get("modo") == "versus" and len(mins) > 1:
                lider = max(mins, key=mins.get)
                vals = sorted(mins.values())
                extra = " — empate 🤜🤛" if vals[-1] == vals[-2] else f" — 👑 ganó {nom(lider)}"
            partes.append(f"🎓 Estudio: {detalle}{extra}")

        # ✅ Hábitos marcados en la semana (lunes a hoy)
        cumplidos = 0
        for i in range(7):
            d = hoy - timedelta(days=i)
            dy, dw, _ = d.isocalendar()
            if f"{dy}-W{dw:02d}" != semana:
                continue
            try:
                cumplidos += len(cargar_registro_dia(d.isoformat()).get("habitos_cumplidos", []))
            except Exception:
                pass
        if cumplidos:
            partes.append(f"✅ Hábitos: marcaron {cumplidos} esta semana")

        # 💸 Gastos del mes (reparto 50/50 en lo compartido)
        mes = hoy.strftime("%Y-%m")
        gastos = [g for g in cargar("gastos.json").get("gastos", [])
                  if str(g.get("fecha") or "")[:7] == mes and (g.get("tipo") or "gasto") == "gasto"]
        if gastos:
            ids = list(personas.keys())
            pagado = {i: 0.0 for i in ids}
            debe = {i: 0.0 for i in ids}
            total_g = 0.0
            for g in gastos:
                try:
                    m = float(g.get("monto") or 0)
                except (TypeError, ValueError):
                    m = 0.0
                total_g += m
                if g.get("pagado_por") in pagado:
                    pagado[g["pagado_por"]] += m
                part = g.get("participacion") or "ambos"
                if part in ids:
                    debe[part] += m
                else:
                    for i in ids:
                        debe[i] += m / (len(ids) or 1)
            deuda = ""
            if len(ids) == 2:
                a, b = ids
                neto_a = pagado[a] - debe[a]
                if abs(neto_a) > 0.005:
                    deudor, acreedor = (b, a) if neto_a > 0 else (a, b)
                    deuda = f" · {nom(deudor)} le debe ${abs(round(neto_a)):,.0f} a {nom(acreedor)}".replace(",", ".")
                else:
                    deuda = " · están a mano 🤝"
            partes.append(f"💸 Este mes: gastado ${round(total_g):,.0f}{deuda}".replace(",", "."))

        # 🛒 Mercado
        pend = sum(1 for m in cargar("lista_mercado.json").get("lista_mercado", [])
                   if not m.get("comprado"))
        if pend:
            partes.append(f"🛒 Mercado: {pend} cosa(s) pendientes")

        partes.append("\n🌟 Arranca semana nueva: elijan su foco en el Sprint 💪")
        texto = "\n".join(partes)

        import avisos
        avisos.avisar_todos("💞 Resumen de su semana",
                            "Cómo les fue juntos esta semana — mírenlo 💪",
                            url="/tablero/nosotros.html", tag="resumen-semanal")
        # El detalle completo va por Telegram (permite más texto)
        for p in personas.values():
            chat = p.get("telegram_chat_id") or ""
            if chat:
                import avisos as _av
                _av._enviar_telegram(chat, texto)
        if not any(p.get("telegram_chat_id") for p in personas.values()):
            telegram_send(texto)
        print(f"💞 Resumen dominical enviado ({semana})")
    except Exception as e:
        print(f"⚠️  resumen dominical: {e}")


def _leer_eventos_google(cals, inicio_dia, fin_dia):
    """[{hora,titulo,calendario}] de eventos OAuth para los calendarios dados (hoy)."""
    eventos = []
    cals = [c for c in cals if not c.get("ical_url")]
    if not cals:
        return eventos
    try:
        from pathlib import Path as _Path
        token_path = _Path(__file__).resolve().parent.parent / "integraciones" / "token.json"
        if not token_path.exists():
            return eventos
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request as GRequest
        from googleapiclient.discovery import build
        SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(GRequest()); token_path.write_text(creds.to_json())
        servicio = build("calendar", "v3", credentials=creds)
        vistos = set()
        for cal in cals:
            try:
                r = servicio.events().list(
                    calendarId=cal["email"], timeMin=inicio_dia.isoformat(),
                    timeMax=fin_dia.isoformat(), singleEvents=True,
                    orderBy="startTime", maxResults=100).execute()
                for ev in r.get("items", []):
                    sv = ev.get("start", {}).get("dateTime")
                    if not sv:
                        continue
                    uid = (ev.get("iCalUID") or ev.get("id", "")).split("@")[0]
                    try:
                        start = datetime.fromisoformat(sv.replace("Z", "+00:00")).astimezone(TZ)
                    except Exception:
                        continue
                    k = (uid, start.isoformat())
                    if k in vistos:
                        continue
                    vistos.add(k)
                    eventos.append({"hora": start.strftime("%H:%M"),
                                    "titulo": ev.get("summary", "(sin título)"),
                                    "calendario": cal.get("nombre_para_mostrar", "")})
            except Exception:
                continue
        eventos.sort(key=lambda e: e["hora"])
    except Exception as e:
        print(f"⚠️  Resumen: error leyendo eventos: {e}")
    return eventos


def enviar_resumen_matutino(forzar: bool = False):
    """Envía el resumen matutino. Si alguna persona ya configuró sus canales
    (Telegram propio o Web Push), lo manda PERSONALIZADO a cada una (sus
    calendarios + su trabajo del canvas + hábitos). Si nadie configuró canales
    todavía, mantiene el comportamiento clásico (Telegram global)."""
    from comun import cargar
    personas = [p for p in cargar("personas.json").get("personas", []) if p.get("activo", True)]
    configuradas = [p for p in personas
                    if p.get("telegram_chat_id") or (p.get("push_subscriptions"))]
    if not configuradas:
        return _resumen_global(forzar)

    DIAS_ES = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
    MESES_ES = ["","enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
    ahora = datetime.now(TZ); hoy = ahora.date()
    fecha_human = f"{DIAS_ES[ahora.weekday()].capitalize()} {hoy.day} de {MESES_ES[hoy.month]}"
    inicio_dia = datetime.combine(hoy, datetime.min.time()).replace(tzinfo=TZ)
    fin_dia = datetime.combine(hoy, datetime.max.time()).replace(tzinfo=TZ)
    cals_all = [c for c in cargar("calendarios.json").get("calendarios_gmail", []) if c.get("activo")]
    historias = cargar("historias.json").get("historias", [])
    comida = _comida_de_hoy(ahora)
    _asegurar_tabla_resumen_persona()

    import avisos
    enviados = 0
    for p in configuradas:
        if not forzar:
            try:
                if _db.query("SELECT 1 FROM resumen_persona_enviado WHERE fecha=%s AND persona_id=%s",
                             (hoy, p["id"])):
                    continue
            except Exception:
                pass
        cals_p = [c for c in cals_all if c.get("persona_id") == p["id"]]
        eventos = _leer_eventos_google(cals_p, inicio_dia, fin_dia)
        his_p = [h for h in historias
                 if h.get("responsable_id") in (p["id"], "ambos") and h.get("estado") != "hecho"
                 and (h.get("estado") == "en_progreso"
                      or (h.get("fecha_objetivo") and h["fecha_objetivo"] <= hoy.isoformat()))]
        habs_hoy = _habitos_de_hoy(ahora, p["id"])

        partes = [f"☀️ *Buenos días {p['nombre']}*", f"\n📅 *Hoy {fecha_human}*"]
        if eventos:
            partes.append(f"\n*━━ Tus reuniones ({len(eventos)}) ━━*")
            partes += [f"🕐 {e['hora']}  {e['titulo']}" for e in eventos]
        else:
            partes.append("\n*━━ Reuniones ━━*\n_Sin reuniones hoy_ ✨")
        if his_p:
            partes.append(f"\n*━━ Tu trabajo de hoy ({len(his_p)}) ━━*")
            partes += [f"• {h['titulo']}" for h in his_p[:8]]
            if len(his_p) > 8:
                partes.append(f"_+ {len(his_p)-8} más en el tablero_")
        if habs_hoy:
            partes.append(f"\n*━━ Hábitos del día ({len(habs_hoy)}) ━━*")
            partes += [f"{h['icono']} {h['nombre']}" for h in habs_hoy[:8]]
        if comida:
            partes.append("\n*━━ Menú de hoy ━━*")
            etiquetas = {"desayuno": "🍳 Desayuno", "almuerzo": "🍽️ Almuerzo",
                         "comida": "🌙 Comida", "snack": "🍎 Snack"}
            for momento in ("desayuno", "almuerzo", "comida", "snack"):
                if comida.get(momento):
                    partes.append(f"{etiquetas[momento]}: {comida[momento]}")
        partes.append("\n_Buen día. Que tu energía rinda._ 💪")
        texto = "\n".join(partes)
        cuerpo_push = f"{len(eventos)} reunión(es) · {len(his_p)} del tablero · {len(habs_hoy)} hábitos"
        if comida.get("almuerzo"):
            cuerpo_push += f" · 🍽️ {comida['almuerzo']}"

        try:
            res = avisos.avisar_persona(p["id"], "Tu plan de hoy", cuerpo_push,
                                        url="/", tag="resumen", telegram_texto=texto)
            if res.get("push") or res.get("telegram"):
                _db.execute("""INSERT INTO resumen_persona_enviado (fecha, persona_id)
                               VALUES (%s,%s) ON CONFLICT DO NOTHING""", (hoy, p["id"]))
                enviados += 1
        except Exception as e:
            print(f"⚠️  Resumen persona {p.get('nombre')}: {e}")
    print(f"☀️  Resumen matutino por persona: {enviados}/{len(configuradas)} enviados")


def _resumen_global(forzar: bool = False):
    """Compone y envía por Telegram el resumen del día: eventos + tareas + hábitos.
    (Comportamiento clásico, cuando aún nadie configuró canales por persona.)

    IDEMPOTENTE: si ya se envió hoy, no envía de nuevo (a menos que forzar=True).
    RESILIENTE: reintenta hasta 3 veces si Telegram falla.
    """
    try:
        from comun import cargar
        import time as _time
        ahora_check = datetime.now(TZ)
        hoy_check = ahora_check.date()
        # Idempotencia: ¿ya se envió hoy?
        if not forzar:
            try:
                rows = _db.query(
                    "SELECT enviado_at FROM resumen_diario_enviado WHERE fecha=%s",
                    (hoy_check,)
                )
                if rows:
                    print(f"☀️  Resumen de {hoy_check} ya enviado (a las {rows[0]['enviado_at']}), no duplico")
                    return
            except Exception as e:
                print(f"⚠️  No se pudo verificar tabla resumen_diario: {e}")
        DIAS_ES = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]
        MESES_ES = ["","enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"]
        EMOJI_PRIORIDAD = {"alta":"🔴","media":"🟡","baja":"⚪"}

        ahora = datetime.now(TZ)
        hoy = ahora.date()
        nombre_dia = DIAS_ES[ahora.weekday()].capitalize()
        fecha_human = f"{nombre_dia} {hoy.day} de {MESES_ES[hoy.month]}"
        nombre_usuario = (cargar("config.json").get("usuario") or {}).get("nombre", "")
        saludo = f"☀️ *Buenos días{' ' + nombre_usuario if nombre_usuario else ''}*"
        partes = [saludo, f"\n📅 *Hoy {fecha_human}*"]

        # ─── EVENTOS DEL DÍA ───
        eventos_hoy = []
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
                cals = [c for c in cargar("calendarios.json").get("calendarios_gmail", [])
                        if c.get("activo") and not c.get("ical_url")]
                inicio_dia = datetime.combine(hoy, datetime.min.time()).replace(tzinfo=TZ)
                fin_dia = datetime.combine(hoy, datetime.max.time()).replace(tzinfo=TZ)
                vistos = set()
                for cal in cals:
                    try:
                        r = servicio.events().list(
                            calendarId=cal["email"],
                            timeMin=inicio_dia.isoformat(),
                            timeMax=fin_dia.isoformat(),
                            singleEvents=True,
                            orderBy="startTime",
                            maxResults=100
                        ).execute()
                        for ev in r.get("items", []):
                            start_v = ev.get("start", {}).get("dateTime")
                            if not start_v:
                                continue
                            uid = (ev.get("iCalUID") or ev.get("id", "")).split("@")[0]
                            try:
                                start = datetime.fromisoformat(start_v.replace("Z", "+00:00")).astimezone(TZ)
                            except Exception:
                                continue
                            key = (uid, start.isoformat())
                            if key in vistos:
                                continue
                            vistos.add(key)
                            eventos_hoy.append({
                                "hora": start.strftime("%H:%M"),
                                "titulo": ev.get("summary", "(sin título)"),
                                "calendario": cal.get("nombre_para_mostrar", "")
                            })
                    except Exception:
                        continue
            eventos_hoy.sort(key=lambda e: e["hora"])
        except Exception as e:
            print(f"⚠️  Resumen: error leyendo eventos: {e}")

        if eventos_hoy:
            partes.append(f"\n*━━ Eventos del día ({len(eventos_hoy)}) ━━*")
            for ev in eventos_hoy:
                partes.append(f"🕐 {ev['hora']}  {ev['titulo']}")
        else:
            partes.append("\n*━━ Eventos del día ━━*\n_Sin reuniones agendadas hoy_ ✨")

        # ─── TAREAS PENDIENTES CON DEADLINE HOY ───
        tareas_hoy = []
        try:
            rows = _db.query(
                "SELECT id, titulo, prioridad, cliente_id FROM actividades "
                "WHERE estado='pendiente' AND deadline=%s ORDER BY "
                "CASE prioridad WHEN 'alta' THEN 1 WHEN 'media' THEN 2 ELSE 3 END",
                (hoy,)
            )
            clientes = {c["id"]: c.get("nombre", "") for c in cargar("clientes.json").get("clientes", [])}
            for r in rows:
                tareas_hoy.append({
                    "titulo": r["titulo"],
                    "prioridad": r.get("prioridad", "media"),
                    "cliente": clientes.get(r.get("cliente_id"), "")
                })
        except Exception as e:
            print(f"⚠️  Resumen: error leyendo tareas: {e}")

        if tareas_hoy:
            partes.append(f"\n*━━ Tareas con deadline hoy ({len(tareas_hoy)}) ━━*")
            for t in tareas_hoy:
                emoji = EMOJI_PRIORIDAD.get(t["prioridad"], "•")
                cli_txt = f" · _{t['cliente']}_" if t["cliente"] else ""
                partes.append(f"{emoji} {t['titulo']}{cli_txt}")

        # ─── HÁBITOS DEL DÍA ───
        try:
            habs_data = cargar("habitos.json")
            cats = {c["id"]: c for c in habs_data.get("categorias", [])}
            todos_habs = habs_data.get("habitos", [])
            # APScheduler usa 0=Lun..6=Dom; el JSON usa 1=Lun..7=Dom
            dia_iso = ahora.isoweekday()  # 1..7
            habs_hoy = []
            for h in todos_habs:
                if not h.get("activo", True):
                    continue
                dias = h.get("dias")
                # Si el hábito tiene 'dias' definido como lista y este día no está → saltar
                if dias and isinstance(dias, list) and dia_iso not in dias:
                    continue
                habs_hoy.append(h)
            if habs_hoy:
                partes.append(f"\n*━━ Hábitos del día ({len(habs_hoy)}) ━━*")
                for h in habs_hoy[:8]:
                    cat = cats.get(h.get("categoria_id"), {})
                    icono = cat.get("icono") or h.get("icono") or "•"
                    dur = f" · {h.get('duracion_min')}min" if h.get("duracion_min") else ""
                    partes.append(f"{icono} {h.get('nombre','(sin nombre)')}{dur}")
                if len(habs_hoy) > 8:
                    partes.append(f"_+ {len(habs_hoy)-8} más_")
        except Exception as e:
            print(f"⚠️  Resumen: error leyendo hábitos: {e}")

        # ─── COMIDA DE HOY (del menú de la semana) ───
        try:
            comida = _comida_de_hoy(ahora)
            if comida:
                partes.append("\n*━━ Menú de hoy ━━*")
                etq = {"desayuno": "🍳 Desayuno", "almuerzo": "🍽️ Almuerzo",
                       "comida": "🌙 Comida", "snack": "🍎 Snack"}
                for momento in ("desayuno", "almuerzo", "comida", "snack"):
                    if comida.get(momento):
                        partes.append(f"{etq[momento]}: {comida[momento]}")
        except Exception as e:
            print(f"⚠️  Resumen: error leyendo comida: {e}")

        partes.append("\n_Buen día. Que tu energía rinda._ 💪")

        # Reintento: hasta 3 intentos con espera creciente
        mensaje = "\n".join(partes)
        ok = False
        intentos = 0
        for intento in range(3):
            intentos = intento + 1
            ok = telegram_send(mensaje)
            if ok:
                break
            print(f"⚠️  Resumen matutino intento {intentos} falló, reintentando...")
            _time.sleep(15 * (intento + 1))  # 15s, 30s, 45s

        if ok:
            # Marcar como enviado HOY (idempotencia)
            try:
                _db.execute("""
                    INSERT INTO resumen_diario_enviado
                      (fecha, eventos_count, tareas_count, habitos_count, intentos)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (fecha) DO UPDATE SET
                      enviado_at = NOW(),
                      eventos_count = EXCLUDED.eventos_count,
                      tareas_count = EXCLUDED.tareas_count,
                      habitos_count = EXCLUDED.habitos_count,
                      intentos = EXCLUDED.intentos
                """, (hoy_check, len(eventos_hoy), len(tareas_hoy),
                      len([h for h in (cargar('habitos.json').get('habitos') or [])
                           if h.get('activo', True)]), intentos))
                print(f"☀️  Resumen matutino enviado y registrado: "
                      f"{len(eventos_hoy)} eventos, {len(tareas_hoy)} tareas "
                      f"(intento {intentos}/3)")
            except Exception as e:
                print(f"⚠️  Resumen enviado pero no se pudo registrar en DB: {e}")
        else:
            print(f"❌ Resumen matutino FALLÓ tras 3 intentos. Telegram no respondió.")
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"⚠️  Error en resumen matutino: {e}")


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
        _enrutar(
            info.get("persona_id"),
            "Nueva reunión agendada",
            f"{info['titulo']} · {fecha} {rango}",
            url="/tablero/agenda.html",
            tag=f"nuevo_{info.get('titulo','')[:20]}",
            telegram_texto=texto,
        )
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

    cuerpo = f"{payload['titulo']} · {hora_ini}" + (f"–{hora_fin}" if hora_fin else "")
    _enrutar(
        payload.get("persona_id"),
        f"En {min_restantes} min",
        cuerpo,
        url=payload.get("meet_link") or "/tablero/agenda.html",
        tag=f"ev_{payload.get('uid','')[:24]}",
        telegram_texto=texto,
    )
    try:
        _db.execute(
            "INSERT INTO eventos_avisados (evento_uid, inicio, tipo_aviso) VALUES (%s,%s,%s) "
            "ON CONFLICT DO NOTHING",
            (payload["uid"], inicio, "pre_10min")
        )
    except Exception as e:
        print(f"⚠️  No se pudo marcar avisado: {e}")
