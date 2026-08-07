"""Utilidades compartidas: cargar/guardar JSON, rutas, fechas."""
from __future__ import annotations
import json
import os
from pathlib import Path
from datetime import datetime, date
from typing import Optional

RAIZ = Path(__file__).resolve().parent.parent
DATOS = RAIZ / "datos"
REGISTROS = DATOS / "registros"


def cargar_env():
    """Carga .env del proyecto en os.environ (sin dependencias)."""
    env_file = RAIZ / ".env"
    if not env_file.exists():
        return
    for linea in env_file.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip())


cargar_env()


# Capa de DB con fallback a JSON
try:
    import db as _db
    _USAR_DB = _db.db_disponible()
except Exception:
    _USAR_DB = False
    _db = None


def cargar(nombre_archivo: str) -> dict:
    if _USAR_DB:
        try:
            return _db.cargar(nombre_archivo)
        except Exception as e:
            print(f"⚠️  DB fallback a JSON ({nombre_archivo}): {e}")
    ruta = DATOS / nombre_archivo
    if not ruta.exists():
        return {}
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar(nombre_archivo: str, datos: dict) -> None:
    if _USAR_DB:
        try:
            _db.guardar(nombre_archivo, datos)
        except Exception as e:
            print(f"⚠️  DB falló al guardar ({nombre_archivo}): {e}")
    # Guardamos siempre también el JSON como respaldo local
    ruta = DATOS / nombre_archivo
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2, default=str)


def cargar_registro_dia(fecha: Optional[str] = None) -> dict:
    if _USAR_DB:
        try:
            return _db.cargar_registro_dia_db(fecha)
        except Exception as e:
            print(f"⚠️  DB fallback a JSON (registro): {e}")
    if fecha is None:
        fecha = date.today().isoformat()
    ruta = REGISTROS / f"{fecha}.json"
    if not ruta.exists():
        return {
            "fecha": fecha,
            "plan_generado": None,
            "tareas_completadas": [],
            "tareas_pendientes": [],
            "habitos_cumplidos": [],
            "notas": "",
            "cerrado": False
        }
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_registro_dia(registro: dict) -> None:
    if _USAR_DB:
        try:
            _db.guardar_registro_dia_db(registro)
        except Exception as e:
            print(f"⚠️  DB falló al guardar registro: {e}")
    fecha = registro["fecha"]
    REGISTROS.mkdir(parents=True, exist_ok=True)
    ruta = REGISTROS / f"{fecha}.json"
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(registro, f, ensure_ascii=False, indent=2, default=str)


def nuevo_id(prefijo: str) -> str:
    # Sufijo aleatorio para evitar colisiones cuando se generan varios ids
    # en el mismo segundo (p. ej. sembrar el canvas de golpe).
    from secrets import token_hex
    return f"{prefijo}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{token_hex(3)}"
