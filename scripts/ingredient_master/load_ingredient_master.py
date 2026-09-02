"""Build and optionally load the MVP Ingredient Master from source CSV/Parquet.

The loader applies reviewed identity rules while keeping the database model
small:

* one representative Ingredient per resolved source branch;
* only reviewed middle-category promotions become child Ingredients;
* source-code collisions are resolved by explicit, versioned branch rules;
* normalized aliases (for example 맵쌀 국수/멥쌀 국수) are emitted once.

Nutrients, origin, production month, and raw/cooked state are source
observations. They are deliberately not copied into ``ingredient``.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, LiteralString, cast

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IDENTITY_RULES = ROOT / "config" / "ingredient_master_source_identity_overrides.csv"
DEFAULT_PROMOTION_RULES = ROOT / "config" / "ingredient_master_promoted_middle_foods.csv"
DEFAULT_DDL = ROOT / "database" / "ddl" / "001_ingredient_master_mvp.sql"
EMPTY_VALUES = {"", "-", "none", "null", "nan", "해당없음"}
LEVEL_FIELDS = {
    "REPRESENTATIVE": ("대표식품코드", "대표식품명"),
    "MIDDLE": ("식품중분류코드", "식품중분류명"),
    "SMALL": ("식품소분류코드", "식품소분류명"),
}
REQUIRED_FIELDS = {
    "식품대분류코드",
    "식품대분류명",
    *[field for pair in LEVEL_FIELDS.values() for field in pair],
}
IngredientKey = tuple[str, str]


@dataclass(frozen=True)
class IdentityOverride:
    large_category_code: str
    representative_code: str
    representative_name_raw: str
    resolved_code: str
    resolved_name: str
    status: str
    resolution_basis: str


@dataclass(frozen=True)
class PromotionRule:
    large_category_code: str
    representative_source_code: str
    representative_source_name: str
    resolved_representative_code: str
    resolved_representative_name: str
    middle_category_code: str
    canonical_name: str
    source_middle_codes: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class IngredientCandidate:
    basis_level: str
    basis_code: str
    basis_name: str
    canonical_name: str
    category_name: str
    source_identity_key: str
    parent_key: IngredientKey | None

    @property
    def key(self) -> IngredientKey:
        return (self.basis_level, self.source_identity_key)


@dataclass
class IngredientPlan:
    ingredients: list[IngredientCandidate]
    blocked_codes: list[dict[str, object]]
    normalized_merges: list[dict[str, object]]
    applied_promotions: list[dict[str, object]]

    def report(self) -> dict[str, object]:
        return {
            "planned_ingredient_count": len(self.ingredients),
            "representative_ingredient_count": sum(
                ingredient.basis_level == "REPRESENTATIVE" for ingredient in self.ingredients
            ),
            "promoted_ingredient_count": sum(ingredient.basis_level == "MIDDLE" for ingredient in self.ingredients),
            "blocked_code_count": len(self.blocked_codes),
            "blocked_codes": self.blocked_codes,
            "normalized_merge_count": len(self.normalized_merges),
            "normalized_merges": self.normalized_merges,
            "applied_promotion_count": len(self.applied_promotions),
            "applied_promotions": self.applied_promotions,
        }


def normalize(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in EMPTY_VALUES else text


def compact_name(value: str) -> str:
    """Return the compact name form used in a source identity key."""

    return "".join(value.split())


def representative_branch_key(large_category_code: str, resolved_code: str, resolved_name: str) -> str:
    return f"K-FIND:{large_category_code}:{resolved_code}:{compact_name(resolved_name)}"


def promotion_branch_key(
    large_category_code: str,
    resolved_code: str,
    resolved_name: str,
    canonical_name: str,
) -> str:
    return (
        representative_branch_key(large_category_code, resolved_code, resolved_name)
        + f":MIDDLE:{compact_name(canonical_name)}"
    )


def read_source(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - dependency error path
            raise RuntimeError("Parquet 입력에는 pyarrow가 필요합니다. `uv sync` 후 다시 실행하세요.") from exc
        return [dict(row) for row in pq.read_table(path).to_pylist()]
    raise ValueError("입력 파일은 .csv 또는 .parquet 이어야 합니다.")


def validate_source_columns(records: Iterable[Mapping[str, object]]) -> None:
    first = next(iter(records), None)
    if first is None:
        raise ValueError("원천 데이터에 행이 없습니다.")
    missing = sorted(REQUIRED_FIELDS - set(first))
    if missing:
        raise ValueError(f"원천 데이터에 필수 컬럼이 없습니다: {', '.join(missing)}")


def read_identity_overrides(path: Path) -> list[IdentityOverride]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "large_category_code",
        "representative_source_code",
        "representative_source_name_raw",
        "resolved_representative_code",
        "resolved_representative_name",
        "source_identity_status",
        "resolution_basis",
    }
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError("identity override CSV에 필수 컬럼이 없습니다: " + ", ".join(sorted(missing)))
    overrides: list[IdentityOverride] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        item = IdentityOverride(
            large_category_code=normalize(row["large_category_code"]),
            representative_code=normalize(row["representative_source_code"]),
            representative_name_raw=normalize(row["representative_source_name_raw"]),
            resolved_code=normalize(row["resolved_representative_code"]),
            resolved_name=normalize(row["resolved_representative_name"]),
            status=normalize(row["source_identity_status"]),
            resolution_basis=normalize(row["resolution_basis"]),
        )
        key = (
            item.large_category_code,
            item.representative_code,
            item.representative_name_raw,
        )
        if not all(key) or not item.resolved_code or not item.resolved_name:
            raise ValueError(f"identity override에 빈 key/value가 있습니다: {row}")
        if key in seen:
            raise ValueError(f"중복 identity override입니다: {key}")
        seen.add(key)
        overrides.append(item)
    return overrides


def read_promotion_rules(path: Path) -> list[PromotionRule]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "large_category_code",
        "representative_source_code",
        "representative_source_name",
        "resolved_representative_code",
        "resolved_representative_name",
        "middle_category_code",
        "canonical_name",
        "source_middle_codes",
        "reason",
    }
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError("promotion CSV에 필수 컬럼이 없습니다: " + ", ".join(sorted(missing)))
    rules: list[PromotionRule] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        source_middle_codes = tuple(
            code for code in (normalize(value) for value in row["source_middle_codes"].split("|")) if code
        )
        rule = PromotionRule(
            large_category_code=normalize(row["large_category_code"]),
            representative_source_code=normalize(row["representative_source_code"]),
            representative_source_name=normalize(row["representative_source_name"]),
            resolved_representative_code=normalize(row["resolved_representative_code"]),
            resolved_representative_name=normalize(row["resolved_representative_name"]),
            middle_category_code=normalize(row["middle_category_code"]),
            canonical_name=normalize(row["canonical_name"]),
            source_middle_codes=source_middle_codes,
            reason=normalize(row["reason"]),
        )
        key = (rule.large_category_code, rule.middle_category_code, rule.canonical_name)
        if not all(
            (
                rule.large_category_code,
                rule.representative_source_code,
                rule.representative_source_name,
                rule.resolved_representative_code,
                rule.resolved_representative_name,
                rule.middle_category_code,
                rule.canonical_name,
                rule.reason,
                rule.source_middle_codes,
            )
        ):
            raise ValueError(f"promotion CSV에 빈 key/value가 있습니다: {row}")
        if key in seen:
            raise ValueError(f"중복 promotion rule입니다: {key}")
        seen.add(key)
        rules.append(rule)
    return rules


def _source_indexes(
    records: list[dict[str, str]],
) -> tuple[
    dict[tuple[str, str], set[tuple[str, str, str]]],
    dict[tuple[str, str, str], set[tuple[str, str]]],
]:
    """Index representative identities and their observed middle categories."""

    representatives: dict[tuple[str, str], set[tuple[str, str, str]]] = defaultdict(set)
    middles: dict[tuple[str, str, str], set[tuple[str, str]]] = defaultdict(set)
    for row in records:
        large_code = normalize(row.get("식품대분류코드"))
        large_name = normalize(row.get("식품대분류명"))
        rep_code = normalize(row.get("대표식품코드"))
        rep_name = normalize(row.get("대표식품명"))
        middle_code = normalize(row.get("식품중분류코드"))
        middle_name = normalize(row.get("식품중분류명"))
        if large_code and large_name and rep_code and rep_name:
            representatives[(large_code, rep_code)].add((rep_name, large_name, large_code))
            if middle_code and middle_name:
                middles[(large_code, rep_code, rep_name)].add((middle_code, middle_name))
    return representatives, middles


def build_plan(
    records: list[dict[str, str]],
    identity_overrides: list[IdentityOverride],
    promotion_rules: list[PromotionRule],
) -> IngredientPlan:
    validate_source_columns(records)
    representatives, middles = _source_indexes(records)
    identity_map = {
        (
            item.large_category_code,
            item.representative_code,
            item.representative_name_raw,
        ): item
        for item in identity_overrides
    }
    blocked_codes: list[dict[str, object]] = []
    normalized_merges: list[dict[str, object]] = []
    candidates: dict[IngredientKey, IngredientCandidate] = {}
    parent_lookup: dict[tuple[str, str, str], IngredientCandidate] = {}

    for (large_code, rep_code), identities in sorted(representatives.items()):
        names = {(name, category, category_code) for name, category, category_code in identities}
        if len(names) != 1:
            matching = [
                item
                for item in identity_overrides
                if item.large_category_code == large_code
                and item.representative_code == rep_code
                and item.representative_name_raw in {name for name, _, _ in names}
            ]
            if len(matching) != len(names):
                blocked_codes.append(
                    {
                        "basis_level": "REPRESENTATIVE",
                        "large_category_code": large_code,
                        "basis_code": rep_code,
                        "identities": [
                            {"basis_name": name, "category_name": category} for name, category, _ in sorted(names)
                        ],
                        "reason": ("공식 대표식품 코드 충돌에 대한 branch rule이 없습니다."),
                    }
                )
                continue
        for rep_name, category_name, _ in sorted(names):
            override = identity_map.get((large_code, rep_code, rep_name))
            if override:
                resolved_code = override.resolved_code
                resolved_name = override.resolved_name
            else:
                resolved_code = rep_code
                resolved_name = rep_name
            source_key = representative_branch_key(large_code, resolved_code, resolved_name)
            candidate = IngredientCandidate(
                basis_level="REPRESENTATIVE",
                basis_code=resolved_code,
                basis_name=resolved_name,
                canonical_name=resolved_name,
                category_name=category_name,
                source_identity_key=source_key,
                parent_key=None,
            )
            if candidate.key in candidates:
                normalized_merges.append(
                    {
                        "large_category_code": large_code,
                        "representative_code": rep_code,
                        "source_identity_key": source_key,
                        "merged_name": rep_name,
                        "canonical_name": candidate.canonical_name,
                    }
                )
                continue
            candidates[candidate.key] = candidate
            parent_lookup[(large_code, rep_code, rep_name)] = candidate

    applied_promotions: list[dict[str, object]] = []
    for rule in promotion_rules:
        parent = parent_lookup.get(
            (
                rule.large_category_code,
                rule.representative_source_code,
                rule.representative_source_name,
            )
        )
        if parent is None:
            raise ValueError(
                "promotion parent가 대표 Ingredient에 없습니다: "
                f"{rule.large_category_code}/{rule.representative_source_code}/"
                f"{rule.representative_source_name}"
            )
        if (
            parent.basis_code != rule.resolved_representative_code
            or parent.basis_name != rule.resolved_representative_name
        ):
            raise ValueError(f"promotion의 resolved representative가 branch rule과 다릅니다: {rule}")
        observed = middles.get(
            (
                rule.large_category_code,
                rule.representative_source_code,
                rule.representative_source_name,
            ),
            set(),
        )
        observed_codes = {code for code, _ in observed}
        missing_middle_codes = sorted(set(rule.source_middle_codes) - observed_codes)
        if missing_middle_codes:
            raise ValueError(f"promotion의 middle code가 원천에 없습니다: {missing_middle_codes} ({rule})")
        selected_name = next(
            (name for code, name in observed if code == rule.middle_category_code),
            None,
        )
        if selected_name is None:
            raise ValueError(f"promotion basis middle code가 원천에 없습니다: {rule}")
        source_key = promotion_branch_key(
            rule.large_category_code,
            rule.resolved_representative_code,
            rule.resolved_representative_name,
            rule.canonical_name,
        )
        candidate = IngredientCandidate(
            basis_level="MIDDLE",
            basis_code=rule.middle_category_code,
            basis_name=selected_name,
            canonical_name=rule.canonical_name,
            category_name=parent.category_name,
            source_identity_key=source_key,
            parent_key=parent.key,
        )
        if candidate.key in candidates:
            raise ValueError(f"promotion identity가 중복됩니다: {candidate.source_identity_key}")
        candidates[candidate.key] = candidate
        applied_promotions.append(
            {
                "canonical_name": rule.canonical_name,
                "basis_code": rule.middle_category_code,
                "source_middle_codes": list(rule.source_middle_codes),
                "parent": parent.canonical_name,
                "reason": rule.reason,
            }
        )

    def resolve(
        candidate: IngredientCandidate,
        ordered: list[IngredientCandidate],
        visiting: set[IngredientKey],
    ) -> None:
        if candidate in ordered:
            return
        if candidate.key in visiting:
            raise ValueError(f"Ingredient parent 관계에 순환이 있습니다: {candidate.key}")
        if candidate.parent_key:
            parent = candidates.get(candidate.parent_key)
            if parent is None:
                raise ValueError(f"{candidate.key}의 parent가 Ingredient 생성 대상에 없습니다: {candidate.parent_key}")
            visiting.add(candidate.key)
            resolve(parent, ordered, visiting)
            visiting.remove(candidate.key)
        ordered.append(candidate)

    ordered: list[IngredientCandidate] = []
    for candidate in sorted(candidates.values(), key=lambda item: item.key):
        resolve(candidate, ordered, set())
    return IngredientPlan(ordered, blocked_codes, normalized_merges, applied_promotions)


def apply_plan(
    plan: IngredientPlan,
    database_url: str,
    source_name: str,
    source_version: str,
    source_uri: str | None,
    ddl_path: Path,
    apply_ddl: bool,
) -> None:
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("PostgreSQL 적재에는 psycopg가 필요합니다. `uv sync` 후 다시 실행하세요.") from exc
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            if apply_ddl:
                ddl = cast(LiteralString, ddl_path.read_text(encoding="utf-8"))
                cursor.execute(sql.SQL(ddl))
            cursor.execute(
                sql.SQL(
                    """
                INSERT INTO ingredient_master.ingredient_source
                    (source_name, source_version, source_uri)
                VALUES (%s, %s, %s)
                ON CONFLICT (source_name, source_version)
                DO UPDATE SET source_uri = EXCLUDED.source_uri
                RETURNING ingredient_source_id
                """
                ),
                (source_name, source_version, source_uri),
            )
            source_row = cursor.fetchone()
            if source_row is None:
                raise RuntimeError("ingredient_source_id를 반환받지 못했습니다.")
            source_id = int(source_row[0])
            loaded_ingredient_ids: dict[IngredientKey, int] = {}
            for ingredient in plan.ingredients:
                parent_id = loaded_ingredient_ids.get(ingredient.parent_key) if ingredient.parent_key else None
                cursor.execute(
                    sql.SQL(
                        """
                    INSERT INTO ingredient_master.ingredient (
                        canonical_name, parent_ingredient_id, category_name, basis_level,
                        basis_code, basis_name, source_identity_key, basis_source_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (basis_source_id, source_identity_key)
                    DO UPDATE SET
                        canonical_name = EXCLUDED.canonical_name,
                        parent_ingredient_id = EXCLUDED.parent_ingredient_id,
                        category_name = EXCLUDED.category_name,
                        basis_level = EXCLUDED.basis_level,
                        basis_code = EXCLUDED.basis_code,
                        basis_name = EXCLUDED.basis_name
                    RETURNING ingredient_id
                    """
                    ),
                    (
                        ingredient.canonical_name,
                        parent_id,
                        ingredient.category_name,
                        ingredient.basis_level,
                        ingredient.basis_code,
                        ingredient.basis_name,
                        ingredient.source_identity_key,
                        source_id,
                    ),
                )
                ingredient_row = cursor.fetchone()
                if ingredient_row is None:
                    raise RuntimeError(f"{ingredient.canonical_name}의 ingredient_id를 반환받지 못했습니다.")
                loaded_ingredient_ids[ingredient.key] = int(ingredient_row[0])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-path", type=Path, required=True)
    parser.add_argument(
        "--source-name",
        default="전국통합식품영양성분정보_원재료성식품_표준데이터",
    )
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--source-uri")
    parser.add_argument("--identity-rules", type=Path, default=DEFAULT_IDENTITY_RULES)
    parser.add_argument("--promotion-rules", type=Path, default=DEFAULT_PROMOTION_RULES)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--database-url")
    parser.add_argument("--ddl-path", type=Path, default=DEFAULT_DDL)
    parser.add_argument("--apply-ddl", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path, label in (
        (args.source_path, "원천 파일"),
        (args.identity_rules, "identity rule 파일"),
        (args.promotion_rules, "promotion rule 파일"),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label}을(를) 찾을 수 없습니다: {path}")
    database_url = args.database_url
    if not args.dry_run and not database_url:
        raise ValueError("실제 적재에는 --database-url이 필요합니다. 검토만 하면 --dry-run을 사용하세요.")
    if args.apply_ddl and not args.ddl_path.is_file():
        raise FileNotFoundError(f"DDL 파일을 찾을 수 없습니다: {args.ddl_path}")
    plan = build_plan(
        read_source(args.source_path),
        read_identity_overrides(args.identity_rules),
        read_promotion_rules(args.promotion_rules),
    )
    report = plan.report()
    if args.report_path:
        args.report_path.parent.mkdir(parents=True, exist_ok=True)
        args.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.dry_run:
        apply_plan(
            plan,
            database_url,
            args.source_name,
            args.source_version,
            args.source_uri,
            args.ddl_path,
            args.apply_ddl,
        )


if __name__ == "__main__":
    main()
