"""Generate conservative Product Variant → Ingredient Master mapping candidates.

The mapper reads the current ``ingredient_master.ingredient`` table (or an
equivalent export), never creates Ingredient records, and never forces a mixed
or processed product into a single Ingredient identity.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

EMPTY_VALUES = {"", "-", "none", "null", "nan", "해당없음"}
INGREDIENT_GROUPS = {
    "agricultural_raw": {
        "곡류",
        "감자 및 전분류",
        "두류",
        "견과 및 종실류",
        "채소류",
        "버섯류",
        "과일류",
    },
    "livestock_egg_raw": {"육류", "난류"},
    "seafood_seaweed_raw": {"어패류 및 기타 수산물", "해조류"},
    "single_animal_ingredient": {"우유류"},
}
ALIAS_RULES = (
    ("멥쌀", "쌀", "백미", "milling_form", "백미"),
    ("멥쌀", "백미", "백미", "milling_form", "백미"),
    ("멥쌀", "현미", "현미", "milling_form", "현미"),
    ("찹쌀", "백옥찹쌀", "", "variety", "백옥찰"),
    ("찹쌀", "무세찹쌀", "", "wash_state", "무세"),
    ("고구마", "호박고구마", "", "market_variant", "호박고구마"),
    ("토마토", "완숙토마토", "", "market_variant", "완숙"),
    ("토마토", "찰토마토", "", "market_variant", "찰"),
    ("방울토마토", "대추방울토마토", "", "variety", "대추"),
    ("토마토", "송이토마토", "", "market_variant", "송이"),
    ("오이", "미니오이", "", "size", "mini"),
    ("큰느타리버섯(새송이버섯)", "새송이버섯", "", "", ""),
    ("큰느타리버섯(새송이버섯)", "새송이", "버섯류", "", ""),
    ("느타리버섯", "참타리", "버섯류", "", ""),
    ("파프리카(착색단고추)", "파프리카", "", "", ""),
    ("파프리카(착색단고추)", "미니파프리카", "", "size", "mini"),
    ("달걀", "란", "달걀", "", ""),
    ("달걀", "유정란", "달걀", "egg_type", "유정"),
    ("달걀", "특란", "달걀", "egg_size", "특"),
    ("달걀", "대란", "달걀", "egg_size", "대"),
    ("달걀", "초란", "달걀", "egg_size", "초"),
    ("달걀", "백색란", "달걀", "shell_color", "백색"),
    ("닭고기", "닭가슴살", "닭/오리고기", "part", "가슴(껍질 제거)"),
    ("닭고기", "닭다리살", "닭/오리고기", "part", "넓적다리"),
    ("돼지고기", "삼겹살", "돼지고기", "part", "삼겹살"),
    ("돼지고기", "목살", "돼지고기", "part", "목심(목심살)"),
    ("돼지고기", "목심", "돼지고기", "part", "목심(목심살)"),
    ("돼지고기", "앞다리살", "돼지고기", "part", "앞다리(앞다리살)"),
    ("돼지고기", "앞다리", "돼지고기", "part", "앞다리"),
    ("돼지고기", "뒷다리", "돼지고기", "part", "뒷다리"),
    ("돼지고기", "뒷다리살", "돼지고기", "part", "뒷다리"),
    ("돼지고기", "등심", "돼지고기", "part", "등심"),
    ("돼지고기", "안심", "돼지고기", "part", "안심(안심살)"),
    ("돼지고기", "항정살", "돼지고기", "part", "앞다리(항정살)"),
    ("돼지고기", "갈매기살", "돼지고기", "part", "삼겹살(갈매기살)"),
)
CATEGORY_ANCHORS = (
    ("닭/오리고기 > 닭고기", "닭고기", "", ""),
    ("돼지고기 > 국내산 돼지고기", "돼지고기", "origin", "국내산"),
    ("수입육 > 수입산 돼지고기", "돼지고기", "origin", "수입산"),
    ("한우/육우 > 한우", "소고기", "cattle_type", "한우"),
    ("한우/육우 > 육우", "소고기", "cattle_type", "육우"),
    ("수입육 > 수입산 소고기", "소고기", "origin", "수입산"),
)
PRODUCT_ATTRIBUTE_RULES = (
    ("채소류", "마늘", "다진", "form", "다진"),
    ("채소류", "", "저민", "cut_style", "저민"),
    ("채소류", "", "채썬", "cut_style", "채썬"),
    ("채소류", "", "절단", "cut_style", "절단"),
    ("채소류", "", "깐", "peel_state", "깐"),
    ("채소류", "", "뿌리손질", "trim_state", "뿌리손질"),
    ("채소류", "", "손질", "trim_state", "손질"),
    ("감자 및 전분류", "", "깐", "peel_state", "깐"),
    ("감자 및 전분류", "", "손질", "trim_state", "손질"),
    ("버섯류", "", "뿌리손질", "trim_state", "뿌리손질"),
)


@dataclass(frozen=True)
class Ingredient:
    ingredient_id: str
    canonical_name: str
    category_name: str
    basis_level: str
    source_identity_key: str
    parent_ingredient_id: str


@dataclass(frozen=True)
class Product:
    variant_id: str
    variant_name: str
    category_path: str
    brand: str
    option_split_complete: bool


@dataclass(frozen=True)
class Candidate:
    ingredient: Ingredient
    matched_term: str
    match_method: str
    attributes: tuple[tuple[str, str], ...]
    score: int


def text(value: object) -> str:
    value = str(value or "").strip()
    return "" if value.lower() in EMPTY_VALUES else value


def compact(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text(value)).lower()


def as_bool(value: object) -> bool:
    return text(value).lower() not in {"false", "0", "no", "n"}


def product_name_for_match(name: str, brand: str) -> str:
    without_brand = re.sub(r"\[[^\]]*\]", " ", name)
    return compact(without_brand.replace(brand, " ") if brand else without_brand)


def read_rows(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq

        return [dict(row) for row in pq.read_table(path).to_pylist()]
    raise ValueError("입력 파일은 CSV 또는 Parquet이어야 합니다.")


def read_ingredients_from_file(path: Path) -> list[Ingredient]:
    required = {
        "ingredient_id",
        "canonical_name",
        "category_name",
        "basis_level",
        "source_identity_key",
    }
    rows = read_rows(path)
    if not rows:
        raise ValueError("Ingredient Master export에 행이 없습니다.")
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"Ingredient Master export 필수 컬럼이 없습니다: {', '.join(sorted(missing))}")
    return [
        Ingredient(
            ingredient_id=text(row["ingredient_id"]),
            canonical_name=text(row["canonical_name"]),
            category_name=text(row["category_name"]),
            basis_level=text(row["basis_level"]),
            source_identity_key=text(row["source_identity_key"]),
            parent_ingredient_id=text(row.get("parent_ingredient_id")),
        )
        for row in rows
    ]


def read_ingredients_from_database(database_url: str) -> list[Ingredient]:
    import psycopg

    query = """
        SELECT ingredient_id, canonical_name, category_name, basis_level,
               source_identity_key, parent_ingredient_id
        FROM ingredient_master.ingredient
        ORDER BY ingredient_id
    """
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            return [Ingredient(*(text(value) for value in row)) for row in cursor.fetchall()]


def read_products(path: Path) -> list[Product]:
    rows = read_rows(path)
    required = {"variant_id", "variant_name", "category_path"}
    if not rows:
        raise ValueError("상품 입력에 행이 없습니다.")
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"상품 입력 필수 컬럼이 없습니다: {', '.join(sorted(missing))}")
    return [
        Product(
            variant_id=text(row["variant_id"]),
            variant_name=text(row["variant_name"]),
            category_path=text(row["category_path"]),
            brand=text(row.get("brand")),
            option_split_complete=as_bool(row.get("option_split_complete", True)),
        )
        for row in rows
    ]


def scope(product: Product) -> tuple[str, str, str]:
    categories = [part.strip() for part in product.category_path.split(" > ") if part.strip()]
    root, path, name = (
        (categories[0] if categories else ""),
        product.category_path,
        product.variant_name,
    )
    if not product.option_split_complete:
        return "REVIEW", "option_not_split", "옵션별 상품이 분리되지 않음"
    if root in {"채소", "쌀/잡곡", "과일/견과"}:
        if any(term in name for term in {"&", "앤", "혼합", "믹스", "모둠", "모듬", "샐러드"}):
            return "REVIEW", "multiple_foods", "여러 원물이 섞인 상품"
        if any(term in path for term in {"간편", "냉동", "믹스", "샐러드"}):
            return "REVIEW", "prepared_food", "손질·냉동·혼합 여부 확인 필요"
        return "TARGET", "agricultural_raw", "농산 원물"
    if root in {"닭/오리고기", "돼지고기", "한우/육우", "수입육", "달걀"}:
        if root == "닭/오리고기":
            plain_name = re.sub(r"\[[^\]]*\]", " ", name)
            plain_name = plain_name.replace("불고기용", "").replace("구이용", "")
            processed_markers = {
                "블랙페퍼",
                "한끼통살",
                "양념",
                "소스",
                "훈제",
                "수비드",
                "그릴",
                "스모크",
                "데리야키",
                "바베큐",
                "마라",
                "불고기",
                "패티",
                "완자",
                "꼬치",
                "튀김",
            }
            if "한끼통살" in name or any(marker in plain_name for marker in processed_markers):
                return (
                    "DEFER",
                    "processed_or_composite",
                    "맛·소스·조리 신호가 있는 닭 가공식품",
                )
        if any(term in path for term in {"가공란", "구운란", "반숙란", "훈제란", "큐브"}):
            return "REVIEW", "prepared_food", "가공 또는 성형 축산물"
        return "TARGET", "livestock_egg_raw", "축산·난류 원물"
    if root == "수산":
        if any(term in path for term in {"수산가공품", "젓갈", "장류"}):
            return "REVIEW", "prepared_food", "수산 가공품"
        return "TARGET", "seafood_seaweed_raw", "수산·해조 원물"
    if root == "유제품" and len(categories) > 1 and categories[1] == "우유":
        return "TARGET", "single_animal_ingredient", "우유"
    if root:
        return "DEFER", "processed_or_composite", "가공·조합식품은 별도 매핑 필요"
    return "OUT_OF_SCOPE", "unknown", "카테고리 정보가 없음"


def category_hints(scope_class: str, category_path: str) -> set[str]:
    if scope_class == "agricultural_raw":
        if "버섯류" in category_path:
            return {"버섯류"}
        if "전통채소" in category_path:
            return {"두류"}
        if "쌀/잡곡" in category_path:
            return {"곡류"}
        if "근채류" in category_path:
            return {"감자 및 전분류"} if "감자" in category_path else {"채소류"}
    if scope_class == "livestock_egg_raw" and "달걀" in category_path:
        return {"난류"}
    if scope_class == "seafood_seaweed_raw" and "해조" in category_path:
        return {"해조류"}
    return set()


def product_attributes(product_name: str, ingredient: Ingredient) -> tuple[tuple[str, str], ...]:
    name = compact(product_name)
    attributes: dict[str, str] = {}
    for category, required_food, term, key, value in PRODUCT_ATTRIBUTE_RULES:
        if category != ingredient.category_name:
            continue
        if required_food and compact(required_food) != compact(ingredient.canonical_name):
            continue
        if compact(term) in name:
            attributes[key] = value
    return tuple(sorted(attributes.items()))


def match_product(product: Product, ingredients: list[Ingredient]) -> tuple[str, str, str, list[Candidate]]:
    decision, scope_class, reason = scope(product)
    if decision != "TARGET":
        return decision, scope_class, reason, []
    name = product_name_for_match(product.variant_name, product.brand)
    pool = [ingredient for ingredient in ingredients if ingredient.category_name in INGREDIENT_GROUPS[scope_class]]
    candidates: list[Candidate] = []
    for ingredient in pool:
        term = compact(ingredient.canonical_name)
        if len(term) >= 2 and term in name:
            candidates.append(Candidate(ingredient, ingredient.canonical_name, "canonical_name", (), len(term) * 10))
    by_name = {compact(ingredient.canonical_name): ingredient for ingredient in pool}
    category = compact(product.category_path)
    for (
        canonical,
        alias,
        required_category,
        attribute_key,
        attribute_value,
    ) in ALIAS_RULES:
        alias_term = compact(alias)
        if alias_term not in name or (required_category and compact(required_category) not in category):
            continue
        ingredient = by_name.get(compact(canonical))
        if ingredient:
            attributes = ((attribute_key, attribute_value),) if attribute_key else ()
            candidates.append(Candidate(ingredient, alias, "reviewed_alias", attributes, len(alias_term) * 10 + 40))
    for prefix, canonical, attribute_key, attribute_value in CATEGORY_ANCHORS:
        if product.category_path != prefix and not product.category_path.startswith(prefix + " > "):
            continue
        ingredient = by_name.get(compact(canonical))
        if ingredient:
            attributes = ((attribute_key, attribute_value),) if attribute_key else ()
            candidates.append(Candidate(ingredient, prefix, "category_anchor", attributes, 60))
    if "토마토" in name:
        candidates = [c for c in candidates if compact(c.ingredient.canonical_name) in {"토마토", "방울토마토"}]
    if "호박고구마" in name:
        candidates = [c for c in candidates if compact(c.ingredient.canonical_name) == "고구마"]
    if "파프리카" in name:
        candidates = [c for c in candidates if compact(c.ingredient.canonical_name) == "파프리카착색단고추"]
    if any(compact(candidate.ingredient.canonical_name) == "백진주" for candidate in candidates):
        candidates = [
            candidate
            for candidate in candidates
            if compact(candidate.ingredient.canonical_name) not in {"멥쌀", "찹쌀"}
        ]
    matched_terms = [compact(candidate.matched_term) for candidate in candidates]
    candidates = [
        candidate
        for candidate in candidates
        if not any(
            compact(candidate.matched_term) != other and compact(candidate.matched_term) in other
            for other in matched_terms
        )
    ]
    hints = category_hints(scope_class, product.category_path)
    if hints:
        grouped: dict[str, list[Candidate]] = {}
        for candidate in candidates:
            grouped.setdefault(compact(candidate.ingredient.canonical_name), []).append(candidate)
        candidates = [
            item
            for group in grouped.values()
            for item in ([c for c in group if c.ingredient.category_name in hints] or group)
        ]
    best: dict[str, Candidate] = {}
    attributes_by_ingredient: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        previous = best.get(candidate.ingredient.ingredient_id)
        if previous is None or candidate.score > previous.score:
            best[candidate.ingredient.ingredient_id] = candidate
        attributes_by_ingredient.setdefault(candidate.ingredient.ingredient_id, {}).update(dict(candidate.attributes))
        attributes_by_ingredient[candidate.ingredient.ingredient_id].update(
            dict(product_attributes(product.variant_name, candidate.ingredient))
        )
    candidates = [
        Candidate(
            ingredient=candidate.ingredient,
            matched_term=candidate.matched_term,
            match_method=candidate.match_method,
            attributes=tuple(sorted(attributes_by_ingredient[candidate.ingredient.ingredient_id].items())),
            score=candidate.score,
        )
        for candidate in best.values()
    ]
    promoted_parent_ids = {
        candidate.ingredient.parent_ingredient_id
        for candidate in candidates
        if candidate.ingredient.parent_ingredient_id
    }
    candidates = [
        candidate for candidate in candidates if candidate.ingredient.ingredient_id not in promoted_parent_ids
    ]
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.ingredient.ingredient_id))
    if not candidates:
        return "UNMAPPED", scope_class, "연결 가능한 Ingredient가 없음", []
    if len(candidates) > 1:
        return "AMBIGUOUS", scope_class, "서로 다른 Ingredient 후보가 둘 이상", candidates
    return "CANDIDATE", scope_class, "단일 Ingredient 후보", candidates


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["variant_id", "mapping_status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products-path", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--database-url")
    source.add_argument("--ingredient-path", type=Path)
    parser.add_argument("--summary-path", type=Path, required=True)
    parser.add_argument("--candidates-path", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ingredients = (
        read_ingredients_from_database(args.database_url)
        if args.database_url
        else read_ingredients_from_file(args.ingredient_path)
    )
    summaries: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    for product in read_products(args.products_path):
        status, scope_class, reason, matches = match_product(product, ingredients)
        summaries.append(
            {
                "variant_id": product.variant_id,
                "variant_name": product.variant_name,
                "category_path": product.category_path,
                "mapping_status": status,
                "scope_class": scope_class,
                "reason": reason,
                "candidate_count": len(matches),
            }
        )
        for rank, match in enumerate(matches, 1):
            candidates.append(
                {
                    "variant_id": product.variant_id,
                    "candidate_rank": rank,
                    "mapping_status": status,
                    "ingredient_id": match.ingredient.ingredient_id,
                    "canonical_name": match.ingredient.canonical_name,
                    "category_name": match.ingredient.category_name,
                    "basis_level": match.ingredient.basis_level,
                    "source_identity_key": match.ingredient.source_identity_key,
                    "matched_term": match.matched_term,
                    "match_method": match.match_method,
                    "attributes": json.dumps(dict(match.attributes), ensure_ascii=False),
                    "reason": reason,
                }
            )
    write_csv(args.summary_path, summaries)
    write_csv(args.candidates_path, candidates)
    print(
        json.dumps(
            {
                "product_count": len(summaries),
                "candidate_row_count": len(candidates),
                "status_counts": {
                    status: sum(row["mapping_status"] == status for row in summaries)
                    for status in sorted({str(row["mapping_status"]) for row in summaries})
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
