"""Migra los datos actuales de archivos JSON a PostgreSQL.

Idempotente: usa ON CONFLICT DO NOTHING para que se pueda correr varias veces.

Uso:
  python3 db/migrar_json_a_db.py
"""
import json
import os
import sys
from pathlib import Path

# Permitir importar comun.py
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
from comun import cargar_env, DATOS, REGISTROS
cargar_env()

try:
    import psycopg2
    from psycopg2.extras import Json
except ImportError:
    print("Falta: pip install psycopg2-binary")
    raise SystemExit(1)


def conectar():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"]
    )


def cargar_json(nombre):
    f = DATOS / nombre
    return json.loads(f.read_text()) if f.exists() else {}


def main():
    conn = conectar()
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET search_path TO organizador, public")

    # --- EMPRESAS ---
    empresas = cargar_json("empresas.json").get("empresas", [])
    for e in empresas:
        cur.execute("""
            INSERT INTO empresas (id, nombre, color, descripcion, activo)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              nombre=EXCLUDED.nombre, color=EXCLUDED.color,
              descripcion=EXCLUDED.descripcion, activo=EXCLUDED.activo
        """, (e["id"], e["nombre"], e.get("color","#888888"),
              e.get("descripcion",""), e.get("activo", True)))
    print(f"  ✅ Empresas: {len(empresas)}")

    # --- PROYECTOS ---
    proyectos = cargar_json("proyectos.json").get("proyectos", [])
    for p in proyectos:
        cur.execute("""
            INSERT INTO proyectos (id, empresa_id, nombre, estado, prioridad, deadline, descripcion)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              nombre=EXCLUDED.nombre, estado=EXCLUDED.estado,
              prioridad=EXCLUDED.prioridad, deadline=EXCLUDED.deadline,
              descripcion=EXCLUDED.descripcion
        """, (p["id"], p["empresa_id"], p["nombre"], p.get("estado","activo"),
              p.get("prioridad","media"), p.get("deadline"), p.get("descripcion","")))
    print(f"  ✅ Proyectos: {len(proyectos)}")

    # --- ACTIVIDADES (TAREAS) ---
    tareas = cargar_json("actividades.json").get("actividades", [])
    for t in tareas:
        cur.execute("""
            INSERT INTO actividades
              (id, empresa_id, proyecto_id, titulo, prioridad, duracion_min,
               deadline, notas, estado, creada, completada_en)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO NOTHING
        """, (t["id"], t.get("empresa_id"), t.get("proyecto_id"), t["titulo"],
              t.get("prioridad","media"), t.get("duracion_min",30),
              t.get("deadline"), t.get("notas",""), t.get("estado","pendiente"),
              t.get("creada"), t.get("completada_en")))
    print(f"  ✅ Tareas: {len(tareas)}")

    # --- HÁBITOS ---
    habitos_data = cargar_json("habitos.json")
    for c in habitos_data.get("categorias", []):
        cur.execute("""
            INSERT INTO habito_categorias (id, nombre, icono, color)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              nombre=EXCLUDED.nombre, icono=EXCLUDED.icono, color=EXCLUDED.color
        """, (c["id"], c["nombre"], c.get("icono","•"), c.get("color","#888888")))

    for h in habitos_data.get("habitos", []):
        cur.execute("""
            INSERT INTO habitos
              (id, categoria_id, nombre, frecuencia, horario_sugerido,
               duracion_min, activo, racha_actual, mejor_racha)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              nombre=EXCLUDED.nombre, frecuencia=EXCLUDED.frecuencia,
              horario_sugerido=EXCLUDED.horario_sugerido,
              duracion_min=EXCLUDED.duracion_min, activo=EXCLUDED.activo,
              racha_actual=EXCLUDED.racha_actual, mejor_racha=EXCLUDED.mejor_racha
        """, (h["id"], h.get("categoria_id"), h["nombre"],
              h.get("frecuencia","diaria"), h.get("horario_sugerido","mañana"),
              h.get("duracion_min",15), h.get("activo", True),
              h.get("racha_actual",0), h.get("mejor_racha",0)))
    print(f"  ✅ Categorías hábitos: {len(habitos_data.get('categorias', []))}")
    print(f"  ✅ Hábitos: {len(habitos_data.get('habitos', []))}")

    # --- CALENDARIOS ---
    cals = cargar_json("calendarios.json").get("calendarios_gmail", [])
    for c in cals:
        cur.execute("""
            INSERT INTO calendarios
              (id, email, ical_url, nombre_para_mostrar, empresa_asociada, color, activo)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
              email=EXCLUDED.email, ical_url=EXCLUDED.ical_url,
              nombre_para_mostrar=EXCLUDED.nombre_para_mostrar,
              empresa_asociada=EXCLUDED.empresa_asociada,
              color=EXCLUDED.color, activo=EXCLUDED.activo
        """, (c["id"], c.get("email",""), c.get("ical_url",""),
              c.get("nombre_para_mostrar", c.get("email","")),
              c.get("empresa_asociada"), c.get("color","#4ECDC4"),
              c.get("activo", True)))
    print(f"  ✅ Calendarios: {len(cals)}")

    # --- CONFIG ---
    config = cargar_json("config.json")
    for clave, valor in config.items():
        cur.execute("""
            INSERT INTO configuracion (clave, valor)
            VALUES (%s, %s)
            ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor, updated_at=NOW()
        """, (clave, Json(valor)))
    print(f"  ✅ Config: {len(config)} claves")

    # --- REGISTROS DIARIOS ---
    if REGISTROS.exists():
        contador = 0
        for f in sorted(REGISTROS.glob("*.json")):
            r = json.loads(f.read_text())
            cur.execute("""
                INSERT INTO planes_diarios (fecha, plan_generado, aprobado, cerrado, notas)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (fecha) DO UPDATE SET
                  plan_generado=EXCLUDED.plan_generado,
                  aprobado=EXCLUDED.aprobado, cerrado=EXCLUDED.cerrado,
                  notas=EXCLUDED.notas, updated_at=NOW()
            """, (r["fecha"], Json(r.get("plan_generado")) if r.get("plan_generado") else None,
                  r.get("aprobado", False), r.get("cerrado", False), r.get("notas","")))
            # Tareas completadas del día
            for tid in r.get("tareas_completadas", []):
                cur.execute("""
                    INSERT INTO tareas_completadas_dia (fecha, tarea_id)
                    VALUES (%s,%s) ON CONFLICT DO NOTHING
                """, (r["fecha"], tid))
            # Hábitos cumplidos
            for hid in r.get("habitos_cumplidos", []):
                cur.execute("""
                    INSERT INTO habitos_registros (habito_id, fecha)
                    VALUES (%s,%s) ON CONFLICT DO NOTHING
                """, (hid, r["fecha"]))
            contador += 1
        print(f"  ✅ Registros diarios: {contador}")

    conn.commit()
    cur.close()
    conn.close()
    print("\n🎉 Migración completa")


if __name__ == "__main__":
    main()
