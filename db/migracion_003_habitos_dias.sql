-- 🗓️ Migración 003: hábitos con días específicos de la semana
-- dias = INT[] con valores 1..7 (ISO: 1=Lun, 7=Dom). NULL si no aplica.
SET search_path TO organizador;

ALTER TABLE habitos
  ADD COLUMN IF NOT EXISTS dias INT[] DEFAULT NULL;

-- Ampliar enum de frecuencia
ALTER TABLE habitos
  DROP CONSTRAINT IF EXISTS habitos_frecuencia_check;

ALTER TABLE habitos
  ADD CONSTRAINT habitos_frecuencia_check
  CHECK (frecuencia IN ('diaria','semanal','quincenal','mensual','dias_especificos'));
