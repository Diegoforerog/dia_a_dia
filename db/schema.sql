-- ============================================================
-- 📅 ORGANIZADOR DE CALENDARIOS - Esquema PostgreSQL
-- ============================================================
-- Tablas para Empresas → Proyectos → Tareas + Hábitos + Calendarios

CREATE SCHEMA IF NOT EXISTS organizador;
SET search_path TO organizador;

-- ============================================================
-- 🏢 EMPRESAS / ÁREAS
-- ============================================================
CREATE TABLE IF NOT EXISTS empresas (
    id              TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    color           TEXT DEFAULT '#888888',
    descripcion     TEXT DEFAULT '',
    activo          BOOLEAN DEFAULT TRUE,
    orden           INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_empresas_activo ON empresas(activo);

-- ============================================================
-- 📁 PROYECTOS
-- ============================================================
CREATE TABLE IF NOT EXISTS proyectos (
    id              TEXT PRIMARY KEY,
    empresa_id      TEXT NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
    nombre          TEXT NOT NULL,
    estado          TEXT DEFAULT 'activo' CHECK (estado IN ('activo','pausado','completado','archivado')),
    prioridad       TEXT DEFAULT 'media' CHECK (prioridad IN ('alta','media','baja')),
    deadline        DATE,
    descripcion     TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_proyectos_empresa ON proyectos(empresa_id);
CREATE INDEX IF NOT EXISTS idx_proyectos_estado ON proyectos(estado);

-- ============================================================
-- 📌 ACTIVIDADES (tareas)
-- ============================================================
CREATE TABLE IF NOT EXISTS actividades (
    id              TEXT PRIMARY KEY,
    empresa_id      TEXT REFERENCES empresas(id) ON DELETE SET NULL,
    proyecto_id     TEXT REFERENCES proyectos(id) ON DELETE SET NULL,
    titulo          TEXT NOT NULL,
    prioridad       TEXT DEFAULT 'media' CHECK (prioridad IN ('alta','media','baja')),
    duracion_min    INT DEFAULT 30,
    deadline        DATE,
    notas           TEXT DEFAULT '',
    estado          TEXT DEFAULT 'pendiente' CHECK (estado IN ('pendiente','en_progreso','completada','descartada')),
    creada          TIMESTAMPTZ DEFAULT NOW(),
    completada_en   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_actividades_estado ON actividades(estado);
CREATE INDEX IF NOT EXISTS idx_actividades_empresa ON actividades(empresa_id);
CREATE INDEX IF NOT EXISTS idx_actividades_deadline ON actividades(deadline);

-- ============================================================
-- 🎯 HÁBITOS - categorías y hábitos
-- ============================================================
CREATE TABLE IF NOT EXISTS habito_categorias (
    id              TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    icono           TEXT DEFAULT '•',
    color           TEXT DEFAULT '#888888'
);

CREATE TABLE IF NOT EXISTS habitos (
    id              TEXT PRIMARY KEY,
    categoria_id    TEXT REFERENCES habito_categorias(id) ON DELETE SET NULL,
    nombre          TEXT NOT NULL,
    frecuencia      TEXT DEFAULT 'diaria' CHECK (frecuencia IN ('diaria','semanal','quincenal','mensual')),
    horario_sugerido TEXT DEFAULT 'mañana',
    duracion_min    INT DEFAULT 15,
    activo          BOOLEAN DEFAULT TRUE,
    racha_actual    INT DEFAULT 0,
    mejor_racha     INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_habitos_activo ON habitos(activo);

-- 1 fila por hábito-día (cuando se marca como cumplido)
CREATE TABLE IF NOT EXISTS habitos_registros (
    habito_id       TEXT NOT NULL REFERENCES habitos(id) ON DELETE CASCADE,
    fecha           DATE NOT NULL,
    cumplido_at     TIMESTAMPTZ DEFAULT NOW(),
    notas           TEXT DEFAULT '',
    PRIMARY KEY (habito_id, fecha)
);
CREATE INDEX IF NOT EXISTS idx_habitos_reg_fecha ON habitos_registros(fecha);

-- ============================================================
-- 📅 CALENDARIOS (iCal URLs + opcionalmente OAuth)
-- ============================================================
CREATE TABLE IF NOT EXISTS calendarios (
    id                  TEXT PRIMARY KEY,
    email               TEXT DEFAULT '',
    ical_url            TEXT DEFAULT '',
    nombre_para_mostrar TEXT NOT NULL,
    empresa_asociada    TEXT REFERENCES empresas(id) ON DELETE SET NULL,
    color               TEXT DEFAULT '#4ECDC4',
    activo              BOOLEAN DEFAULT TRUE,
    ultimo_sync         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Cache opcional de eventos leídos (para no pegarle al iCal en cada lectura)
CREATE TABLE IF NOT EXISTS eventos_cache (
    id              SERIAL PRIMARY KEY,
    calendario_id   TEXT REFERENCES calendarios(id) ON DELETE CASCADE,
    id_externo      TEXT,
    titulo          TEXT,
    inicio          TIMESTAMPTZ,
    fin             TIMESTAMPTZ,
    ubicacion       TEXT,
    descripcion     TEXT,
    sync_at         TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (calendario_id, id_externo)
);
CREATE INDEX IF NOT EXISTS idx_eventos_cal_inicio ON eventos_cache(calendario_id, inicio);

-- ============================================================
-- 📊 PLANES DIARIOS (lo que la IA arma cada día)
-- ============================================================
CREATE TABLE IF NOT EXISTS planes_diarios (
    fecha           DATE PRIMARY KEY,
    plan_generado   JSONB,
    aprobado        BOOLEAN DEFAULT FALSE,
    cerrado         BOOLEAN DEFAULT FALSE,
    notas           TEXT DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Tareas completadas en cada día (puede ser una tarea recurrente o cumplimiento del día)
CREATE TABLE IF NOT EXISTS tareas_completadas_dia (
    fecha           DATE NOT NULL,
    tarea_id        TEXT NOT NULL REFERENCES actividades(id) ON DELETE CASCADE,
    completada_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (fecha, tarea_id)
);

-- ============================================================
-- ⚙️ CONFIGURACIÓN (key-value flexible)
-- ============================================================
CREATE TABLE IF NOT EXISTS configuracion (
    clave           TEXT PRIMARY KEY,
    valor           JSONB NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 🔄 TRIGGER auto-update de updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION organizador.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t TEXT;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'organizador'
               AND tablename IN ('empresas','proyectos','planes_diarios')
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS trg_%I_updated ON organizador.%I;
            CREATE TRIGGER trg_%I_updated
            BEFORE UPDATE ON organizador.%I
            FOR EACH ROW EXECUTE FUNCTION organizador.set_updated_at();
        ', t, t, t, t);
    END LOOP;
END $$;

-- ============================================================
-- ✅ FIN
-- ============================================================
