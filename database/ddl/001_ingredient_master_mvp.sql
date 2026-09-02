-- Ingredient Master MVP
-- PostgreSQL 14+
--
-- `ingredient_master.ingredient` stores stable Ingredient identity: the material axis of the fresh-food
-- domain. Productized foods and cooking intents are separate product/service
-- concerns. A source row's nutrients, origin, production date, and raw/cooked
-- state remain observations and are not copied into this table.

CREATE SCHEMA IF NOT EXISTS ingredient_master;

CREATE TABLE IF NOT EXISTS ingredient_master.ingredient_source (
    ingredient_source_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_version TEXT NOT NULL DEFAULT 'unspecified',
    source_uri TEXT,
    UNIQUE (source_name, source_version)
);

CREATE TABLE IF NOT EXISTS ingredient_master.ingredient (
    ingredient_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_name TEXT NOT NULL CHECK (btrim(canonical_name) <> ''),
    parent_ingredient_id BIGINT REFERENCES ingredient_master.ingredient (ingredient_id) ON DELETE RESTRICT,
    category_name TEXT NOT NULL CHECK (btrim(category_name) <> ''),
    basis_level TEXT NOT NULL CHECK (
        basis_level IN ('REPRESENTATIVE', 'MIDDLE', 'SMALL')
    ),
    basis_code TEXT NOT NULL CHECK (btrim(basis_code) <> ''),
    basis_name TEXT NOT NULL CHECK (btrim(basis_name) <> ''),
    source_identity_key TEXT NOT NULL CHECK (btrim(source_identity_key) <> ''),
    basis_source_id BIGINT NOT NULL
        REFERENCES ingredient_master.ingredient_source (ingredient_source_id) ON DELETE RESTRICT,
    CONSTRAINT ingredient_parent_must_differ_from_self
        CHECK (parent_ingredient_id IS NULL OR parent_ingredient_id <> ingredient_id),
    CONSTRAINT ingredient_basis_is_unique
        UNIQUE (basis_source_id, source_identity_key)
);

CREATE INDEX IF NOT EXISTS ingredient_parent_ingredient_id_idx
    ON ingredient_master.ingredient (parent_ingredient_id);

CREATE INDEX IF NOT EXISTS ingredient_category_name_idx
    ON ingredient_master.ingredient (category_name);

CREATE INDEX IF NOT EXISTS ingredient_canonical_name_idx
    ON ingredient_master.ingredient (canonical_name);

COMMENT ON TABLE ingredient_master.ingredient IS
    'MVP Ingredient identity master derived from an official food-source hierarchy.';
COMMENT ON COLUMN ingredient_master.ingredient.basis_level IS
    'Original hierarchy level selected as the Ingredient identity: REPRESENTATIVE, MIDDLE, or SMALL.';
COMMENT ON COLUMN ingredient_master.ingredient.basis_source_id IS
    'Dataset source used to create this Ingredient; it is not an individual observation row.';
COMMENT ON COLUMN ingredient_master.ingredient.source_identity_key IS
    'Stable resolved source branch key. It distinguishes approved code collisions and normalized aliases.';
