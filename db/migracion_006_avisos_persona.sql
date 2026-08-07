-- 🔔 Migración 006: Fase 2 — avisos por persona
-- Dueño (persona) en calendarios y recordatorios, para enrutar los avisos.
-- Fecha: 2026-08-07

SET search_path TO organizador;

ALTER TABLE calendarios   ADD COLUMN IF NOT EXISTS persona_id TEXT;
ALTER TABLE recordatorios ADD COLUMN IF NOT EXISTS persona_id TEXT;

CREATE INDEX IF NOT EXISTS idx_calendarios_persona ON calendarios(persona_id);
