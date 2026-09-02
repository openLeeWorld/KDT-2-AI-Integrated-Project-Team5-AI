from scripts.ingredient_master.map_products_to_ingredient_master import Ingredient, Product, match_product

INGREDIENTS = [
    Ingredient("1", "호박", "채소류", "REPRESENTATIVE", "K:호박", ""),
    Ingredient("2", "애호박", "채소류", "MIDDLE", "K:애호박", "1"),
    Ingredient("3", "고구마", "채소류", "REPRESENTATIVE", "K:고구마", ""),
    Ingredient("4", "토마토", "채소류", "REPRESENTATIVE", "K:토마토", ""),
    Ingredient("5", "방울토마토", "채소류", "MIDDLE", "K:방울토마토", "4"),
    Ingredient("6", "돼지고기", "육류", "REPRESENTATIVE", "K:돼지고기", ""),
    Ingredient("7", "소고기", "육류", "REPRESENTATIVE", "K:소고기", ""),
    Ingredient("8", "감자", "감자 및 전분류", "REPRESENTATIVE", "K:감자", ""),
]


def product(name, category, *, split=True):
    return Product("v1", name, category, "", split)


def test_child_ingredient_wins_over_parent_ingredient():
    status, _, _, candidates = match_product(product("친환경 애호박 1개", "채소 > 과채류 > 호박"), INGREDIENTS)

    assert status == "CANDIDATE"
    assert [candidate.ingredient.canonical_name for candidate in candidates] == ["애호박"]


def test_reviewed_alias_preserves_product_attribute():
    status, _, _, candidates = match_product(
        product("대추방울토마토 500g", "과일/견과 > 국산과일 > 토마토"), INGREDIENTS
    )

    assert status == "CANDIDATE"
    assert candidates[0].ingredient.canonical_name == "방울토마토"
    assert candidates[0].attributes == (("variety", "대추"),)


def test_product_with_multiple_raw_ingredients_is_held():
    status, _, _, candidates = match_product(product("나베용 채소 모둠", "채소 > 간편채소"), INGREDIENTS)

    assert status == "REVIEW"
    assert candidates == []


def test_unsplit_option_product_is_held():
    status, _, _, candidates = match_product(product("호박 2종", "채소 > 과채류 > 호박", split=False), INGREDIENTS)

    assert status == "REVIEW"
    assert candidates == []


def test_livestock_alias_maps_to_species_with_cut_attribute():
    status, _, _, candidates = match_product(product("한돈 삼겹살 300g", "돼지고기 > 국내산 돼지고기"), INGREDIENTS)

    assert status == "CANDIDATE"
    assert candidates[0].ingredient.canonical_name == "돼지고기"
    assert candidates[0].attributes == (("origin", "국내산"), ("part", "삼겹살"))


def test_category_anchor_maps_livestock_when_name_only_has_cut():
    status, _, _, candidates = match_product(product("절단 국거리", "한우/육우 > 육우 > 육우"), INGREDIENTS)

    assert status == "CANDIDATE"
    assert candidates[0].ingredient.canonical_name == "소고기"
    assert candidates[0].attributes == (("cattle_type", "육우"),)


def test_processed_chicken_is_deferred():
    status, _, _, candidates = match_product(product("닭가슴살 블랙페퍼", "닭/오리고기 > 닭고기"), INGREDIENTS)

    assert status == "DEFER"
    assert candidates == []


def test_preparation_state_is_saved_as_an_attribute_not_a_new_ingredient():
    status, _, _, candidates = match_product(product("깐 감자 300g", "채소 > 근채류 > 감자"), INGREDIENTS)

    assert status == "CANDIDATE"
    assert candidates[0].ingredient.canonical_name == "감자"
    assert candidates[0].attributes == (("peel_state", "깐"),)
