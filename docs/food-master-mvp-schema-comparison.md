# Food Master MVP 스키마 변경안

## 결론

Food Master의 현재 MVP 책임은 **공식 원천 계층에서 선택한 안정적인 식품 정체성을 저장하는 것**이다.
`전국통합식품영양성분정보_원재료성식품_표준데이터`의 한 행이나 영양값을 그대로 저장하지 않는다.

구현 DDL은 [`database/ddl/001_food_master_mvp.sql`](../database/ddl/001_food_master_mvp.sql)에 둔다.

## 전후 비교

| 구분 | 기존 Food Concept 설계 | 변경 후 Food Master MVP |
| --- | --- | --- |
| 주 목적 | 식품 identity, 원천 관측, 속성, 상품 매핑 및 검수까지 하나의 설계로 관리 | 서비스 공통 Food identity와 그 생성 근거만 관리 |
| 핵심 엔터티 | `food_concept`, observation link, attribute 정의/정책, product-food map, hold/review | `food_source`, `food` |
| 원천 행 처리 | 원천 행을 관측·selector까지 별도 모델로 연결 | 원천 계층을 Food 생성 기준으로만 사용 |
| 중분류 처리 | R1~R6 정책, facet/selector, 검수 상태를 함께 관리 | 정책 결과로 선택된 대표·중분류·소분류만 Food의 basis로 저장 |
| 영양·원산지·생것/삶은것 | Observation/Attribute 모델에서 보존 | `food`에 저장하지 않음; 필요할 때 별도 테이블로 추가 |
| 상품 매핑 | Product Variant, 후보 상태, 속성·근거까지 포함 | 이번 DDL 범위 밖; 다음 단계에서 `product_food_mapping`으로 추가 |
| 내부 식별자 | `food_concept_id`와 다수의 파생 키 | PostgreSQL `food_id` 정수 키 |

기존 정책과 검수 산출물은 원천 계층을 선택하는 근거로 계속 참고할 수 있다. 다만 새 MVP DB는
그 전체 파이프라인을 선행 조건으로 요구하지 않는다.

## 데이터 모델

```text
food_source 1 ───< food >─── 0..1 parent food
```

### `food_source`

Food를 만들 때 사용한 데이터셋을 식별한다. 원천의 개별 행이나 영양 관측을 저장하는 테이블이 아니다.

| 컬럼 | 의미 |
| --- | --- |
| `food_source_id` | 내부 Source ID |
| `source_name` | 데이터셋 이름 |
| `source_version` | 기준일·배포 버전 |
| `source_uri` | 원본 다운로드 또는 설명 URL |

초기에는 `전국통합식품영양성분정보_원재료성식품_표준데이터`를 한 행으로 등록한다.

### `food`

| 컬럼 | 의미 |
| --- | --- |
| `food_id` | 내부 Food ID |
| `canonical_name` | 서비스에서 사용하는 표준 식품명 |
| `parent_food_id` | 상위 Food. 최상위 Food면 `NULL` |
| `category_name` | 원본 식품대분류명 |
| `basis_level` | Food 생성에 선택한 원본 계층: `REPRESENTATIVE`, `MIDDLE`, `SMALL` |
| `basis_code` | 선택한 계층의 공식 코드 |
| `basis_name` | 선택한 계층의 원본 명칭 |
| `basis_source_id` | Food 생성에 사용한 `food_source` |

`(basis_source_id, basis_level, basis_code)`는 유일해야 한다. 반면 `canonical_name`은 유일 제약을
두지 않는다. 서로 다른 공식 원천 branch의 동명 식품을 자동 병합하지 않기 위해서다.

## 생성 예시

| canonical_name | parent | basis_level | basis_name | 설명 |
| --- | --- | --- | --- | --- |
| 감자 | - | `REPRESENTATIVE` | 감자 | 수미·대지·생것·삶은것을 하나의 기본 Food로 묶음 |
| 호박 | - | `REPRESENTATIVE` | 호박 | 상위 식품 identity |
| 애호박 | 호박 | `MIDDLE` | 애호박 | 실제 식재료 단위이므로 별도 Food |
| 파 | - | `REPRESENTATIVE` | 파 | 상위 식품 identity |
| 대파 | 파 | `MIDDLE` | 대파 | 실제 판매·조리 단위이므로 별도 Food |

`생것`, `삶은것`, 품종, 원산지, 생산월, 영양성분은 `food`의 행이나 컬럼을 늘리는 근거가 아니다.
예를 들어 수미 감자와 대지 감자는 모두 `감자`에 연결하고, 필요한 시점에 관측 테이블에서 상태·품종을
선택한다.

## 의도적으로 다음 단계로 미룬 것

- 원본 행·영양성분·보관 정보: `food_observation`, `food_nutrition` 등으로 별도 추가
- Food alias와 검색어 정규화: 매핑 정확도 요구가 생길 때 추가
- 마켓컬리 Product Variant → Food 연결: `product_food_mapping` 테이블과 Python 매핑 스크립트로 추가
- 상품의 품종·부위·원산지·손질 상태: Product-Food 관계의 속성으로 추가
- R1~R6 정책·HOLD·사람 검수 이력: 매핑/운영 단계에서 필요한 범위만 별도 추가

이 분리는 Food identity를 먼저 안정화하고, 상품 매핑의 후보·근거·검수 요구가 확정된 뒤 필요한
테이블만 추가하기 위한 것이다.

## 적용 순서

1. PostgreSQL에서 `database/ddl/001_food_master_mvp.sql`을 실행한다.
2. 공식 원천 데이터셋을 `food_source`에 등록한다.
3. Food Master 정책으로 대표·중분류·소분류 중 Food가 될 계층을 선택해 `food`에 적재한다.
4. 다음 작업에서 마켓컬리 상품 원본과 `food`를 연결하는 Python 스크립트 및 매핑 테이블을 추가한다.
