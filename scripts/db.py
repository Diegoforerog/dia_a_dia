"""Capa de acceso a PostgreSQL — mantiene compatibilidad con la interfaz de cargar/guardar JSON.

Estrategia:
  cargar('empresas.json')   → SELECT * FROM empresas      → devuelve {"empresas": [...]}
  guardar('empresas.json',{...}) → UPSERT + DELETE faltantes
  cargar_registro_dia()     → JOIN planes_diarios + tareas + hábitos
"""
import os
import json
import threading
from datetime import date, datetime
from typing import Optional, List, Dict, Any

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
    DISPONIBLE = True
except ImportError:
    DISPONIBLE = False

_local = threading.local()


def db_disponible() -> bool:
    if not DISPONIBLE:
        return False
    return all(os.environ.get(v) for v in ["DB_HOST","DB_USER","DB_PASSWORD","DB_NAME"])


def _get_conn():
    """Conexión thread-local; reconecta si se cayó."""
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed:
        conn = psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", 5432)),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            dbname=os.environ["DB_NAME"],
            connect_timeout=10
        )
        conn.autocommit = True
        _local.conn = conn
    return conn


def _cursor():
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SET search_path TO organizador, public")
    return cur


def query(sql: str, params=None) -> List[Dict]:
    cur = _cursor()
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    return rows


def query_one(sql: str, params=None) -> Optional[Dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=None) -> None:
    cur = _cursor()
    cur.execute(sql, params)
    cur.close()


def _serial(v):
    """Convierte tipos no-JSON (date, datetime) a string."""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _row_to_dict(row: Dict) -> Dict:
    return {k: _serial(v) for k, v in row.items()}


# ============================================================
# CARGAR — devuelve dicts con el mismo shape que los JSON antiguos
# ============================================================

def cargar(nombre_archivo: str) -> Dict:
    # Acepta tanto "clientes.json" como el antiguo "empresas.json"
    if nombre_archivo in ("clientes.json", "empresas.json"):
        rows = query("SELECT id, nombre, color, descripcion, activo FROM clientes ORDER BY orden, nombre")
        return {"clientes": [_row_to_dict(r) for r in rows]}

    if nombre_archivo == "proyectos.json":
        rows = query("""SELECT id, cliente_id, nombre, estado, prioridad, deadline, descripcion
                        FROM proyectos ORDER BY created_at""")
        return {"proyectos": [_row_to_dict(r) for r in rows]}

    if nombre_archivo == "actividades.json":
        rows = query("""SELECT id, cliente_id, proyecto_id, titulo, prioridad,
                               duracion_min, deadline, notas, estado, creada, completada_en
                        FROM actividades ORDER BY creada DESC""")
        return {"actividades": [_row_to_dict(r) for r in rows]}

    if nombre_archivo == "habitos.json":
        cats = query("SELECT id, nombre, icono, color FROM habito_categorias ORDER BY nombre")
        habs = query("""SELECT id, categoria_id, nombre, frecuencia, horario_sugerido,
                               duracion_min, activo, racha_actual, mejor_racha, dias, tipo
                        FROM habitos ORDER BY created_at""")
        return {
            "categorias": [_row_to_dict(c) for c in cats],
            "habitos": [_row_to_dict(h) for h in habs]
        }

    if nombre_archivo == "calendarios.json":
        rows = query("""SELECT id, email, ical_url, nombre_para_mostrar, cliente_asociado, color, activo
                        FROM calendarios ORDER BY nombre_para_mostrar""")
        return {"calendarios_gmail": [_row_to_dict(r) for r in rows]}

    if nombre_archivo == "config.json":
        rows = query("SELECT clave, valor FROM configuracion")
        return {r["clave"]: r["valor"] for r in rows}

    if nombre_archivo == "recordatorios.json":
        rows = query("""SELECT id, titulo, mensaje, fecha_hora, repetir, cliente_id,
                               enviado, enviado_at, activo, creado_at
                        FROM recordatorios ORDER BY fecha_hora DESC""")
        return {"recordatorios": [_row_to_dict(r) for r in rows]}

    return {}


# ============================================================
# GUARDAR — sincroniza listas completas (upsert + delete faltantes)
# ============================================================

def _sync_lista(tabla: str, items: List[Dict], columnas: List[str], pk: str = "id"):
    """Upsert de cada item + DELETE de los ids que ya no están."""
    if not items:
        execute(f"DELETE FROM {tabla}")
        return
    ids_actuales = [i[pk] for i in items]
    placeholders = ",".join(["%s"] * len(ids_actuales))
    execute(f"DELETE FROM {tabla} WHERE {pk} NOT IN ({placeholders})", ids_actuales)
    cols = ",".join(columnas)
    vals_placeholder = ",".join(["%s"] * len(columnas))
    update_set = ",".join([f"{c}=EXCLUDED.{c}" for c in columnas if c != pk])
    for it in items:
        valores = [it.get(c) for c in columnas]
        sql = f"""INSERT INTO {tabla} ({cols}) VALUES ({vals_placeholder})
                  ON CONFLICT ({pk}) DO UPDATE SET {update_set}"""
        execute(sql, valores)


def guardar(nombre_archivo: str, datos: Dict) -> None:
    if nombre_archivo in ("clientes.json", "empresas.json"):
        # Soporta tanto la key nueva 'clientes' como la vieja 'empresas'
        lista = datos.get("clientes") or datos.get("empresas") or []
        _sync_lista("clientes", lista,
                    ["id","nombre","color","descripcion","activo"])
        return

    if nombre_archivo == "proyectos.json":
        _sync_lista("proyectos", datos.get("proyectos", []),
                    ["id","cliente_id","nombre","estado","prioridad","deadline","descripcion"])
        return

    if nombre_archivo == "actividades.json":
        _sync_lista("actividades", datos.get("actividades", []),
                    ["id","cliente_id","proyecto_id","titulo","prioridad",
                     "duracion_min","deadline","notas","estado","creada","completada_en"])
        return

    if nombre_archivo == "habitos.json":
        _sync_lista("habito_categorias", datos.get("categorias", []),
                    ["id","nombre","icono","color"])
        _sync_lista("habitos", datos.get("habitos", []),
                    ["id","categoria_id","nombre","frecuencia","horario_sugerido",
                     "duracion_min","activo","racha_actual","mejor_racha","dias","tipo"])
        return

    if nombre_archivo == "calendarios.json":
        _sync_lista("calendarios", datos.get("calendarios_gmail", []),
                    ["id","email","ical_url","nombre_para_mostrar",
                     "cliente_asociado","color","activo"])
        return

    if nombre_archivo == "config.json":
        execute("DELETE FROM configuracion")
        for clave, valor in datos.items():
            execute("INSERT INTO configuracion (clave, valor) VALUES (%s,%s)",
                    (clave, Json(valor)))
        return

    if nombre_archivo == "recordatorios.json":
        _sync_lista("recordatorios", datos.get("recordatorios", []),
                    ["id","titulo","mensaje","fecha_hora","repetir","cliente_id",
                     "enviado","enviado_at","activo"])
        return


# ============================================================
# REGISTRO DIARIO (plan + tareas cumplidas + hábitos cumplidos)
# ============================================================

def cargar_registro_dia_db(fecha: Optional[str] = None) -> Dict:
    if fecha is None:
        fecha = date.today().isoformat()
    plan = query_one("SELECT * FROM planes_diarios WHERE fecha=%s", (fecha,))
    tareas = [r["tarea_id"] for r in query(
        "SELECT tarea_id FROM tareas_completadas_dia WHERE fecha=%s", (fecha,))]
    habs = [r["habito_id"] for r in query(
        "SELECT habito_id FROM habitos_registros WHERE fecha=%s", (fecha,))]
    if plan:
        return {
            "fecha": fecha,
            "plan_generado": plan.get("plan_generado"),
            "aprobado": plan.get("aprobado", False),
            "cerrado": plan.get("cerrado", False),
            "notas": plan.get("notas", ""),
            "tareas_completadas": tareas,
            "habitos_cumplidos": habs,
            "tareas_pendientes": []
        }
    return {
        "fecha": fecha,
        "plan_generado": None,
        "aprobado": False,
        "cerrado": False,
        "notas": "",
        "tareas_completadas": tareas,
        "habitos_cumplidos": habs,
        "tareas_pendientes": []
    }


def guardar_registro_dia_db(registro: Dict) -> None:
    fecha = registro["fecha"]
    plan = registro.get("plan_generado")
    execute("""
        INSERT INTO planes_diarios (fecha, plan_generado, aprobado, cerrado, notas)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (fecha) DO UPDATE SET
          plan_generado=EXCLUDED.plan_generado,
          aprobado=EXCLUDED.aprobado,
          cerrado=EXCLUDED.cerrado,
          notas=EXCLUDED.notas,
          updated_at=NOW()
    """, (fecha, Json(plan) if plan else None,
          registro.get("aprobado", False), registro.get("cerrado", False),
          registro.get("notas", "")))

    # Sincronizar tareas completadas
    execute("DELETE FROM tareas_completadas_dia WHERE fecha=%s", (fecha,))
    for tid in registro.get("tareas_completadas", []):
        execute("INSERT INTO tareas_completadas_dia (fecha, tarea_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (fecha, tid))

    # Sincronizar hábitos cumplidos
    execute("DELETE FROM habitos_registros WHERE fecha=%s", (fecha,))
    for hid in registro.get("habitos_cumplidos", []):
        execute("INSERT INTO habitos_registros (habito_id, fecha) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (hid, fecha))
