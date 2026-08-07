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
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _conn(host, port, user, password, dbname):
    import psycopg2
    c = psycopg2.connect(host=host, port=int(port), user=user,
                         password=password, dbname=dbname, connect_timeout=10)
    c.autocommit = True
    return c


def _split_sql(texto: str):
    """Divide un .sql en sentencias respetando bloques $$...$$ (plpgsql)."""
    stmts, actual, en_dolar = [], [], False
    for linea in texto.splitlines():
        sin_comentario = linea.split("--")[0] if not en_dolar else linea
        actual.append(linea)
        for _ in re.findall(r"\$\$", sin_comentario):
            en_dolar = not en_dolar
        if not en_dolar and sin_comentario.rstrip().endswith(";"):
            stmt = "\n".join(actual).strip()
            if stmt and not stmt.startswith("--"):
                stmts.append(stmt)
            actual = []
    resto = "\n".join(actual).strip()
    if resto and not resto.startswith("--"):
        stmts.append(resto)
    return stmts


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
        print(f"⚠️  Bootstrap: no pude conectar a {host}:{port} — omito")
        return
    cur = base_admin.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{dbname}"')
        print(f"✓ Bootstrap: base «{dbname}» creada en {host}")
    cur.close(); base_admin.close()

    conn = _conn(host, port, user, pwd, dbname)
    cur = conn.cursor()
    # Lock consultivo: si hay varios workers, solo uno hace el bootstrap
    cur.execute("SELECT pg_try_advisory_lock(772026)")
    if not cur.fetchone()[0]:
        print("⏭️  Bootstrap: otro proceso lo está haciendo")
        conn.close(); return

    try:
        # ── 2. Esquema (solo en BD fresca) ──
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name='organizador'")
        if not cur.fetchone():
            archivos = [RAIZ / "db" / "schema.sql"] + sorted((RAIZ / "db").glob("migracion_*.sql"))
            for f in archivos:
                for stmt in _split_sql(f.read_text()):
                    try:
                        cur.execute(stmt)
                    except Exception as e:
                        print(f"⚠️  Bootstrap {f.name}: {str(e).splitlines()[0]}")
            print(f"✓ Bootstrap: esquema creado ({len(archivos)} archivos SQL)")

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

        # ── 3. Importar datos del Postgres viejo (una sola vez) ──
        viejo_host = os.environ.get("MIGRAR_DESDE_HOST", "")
        if viejo_host:
            cur.execute("SELECT COUNT(*) FROM organizador.clientes")
            if cur.fetchone()[0] == 0:
                _importar_datos(cur, viejo_host)
            else:
                print("⏭️  Bootstrap: ya hay datos — no importo de nuevo")
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

    total = 0
    for t in tablas:
        try:
            cols_v = set(columnas(vc, t))
            cols_d = columnas(cur_destino, t)
            if not cols_d:
                # La tabla no existe en destino (la crea el scheduler después) → crear copia
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
            for fila in filas:
                try:
                    cur_destino.execute(
                        f'INSERT INTO organizador."{t}" ({collist}) VALUES ({ph}) ON CONFLICT DO NOTHING',
                        fila)
                except Exception as e:
                    print(f"⚠️  fila en {t}: {str(e).splitlines()[0]}")
            total += len(filas)
            print(f"  ↳ {t}: {len(filas)} filas")
        except Exception as e:
            print(f"⚠️  tabla {t}: {str(e).splitlines()[0]}")
    vc.close(); viejo.close()
    print(f"✓ Bootstrap: importadas ~{total} filas desde {viejo_host}")
