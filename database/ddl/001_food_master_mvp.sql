-- Food Master MVP
-- PostgreSQL 14+
--
-- `food` stores stable food identity only. A source row's nutrients, origin,
-- production date, and raw/cooked state remain observations and are not copied
-- into this table.

CREATE SCHEMA IF NOT EXISTS food_master;

CREATE TABLE IF NOT EXISTS food_master.food_source (
    food_source_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_version TEXT NOT NULL DEFAULT 'unspecified',
    source_uri TEXT,
    UNIQUE (source_name, source_version)
);

CREATE TABLE IF NOT EXISTS food_master.food (
    food_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_name TEXT NOT NULL CHECK (btrim(canonical_name) <> ''),
    parent_food_id BIGINT REFERENCES food_master.food (food_id) ON DELETE RESTRICT,
    category_name TEXT NOT NULL CHECK (btrim(category_name) <> ''),
    basis_level TEXT NOT NULL CHECK (
        basis_level IN ('REPRESENTATIVE', 'MIDDLE', 'SMALL')
    ),
    basis_code TEXT NOT NULL CHECK (btrim(basis_code) <> ''),
    basis_name TEXT NOT NULL CHECK (btrim(basis_name) <> ''),
    source_identity_key TEXT NOT NULL CHECK (btrim(source_identity_key) <> ''),
    basis_source_id BIGINT NOT NULL
        REFERENCES food_master.food_source (food_source_id) ON DELETE RESTRICT,
    CONSTRAINT food_parent_must_differ_from_self
        CHECK (parent_food_id IS NULL OR parent_food_id <> food_id),
    CONSTRAINT food_basis_is_unique
        UNIQUE (basis_source_id, source_identity_key)
);

CREATE INDEX IF NOT EXISTS food_parent_food_id_idx
    ON food_master.food (parent_food_id);

CREATE INDEX IF NOT EXISTS food_category_name_idx
    ON food_master.food (category_name);

CREATE INDEX IF NOT EXISTS food_canonical_name_idx
    ON food_master.food (canonical_name);

COMMENT ON TABLE food_master.food IS
    'MVP Food identity master derived from an official food-source hierarchy.';
COMMENT ON COLUMN food_master.food.basis_level IS
    'Original hierarchy level selected as the Food identity: REPRESENTATIVE, MIDDLE, or SMALL.';
COMMENT ON COLUMN food_master.food.basis_source_id IS
    'Dataset source used to create this Food; it is not an individual observation row.';
COMMENT ON COLUMN food_master.food.source_identity_key IS
    'Stable resolved source branch key. It distinguishes approved code collisions and normalized aliases.';
