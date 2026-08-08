-- 🔐 Migración 009: login por persona
-- Cada persona guarda el hash de su contraseña (pbkdf2). Nunca se expone al cliente.
-- Fecha: 2026-08-08

SET search_path TO organizador;

ALTER TABLE personas ADD COLUMN IF NOT EXISTS pass_hash TEXT;
