-- 🏃 Migración 011: Sprint de la semana (ritual de pareja)
-- Un foco + metas por semana ISO; racha = semanas cerradas seguidas.
-- Fecha: 2026-08-08

SET search_path TO organizador;

CREATE TABLE IF NOT EXISTS sprints (
    semana     TEXT PRIMARY KEY,               -- YYYY-Www
    lema       TEXT DEFAULT '',                -- el foco de la semana
    metas      JSONB DEFAULT '[]'::jsonb,       -- [{id, texto, responsable_id, hecha}]
    cerrado    BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
