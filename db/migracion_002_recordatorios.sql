-- 🔔 Migración 002: tabla de recordatorios
SET search_path TO organizador;

CREATE TABLE IF NOT EXISTS recordatorios (
    id              TEXT PRIMARY KEY,
    titulo          TEXT NOT NULL,
    mensaje         TEXT DEFAULT '',
    fecha_hora      TIMESTAMPTZ NOT NULL,
    repetir         TEXT DEFAULT 'no' CHECK (repetir IN ('no','diario','semanal','mensual','anual')),
    cliente_id      TEXT REFERENCES clientes(id) ON DELETE SET NULL,
    enviado         BOOLEAN DEFAULT FALSE,
    enviado_at      TIMESTAMPTZ,
    activo          BOOLEAN DEFAULT TRUE,
    creado_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rec_fecha ON recordatorios(fecha_hora) WHERE NOT enviado AND activo;
CREATE INDEX IF NOT EXISTS idx_rec_activo ON recordatorios(activo, enviado);
