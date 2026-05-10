"""Lee eventos de tus calendarios de Gmail (solo lectura) y los inyecta
como bloques fijos en el registro del día, para que el planificador IA
los respete.

Requisitos:
  pip install google-auth google-auth-oauthlib google-api-python-client

Setup:
  Ver integraciones/README_google.md

Uso:
  python scripts/leer_google_calendar.py
"""
import os
import json
from datetime import datetime, date, time, timezone, timedelta
from pathlib import Path
from comun import cargar, cargar_registro_dia, guardar_registro_dia, DATOS

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    print("⚠️  Falta instalar:")
    print("    pip install google-auth google-auth-oauthlib google-api-python-client")
    raise SystemExit(1)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
RUTA_CRED = DATOS.parent / "integraciones" / "credentials.json"
RUTA_TOKEN = DATOS.parent / "integraciones" / "token.json"


def obtener_servicio():
    creds = None
    if RUTA_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(RUTA_TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not RUTA_CRED.exists():
                print(f"⚠️  Falta el archivo: {RUTA_CRED}")
                print("    Ver: integraciones/README_google.md")
                raise SystemExit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(RUTA_CRED), SCOPES)
            creds = flow.run_local_server(port=0)
        RUTA_TOKEN.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def leer_eventos_hoy(servicio) -> list:
    cals_config = cargar("calendarios.json")["calendarios_gmail"]
    activos = [c for c in cals_config if c.get("activo")]

    if not activos:
        print("⚠️  Ningún calendario marcado como activo en datos/calendarios.json")
        return []

    inicio = datetime.combine(date.today(), time.min).astimezone()
    fin = datetime.combine(date.today(), time.max).astimezone()

    eventos = []
    for cal in activos:
        try:
            r = servicio.events().list(
                calendarId=cal["email"],
                timeMin=inicio.isoformat(),
                timeMax=fin.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()
            for ev in r.get("items", []):
                start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
                end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
                eventos.append({
                    "id_externo": ev.get("id"),
                    "calendario": cal["nombre_para_mostrar"],
                    "empresa_id": cal.get("empresa_asociada"),
                    "titulo": ev.get("summary", "(sin título)"),
                    "inicio": start,
                    "fin": end,
                    "ubicacion": ev.get("location", ""),
                    "es_evento_fijo": True
                })
        except Exception as e:
            print(f"  ⚠️  Error leyendo {cal['email']}: {e}")
    return eventos


def main() -> None:
    print("📅 Leyendo eventos de hoy desde tus calendarios Gmail...")
    servicio = obtener_servicio()
    eventos = leer_eventos_hoy(servicio)
    print(f"   Encontrados: {len(eventos)} eventos")

    registro = cargar_registro_dia()
    registro["eventos_gmail"] = eventos
    guardar_registro_dia(registro)
    print(f"💾 Guardados en registro del día. El planificador los respetará como bloques fijos.")


if __name__ == "__main__":
    main()
