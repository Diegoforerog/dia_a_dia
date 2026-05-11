-- 🟢🔴 Migración 004: hábitos buenos (quieres hacer) vs malos (quieres evitar)
-- bueno: marca = lo hice ✓ · racha = días consecutivos cumplidos
-- malo:  marca = caí ✗ · racha = días consecutivos SIN caer
SET search_path TO organizador;

ALTER TABLE habitos
  ADD COLUMN IF NOT EXISTS tipo TEXT DEFAULT 'bueno';

ALTER TABLE habitos
  DROP CONSTRAINT IF EXISTS habitos_tipo_check;

ALTER TABLE habitos
  ADD CONSTRAINT habitos_tipo_check CHECK (tipo IN ('bueno','malo'));
