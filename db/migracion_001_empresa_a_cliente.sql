-- 🔄 Migración 001: renombrar "empresa" → "cliente" en todo el esquema
-- Fecha: 2026-05-10

SET search_path TO organizador;

-- Tabla principal
ALTER TABLE empresas RENAME TO clientes;

-- Columnas FK
ALTER TABLE proyectos RENAME COLUMN empresa_id TO cliente_id;
ALTER TABLE actividades RENAME COLUMN empresa_id TO cliente_id;
ALTER TABLE calendarios RENAME COLUMN empresa_asociada TO cliente_asociado;

-- Índices
ALTER INDEX IF EXISTS idx_empresas_activo RENAME TO idx_clientes_activo;
ALTER INDEX IF EXISTS idx_proyectos_empresa RENAME TO idx_proyectos_cliente;
ALTER INDEX IF EXISTS idx_actividades_empresa RENAME TO idx_actividades_cliente;

-- Trigger updated_at sigue funcionando, pero re-creamos el del antiguo nombre
DROP TRIGGER IF EXISTS trg_empresas_updated ON clientes;
DROP TRIGGER IF EXISTS trg_clientes_updated ON clientes;
CREATE TRIGGER trg_clientes_updated
  BEFORE UPDATE ON clientes
  FOR EACH ROW EXECUTE FUNCTION organizador.set_updated_at();
