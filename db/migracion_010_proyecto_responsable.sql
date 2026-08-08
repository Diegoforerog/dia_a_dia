-- 👥 Migración 010: responsable por proyecto (persona | 'ambos' | null)
-- Los clientes son compartidos; la responsabilidad se asigna por proyecto y por historia.
-- Fecha: 2026-08-08

SET search_path TO organizador;

ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS responsable_id TEXT;
