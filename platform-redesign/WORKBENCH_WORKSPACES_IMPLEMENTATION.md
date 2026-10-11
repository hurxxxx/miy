# Workbench 작업 환경 구현 기록

2026-10-11 사용자 `구현` 지시로 시작했다. 계획 원본은 [WORKBENCH_WORKSPACES.md](WORKBENCH_WORKSPACES.md), 상태 원본은 [WORK_ITEMS.md](WORK_ITEMS.md)다.

**현재 인수:** 개발 Core·별도 Workbench r21에 반영했고, 운영자 지원 단일 소유자의 native 개발 → 앱 미리보기 → MR117 필수 CI/리뷰 → dev 병합 → 안정된 개발 앱 실행 → 명시적 정리를 실제 확인했다. 원 정리 요청의 unknown은 MR121 관측 복구 후 같은 요청의 명시적 계속으로 완료했으며 임시 자원 부재·개발 앱/데이터 보존의 독립38항목도 통과했다. 상세 버전·실패 이력·실제 근거는 [배포 인수 기록](WORKBENCH_WORKSPACES_DEPLOYMENT.md)이 소유한다. 의미 검색(임베딩 서버 없음)·일반 직원 계정·다중 사용자·운영 rollout은 미검증으로 유지한다.

## 실행 범위

첫 구현 지시는 로컬 코드·문서·격리 검사까지였다. 이후 사용자가 **배포·실제 테스트·이전 앱 코드 정리 후 개편 방식 재검증**을 명시했다. 이에 개발 Core/별도 Workbench 배포·환경 준비·기존 시범 코드 보관/실행 중지·새 실제 사용자 흐름을 확인했다. 기존 시범 데이터·등록/세션 이력과 운영 플랫폼은 보존했다. 현재 상태와 실제 근거는 [배포 인수 기록](WORKBENCH_WORKSPACES_DEPLOYMENT.md)이 소유한다.

## 분담과 공통 계약

- Workbench backend: Workspace/독립 operation/Task 연결, lease, Git·checkpoint·MR와 API.
- Workbench UI: 작업 선택/상태/브랜치/앱 링크/반영/재개. 기존 일반 세션 호환.
- 앱 검색: optional manifest, SDK/API·권한, 설치 DB migration·projection/outbox, backend/gateway 소비.
- 통합 담당: Core 후보 소스/빌드/설치 연결, 실행 환경 adapter, 관리 프로파일·공용 빌드 경계, 생성 계약과 통합 검사, 소유 문서.

Git·환경 자격증명은 서버 밖으로 반환하지 않는다. 환경 operation은 UUID와 입력 버전을 보존하고 응답 유실을 성공이나 새 요청으로 바꾸지 않는다. 상세 구현 결과와 검사 근거는 통합 시 이 문서에 누적한다.

## 구현 결과

- Workbench SQLite `console_sqlite_0009`에 Workspace와 Task와 독립적인 operation을 추가했다. 같은 Project의 작업·브랜치·환경·여러 대화 연결, 단일 쓰기 lease, 중지/재개/응답 유실 관측을 제공한다.
- 검증한 `origin/dev`에서 이름 있는 기능 브랜치와 worktree를 만든다. `personal-apps/<app-id>/`만 native SDK executor에 노출하고 Git metadata·자격증명은 서버 broker에 남긴다. 플랫폼 `.env` 전체를 복사하지 않는다.
- Core의 후보 정의와 임시 installation은 정식 정의·안정된 개발 installation과 분리했다. 앱 subtree만 hash 검증·추출해 격리 빌드한다. 구현 턴의 실제 변경을 저장·갱신하며 실패한 빌드는 이전 실행 버전을 유지한다.
- 화면에서 브랜치·소스 버전·실행 상태를 확인하고 Core가 발급한 포털 앱 링크를 새 탭으로 연다. HMR/Workbench iframe은 추가하지 않았다.
- `개발에 반영`은 GitLab 필수 리뷰·CI와 정확한 MR 병합, 영속 소스 인계, 안정된 개발 installation의 실제 실행 관측을 연결한다. 병합만으로 완료 처리하지 않는다. 정리 후에도 안정된 앱 빌드는 MIY 저장소의 통합 소스를 사용한다.
- 정리는 작업 UUID·소유 receipt·Git 상태에 근거한다. 임시 앱 admission/실행기를 먼저 닫고 검색·DB·SDK units·worktree·기능 브랜치를 정리한다. 불명확한 결과나 새 변경은 보존한다. 검색 삭제 도중 응답 유실도 기록된 단계와 실제 자원 identity로 이어간다.
- 앱 검색 manifest·`search:read`·SDK/API, PostgreSQL 원본과 같은 트랜잭션의 outbox, Core embedding gateway와 OpenSearch/Qdrant adapter를 추가했다. 현재 원본 권한으로 검색 결과를 재확인한다. 검색을 선언하지 않은 기존 manifest의 digest는 유지한다.
- `personal-apps/**`를 Nx/root workspace 탐색에서 제외하고 별도 `personal_app_validation` 필수 CI를 연결했다. 설치된 신뢰 Core builder가 앱을 격리 검사하며 앱 소스의 host 실행은 허용하지 않는다.
- SDK v3 bundle을 오프라인 발급했다. v2 pin과 기존 bundle 검증은 보존했다. 관리 helper, systemd 예제, profile 예제, API/Workbench 생성 계약과 소유 문서를 갱신했다.

## 초기 로컬 검사 기록

반복 전체 검사를 피하고 변경 영역별 묶음 검사 뒤 실패/수정 부분만 재검증했다. 아래 수치는 서로 겹치는 실행이므로 합산하지 않는다.

| 영역 | 결과와 실제 검사 범위 |
| --- | --- |
| Core 위임·빌드/배포·runtime | 수정 후 117 PASS / 1 SKIP. 최초 통합의 DB 인자 누락과 gateway 경로 수 fixture 불일치 수정 |
| Workspace API·영속 소스 인계·환경/정리/CI | 통합 26 PASS 및 subtest 4. 후속 빌드 claim 경합·JSON null 정리·프로파일 확장 회귀 포함 최종 5 PASS |
| Manifest 정규화·runtime 정리 | 51 PASS. 기존 digest, search 선택 선언, 타 소유 자원 보존 포함 |
| Workbench backend 전체 | 최초 1,190 PASS / 9 FAIL / 25 SKIP. 기존 실패 9건 모두 수정 후 PASS, 자식 이력 보존 회귀 1건 추가 PASS. SDK/포장 3건과 migration 7건을 각각 재검증했으며 전체 검사는 반복하지 않음 |
| Workbench UI | 영향 33 PASS, TypeScript·production build PASS, ESLint 오류 0(기존 경고 2); Vite 큰 chunk 경고는 남음 |
| Native helper·SDK producer | helper 14 PASS, SDK 관련 19 PASS. 가짜 systemd lifecycle 및 실제 오프라인 v3 bundle 발급/검증; 실제 서비스 기동은 없음 |
| 검색 SDK·API/DB·삭제 복구 | SDK 47 PASS. 실제 격리 PG18 검색 9 PASS, 데이터/소유 정리 11 PASS, 부분 삭제 재개 4 PASS. HTTP/비활성 guard도 통과 |
| GitLab CI 계약 | 70 PASS, pipeline checker PASS |
| 생성 계약·구조 | API/schema·Workbench 계약·starter bundle 일치 PASS, API i18n/import 경계 PASS, Alembic 단일 head(35파일) PASS, 영향 Ruff/diff PASS |

실패 원인을 수정하며 기존 검사의 권한/업그레이드 assertion을 보존했다. 특히 SQLite migration의 테이블 재생성이 `ON DELETE CASCADE` 자식 이력을 삭제할 수 있는 문제를 실제 이전 데이터 fixture가 검출했다. FK를 끄거나 assertion을 줄이지 않고 테이블을 보존하는 native DDL로 수정했다. Fixture 보정 직후 5 PASS / 1 FAIL에서 확인된 실제 결함이며 최종 migration 7 PASS로 업그레이드·다운그레이드·재업그레이드의 자식 이력과 FK 무결성을 확인했다. 빌드가 claim된 직후 작업 중지가 발생해도 실패 상태와 슬롯을 회수하도록 수정했다. Core Alembic은 격리 테스트 DB에서 적용했으며 기존 개발/운영 DB에는 적용하지 않았다.

검색 검사는 실제 격리 PostgreSQL과 Qdrant SDK의 로컬 모드 및 HTTP 경계 fixture를 사용했다. 실제 OpenSearch/Qdrant 서버·embedding gateway·GitLab MR·native managed systemd·새 UI 전체 브라우저 흐름의 성공을 증명하지 않는다. SDK bundle 제작도 실행 호스트 설치를 뜻하지 않는다.

초기 로컬 단계의 `pnpm check:env-contract`는 당시 개발 `.env`에 새 키 `MIY_INDEPENDENT_APP_WORKSPACE_PROFILES`, `MIY_INDEPENDENT_APP_SEARCH_ENABLED`가 없어 **실패**했다. 설정 모델과 `.env.example`에는 기본 비활성 값을 반영했지만 그 단계에서는 실제 환경 파일·서비스를 변경하지 않았다. 이후 서버 준비·환경 계약 PASS는 [배포 인수 기록](WORKBENCH_WORKSPACES_DEPLOYMENT.md)에서 별도 근거로 확인한다. 원 실패를 PASS로 바꾸지 않는다.

로컬 receipt는 `.runtime/workbench-workspaces-20261011/`, `.runtime/structural-integration-20261010/`에 보존한다. 실제 서비스 상태·원격 필수 리뷰·CI의 대체 근거로 사용하지 않는다.

## 현재 남은 인수 범위

managed 대표 흐름과 정리는 실제 전달·독립 확인을 마쳤다. 검색은 승인 embedding 서버가 없어 비활성/미검증이며 엔진 격리 확인을 실제 앱 의미 검색 성공으로 표시하지 않는다. 일반 직원 계정·완전 자가 온보딩·다중 사용자·운영 rollout도 이번 운영자 지원 단일 소유자 인수로 대신하지 않는다. 최신 상태는 [배포 인수 기록](WORKBENCH_WORKSPACES_DEPLOYMENT.md)을 따른다.

## 초기 활성화 계획 — 당시 로컬 구현 종료 시점

아래는 실제 배포 전에 남겼던 계획이다. 코드·서버·SDK/runner 준비와 대표 앱의 dev 반영·정리는 이후 완료했으며, 이 목록을 현재의 미배포 상태로 읽지 않는다. 검색 활성화 한계는 위 현재 범위와 배포 문서에 남긴다.

1. 승인된 전달 절차로 코드와 별도 Workbench release를 준비하고 Core/SQLite 마이그레이션을 적용한다. 실제 환경 파일의 새 기본 키를 추가해 환경 계약 검사를 통과시킨다.
2. SDK v3 설치·검증, 보호된 managed helper 설정과 Linux user systemd/namespace를 준비한다. Core profile에 저장소·이미지·소유 경로·HTTPS 슬롯을 지정한다. 신규 앱의 안정된 개발 target과 명시적 `workspace` 위임을 준비한다.
3. 전용 개인 앱 CI runner와 신뢰된 entrypoint/config/image를 설치한다. 준비 전 해당 앱 MR의 필수 job은 통과할 수 없다.
4. 검색 엔진을 사설 접근으로 제한하고 Compose의 loopback 변경을 정상 절차로 적용한다. 승인 embedding 경로·검색 프로파일을 확인한 뒤 검색 기능을 활성화한다. 앱에 직접 엔진/DB 자격증명을 제공하지 않는다.
5. 장비 앱으로 새 작업 → native 편집 → 포털 실행 → 데이터/검색 → 재접속 → dev MR/병합 → 안정된 개발 앱 실행 → 임시 자원 정리를 한 번의 대표 브라우저 인수로 확인한다. 실패 빌드/응답 유실·새 변경 보존도 함께 확인한다.

위 항목은 필수 활성화·인수 작업이다. 후속 고도화로 넘기지 않는다. 실행 중인 외부 mutation과 중지 요청을 강제로 끊지 않고 관측 가능한 상태에서 이어간다. 검색 provisioning의 불명확한 상태는 자동 삭제하지 않으며 운영자 확인이 필요하다. GitLab target은 병합 전후 검증하나 API 자체가 원자적 target CAS를 제공하지 않으므로 경합은 HOLD로 남긴다.

다중 사용자·다른 OS 실행 호스트·장비 앱 업무 기능/검색 화면·HMR·운영 앱 검색 승격·고급 복구 화면은 [후속 고도화](FOLLOW_UP_ENHANCEMENTS.md)로 분리했다. 기존 장비 앱 저장소/실행·데이터를 이 구현에서 이전하거나 삭제하지 않았다.
