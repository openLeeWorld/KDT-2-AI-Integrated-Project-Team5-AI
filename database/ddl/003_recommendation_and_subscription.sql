-- My컬리키친 Recommendation Log & Subscription (Phase 2~3)
-- PostgreSQL 14+
--
-- 002_kitchen_core_mvp.sql 이후에 실행한다.
-- 개인화 강화(인기 집계, 찜, 추천 요청/결과 로그)와 서비스 확장(구독)을 담는다.
-- 추천 품질을 나중에 평가하려면 클릭/담기 같은 행동을 처음부터 쌓아야 하므로
-- 추천 결과 로그는 MVP 직후 바로 적재를 시작하는 것을 권장한다.


-- ---------------------------------------------------------------------------
-- 개인화 입력 데이터
-- ---------------------------------------------------------------------------

-- 기간별 인기 상품 스냅샷. 최근 1시간/24시간/7일처럼 창을 나눠 적재한다.
CREATE TABLE IF NOT EXISTS kitchen.product_popularity (
    product_popularity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL
        REFERENCES kitchen.products (product_id) ON DELETE CASCADE,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    purchase_count INTEGER NOT NULL DEFAULT 0 CHECK (purchase_count >= 0),
    view_count INTEGER NOT NULL DEFAULT 0 CHECK (view_count >= 0),
    popularity_rank INTEGER CHECK (popularity_rank IS NULL OR popularity_rank > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT product_popularity_period_is_valid CHECK (period_end > period_start),
    CONSTRAINT product_popularity_window_is_unique
        UNIQUE (product_id, period_start, period_end)
);

-- 특정 기간 창에서 상위 N개를 뽑는 조회 경로.
CREATE INDEX IF NOT EXISTS product_popularity_window_rank_idx
    ON kitchen.product_popularity (period_start, period_end, popularity_rank);

CREATE TABLE IF NOT EXISTS kitchen.user_liked_recipes (
    user_id BIGINT NOT NULL
        REFERENCES kitchen.users (user_id) ON DELETE CASCADE,
    recipe_id BIGINT NOT NULL
        REFERENCES kitchen.recipes (recipe_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, recipe_id)
);

-- 레시피 인기도 및 협업 필터링 후보 생성용 역방향 조회.
CREATE INDEX IF NOT EXISTS user_liked_recipes_recipe_id_idx
    ON kitchen.user_liked_recipes (recipe_id);


-- ---------------------------------------------------------------------------
-- 추천 요청 및 결과 로그
-- ---------------------------------------------------------------------------

-- input_context에는 요청 시점의 냉장고 상태나 선호처럼 재현에 필요한 값만 담는다.
-- 개인 식별 정보는 넣지 않고 user_id로만 참조한다.
CREATE TABLE IF NOT EXISTS kitchen.recommendation_requests (
    recommendation_request_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL
        REFERENCES kitchen.users (user_id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (
        type IN (
            'FRIDGE_TO_RECIPE',
            'PREFERENCE_TO_PRODUCT',
            'PRODUCT_TO_RECIPE',
            'RECIPE_TO_INGREDIENT',
            'SEARCH_KEYWORD'
        )
    ),
    input_context JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT recommendation_requests_context_is_object
        CHECK (input_context IS NULL OR jsonb_typeof(input_context) = 'object')
);

CREATE INDEX IF NOT EXISTS recommendation_requests_user_type_created_at_idx
    ON kitchen.recommendation_requests (user_id, type, created_at DESC);

-- 한 행은 상품 추천이거나 레시피 추천이며 둘을 동시에 가리키지 않는다.
CREATE TABLE IF NOT EXISTS kitchen.recommendation_results (
    recommendation_result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recommendation_request_id BIGINT NOT NULL
        REFERENCES kitchen.recommendation_requests (recommendation_request_id) ON DELETE CASCADE,
    product_id BIGINT
        REFERENCES kitchen.products (product_id) ON DELETE SET NULL,
    recipe_id BIGINT
        REFERENCES kitchen.recipes (recipe_id) ON DELETE SET NULL,
    score NUMERIC(8, 5),
    result_rank INTEGER NOT NULL CHECK (result_rank > 0),
    clicked BOOLEAN NOT NULL DEFAULT FALSE,
    added_to_cart BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT recommendation_results_target_is_exclusive
        CHECK ((product_id IS NOT NULL) <> (recipe_id IS NOT NULL)),
    CONSTRAINT recommendation_results_rank_is_unique
        UNIQUE (recommendation_request_id, result_rank)
);

-- 상품/레시피별 노출 대비 클릭률 집계용.
CREATE INDEX IF NOT EXISTS recommendation_results_product_id_idx
    ON kitchen.recommendation_results (product_id)
    WHERE product_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS recommendation_results_recipe_id_idx
    ON kitchen.recommendation_results (recipe_id)
    WHERE recipe_id IS NOT NULL;


-- ---------------------------------------------------------------------------
-- 구독
-- ---------------------------------------------------------------------------

-- cycle_days는 7=매주, 14=격주, 28=4주마다. weekday는 0=일요일 ~ 6=토요일이며
-- 주 단위 배수 주기가 아닌 구독에서는 NULL로 둔다.
CREATE TABLE IF NOT EXISTS kitchen.subscriptions (
    subscription_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL
        REFERENCES kitchen.users (user_id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL
        REFERENCES kitchen.products (product_id) ON DELETE RESTRICT,
    cycle_days INTEGER NOT NULL CHECK (cycle_days > 0),
    weekday SMALLINT CHECK (weekday IS NULL OR weekday BETWEEN 0 AND 6),
    first_delivery_date DATE NOT NULL,
    next_delivery_date DATE,
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'PAUSED', 'CANCELED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT subscriptions_next_delivery_is_not_before_first
        CHECK (next_delivery_date IS NULL OR next_delivery_date >= first_delivery_date)
);

CREATE OR REPLACE TRIGGER subscriptions_set_updated_at
    BEFORE UPDATE ON kitchen.subscriptions
    FOR EACH ROW EXECUTE FUNCTION kitchen.set_updated_at();

-- 배송일 배치가 읽는 경로.
CREATE INDEX IF NOT EXISTS subscriptions_active_next_delivery_idx
    ON kitchen.subscriptions (next_delivery_date)
    WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS subscriptions_user_status_idx
    ON kitchen.subscriptions (user_id, status);


-- ---------------------------------------------------------------------------
-- 주석
-- ---------------------------------------------------------------------------

COMMENT ON TABLE kitchen.product_popularity IS
    '기간별 인기 상품 스냅샷. 최근 1시간/24시간/7일처럼 창을 나눠 적재한다.';
COMMENT ON TABLE kitchen.recommendation_requests IS
    '추천 요청 로그. input_context는 재현에 필요한 값만 담고 개인 식별 정보는 넣지 않는다.';
COMMENT ON COLUMN kitchen.recommendation_requests.input_context IS
    '요청 시점 입력 스냅샷. 예: {"fridgeItems": [101, 102], "mealTime": "DINNER"}';
COMMENT ON TABLE kitchen.recommendation_results IS
    '추천 결과와 클릭/담기 반응 로그. 추천 품질 평가와 개인화 모델 개선의 학습 데이터가 된다.';
COMMENT ON CONSTRAINT recommendation_results_target_is_exclusive
    ON kitchen.recommendation_results IS
    '한 행은 상품 추천이거나 레시피 추천이며 둘을 동시에 가리키지 않는다.';
COMMENT ON COLUMN kitchen.subscriptions.cycle_days IS
    '배송 주기(일). 7은 매주, 14는 격주, 28은 4주마다를 뜻한다.';
COMMENT ON COLUMN kitchen.subscriptions.weekday IS
    '배송 요일 0=일요일 ~ 6=토요일. 주 단위 배수 주기가 아니면 NULL.';
