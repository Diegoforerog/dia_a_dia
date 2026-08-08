"""Aprovisionamiento automático de la base de datos al arrancar.

Se activa con BOOTSTRAP_DB=1. Es idempotente y seguro de correr en cada boot:

1. Si la base DB_NAME no existe en el servidor DB_HOST → la crea
   (conectándose a la base de mantenimiento DB_BOOTSTRAP_DB, default 'postgres',
   con fallback a la base propia del servicio, p. ej. 'puercaton').
2. Crea el esquema: corre db/schema.sql + db/migracion_*.sql en orden,
   SOLO cuando el esquema 'organizador' aún no existe (BD fresca).
3. Importación única de datos: si MIGRAR_DESDE_HOST está definido y las
   tablas destino están vacías, copia los datos del esquema organizador
   del Postgres viejo (por red interna; no requiere exponer puertos).

Pensado para mudanzas de VPS/servicio sin pasos manuales.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Traza del último bootstrap (la expone /api/db/diag para diagnóstico remoto)
TRAZA = []


def _t(msg):
    TRAZA.append(str(msg)[:300])
    print(f"[bootstrap] {msg}")


def _conn(host, port, user, password, dbname):
    import psycopg2
    c = psycopg2.connect(host=host, port=int(port), user=user,
                         password=password, dbname=dbname, connect_timeout=10)
    c.autocommit = True
    return c




def ejecutar():
    if os.environ.get("BOOTSTRAP_DB") != "1":
        return
    host = os.environ.get("DB_HOST")
    if not host:
        print("⚠️  BOOTSTRAP_DB=1 pero falta DB_HOST — omito")
        return
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "postgres")
    pwd = os.environ.get("DB_PASSWORD", "")
    dbname = os.environ.get("DB_NAME", "dia_a_dia")

    # ── 1. Crear la base si no existe ──
    base_admin = None
    for candidata in [os.environ.get("DB_BOOTSTRAP_DB", "postgres"), "puercaton", dbname]:
        try:
            base_admin = _conn(host, port, user, pwd, candidata)
            break
        except Exception:
            continue
    if base_admin is None:
        _t(f"⚠️  Bootstrap: no pude conectar a {host}:{port} — omito")
        return
    cur = base_admin.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{dbname}"')
        _t(f"✓ Bootstrap: base «{dbname}» creada en {host}")
    cur.close(); base_admin.close()

    conn = _conn(host, port, user, pwd, dbname)
    cur = conn.cursor()
    # Lock consultivo: si hay varios workers, solo uno hace el bootstrap
    cur.execute("SELECT pg_try_advisory_lock(772026)")
    if not cur.fetchone()[0]:
        _t("⏭️  Bootstrap: otro proceso lo está haciendo")
        conn.close(); return

    try:
        # ── 2. Esquema (si falta la tabla ancla, correr TODO de nuevo —
        # auto-sanador si un intento anterior quedó a medias) ──
        cur.execute("CREATE SCHEMA IF NOT EXISTS organizador")
        cur.execute("SET search_path TO organizador, public")
        cur.execute("""SELECT 1 FROM information_schema.tables
                       WHERE table_schema='organizador' AND table_name='clientes'""")
        if cur.fetchone():
            _t("⏭️  Bootstrap: esquema ya completo")
        else:
            archivos = [RAIZ / "db" / "schema.sql"] + sorted((RAIZ / "db").glob("migracion_*.sql"))
            _t(f"Bootstrap: creando esquema con {len(archivos)} archivos…")
            for f in archivos:
                # Cada archivo se ejecuta COMPLETO (multi-sentencia). En una BD
                # fresca la secuencia corre limpia; si un archivo falla se
                # registra y se sigue con el siguiente.
                try:
                    cur.execute(f.read_text())
                    _t(f"  ✓ {f.name}")
                except Exception as e:
                    _t(f"  ⚠️ {f.name}: {str(e).splitlines()[0]}")
                # Los archivos pueden cambiar el search_path — lo restauramos
                cur.execute("SET search_path TO organizador, public")
            _t("✓ Bootstrap: esquema creado")

        # ── 2b. Tablas de runtime del scheduler (las crea él también, pero
        # las necesitamos ANTES de importar para no perder su historial) ──
        cur.execute("SET search_path TO organizador")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS eventos_conocidos (
                uid TEXT NOT NULL, inicio TIMESTAMPTZ NOT NULL,
                titulo TEXT, fin TIMESTAMPTZ, calendario TEXT, cliente TEXT,
                ubicacion TEXT, organizador TEXT, html_link TEXT, meet_link TEXT,
                visto_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (uid, inicio))""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS resumen_diario_enviado (
                fecha DATE PRIMARY KEY, enviado_at TIMESTAMPTZ DEFAULT NOW(),
                eventos_count INT DEFAULT 0, tareas_count INT DEFAULT 0,
                habitos_count INT DEFAULT 0, intentos INT DEFAULT 1)""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS eventos_avisados (
                id SERIAL PRIMARY KEY, evento_uid TEXT NOT NULL,
                inicio TIMESTAMPTZ NOT NULL, tipo_aviso TEXT NOT NULL DEFAULT 'pre_10min',
                avisado_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (evento_uid, inicio, tipo_aviso))""")

        # ── 2c. Columnas nuevas idempotentes (corre en cada boot; cubre BD ya
        # existente donde no se re-ejecutan las migraciones de esquema) ──
        for alter in [
            "ALTER TABLE calendarios   ADD COLUMN IF NOT EXISTS persona_id TEXT",
            "ALTER TABLE recordatorios ADD COLUMN IF NOT EXISTS persona_id TEXT",
            "ALTER TABLE habitos ADD COLUMN IF NOT EXISTS alcance TEXT DEFAULT 'personal'",
            "ALTER TABLE habitos ADD COLUMN IF NOT EXISTS persona_id TEXT",
            "ALTER TABLE personas ADD COLUMN IF NOT EXISTS pass_hash TEXT",
            "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS responsable_id TEXT",
            "ALTER TABLE gastos ADD COLUMN IF NOT EXISTS tipo TEXT DEFAULT 'gasto'",
        ]:
            try:
                cur.execute(alter)
            except Exception as e:
                _t(f"⚠️  columna: {str(e).splitlines()[0]}")

        # ── 2d. Tablas de módulos nuevos (Fase 4 comidas), idempotente ──
        for ddl in [
            """CREATE TABLE IF NOT EXISTS recetas (
                id TEXT PRIMARY KEY, nombre TEXT NOT NULL, tipo TEXT DEFAULT 'almuerzo',
                gustos JSONB DEFAULT '[]'::jsonb, ingredientes JSONB DEFAULT '[]'::jsonb,
                pasos TEXT DEFAULT '', favorita BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS menus (
                semana TEXT PRIMARY KEY, dias JSONB DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS despensa (
                id TEXT PRIMARY KEY, item TEXT NOT NULL, unidad TEXT DEFAULT '',
                estado TEXT DEFAULT 'hay', categoria TEXT DEFAULT '',
                updated_at TIMESTAMPTZ DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS lista_mercado (
                id TEXT PRIMARY KEY, item TEXT NOT NULL, cantidad TEXT DEFAULT '',
                unidad TEXT DEFAULT '', origen TEXT DEFAULT 'manual',
                comprado BOOLEAN DEFAULT FALSE, created_at TIMESTAMPTZ DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS sprints (
                semana TEXT PRIMARY KEY, lema TEXT DEFAULT '', metas JSONB DEFAULT '[]'::jsonb,
                cerrado BOOLEAN DEFAULT FALSE, updated_at TIMESTAMPTZ DEFAULT NOW())""",
            """CREATE TABLE IF NOT EXISTS gastos (
                id TEXT PRIMARY KEY, fecha DATE, descripcion TEXT NOT NULL,
                monto DOUBLE PRECISION DEFAULT 0, categoria TEXT DEFAULT '',
                pagado_por TEXT, participacion TEXT DEFAULT 'ambos',
                tipo TEXT DEFAULT 'gasto',
                created_at TIMESTAMPTZ DEFAULT NOW())""",
        ]:
            try:
                cur.execute(ddl)
            except Exception as e:
                _t(f"⚠️  tabla módulo: {str(e).splitlines()[0]}")

        # ── 3. Importar datos del Postgres viejo (por tabla: solo si está vacía) ──
        viejo_host = os.environ.get("MIGRAR_DESDE_HOST", "")
        if viejo_host:
            _importar_datos(cur, viejo_host)
    except Exception as e:
        import traceback
        _t(f"💥 Bootstrap: {type(e).__name__}: {e}")
        _t(traceback.format_exc()[-280:])
    finally:
        cur.execute("SELECT pg_advisory_unlock(772026)")
        cur.close(); conn.close()


def _importar_datos(cur_destino, viejo_host):
    """Copia todas las tablas del esquema organizador del PG viejo, mapeando
    solo las columnas que existen en ambos lados."""
    viejo = _conn(
        viejo_host,
        os.environ.get("MIGRAR_DESDE_PORT", "5432"),
        os.environ.get("MIGRAR_DESDE_USER", os.environ.get("DB_USER", "postgres")),
        os.environ.get("MIGRAR_DESDE_PASSWORD", os.environ.get("DB_PASSWORD", "")),
        os.environ.get("MIGRAR_DESDE_DB", "nextgen"),
    )
    vc = viejo.cursor()
    vc.execute("""SELECT table_name FROM information_schema.tables
                  WHERE table_schema='organizador' AND table_type='BASE TABLE'""")
    tablas = [r[0] for r in vc.fetchall()]

    def columnas(cur, tabla):
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema='organizador' AND table_name=%s""", (tabla,))
        return [r[0] for r in cur.fetchall()]

    # Orden: primero las tablas sin dependencias (clientes antes que proyectos, etc.)
    orden_pref = ["clientes", "empresas", "personas", "proyectos", "epicas", "historias",
                  "actividades", "habito_categorias", "habitos", "habitos_registros",
                  "calendarios", "eventos_cache", "planes_diarios", "tareas_completadas_dia",
                  "configuracion", "recordatorios", "eventos_conocidos", "eventos_avisados",
                  "resumen_diario_enviado"]
    tablas.sort(key=lambda t: orden_pref.index(t) if t in orden_pref else 99)

    from psycopg2.extras import Json

    total = 0
    for t in tablas:
        try:
            cols_v = set(columnas(vc, t))
            cols_d = columnas(cur_destino, t)
            if not cols_d:
                # La tabla no existe en destino (la crea el scheduler después)
                continue
            # Gate por tabla: si ya tiene filas, no re-importar
            cur_destino.execute(f'SELECT COUNT(*) FROM organizador."{t}"')
            if cur_destino.fetchone()[0] > 0:
                continue
            comunes = [c for c in cols_d if c in cols_v]
            if not comunes:
                continue
            collist = ",".join(f'"{c}"' for c in comunes)
            vc.execute(f'SELECT {collist} FROM organizador."{t}"')
            filas = vc.fetchall()
            if not filas:
                continue
            ph = ",".join(["%s"] * len(comunes))
            copiadas = 0
            for fila in filas:
                # dict/list (columnas json/jsonb) necesitan el adaptador Json
                valores = [Json(v) if isinstance(v, (dict, list)) else v for v in fila]
                try:
                    cur_destino.execute(
                        f'INSERT INTO organizador."{t}" ({collist}) VALUES ({ph}) ON CONFLICT DO NOTHING',
                        valores)
                    copiadas += 1
                except Exception as e:
                    _t(f"⚠️  fila en {t}: {str(e).splitlines()[0]}")
            total += copiadas
            _t(f"  ↳ {t}: {copiadas}/{len(filas)} filas")
        except Exception as e:
            _t(f"⚠️  tabla {t}: {str(e).splitlines()[0]}")
    vc.close(); viejo.close()
    _t(f"✓ Bootstrap: importadas ~{total} filas desde {viejo_host}")
