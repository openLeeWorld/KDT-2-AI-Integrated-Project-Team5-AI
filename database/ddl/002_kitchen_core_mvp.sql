-- My컬리키친 kitchen 스키마 코어 (Phase 1 MVP)
-- PostgreSQL 14+
--
-- 추천 엔진이 후보를 만들기 위해 읽는 "정답 데이터"와 사용자 행동 로그를 담는다.
-- AI/LLM 계층은 이 스키마의 결과를 설명하는 역할만 하며, 상품/레시피를 직접
-- 생성하지 않는다. 식재료 정체성 축(`ingredient_master`)과는 스키마를 분리하고,
-- 상품-식재료 연결은 매핑 테이블이 준비된 뒤 별도로 추가한다.

CREATE SCHEMA IF NOT EXISTS kitchen;

-- updated_at 자동 갱신용 공통 트리거 함수.
CREATE OR REPLACE FUNCTION kitchen.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $fn$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$fn$;


-- ---------------------------------------------------------------------------
-- 사용자 및 식단 선호
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS kitchen.users (
    user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL CHECK (btrim(email) <> ''),
    nickname TEXT CHECK (nickname IS NULL OR btrim(nickname) <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_email_is_unique UNIQUE (email)
);

CREATE OR REPLACE TRIGGER users_set_updated_at
    BEFORE UPDATE ON kitchen.users
    FOR EACH ROW EXECUTE FUNCTION kitchen.set_updated_at();

-- 식단 선호 마스터. `code`는 프론트엔드 preference pool 키와 1:1로 대응한다.
CREATE TABLE IF NOT EXISTS kitchen.preference_categories (
    preference_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code TEXT NOT NULL CHECK (btrim(code) <> ''),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    description TEXT,
    CONSTRAINT preference_categories_code_is_unique UNIQUE (code)
);

-- weight는 선호 강도(0~1). 추천 점수의 preference_score 계산에 그대로 곱한다.
CREATE TABLE IF NOT EXISTS kitchen.user_preferences (
    user_id BIGINT NOT NULL
        REFERENCES kitchen.users (user_id) ON DELETE CASCADE,
    preference_id BIGINT NOT NULL
        REFERENCES kitchen.preference_categories (preference_id) ON DELETE RESTRICT,
    weight NUMERIC(5, 4) NOT NULL DEFAULT 1.0
        CHECK (weight >= 0 AND weight <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, preference_id)
);

CREATE INDEX IF NOT EXISTS user_preferences_preference_id_idx
    ON kitchen.user_preferences (preference_id);


-- ---------------------------------------------------------------------------
-- 상품 카탈로그
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS kitchen.product_categories (
    product_category_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    CONSTRAINT product_categories_name_is_unique UNIQUE (name)
);

-- price는 원 단위 정수. 통화가 늘어나면 currency 컬럼을 별도로 추가한다.
CREATE TABLE IF NOT EXISTS kitchen.products (
    product_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    description TEXT,
    price INTEGER NOT NULL CHECK (price >= 0),
    image_url TEXT,
    product_category_id BIGINT
        REFERENCES kitchen.product_categories (product_category_id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE TRIGGER products_set_updated_at
    BEFORE UPDATE ON kitchen.products
    FOR EACH ROW EXECUTE FUNCTION kitchen.set_updated_at();

-- 카테고리별 판매 중 상품 후보 조회가 식단 선호 추천의 1단계라 부분 인덱스로 좁힌다.
CREATE INDEX IF NOT EXISTS products_active_category_idx
    ON kitchen.products (product_category_id)
    WHERE is_active;

CREATE INDEX IF NOT EXISTS products_name_idx
    ON kitchen.products (name);


-- ---------------------------------------------------------------------------
-- 레시피
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS kitchen.recipes (
    recipe_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    description TEXT,
    image_url TEXT,
    cooking_time INTEGER CHECK (cooking_time IS NULL OR cooking_time > 0),
    difficulty TEXT CHECK (difficulty IS NULL OR difficulty IN ('EASY', 'NORMAL', 'HARD')),
    serving_size INTEGER NOT NULL DEFAULT 1 CHECK (serving_size > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE TRIGGER recipes_set_updated_at
    BEFORE UPDATE ON kitchen.recipes
    FOR EACH ROW EXECUTE FUNCTION kitchen.set_updated_at();

CREATE INDEX IF NOT EXISTS recipes_name_idx
    ON kitchen.recipes (name);

-- 냉장고-레시피, 상품-레시피, 부족 재료 계산이 모두 이 테이블을 거친다.
CREATE TABLE IF NOT EXISTS kitchen.recipe_ingredients (
    recipe_ingredient_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipe_id BIGINT NOT NULL
        REFERENCES kitchen.recipes (recipe_id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL
        REFERENCES kitchen.products (product_id) ON DELETE RESTRICT,
    quantity NUMERIC(10, 2) CHECK (quantity IS NULL OR quantity > 0),
    unit TEXT CHECK (unit IS NULL OR btrim(unit) <> ''),
    required BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT recipe_ingredients_pair_is_unique UNIQUE (recipe_id, product_id)
);

-- 상품 상세에서 연관 레시피를 역방향으로 찾는 경로.
CREATE INDEX IF NOT EXISTS recipe_ingredients_product_id_idx
    ON kitchen.recipe_ingredients (product_id);

CREATE TABLE IF NOT EXISTS kitchen.recipe_steps (
    recipe_step_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipe_id BIGINT NOT NULL
        REFERENCES kitchen.recipes (recipe_id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL CHECK (step_number > 0),
    title TEXT,
    description TEXT,
    CONSTRAINT recipe_steps_order_is_unique UNIQUE (recipe_id, step_number)
);


-- ---------------------------------------------------------------------------
-- My 냉장고
-- ---------------------------------------------------------------------------

-- product_id는 카탈로그에 없는 재료를 직접 등록하는 경우를 위해 NULL을 허용한다.
-- 상품과 연결되지 않은 행은 레시피 매칭 대상에서 제외된다.
CREATE TABLE IF NOT EXISTS kitchen.fridge_items (
    fridge_item_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL
        REFERENCES kitchen.users (user_id) ON DELETE CASCADE,
    product_id BIGINT
        REFERENCES kitchen.products (product_id) ON DELETE SET NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    purchased_at TIMESTAMPTZ,
    opened_at TIMESTAMPTZ,
    expiration_date DATE,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'EXPIRED', 'DELETED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fridge_items_opened_after_purchase
        CHECK (opened_at IS NULL OR purchased_at IS NULL OR opened_at >= purchased_at)
);

CREATE OR REPLACE TRIGGER fridge_items_set_updated_at
    BEFORE UPDATE ON kitchen.fridge_items
    FOR EACH ROW EXECUTE FUNCTION kitchen.set_updated_at();

-- 냉장고 추천은 항상 "특정 사용자의 ACTIVE 재료"만 읽는다.
CREATE INDEX IF NOT EXISTS fridge_items_active_user_product_idx
    ON kitchen.fridge_items (user_id, product_id)
    WHERE status = 'ACTIVE';

-- 유통기한 임박 가산점 계산 및 만료 배치용.
CREATE INDEX IF NOT EXISTS fridge_items_active_expiration_idx
    ON kitchen.fridge_items (expiration_date)
    WHERE status = 'ACTIVE';


-- ---------------------------------------------------------------------------
-- 사용자 행동 로그
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS kitchen.purchase_history (
    purchase_history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL
        REFERENCES kitchen.users (user_id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL
        REFERENCES kitchen.products (product_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    purchased_at TIMESTAMPTZ NOT NULL
);

-- 최근 구매 이력 조회가 개인화 점수의 기본 입력이다.
CREATE INDEX IF NOT EXISTS purchase_history_user_purchased_at_idx
    ON kitchen.purchase_history (user_id, purchased_at DESC);

-- 인기 상품 집계용.
CREATE INDEX IF NOT EXISTS purchase_history_product_purchased_at_idx
    ON kitchen.purchase_history (product_id, purchased_at DESC);

-- 비로그인 검색도 급상승 검색어 집계에 쓰이므로 user_id는 NULL을 허용한다.
CREATE TABLE IF NOT EXISTS kitchen.search_history (
    search_history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT
        REFERENCES kitchen.users (user_id) ON DELETE SET NULL,
    keyword TEXT NOT NULL CHECK (btrim(keyword) <> ''),
    searched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS search_history_user_searched_at_idx
    ON kitchen.search_history (user_id, searched_at DESC);

CREATE INDEX IF NOT EXISTS search_history_keyword_searched_at_idx
    ON kitchen.search_history (keyword, searched_at DESC);


-- ---------------------------------------------------------------------------
-- 주석
-- ---------------------------------------------------------------------------

COMMENT ON SCHEMA kitchen IS
    'My컬리키친 서비스 도메인. 추천 엔진이 후보를 만들기 위해 읽는 정답 데이터를 보관한다.';
COMMENT ON TABLE kitchen.preference_categories IS
    '식단 선호 마스터. code는 프론트엔드 preference pool 키와 대응한다.';
COMMENT ON COLUMN kitchen.user_preferences.weight IS
    '선호 강도 0~1. 추천 점수의 preference_score에 곱해서 사용한다.';
COMMENT ON TABLE kitchen.recipe_ingredients IS
    '냉장고-레시피, 상품-레시피, 부족 재료 계산을 모두 잇는 핵심 연결 테이블.';
COMMENT ON COLUMN kitchen.recipe_ingredients.required IS
    'FALSE면 선택 재료라 부족 재료 목록에서 제외하거나 가중치를 낮춰 계산한다.';
COMMENT ON COLUMN kitchen.fridge_items.product_id IS
    '카탈로그 밖의 재료를 직접 등록한 경우 NULL. NULL인 행은 레시피 매칭 대상이 아니다.';
COMMENT ON COLUMN kitchen.fridge_items.status IS
    'ACTIVE는 보유 중, EXPIRED는 유통기한 경과, DELETED는 사용자가 내린 소프트 삭제.';
COMMENT ON COLUMN kitchen.search_history.user_id IS
    '비로그인 검색도 급상승 검색어 집계에 사용하므로 NULL을 허용한다.';
