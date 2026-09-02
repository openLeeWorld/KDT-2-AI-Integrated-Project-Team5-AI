from pathlib import Path

from scripts.food_master.load_food_master import (
    IdentityOverride,
    PromotionRule,
    build_plan,
    read_identity_overrides,
    read_promotion_rules,
)

ROOT = Path(__file__).resolve().parents[1]


def row(
    *,
    category_code="06",
    category="채소류",
    representative_code="06198",
    representative_name="호박",
    middle_code="0619800",
    middle_name="해당없음",
    small_code="061980000",
    small_name="해당없음",
):
    return {
        "식품대분류코드": category_code,
        "식품대분류명": category,
        "대표식품코드": representative_code,
        "대표식품명": representative_name,
        "식품중분류코드": middle_code,
        "식품중분류명": middle_name,
        "식품소분류코드": small_code,
        "식품소분류명": small_name,
    }


def test_representative_is_the_default_food():
    plan = build_plan([row(), row(middle_code="0619805", middle_name="애호박")], [], [])

    assert [(food.basis_level, food.canonical_name) for food in plan.foods] == [
        ("REPRESENTATIVE", "호박")
    ]


def test_r2_promotion_creates_a_child_food():
    plan = build_plan(
        [row(), row(middle_code="0619805", middle_name="애호박")],
        [],
        [
            PromotionRule(
                large_category_code="06",
                representative_food_code="06198",
                representative_food_name="호박",
                resolved_representative_code="06198",
                resolved_representative_name="호박",
                middle_category_code="0619805",
                canonical_name="애호박",
                source_middle_codes=("0619805",),
                reason="실제 식재료 단위",
            )
        ],
    )

    assert [(food.canonical_name, food.parent_key) for food in plan.foods] == [
        ("호박", None),
        ("애호박", ("REPRESENTATIVE", "K-FIND:06:06198:호박")),
    ]


def test_r3_promotion_uses_a_composite_name():
    records = [
        row(
            category_code="02",
            category="감자 및 전분류",
            representative_code="02014",
            representative_name="전분",
            middle_code="0201402",
            middle_name="고구마",
        )
    ]
    plan = build_plan(
        records,
        [],
        [
            PromotionRule(
                large_category_code="02",
                representative_food_code="02014",
                representative_food_name="전분",
                resolved_representative_code="02014",
                resolved_representative_name="전분",
                middle_category_code="0201402",
                canonical_name="고구마 전분",
                source_middle_codes=("0201402",),
                reason="복합 identity",
            )
        ],
    )

    child = next(food for food in plan.foods if food.basis_level == "MIDDLE")
    assert child.canonical_name == "고구마 전분"
    assert child.parent_key == ("REPRESENTATIVE", "K-FIND:02:02014:전분")


def test_normalized_merge_emits_one_food():
    records = [
        row(
            category_code="01",
            category="곡류",
            representative_code="01010",
            representative_name="맵쌀 국수",
        ),
        row(
            category_code="01",
            category="곡류",
            representative_code="01010",
            representative_name="멥쌀 국수",
        ),
    ]
    overrides = [
        IdentityOverride(
            "01",
            "01010",
            "맵쌀 국수",
            "01010",
            "멥쌀 국수",
            "CONFIRMED_NORMALIZED_MERGE",
            "표기 변이",
        ),
        IdentityOverride(
            "01",
            "01010",
            "멥쌀 국수",
            "01010",
            "멥쌀 국수",
            "CONFIRMED_NORMALIZED_MERGE",
            "표기 변이",
        ),
    ]
    plan = build_plan(records, overrides, [])

    assert len(plan.foods) == 1
    assert plan.foods[0].canonical_name == "멥쌀 국수"
    assert len(plan.normalized_merges) == 1


def test_internal_branch_override_keeps_colliding_code_as_two_foods():
    records = [
        row(
            representative_code="06101",
            representative_name="상추",
            middle_code="0610103",
            middle_name="로메인",
        ),
        row(
            representative_code="06101",
            representative_name="생강",
            middle_code="0610100",
            middle_name="해당없음",
        ),
    ]
    overrides = [
        IdentityOverride(
            "06",
            "06101",
            "상추",
            "06101-01",
            "상추",
            "CONFIRMED_INTERNAL_BRANCH_CODE",
            "branch",
        ),
        IdentityOverride(
            "06",
            "06101",
            "생강",
            "06101-02",
            "생강",
            "CONFIRMED_INTERNAL_BRANCH_CODE",
            "branch",
        ),
    ]
    plan = build_plan(records, overrides, [])

    assert {food.basis_code for food in plan.foods} == {"06101-01", "06101-02"}
    assert plan.blocked_codes == []


def test_unresolved_collision_is_blocked():
    plan = build_plan(
        [
            row(representative_code="06101", representative_name="상추"),
            row(representative_code="06101", representative_name="생강"),
        ],
        [],
        [],
    )

    assert plan.foods == []
    assert plan.blocked_codes[0]["basis_code"] == "06101"


def test_versioned_config_contains_the_approved_policy_set():
    identity_rules = read_identity_overrides(
        ROOT / "config" / "food_master_source_identity_overrides.csv"
    )
    promotion_rules = read_promotion_rules(
        ROOT / "config" / "food_master_promoted_middle_foods.csv"
    )

    assert len(identity_rules) == 8
    assert len(promotion_rules) == 21
