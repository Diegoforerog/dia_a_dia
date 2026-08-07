-- 🍽️ Migración 008: Fase 4 — Comidas + Despensa (módulo compartido de la pareja)
-- Recetas, menú semanal, despensa (inventario) y lista de mercado.
-- Fecha: 2026-08-07

SET search_path TO organizador;

-- Recetas (banco de recetas favoritas)
CREATE TABLE IF NOT EXISTS recetas (
    id            TEXT PRIMARY KEY,
    nombre        TEXT NOT NULL,
    tipo          TEXT DEFAULT 'almuerzo',   -- desayuno | almuerzo | cena | snack
    gustos        JSONB DEFAULT '[]'::jsonb,  -- etiquetas: rápido, saludable, favorito de X…
    ingredientes  JSONB DEFAULT '[]'::jsonb,  -- [{item, cantidad, unidad}]
    pasos         TEXT DEFAULT '',
    favorita      BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Menú semanal (un blob por semana ISO: {lunes:{desayuno,almuerzo,cena,snack}, ...})
CREATE TABLE IF NOT EXISTS menus (
    semana     TEXT PRIMARY KEY,              -- YYYY-Www
    dias       JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Despensa (inventario con nivel)
CREATE TABLE IF NOT EXISTS despensa (
    id         TEXT PRIMARY KEY,
    item       TEXT NOT NULL,
    unidad     TEXT DEFAULT '',
    estado     TEXT DEFAULT 'hay',            -- hay | poco | agotado
    categoria  TEXT DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Lista de mercado (generada del menú − despensa + faltantes; con check de comprado)
CREATE TABLE IF NOT EXISTS lista_mercado (
    id         TEXT PRIMARY KEY,
    item       TEXT NOT NULL,
    cantidad   TEXT DEFAULT '',
    unidad     TEXT DEFAULT '',
    origen     TEXT DEFAULT 'manual',         -- menu | despensa | manual
    comprado   BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
