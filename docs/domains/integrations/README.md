# 플랫폼 API 키와 외부 연계 계약

이 도메인은 회사 내부 또는 승인된 외부 시스템이 miy의 제한된 company-level
projection을 읽는 경계를 소유한다. 조직·임직원 디렉터리와 앱 관리 집계를 읽기 전용으로
제공하며 사용자 세션, 관리자 API, 앱 API를 대신하는 범용 서비스 계정이 아니다.

핵심 결정과 보안 근거는
[ADR 0010](../../../adr/0010-platform-api-key-directory-integration.md)에 기록한다.

## 자격 증명 경계

- 새 키는 `miy_pk_` 접두사를 가진 opaque bearer token이다. 기존 `mty_pk_` 키도
  동일한 검증·scope·폐기 정책으로 인정한다. 기존 암호문의 버전별 key-derivation purpose는
  유지하며, 브랜드 변경만으로 토큰·hash·암호문을 다시 쓰지 않는다.
- 외부 endpoint는 일반 사용자 access token을 거부하고, 일반 API도 플랫폼 API 키를 사용자
  세션으로 인정하지 않는다.
- 서버는 인증용 SHA-256 hash, 목록용 prefix, 관리자 재표시용 암호문만 저장한다.
- 암호화에는 전용
  `MIY_PLATFORM_API_KEY_ENCRYPTION_KEY`를 사용한다. 값이 없으면 키 발급·재표시는
  fail closed지만 기존 hash 기반 인증은 계속 동작한다.
- 폐기 시 암호문을 즉시 비우고 hash row는 감사·재사용 방지를 위해 보존한다. 폐기된 키는
  다시 활성화하거나 재표시할 수 없다.
- 키 원문, Authorization header와 암호문은 API 응답 목록, 로그, 감사 payload에 넣지 않는다.
  발급·재표시 응답과 인증 실패 응답에는 `private, no-store`를 적용한다.

관리자가 키를 재표시할 수 있는 것은 현재 승인된 제품 요구사항이다. 따라서 전용 암호화 키의
접근 통제가 키 데이터베이스 접근 통제만큼 중요하다. 재표시 작업은 항상 감사한다.

## Scope와 endpoint

| Scope               | Method and path                                         | Projection                                        |
| ------------------- | ------------------------------------------------------- | ------------------------------------------------- |
| `organization:read` | `GET /api/v1/integrations/directory/organization-units` | 조직 계층과 활성 상태                             |
| `people:read`       | `GET /api/v1/integrations/directory/people`             | 사용자 식별·프로필·주 소속 메타데이터             |
| `app-catalog:read`  | `GET /api/v1/integrations/apps`                         | 앱 식별자·회사 활성화·설치 버전·운영 AI 등록 여부 |
| `app-usage:read`    | `GET /api/v1/integrations/apps/{app_id}/usage`          | 앱별 월간 실행·AI 토큰 집계                       |

Scope registry는 코드의 고정 allowlist이며 임의 문자열 scope를 발급할 수 없다. 각 route는
OpenAPI의 `x-miy-platform-api-scopes` extension으로 요구 scope를 선언한다. 관리자
목록 API는 이 OpenAPI 계약에서 scope별 operation과 Swagger/ReDoc 링크를 파생한다. 문서 목록을
별도 하드코딩하지 않는다.

외부 목록은 `page`와 최대 200인 `page_size`를 받는다. 디렉터리는 기본적으로 활성 항목만,
앱 목록은 비활성 앱도 활성 여부와 함께 반환한다.
응답은 요청 시점의 현재 상태 projection이다. 페이지 사이의 snapshot consistency, delta token,
tombstone, webhook과 exactly-once 전달은 현재 제공하지 않는다. 장기 동기화 consumer는 전체
재조정이 가능해야 한다.

## 관리자 수명주기

| 기능              | API                                                | 권한                      |
| ----------------- | -------------------------------------------------- | ------------------------- |
| 목록과 scope 문서 | `GET /api/v1/admin/platform-api-keys`              | `platform_api_key.read`   |
| 발급              | `POST /api/v1/admin/platform-api-keys`             | `platform_api_key.write`  |
| 재표시            | `POST /api/v1/admin/platform-api-keys/{id}/reveal` | `platform_api_key.reveal` |
| 폐기              | `POST /api/v1/admin/platform-api-keys/{id}/revoke` | `platform_api_key.write`  |

현재 `platform_admin`만 이 권한들을 가진다. 관리 UI는 `/admin/api-integrations`에 있으며 원문을
브라우저 저장소에 쓰지 않고 dialog를 닫을 때 component state에서 제거한다.

## 감사와 운영

- 발급 감사는 actor, API key ID와 승인된 scope를 기록한다. 목록·재표시·폐기는 actor와 key
  수명주기를, 성공한 외부 read는 API key ID, scope가 고정된 operation, 결과 수와 paging 정보를
  기록한다. 키 원문과 projection 본문은 감사 payload에 넣지 않는다.
- 키 hash와 prefix로 원문을 복원할 수 없다. 재표시는 암호문을 통해서만 수행한다.
- 암호화 root를 변경하면 기존 키 인증은 계속 가능하지만 기존 암호문 재표시는 불가능해진다.
  회전 시 새 root로 새 키를 발급해 consumer를 전환한 뒤 이전 키를 폐기한다.
- 외부 쓰기, SCIM provisioning, inbound webhook, customer-defined scope, IP allowlist와 키별 rate
  limit는 현재 non-goal이다. 추가 시 별도 위협 모델과 rollout gate가 필요하다.

## 검증

- API, scope, 저장·폐기·감사 계약:
  `apps/api/tests/test_organization_integrations.py`, `apps/api/tests/test_app_integrations.py`
- OpenAPI/generated client: `pnpm generate:api-client`, `pnpm check:api-contract`
- Migration graph: `pnpm check:alembic-graph`, `pnpm test:alembic-graph`

## 인사 그룹 조회

외부 `/integrations/directory/organization-units`와 `organization:read` 범위는 인사 정보 출처 그룹의
읽기 전용 projection으로 유지한다. 직접 생성 그룹은 이 범위에 포함하지 않는다. 응답의 ID와
상위 ID, 사용자 주 소속 ID는 그룹 ID이며 `source_reference`로 인사 원본 식별자를 제공한다.
기존 조직 ID의 이전과 참조 갱신은 [사용자·그룹·인사배치 계약](../organization/README.md#마이그레이션과-검증)을 따른다.

## 앱 관리 조회

앱 집계 응답은 `schema_version: 1`과 생성 시각을 포함한다. 카탈로그는 canonical 앱 계약,
회사 앱 활성화 설정, 등록된 AI workload, 실행 프로세스의 고정된 runtime revision과 독립 앱 등록·설치를 읽는다.
`enabled`는 회사의 앱 활성화 여부이며 개별 사용자의 실행 권한을 의미하지 않는다.
MIY Web/API/Worker의 앱은 `miy-app` 배포 단위를 공유한다. 별도 서비스인 MIY Workbench의
설치 버전은 MIY API에서 추정하지 않고 `null`로 반환한다.
관리 메타데이터가 없어도 앱은 포함하며 배포 단위·설치 버전을 임의로 채우지 않는다.
독립 앱의 활성 표시는 production 설치가 ready인 경우이며 개별 사용자 admission은 별도로 검사한다.
`page`(1부터), `page_size`(1~200)로 전체를 조회하며 총 앱 수에는 200개 제한이 없다.
표시 정체성(`title`, `title_translations`, `icon_key`)도 같은 등록 정의에서 제공한다.
독립 앱은 해당 정의의 `source_repository`, `source_directory`, `definition_digest`를 포함하며
Workbench가 소유자 지정 체크아웃을 검증하는 데 사용한다. 저장소 URL은 정의의 비밀 없는 HTTPS
정체성이며 자격 증명·소유자/그룹 목록·호스트 실행 명령은 반환하지 않는다.
`catalog_revision`은 전체 projection의 해시로 페이지 사이의 앱·활성 상태·설치 변경을 감지한다.
소비자는 모든 페이지의 revision·총 개수와 중복·누락을 검증한 뒤 완전한 관측으로 취급한다.

독립 앱의 `GET /api/v1/integrations/apps/{app_id}/installations`도 `app-catalog:read`로
조회한다. 같은 페이지·revision 계약으로 환경·주소·활성 여부·generation과 실제 설치된
release/revision/digest, 각 설치의 최신 배포 요청 ID·상태·안전한 실패 코드를 반환한다.
아직 반영되지 않은 queued/unknown 요청을 설치 성공으로 해석하지 않는다. 이 값은 내구성 있는
배포 기록이며 서비스의 현재 HTTP 응답이나 자원 상태를 측정한 health check가 아니다.
사용자·그룹·승인 권한 목록, 런타임 설정·자격 증명은 포함하지 않으며 이 키로 배포 요청을
생성하거나 실행할 수 없다. 지원하지 않는 기존 내장 앱 ID 또는 미등록 ID는 404다.

사용량의 선택적 `month=YYYY-MM-DD`는 해당 날짜가 속한 UTC 월을 지정한다. 앱 열기는
`app.open` 이벤트, 운영 AI 호출은 같은 앱·월의 `llm_call` 감사 기록에서 집계한다.
사용자·업무 내용·프롬프트·원본 오류·키·설정은 반환하지 않는다. AI 기록은 최대 100,000건을
집계하며 초과 시 `complete: false`를 반환한다. 토큰을 보고하지 않은 호출은
`unreported_calls`로 표시하고, 모든 호출의 토큰이 미보고이면 `total_tokens: null`이다.
호출 자체가 없으면 0이다. 현재 출처에는 청구 금액이 없으므로 `amount_minor: null`,
`cost_basis: not_reported`를 반환한다. 개발용 구독 토큰과 운영 AI 토큰은 합치지 않는다.

기존 키에 scope가 자동 추가되지는 않는다. 관리자가 필요한 두 읽기 scope만 승인해 발급한
키를 [Workbench의 서버 설정](../../apps/codex-console/README.md)에 연결한다. 성공한 앱 read는
키 ID·operation·대상 앱을 감사하고 `private, no-store`를 적용한다. 키 폐기나 MIY 장애는
Workbench의 독립 로그인·개발·복구 기능을 막지 않으며 원격 집계는 확인 불가 상태가 된다.
