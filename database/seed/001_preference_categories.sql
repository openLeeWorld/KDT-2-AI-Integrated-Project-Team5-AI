-- 식단 선호 마스터 시드 데이터
-- 002_kitchen_core_mvp.sql 실행 후 적재한다. 재실행해도 안전하다.

INSERT INTO kitchen.preference_categories (code, name, description) VALUES
    ('vegan', '비건', '과일과 채소 위주의 비건식'),
    ('proteinDiet', '단백질 다이어트', '단백질 중심의 다이어트 식단'),
    ('meatHearty', '육류 든든식', '육류 중심의 든든한 식단'),
    ('mealkit', '간편식', '밀키트와 레토르트 위주의 간편식'),
    ('lowCarb', '저탄수', '저탄수 저당 식단'),
    ('spicy', '매콤한 한상', '얼큰하고 매콤한 자극적인 한상'),
    ('homestyle', '집밥', '정성 가득 집밥 스타일'),
    ('brunch', '브런치', '브런치 스타일')
ON CONFLICT (code) DO UPDATE
    SET name = EXCLUDED.name,
        description = EXCLUDED.description;
