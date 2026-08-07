-- 🎯 Migración 007: Fase 3 — hábitos mixtos (personales + de pareja)
-- alcance: 'personal' (de una persona, con su racha) o 'pareja' (compartido).
-- Fecha: 2026-08-07

SET search_path TO organizador;

ALTER TABLE habitos ADD COLUMN IF NOT EXISTS alcance    TEXT DEFAULT 'personal';
ALTER TABLE habitos ADD COLUMN IF NOT EXISTS persona_id TEXT;
