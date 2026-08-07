-- 🚀 Migración 005: Día a día PRO — Fase 0 + 1
-- Personas (pareja) + Proyectos estilo SCRUM (épicas → historias → subtareas)
-- Fecha: 2026-08-07
--
-- Nota de diseño: el JSON local es la fuente de verdad y estas tablas son el
-- espejo (patrón cargar/guardar). Por eso epica_id / responsable_id son TEXT
-- sin FK — evita fallos de orden de sincronización entre archivos.

SET search_path TO organizador;

-- ============================================================
-- 👤 PERSONAS (Diego + Esposa; ligero, sin roles)
-- ============================================================
CREATE TABLE IF NOT EXISTS personas (
    id                  TEXT PRIMARY KEY,
    nombre              TEXT NOT NULL,
    color               TEXT DEFAULT '#2563EB',
    emoji               TEXT DEFAULT '',
    activo              BOOLEAN DEFAULT TRUE,
    telegram_chat_id    TEXT DEFAULT '',
    push_subscriptions  JSONB DEFAULT '[]'::jsonb,
    orden               INT DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- 📦 ÉPICAS (fases dentro de un proyecto)
-- ============================================================
CREATE TABLE IF NOT EXISTS epicas (
    id              TEXT PRIMARY KEY,
    proyecto_id     TEXT NOT NULL,
    titulo          TEXT NOT NULL,
    descripcion     TEXT DEFAULT '',
    prioridad       TEXT DEFAULT 'media',
    estado          TEXT DEFAULT 'abierta' CHECK (estado IN ('abierta','en_progreso','hecha')),
    orden           INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_epicas_proyecto ON epicas(proyecto_id);

-- ============================================================
-- 🗂️ HISTORIAS (tarjetas del canvas Kanban)
--    subtareas y criterios viven DENTRO de la historia (JSONB)
-- ============================================================
CREATE TABLE IF NOT EXISTS historias (
    id               TEXT PRIMARY KEY,
    proyecto_id      TEXT NOT NULL,
    epica_id         TEXT,
    titulo           TEXT NOT NULL,
    descripcion      TEXT DEFAULT '',
    responsable_id   TEXT,
    prioridad        TEXT DEFAULT 'media' CHECK (prioridad IN ('baja','media','alta','critica')),
    estado           TEXT DEFAULT 'backlog' CHECK (estado IN ('backlog','planeado','en_progreso','qa','bloqueado','hecho')),
    etiquetas        JSONB DEFAULT '[]'::jsonb,
    estimacion_horas REAL,
    fecha_objetivo   DATE,
    motivo_bloqueo   TEXT DEFAULT '',
    criterios        JSONB DEFAULT '[]'::jsonb,   -- [{texto, hecho}]
    subtareas        JSONB DEFAULT '[]'::jsonb,   -- [{id, titulo, hecho, responsable_id}]
    origen           TEXT DEFAULT '',             -- ej. 'actividad:tarea_x' si vino de la migración
    orden            INT DEFAULT 0,
    creada           TIMESTAMPTZ DEFAULT NOW(),
    completada_en    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_historias_proyecto ON historias(proyecto_id);
CREATE INDEX IF NOT EXISTS idx_historias_estado ON historias(estado);
