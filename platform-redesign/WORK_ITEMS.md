# 재설계 작업 목록

**이전 재시작 뒤 구현 재개 기록 — 2026-10-07:** [RESTART_CHECKPOINT.md](RESTART_CHECKPOINT.md)의 동결 입력을 확인했다. PMS 부모 통합과 Recording managed의 비활성 권한·전달·legacy 영향 검증·독립 리뷰를 마쳤다. 공식 UI source/build 12/12개와 최종 두 build·브라우저 통합을 마쳤다. 독립 API·데이터·worker 서비스와 Workbench native 실행은 필수 잔여다. 일회성 [긴급 백업](EMERGENCY_BACKUP.md)은 완료했으며 추가 게시·배포 없이 로컬 작업을 이어간다.
작업별 상태와 의존성의 원본이다. 목표와 설계는 [PLAN.md](PLAN.md), 현재 위치는 [STATUS.md](STATUS.md), 증거는 [VALIDATION.md](VALIDATION.md)를 참조한다.

**2026-10-07 재개:** 중간 점검에서 정한 구조 우선 기준으로 제품 구현을 재개한다. 공식 UI 전체 모듈 소유권·worker 실행 세대·source outbox 전달 경계를 병렬 진행한다. 원본88개 보호와 비활성 worker profile 기반은 로컬 검증을 마쳤다.

현재 승인 범위는 [구조 우선 기준](PLAN.md#구조-완성-우선과-앱별-후속-작업)의 구현·검증과 사용자가 후속 지시한 커밋·push·upstream PR·정상 병합 및 개발/운영 배포다. 필수 리뷰·전체 릴리스 CI·저장 공간·배포 계약을 통과한 뒤 해당 전달을 진행하며 기존 실패를 면제하지 않는다. 앱별 비필수 개선·상세 검증은 [APP_ISSUES.md](APP_ISSUES.md)에 별도로 보류하며 아래 작업의 의존성에 포함하지 않는다. `ready`는 의존성 충족을 뜻하며 커밋·원격 변경·운영 배포 승인을 뜻하지 않는다.

## 상태와 완료 규칙

`planned → ready → in_progress → validating → done`을 사용한다. 실제 장애 요인이 있는 항목은 `blocked`, 명시적으로 후속으로 미룬 항목은 `deferred`다. 미착수를 장애로 표시하지 않는다.

- 착수 전에 변경 경로, 관련 계약과 세부 완료 조건을 확인한다. 기존 하네스·스킬은 절차로 적용하지 않고 최소화 대상으로 검토한다.
- 구현·관련 검증·소유 문서 갱신을 모두 마쳐야 제품 작업을 `done`으로 표시한다. 문서 작업 완료와 구분한다.
- 변경된 구조 계약·대표 경로와 치명적 실패 경계의 검증은 각 작업에서 수행한다. `VAL-001`까지 미루지 않는다. 앱별 상세 기능 검증은 이슈 대장으로 분리하고 별도 지시 전까지 수행하지 않는다.
- 상태 변경 시 근거를 연결하고 현재 단계에 영향이 있으면 `STATUS.md`를 갱신한다.
- 작업 분할 시 기존 ID는 승인된 구조 범위를 소유하는 부모 작업으로 유지하고 하위 ID를 추가한다. 부모는 해당 하위 작업의 완료와 연결 확인 후 완료한다. 보류한 앱별 이슈는 구조 작업의 필수 하위 항목으로 집계하지 않는다.
- 각 작업은 해당 경로의 지침 점검을 반드시 수행한다. 충돌이 있으면 필요한 `POL-001`~`POL-003` 범위의 전환·검증을 먼저 수행하고 근거를 연결한다. 충돌이 없는 작은 수정·읽기 전용 조사가 전체 정책 전환을 기다릴 필요는 없다.
- 표의 의존성은 결과·계약이 실제 필요한 연결이다. 같은 경로의 동시 수정은 순서를 조정하며 표 자체가 여러 에이전트의 병렬 실행을 지시하지 않는다.

## 문서와 경로별 정책 전환

| ID      | 작업과 변경 범위                                      | 의존성  | 상태        | 완료 조건·근거                                                                    |
| ------- | ----------------------------------------------------- | ------- | ----------- | --------------------------------------------------------------------------------- |
| DOC-001 | 루트의 계획·정책·작업·상태·진행·검증 문서 7개 생성    | 없음    | done        | 최초 문서 기준선. `D-001`~`D-004`                                                 |
| REV-001 | 공식 사례·개발 원칙·AI native 방법론과 계획·코드 대조 | DOC-001 | done        | [REVIEW.md](REVIEW.md)의 근거·권고·한계. `D-005`, `D-006`                         |
| DOC-002 | 리뷰 8개 항목을 목표 설계·정책·작업·검증 기준에 반영  | REV-001 | done        | 반영 위치·의존성·상태 일치, 제품 미착수 유지. `D-007`                             |
| POL-001 | 변경 경로별 지침·스킬·ADR·검사기의 충돌 적용표 보완   | DOC-002 | in_progress | 경로별 유지·대체·제외 대상, 대체 검사·소유자 확정. 모든 경로가 정리되면 전체 완료 |
| POL-002 | 해당 경로의 지침·도구 연결·스킬 선택·구조 검사 전환   | POL-001 | in_progress | 신규 독립 앱과 기존 유지보수 경로 구분, 필수 경계 보존. 경로별 적용 근거 누적     |
| POL-003 | 변경 경로의 새 세션·재개 세션 회귀 평가               | POL-002 | in_progress | 실제 지침 선택·결과, 버전·기준선·반복 평가. `A-001`~`A-003`                       |

`POL-001`~`POL-003`은 전체 적용 범위의 집계 작업이다. 경로별로 조사→전환→평가를 진행하고 집계 작업 전체가 끝나기 전에도 해당 범위의 근거를 사용할 수 있다. 활성 지침을 바꾸지 않은 이번 문서 반영으로 이 작업들을 완료하지 않는다.

## 앱 발견과 계약

| ID      | 작업과 변경 범위                                   | 의존성  | 상태        | 완료 조건·근거                                                                           |
| ------- | -------------------------------------------------- | ------- | ----------- | ---------------------------------------------------------------------------------------- |
| CAT-001 | 기존 카탈로그의 누락·표시·전체 조회 개선           | DOC-002 | done        | 허용된 앱의 발견과 개발/미리보기/배포 가능 상태 구분, 제한 이유·조회 오류 표시. `F-001`  |
| CAT-002 | 정의·릴리스·설치 계약, manifest 투영과 기존 어댑터 | DOC-002 | in_progress | 원본·투영 소유, 버전·폐기·소비자 호환, 정의 오류/삭제와 설치 제거 분리. `F-002`, `F-004` |

기존 목록 수정과 새 계약 설계는 서로의 전체 완료를 기다리지 않는다. 공통 필드나 어댑터가 겹치면 계약을 먼저 맞춘다.

## 기존 Workbench 사용성과 후속 앱 연결

| ID      | 작업과 변경 범위                                      | 의존성                   | 상태        | 완료 조건·근거                                                                                                         |
| ------- | ----------------------------------------------------- | ------------------------ | ----------- | ---------------------------------------------------------------------------------------------------------------------- |
| WB-001  | 기존 Task·native 실행에 여러 앱·저장소·개발 환경 연결 | ENV-001                  | in_progress | 허용된 경로·실행 권한, 소비 RPC 호환, 단일 소유자·SQLite·구독 인증·이력 보존. `F-005`, `F-006`, `A-003`                |
| WB-002  | 세션 탐색·전환·재개와 에이전트 상태·결과·중단 경험    | DOC-002                  | in_progress | 기존 저장소에서 먼저 검증. 기록·로드·turn·연결 상태 구분, 입력 보존, 재접속 중복 실행 방지. `F-006`, `F-007`, `A-003`  |
| WB-003  | 표준 템플릿·하네스·자연어 맥락 연결 전체              | WB-003A, WB-003B         | planned     | 두 하위 범위의 통합과 기존 동작 회귀 확인. `F-008`, `F-009`                                                            |
| WB-003A | 기존 검토·테스트 템플릿과 맥락·완료 근거 개선         | DOC-002                  | in_progress | 기존 버전·snapshot·launch 중복 방지 재사용, 필요한 맥락 선택, 대표 자연어 반복 평가. `F-008`, `F-009`, `A-001`~`A-003` |
| WB-003B | 새 앱 미리보기·배포·복구 계약을 기존 템플릿에 연결    | WB-003A, WB-001, REL-001 | in_progress | 앱·환경·산출물·검증 근거 확인, 외부 배포 조회·재개, 권한 내 셀프서비스. `F-003`, `F-008`, `F-010`                      |
| WB-004  | 운영 관측과 점검·복구 연결 전체                       | WB-004A, WB-004B         | planned     | 관측과 조치의 연결, 독립 서비스 장애·stale·unknown 처리. `F-010`                                                       |
| WB-004A | 기존 읽기 전용 관측의 상태·시각·버전 표시 보완        | DOC-002                  | done        | 기존 관측 재사용, 미확인 값 추정 금지, 관측만으로 운영 변경 없음. `F-010`                                              |
| WB-004B | 새 앱·미리보기 관측과 점검·복구 템플릿 연결           | WB-004A, WB-003B         | in_progress | 실제 설치·릴리스·외부 요청 상태 연결, 실패·재시작·응답 유실 복구. `F-010`                                              |

`WB-002`, `WB-003A`, `WB-004A`는 새 앱 런타임 전체를 기다리지 않는다. `WB-001` 연결 후 여러 저장소·환경에서 해당 흐름을 추가 검증한다. 계정 풀은 실제 계정 유형의 공식 지원을 확인한 경우에만 활성화한다. 진행 중 계정 임의 교체, 자동 API 과금 전환, 다중 사용자 로그인·DB 전환은 추가하지 않는다.

## 독립 앱 시범 적용·개발 환경·배포

| ID       | 작업과 변경 범위                                      | 의존성             | 상태        | 완료 조건·근거                                                                                                |
| -------- | ----------------------------------------------------- | ------------------ | ----------- | ------------------------------------------------------------------------------------------------------------- |
| APP-001  | 앱 세션 교환, SDK와 포털 호스트 연결                  | CAT-002            | in_progress | 범위·수명·철회·교환 재사용 방지, 메시지 검증, 쿠키 제한·독립 로그인·탐색 확인. `F-002`, `F-004`, `F-006`      |
| ENV-001  | 앱·브랜치별 코드·실행·데이터·미리보기 환경            | CAT-002            | in_progress | 검증된 프로파일, 호스트 명령·마운트·자격증명 경계, 기본 자원 제한·정리, worktree 충돌 처리. `F-004`, `F-005`  |
| APP-002  | 웹·API·worker 계약과 앱 템플릿·마이그레이션 연결 전체 | APP-002A, APP-002B | planned     | UI 및 DB·권한 시험 앱의 전체 생성·등록·실행 근거와 공통 계약 정리. `F-002`, `F-004`                           |
| APP-002A | 최소 웹·API·worker 계약과 UI 시험 앱 템플릿           | APP-001, ENV-001   | in_progress | UI 앱 생성·등록·미리보기, 포털 앱별 코드 수정 없음. `F-002`, `F-004`                                          |
| APP-002B | DB·권한 시험 앱과 데이터·마이그레이션 계약 확장       | REL-001A           | in_progress | UI 앱 전체 흐름 확인 뒤 DB 앱 생성·등록·실행, 데이터·권한 경계 확인. `F-002`, `F-004`                         |
| REL-001  | 검증된 불변 산출물 배포·상태 확인·복구 전체           | REL-001A, REL-001B | planned     | UI 및 DB 앱의 독립 배포·증거·반복 요청·복구 검증 통합. `F-003`, `F-010`                                       |
| REL-001A | UI 시험 앱의 불변 산출물 배포·조회·복구               | APP-002A, ENV-001  | in_progress | UI 앱 전체 흐름 연결. 소스·digest·환경·검증 일치, 응답 유실·중복 요청·이미지 복구. `F-003`, `F-010`의 UI 범위 |
| REL-001B | DB 앱 배포·마이그레이션·복구 검증                     | APP-002B, REL-001A | in_progress | DB 앱에 같은 배포 계약 적용, 반복 마이그레이션 방지·DB 호환·이미지/DB 복구 구분. `F-003`, `F-004`, `F-010`    |
| ENV-002  | 로컬·서버 공통 환경 호환과 자원 제한·수용량 측정      | ENV-001            | in_progress | 실제 제한값·초과 동작 확인, 미리보기 4개·무거운 빌드 1개 목표 측정. `F-005`                                   |

`ENV-001`의 기본 격리·자원 제한은 앱 실행 전 충족한다. 병행 실행 수용량을 측정하는 `ENV-002` 전체 완료는 단일 앱 배포 경로 개발의 선행 조건이 아니다. `APP-002A`→`REL-001A`에서 UI 시험 앱의 생성→등록→미리보기→배포→복구를 먼저 연결하고, `APP-002B`→`REL-001B`에서 DB·권한 시험 앱으로 확장한다. UI 앱 배포가 DB 시험 앱의 준비를 기다리지 않게 부모 작업도 분할했다. 기능별 검증은 진행 중 함께 수행하며 두 앱의 완료 근거가 있어야 전체 시범 적용을 마친다.

## 공식 앱 경계·분리와 이전

| ID        | 작업과 변경 범위                                       | 의존성                                                             | 상태        | 완료 조건·근거                                                                                                        |
| --------- | ------------------------------------------------------ | ------------------------------------------------------------------ | ----------- | --------------------------------------------------------------------------------------------------------------------- |
| OFF-001   | 공식 업무 기능과 공통 기반의 소유·API·데이터 경계 조사 | DOC-002                                                            | done        | 소유자·소비자·접근 의미·호환 범위와 ADR 대체 대상 정리. Workbench 완료를 기다리지 않음 [조사 기록](OFFICIAL_APPS.md). |
| OFF-002   | 공식 앱 묶음의 프로젝트·빌드·서비스·릴리스 분리        | OFF-001, APP-002, REL-001                                          | in_progress | 하위 단계와 시범 적용 근거 반영, 기존 ID·경로·데이터·공통 API 호환, 독립 배포·복구. `F-003`, `F-004`                  |
| OFF-002A  | 공식 묶음 UI 프로젝트·빌드와 소유 경계                 | OFF-001                                                            | in_progress | 단방향 composition adapter, 프로젝트 순환 없음, 기존 앱 ID·scope·직접 링크 보존. 실제 서비스 전환과 구분              |
| OFF-002B  | 공식 API·worker 서비스와 데이터 소유 경계 분리         | OFF-002A, APP-002, REL-001                                         | in_progress | 공통 인증·권한 계약, 단일 writer, DB 권한, worker·검색·파일 소비자 호환, 독립 서비스 artifact·복구 검증               |
| MIG-001   | 기존 앱 순차 이전과 정적 조립·임시 호환 경로 정리      | OFF-002                                                            | planned     | 앱별 전환·복구·변경 계약과 대표 소비자 검증, ID·주소·권한·데이터 보존. 앱 전체 업무 검증은 별도 보류                  |
| VAL-001   | 전체 작업 흐름의 통합·자원·복구·지침 회귀 확인         | CAT-001, MIG-001, ENV-002, WB-001, WB-002, WB-003, WB-004, POL-003 | planned     | 각 작업의 기존 증거 대조와 연결·누락 검증. `F-001`~`F-010`, `A-001`~`A-003`                                           |
| CLOSE-001 | 설치·운영·앱 계약·지침의 최종 소유 문서와 인수 정리    | VAL-001                                                            | planned     | 구현 중 갱신한 소유 문서의 최종 일치 확인, 임시 예외 종료와 인수                                                      |

설치·운영 소유 문서는 실제 구현이 바뀌는 작업에서 함께 갱신한다. `CLOSE-001`까지 갱신을 미루지 않는다.

`OFF-002A/B`는 실제 코드·데이터 소유와 빌드·실행·배포 경계 완성에 집중한다. 소스 이전 중 발견한 문제는 구조 필수·치명적 여부로 분류하며 비필수 앱 개선을 추가하지 않는다. `VAL-001`은 동적 등록→개발→미리보기→배포→관측·복구의 연결과 권한·데이터 보존을, `CLOSE-001`은 그 근거와 후속 이슈의 분리를 확인한다. 이슈 대장이 남아 있어도 구조 기준을 충족하면 구조 인수할 수 있으며 전체 앱 기능 인수 완료로 표현하지 않는다.

### 현재 하위 구현 근거와 다음 연결

2026-10-08 PR70 병합 뒤 사용자의 다음 구현 지시로 세 경계를 진행한다.
`OFF-002B`의 인증 전용 최소 열·현재 정책 reader와 Files private root 폴더/
평면 자식 1~16개 변경, `WB-001/002`의 개인 앱 Task 시작 전 연결·설정 확인이다.
각 경로를 분리해 멀티에이전트로 구현·리뷰하고 실제 제한 계정과
지연·회수·취소 경계를 검증했다. 세 하위 범위의 독립 차단 결함은0이다.
공식 조회52·기존 영향69, 폴더 pure21/actual26, Workbench Python98/UI183을
각 범위로 구분하며 [검증 기록](VALIDATION.md)에 초기 실패와 입력 시점을 남긴다.
아래 최초 인수 당시에는 로컬 미커밋·비활성 범위였으며
전체 reader HTTP 전환, tree publication/hold, native sandbox·전체 자연어
개발/배포 완료로 표시하지 않는다. 새 operational grant/서비스/게시 변경은
하지 않았다. 이 결과는 아래 역사적 인수 수에 합산하지 않는다.

2026-10-07 23:46 UTC에 현재 재설계 checkpoint를 GitHub PR69로 병합하고
이번 작업 브랜치를 원격·로컬 모두 삭제했다. dev/main은 유지했다.
[게시 기록](PUBLICATION_CHECKPOINT.md)과 [고정 Source aggregate slice](FILES_SOURCE_AGGREGATE.md)가
후속 구현을 소유한다. private native root File 한 개의 Source-only
soft-delete·exact event observer와 공유 Session routing 거부를 로컬 비활성
범위로 인수했다. 작성자41·실제 제한 Source 고유30·기존 영향81개와 독립
리뷰의 차단 결함0을 확인했다. 병합 후 코드는
[GitHub PR70](https://github.com/hurxxxx/miy/pull/70)으로 게시했다. 다음은
전체 tree의 유한 명령과 publication hold·원자 apply 조립이다. 이 첫 slice는
전체 tree/publication나 OFF-002B 완료를 뜻하지 않는다. runtime 계약은
[SOURCE_MUTATIONS.md](../apps/api/src/miy_api/domains/files/SOURCE_MUTATIONS.md)가,
실행별 입력과 한계는 [VALIDATION.md](VALIDATION.md)가 소유한다.
후속작업의 착수 순서·의존성과 완료 기준은 [NEXT_STEPS.md](NEXT_STEPS.md)에
식별했으며 해당 작업 상태의 원본은 이 작업표를 유지한다.

Files F4 후속: Core effect의 최신 controlled102·generation/helper110과 actual Data83·Source72·mandatory175개를 구분해 로컬 비활성 인수와 독립 리뷰를 마쳤다. 최소 owner58/caller125 SELECT와 신규 SQL/기존46 계약 불변, ACK/unknown 결과·동시성·이력·세션 소유권을 확인했다. Source TEMP 인증/cancellation은 최신 actual81·현재243개 불변과 독립 리뷰로 인수했다. 준비된 vector 한도 adapter는 고유118개·별도 기존39개 영향, 현재selected29·owned4 불변과 독립 리뷰로 인수했다. bounded PUT도 현재68개·actual0/small/250MiB version/SHA·missing-Version2 case·selected21/actual10 불변과 독립 리뷰로 인수했다. 다음은 Source aggregate와 publication/원자 apply 조립이다. 런타임은 files/PUBLICATION_STORAGE.md가 소유한다. durable caller retention·불변 publication·tree/bootstrap·F5 서비스 조립은 필수 잔여다. 이 checkpoint로 OFF-002B나 전체 F4를 완료하지 않는다.

- `OFF-002A`: 공식 UI **12/12개**의 전체 source/build 소유 이전을 로컬 검증했다. Diagrams·Bento·Mail·Whiteboard·Community·Docs·Recording·Meeting·Planner·PMS·Files·Video Chat이 실제 suite 소유이며 공용 Chatbot은 platform 소유다. 최신 PMS 부모 독립 비교는 구현 94개·소비자 본문 5개·HTML·전체 catalog 동등성이며 suite 917/platform 124/root 44/PMS 318개 및 타입·경계 검사를 보존한다. 새 두 build·production browser 각 31개, actual-dev 새 PMS 다섯 경로가 통과했다. 전체 dev30 PASS/1기존 Meeting read-count fixture FAIL은 APP-ISS-007로 구분한다. 선택 입력 1,734개 중 제품 등 1,733개·owner 275개는 불변이며 후기 E2E 하나만 보완했다. Files·Video Chat·공용 Chatbot의 부모 비교는 실제 본문74개·Video helper14개·전체 catalog·CSS·Files 공개 API와 owner254/review35개를 확인했다. 최종 포털 build8,567 modules/26.23초·공식 build7,833 modules/22.81초, 포털37·공식36개의 고유 합성 브라우저 PASS와 selected dev6 PASS를 마쳤다. official의 portal-only Chatbot skip1개와 각 Whiteboard 별도 실행을 명시하고 중복을 합산하지 않는다. 선택 입력1,823개는 두 build 전부터 최종 브라우저 뒤까지 불변이다. source/build 통합 인수는 12/12개지만 독립 runtime/release·전체 portal 업무 조립 정리는 완료로 표시하지 않는다. 해당 UI의 상세 근거는 별도 기록을 따르며 앱 기능 인수로 확대하지 않는다. source/build 소유 이전을 별도 서비스·릴리스 활성화로 확대하지 않는다. [VALIDATION.md](VALIDATION.md), [APP_ISSUES.md](APP_ISSUES.md)가 증거·후속을 소유한다.
- `OFF-002B`: 원본 **88/88** guard와 source/Core transport 권한 분리, 비활성 worker profile, Files·Mail·Recording의 주요 claim·COMMIT·외부 효과 경계를 로컬 검증했다. 고정 4종 source outbox/Core receipt와 신규 Docs visibility 생산점도 연결했다. 최신 Core Docs legacy repair는 source SELECT만으로 고정 세 종류를 원자 변환하며 actual PG **238 PASS**, captured 107/최종 owner 등 116개·과거 migration 23개 불변과 독립 리뷰를 통과했다. Recording legacy 발행 응답 유실·두 retry의 권한 공백도 actual PG **68 PASS**, 입력 164/owner 6개와 독립 리뷰로 보완했다. 원 attempt·audio를 보존하며 retry reset+attempt는 한 COMMIT이다. 고정 네 단계 Source command/Core publication 두 표의 비활성 구현과 현재 권한·영향 legacy·독립 리뷰를 마쳤다. 동시 Core 준비 경쟁을 재현한 뒤 고정 ON CONFLICT와 기존 binding의 현재 권한 재검사로 보완했다. actual PG pipeline **37 PASS**, 최종 authority/이전 schema/원본88개/fixture **95 PASS·입력785개**, 영향 legacy **125 PASS·입력180개**, 원자 복원·실패 경계 **6 PASS**를 기록했고 독립 리뷰의 17개 입력도 그대로다. 초기 legacy 122 setup ERROR와 중간 fixture 실패는 보존하며 제품 SQL/역할 권한을 넓히지 않고 exact empty baseline과 한 transaction의 복원으로 수정했다. 검사 수는 중복 포함이며 합산하지 않는다. wire11·worker23·API 구조736/3250도 통과했으나 실제 broker·ACK·서비스 근거가 아니다. 기본 API는 legacy, official profile은 비활성 상태를 유지한다. Docs/PMS/회의 Source-only 전달과 Files F1/F2 경계는 로컬 비활성 범위로 인수했다. Files F3의 고정 Core ingress/consumer·partition 잠금·현재 결과 표식 검사는 로컬 비활성 범위로 인수했다. native189개·mandatory167개와 입력812/813개 불변·독립 리뷰를 확인했고 중복을 합산하지 않는다. F4는 runner 소유권51개·Core setup30개·별도 Source descriptor47개와 영향173개·독립 검토를 마쳤다. 정렬 corpus 선잠금 workset34개, pinned transport29개와 실제 소유 MinIO를 확인했고 명령 영향51개와 strict paired reader55개·실제 READ profile34개 고유 검증 및 독립 리뷰를 마쳤다. 다음은 durable effect/lifecycle 조립이다. 전체 bootstrap과 publication/effect 완료로 표시하지 않는다. Files 불변 입력/업로드·allocation/트리·materializer 최신 Source event provenance·remote 불확실성·broker/Beat·auth/ACL/audit/routing·최소 서비스 권한과 실제 서비스 조립은 남는다. 기존 wheels/image는 최신 소스를 포함하지 않는다. shared DB migration/grant·운영 consumer·공식 owner·서비스 활성화는 수행하지 않았다. 단계별 근거는 [VALIDATION.md](VALIDATION.md)가 소유한다.
- `OFF-002B` 근거 시점: 각 PG 실행 당시 selected before==after와 소유 자원 정리는 확인했다. 이후 UI 소유 경로 생성으로 현재 authority785에는 Core `app_contracts_generated.py`와 suite `ownership.json` 두 경로, legacy180에는 생성 Core metadata 한 경로의 차이가 있다. managed37의 captured180에는 후기 conftest 복원 수정과 생성 Core metadata가 달라졌으며 제품 프로토콜은 그대로다. UI metadata·원자 복원 수정은 해당 후속 근거와 구분하고 현재 전체 source hash가 과거 capture와 같다고 표시하지 않는다. 운영 적용에는 새 schema expand와 matched 신규 principal/artifact, 현재 서비스 app/ACL·AI/audit·credential 권한, 실제 bounded broker/queue/Beat, remote unknown receipt·취소·복구와 구형 stranded attempt 조정이 필요하다. 이는 앱별 후속 이슈로 넘기지 않는 필수 구조 작업이다.
- `APP-001`: 설치별 PKCE 앱 세션과 iframe/독립 popup, 기존 인증을 유지하는 선택적 테마·언어 초기값/변경 통지를 구현했다. SDK·host·canonical template·별도-origin 브라우저와 실제 두 template Docker 빌드/실행을 검증했다. 탐색은 [SDK_NAVIGATION.md](SDK_NAVIGATION.md)의 앱ID/설치 기반 제안·현재 권한 재조회·사용자 클릭 방식으로 구현했다. SDK 19개·웹 60개·실제 iframe/popup/제안 후 권한 회수 브라우저를 통과했고 canonical starter도 갱신했다. 파일 선택은 [SDK_FILES.md](SDK_FILES.md)의한 파일/10MiB/짧은 목적별 서명/현재Files ACL·세션으로 구현·검증했다. 실제PG151+후속2/SDK44/host45/picker28과 최종portal27개 중파일4개·새WB후보8d8b5fa8을 확인했다. 동기SQL선점 없는 기한/실제환경키 미적용/liveMinIO미검증을 구분한다. 추가 공통 API 계약과 실제 운영 배치 도메인의 브라우저 검사는 남아 있다.
- `WB-003B`·`APP-002A/B`: 준비된 source/installation에서는 typed delivery 도구를 사용할 수 있다. 새 Project에서 코어가 배포한 starter·SDK로 허용한 새 source 생성·첫 Git commit·binding을 연결했다. 현재 clean 소스를 읽는 등록 초안과 파일 내보내기, MIY 소유자 로그인에서 personal 정의·비활성 development 설치를 원자적으로 만드는 API·portal 화면도 구현했다. 설치 목록·설치별 Task 선택은 기존 기능을 재사용한다. 현재 소스와 등록 정의/commit의 차이를 명시적으로 조회하는 연결도 구현했다. 파일 없는 최초 등록 1회 위임의 Core·portal은 실제 PG 154개·portal unit 48개·브라우저 4개 및 독립 리뷰를 통과했고, Workbench 현재 세션/Task·private credential·native adapter의 등록/기존 복구 94개와 실제 서버 브라우저 3개도 통과했다. 세션/RPC 교체 차단과 고정 receipt 복구를 확인했고 기존 전체 브라우저 33개·등록 3개와 동일 frontend인 SQLite 0008 후보 `6bd4401f…` 검증까지 통과했다. [OWNER_PREVIEW.md](OWNER_PREVIEW.md)의 소유자 초기 개발 설정도 실제 PG 158개·포털 unit 78개·새 브라우저 3개로 검증했다. SDK/설정 링크를 더한 `3d724785…`는 frontend159개·등록3/source준비1을 확인했다. 현재 최신 후보는 최종 파일SDK의 `8d8b5fa8…`이며 SQLite/vault/backup/두starter/packagedUnicode검사로 검증했다. 새 후보에서 이전 browser/native 결과를 다시 수행했다고 표시하지 않는다. 최초 등록/설정은 실행 준비를 뜻하지 않으며 전체 자연어 전달·executor·위임 연결은 미완료다.
- `WB-002`: 입력 텍스트·문서 초안·목록 검색/필터/선택에 이어 작업별 대화 위치와 최신 항목 따라가기를 보존한다. 실제 브라우저의 목록/작업/뒤로가기·모바일 재노출을 확인했다. 현재 페이지의 최근 100개 작업에 한정하며 새로고침·지연 이미지 재배치는 별개다. 첨부·skill 선택 보존과 전송/로그아웃 정리, 저장된 결과/현재 native loaded 상태 분리와 관측 실패·stale 표시도 구현하고 통합·독립 후보 검증을 마쳤다. 새 에이전트 실행 엔진을 만들지 않는다.
- `WB-002` 관측 하위 범위: 기존 Task/Agent 실행 상태·lease와 독립된 nullable projection에 native thread 상태·확인 시각·마지막 turn·조회 시도/실패를 저장한다. root는 기존 `thread/read(includeTurns:false)`를 사용하고 turn 알림/child 조회를 재사용한다. 이전 완료 기록에서 loaded 상태를 추정하지 않으며 SSE 단절·조회 실패가 재실행을 일으키지 않는다. pinned 소비 계약·generation·부분 조회 실패·실제 PostgreSQL frozen import·별도 0007 후보를 통과했다. 실행별 실패와 수정 후 재검사는 검증 문서에 구분한다.
- `VAL-001`: 집중 결과를 전체 계획 완료로 합산하지 않는다. 최종 통합·새 앱 자연어 전체 흐름·native 격리 실행은 각각 별도 근거가 필요하다. 상세 실행 수·초기 실패·한계는 [VALIDATION.md](VALIDATION.md)가 소유한다.

`OFF-002B`의 Docs/PMS/회의 하위 경계는 준비된 Source-only hook과 별도 Core 수락을 구현하고 집중 실제 PostgreSQL **70개**를 통과했다. 원본/Core 각각의 COMMIT까지 metadata SHARE, 같은 event ID/digest 복구, Core 새·병합 job의 즉시 발행 억제를 포함한다. 기존 원본90개·Recording·권한·migration·legacy 영향은 **343 PASS/4 fixture FAIL** 뒤 해당 세 테스트 파일의 **102 PASS**로 정정 검증했다. 최종1,101개 입력과 제품·이전25 migration의 불변성을 확인했으며 두 실행은 중복된다. 전체 서비스 전환 상태는 계속 `in_progress`다. Source의 회사 default-only와 Core의 유효한 managed 허용 계약은 구분한다. 실행 당시 불변성과 이전 UI 통합 시점의 metadata 비교를 현재 전체 API hash 동일성으로 확대하지 않는다.

`OFF-002B`의 Files F1은 Core cached-ready reader·actual event/head/checksum·명시적 not-ready·Source 쓰기 없는 callback과 최소 reader role을 인수했다. metadata 권위 필드 덮어쓰기, 실행 전/후 제어오류 분류, hold COMMIT unknown의 일반 retry 진입, 기존 bootstrap의 제거된 설정 참조를 함께 수정했다. 최신 제한 native/external2를 포함한 영향 API는 초기96 PASS/4 FAIL 뒤 bootstrap7 PASS(3중복)로100개 고유 수락, 최종1,148개 불변과 이전26 migration 보존이다. reader65·재현1과 final worker47은 별도 범위다. F2는 원문 중간 복제 없이 요청/result/event ID·durable claim/input과 canonical artifact+terminal digest를 Source에 저장하는 로컬 경계를 인수했다. ready/unsupported는 실제 result intent까지 같은 COMMIT, known failed는 새 intent 없이 history만 확정한다. shared pure artifact76 PASS·Root 독립 검토와 최소 current-policy query의 기존35 PASS를 마쳤고 새 제한 role/명령/runner는 actual PG74·후기41·mandatory270 고유 수락과 독립 검토를 마쳤다. 이는 F2 인수 시점의 근거이며 F4 runner 보완은 별도 시점으로 기록한다. current actor/app/ACL 조회를 실제 최소 column profile에 맞추며 Core pending/ready 수락·immutable object·partition/트리·서비스 조립은 필수 후속이다. [FILES_SOURCE_RESULTS.md](FILES_SOURCE_RESULTS.md)가 단계별 계획을 소유한다.

## 후속 작업

| ID      | 범위                         | 상태     | 이번에 하지 않는 일                                     |
| ------- | ---------------------------- | -------- | ------------------------------------------------------- |
| FUT-001 | 다중 사용자 Workbench        | deferred | 사용자별 로그인·권한·대화·자격증명·작업 데이터 격리     |
| FUT-002 | 공유 Workbench 저장소와 운영 | deferred | 다중 사용자용 PostgreSQL 전환과 사용자별 자원·계정 배정 |
| FUT-003 | 공식 앱의 추가 서비스 분리   | deferred | 공식 묶음 내 각 앱을 일괄 개별 서비스로 분리            |

## 작업 기록 형식

```text
작업 ID와 하위 범위:
변경 경로와 제외 범위:
의존 작업과 기준 소스 버전:
경로별 정책 판단·전환·회귀 평가 근거:
선택한 스킬과 참조 버전:
완료 조건과 기능 검증:
남은 항목 또는 중단 이유:
다음 행동:
```

- `CAT-002`·`WB-003B` 최초 등록 하위 범위: Core API의 UUID·입력 digest·현재 권한·원자적 rollback·동시 요청을 실제 PostgreSQL에서 검증했다(71개). Workbench 현재 소스의 읽기 전용 초안과 정규화 호환을 연결했다(영향 회귀 137개, 삼자 정규화 45개). 핵심 계약의 불리언 거부/정수 버전 호환 검사를 기존 CI에 추가했고 새로운 일반 개발 하네스는 만들지 않았다. 파일 전달 UI·portal 등록·독립 Workbench 후보도 검증했으며 전체 자연어 생성→등록→실행 완료와 구분한다.
- `CAT-002`·`WB-004B` 등록 관측 하위 범위: 기존 metadata 조회 scope에 등록 commit과 관측 지원 버전을 additive로 추가했다. Workbench가 현재 소스와 비교해 일치/정의·commit 차이/소스 충돌/명확한 미등록/확인 불가를 구분한다. capability 없는 이전 서버·페이지 변경·stale 자료로 미등록을 확정하지 않는다. backend 116개·Core 실제 PostgreSQL 44개·전체 frontend 143개와 독립 리뷰, 상태 확인과 기존 설치 화면 연결의 실제 브라우저·최종 독립 후보 검증을 마쳤다. 등록 이후 실행 준비와 자연어 전체 흐름의 완료는 별개다.

### 2026-10-08 후속 전달과 다음 P0

PR78/MR85까지 fixture 보완과 필수 리뷰·게시·정리를 마쳤으며 `REL-001`의 실제 운영 전달은 full225/393의 저장 공간 선행조건 해소를 기다린다. 테스트 실행0을 제품 실패로 분류하지 않는다. Current state/evidence는 STATUS·PUBLICATION_CHECKPOINT·VALIDATION이 소유한다.

`OFF-002B`는 별도 로컬 worktree에서 기존14표/87열 reader의 server-owned HTTP 조립에 착수했다. 옵션 미구현의 실제 red와 raw cancellation의 admission gap을 먼저 재현하고, current scope/credential→restricted auth→Source ACL 순서·private503·cleanup을 검증한다. Default/ASGI는 비활성이며 operational grant/cutover 완료가 아니다. `WB-001/002`·`ENV-001`은 정확0.160.1 public package/protocol 검사를 준비했고 offline native helper 선행조건을 확인한다. 실제 지원 executor·hard bounds·turn·resume/history 인수는 남는다. 기존 작업 상태는 계속 in_progress로 유지하며 새 app 상세 기능·다중 사용자 범위는 추가하지 않는다.

## 2026-10-08 — 현재 OFF-002B HTTP 하위 범위

공식 auth-only HTTP의 현재 로컬 검증은 pure31 PASS/8.60초, 실제 PostgreSQL·HTTP13 PASS/27.42초, 기존 composition10 PASS/10.75초다. 서로 다른 선택31+13은 새44개이고 기존10개는 별도 영향 범위다. Raw·반복 host cancellation와 AnyIO 대기/실행 취소에서 worker 종료·Session 정리 전 admission을 반환하지 않는 경계를 확인했다. 네 HTTP GET은 genuine 현재 앱 세션/binding·제한된 auth PostgreSQL 역할·실제 Source ACL을 사용했다. Business Source fixture는 권한 있는 합성 계정이므로 최소 Source operational 역할 전체 인수로 확대하지 않는다. Profile14표/87열과 기존 기본 인증·비활성 ASGI를 유지했고 API architecture/i18n·independent app schema/OpenAPI/contract source --check를 통과했다. Operational role/grant·WS·공식 서비스 전환은 아직 하지 않았다.

상위 OFF-002B·Workbench 격리 실행·최종 네 영역의 상태를 완료로 바꾸지 않는다. 앱별 세부 기능·다중 사용자는 기존 보류를 유지한다.

## 2026-10-08 16:06 — 실제 저장 공간 기준 회복

2026-10-08 16:06 UTC의 실제 Docker 저장 경로 검사가15.0GiB free/84.7% used로 기존15GiB·15% 기준을 통과했다. 앞선225/393의 저장 공간 실패는 역사로 보존한다. 실제 free 증가의 원인이나 cache reclaimed 수와의 인과는 확정하지 않는다. 여유 폭이 작으므로 최신 source의 필수 전체 CI에서도 원래 floor를 그대로 확인한다. 다음 auth HTTP의 최종 독립 리뷰·정상 feature 병합 후 최신 dev 전체 릴리스를 진행하며 운영은 아직 배포하지 않았다.

## 2026-10-08 — HTTP 전달 완료와 WS 구조 착수

공식 auth HTTP `782b9844`는 필수226/394 SUCCESS/177.379623초 뒤 GitHub PR79의 `cf06470b`, 내부 MR86의 `77abc792`로 정상 병합했다. 두 merge tree는 `ecb4ab56c53ea5740fe6475cf201d3ddbddfba70`로 같으며 소유 feature 브랜치를 양쪽 원격·로컬에서 정리했다. Persistent dev/main과 upstream push 차단은 유지했다. 최신 전체227/395는19.517891초에 저장 공간 검사에서 실패해 제품 테스트0이다. 잠깐의15.0GiB floor 통과는 실행 준비 뒤의 지속 여유를 보증하지 않는다. 스토리지 여유 확보와 정확한 최신 source/target/tree 전체 CI가 운영 전달의 필수 선행조건이며 main/prod는 `9e9280df`다. 새 운영 배포는 없다.

Workbench 자원 선행검사는 task-owned systemd transient service에서 UID1000·private network namespace·CPUQuota50%·MemoryMax256MiB·MemorySwapMax0·TasksMax16의 실제 kernel 값을 확인했다. 실제15개 자식이 같은 owned cgroup에 있고 다음 fork가 EAGAIN으로 거부됨을 parent에서 관측했다. 자식 전체를 reap하고 임시 unit 부재를 확인했다. 최초 child-side 관측 실행 뒤 같은 case의 parent-side 관측 보강을 반복했으며 고유 범위로 합산하지 않는다. 메모리 압력·native-in-manager·제품 executor/WS/turn 인수로 확대하지 않으며 기존 서비스·host policy·auth는 변경0이다. 표준 socket-proxyd의 별도 합성 ingress 검증과 현재 Codex/Task 경로 보존을 이어간다.

다음 OFF-002B 작업은 `77abc792` 기반 별도 worktree의 Docs·Whiteboard WS 인증 조립이다. 기존 제한 auth callable/budget와 public HTTPConnection/Yjs authorize callback을 재사용하고 고정 route scope로 접속·주기·각 recv/send의 current auth→Source ACL/writer fence 순서를 연결한다. Default·비활성 ASGI·14표/87열·room/codec/hub·운영 role/grant를 보존한다. 이 구현은 아직 별도 로컬 작업이며 최소 Source service 역할·검색/AI approval/audit·공식 cutover·네 영역 전체 인수는 남아 있다.

## 2026-10-08 — WS 로컬 인수와 Workbench native 환경 선행조건

현재 dev는 `77abc792`, main/prod는 `9e9280df`다. PR79/MR86은 리뷰226/394 뒤 병합·소유 feature 브랜치 정리를 마쳤다. 전체227/395는 저장 공간 검사 실패로 제품 테스트0이다. 16:06의 일시적인15.0GiB 통과 뒤 다시 실패했으므로 지속 headroom과 최신 source/target/tree의 정상 full CI가 필요하다. 기준을 낮추지 않으며 새 운영 배포는 없다.

Docs·Whiteboard의 준비된 WS 조립은 pure16·실제 PostgreSQL/native WS30으로 새46개를 인수했고, 기존 HTTP44·composition10의 영향54개도 통과했다. 시간은 ws_pure: 5.33s, ws_native: 56.40s, ws_compat: 40.57s다. 실제 Source 편집 공유를 read로 회수한4개 recv/send 검사와 current auth·writer fence·private503/1013·제한 reader 취소/permit 경계를 확인했다. 초기 pure13 PASS/3 FAIL은 공개 WebSocket 생성자 fixture를 수정한 동일 선택의 전후 결과이며 고유 성공 수에 합산하지 않는다. 제품 조립 전 Source trap 관측 red1도 보존한다. 첫 계약 검사의 domain→composition-root 역방향 import는 공용 WS 어댑터를 도메인 소유 모듈로 옮겨 수정했다. 그 구조 변경 뒤 영향을 받는 pure/native/HTTP 검사를 재실행한 현재 결과이며 전후 실행을 합산하지 않는다. API architecture/i18n와 생성 API/독립 앱/OpenAPI/contract source 검사를 통과했다. Business Source는 권한 있는 합성 fixture이며 최소 Source operational 역할·전체 Source worker 취소를 인수한 것이 아니다. 14표/87열·기본 인증·비활성 ASGI·hub/codec/room·운영 role/grant를 보존했다. 아직 별도 로컬 미커밋이며 최종 독립 인수·필수 리뷰·정상 게시/병합은 남아 있다.

Workbench의 정확 Codex0.160.1은 표준 systemd-socket-proxyd ingress와 owned transient supervisor 안에서 기존 executor_probe로 실제 인증 없는 연결 거부·정확 버전/cwd·native readOnly/workspaceWrite·자식 명령·Git 쓰기 거부·host canary 비노출을 통과했다. Native와 proxy는 같은 private network namespace의 loopback만 사용했고 caller namespace와 달랐다. 실제 kernel 한도는 CPU1·메모리1GiB·swap0·PIDs64, UID1000·capability0·no-new-privileges이며 endpoint와3개 owned unit/process/cgroup 정리도 통과했다. 앞선 합성 ingress37bytes·자원 fork 한도 검사는 각각 별도 선행조건이다. 같은 pin의 공개 JSON schema440개로 기존0.159.2 소비 계약과 별도0.160.1 remote 계약의 호환을 확인했다. 현재 설치된 CLI/템플릿/서비스·설정은 변경하지 않았다. 구독 인증을 사용하는 실제 제품 Task의 계획 승인→수정→같은 thread 재개/history·중단/단절과 재사용 가능한 운영 설정 적용은 남아 있다. Remote app mount에는 인증을 복사하지 않는다. 기존 secured API·Runtime·SQLite·Codex 수명을 재사용한다.

## 2026-10-08 18:38 — 최신 착수 상태

`OFF-002B`는 auth HTTP와 Docs·Whiteboard WS의 필수 리뷰·양쪽 정상 병합을 마쳤다. 준비된 Whiteboard Source ACL callback의 제한 조회·현재 권한 재검사·읽기 전용 실행/정리와 영향 검증을 로컬 인수했고 최종 독립 검토·정상 feature 전달을 진행한다. 최소 operational 역할·room 초기화/영속화·Docs Source·공식 cutover는 필수 잔여이므로 in_progress다.

`WB-001/002`·`ENV-001`은 원 native Task의 계획·승인 후 격리 수정·동일 thread 후속 요청을 실제 인수했다. Cold resume 호환 수정은 필수 리뷰 뒤 양쪽 정상 병합·소유 브랜치 정리를 완료했다. 다음 최소 재사용 운영 정의·실제 중단/단절·별도 Workbench 서비스 적용·개인 앱 전체 흐름은 남아 상태는 in_progress다.

`REL-001`·`VAL-001`은 full231/399의 저장 공간 선행조건 실패로 in_progress다. 최신 dev는 `436c7792`, main/prod는 `9e9280df`이며 전체 검증·MR81 병합·새 운영 배포·네 영역 전체 인수는 미완료다. 앱별 기능·다중 사용자 범위는 추가하지 않는다.

## 2026-10-08 18:52 — Source 전달과 native 정의 후속

`OFF-002B`의 준비된 Whiteboard Source ACL 읽기 하위 범위는 독립 검토·필수 리뷰·정상 양쪽 병합·소유 브랜치 정리를 마쳤다. Initial collab row readOnly loader와 room/writer가 보장된 초기화·영속화·Docs Source·operational 최소 역할·서비스 전환은 남아 in_progress다.

`WB-001/002`·`ENV-001`의 최소 표준 native executor 정의는 source-only 구현·단위/공개 parser 검사를 마쳤다. 최종 독립 리뷰·정상 전달과 immutable 운영 cache·실제 설치 enforcement·보호 설정·별도 Workbench 서비스 반영·중단/단절·개인 앱 전체 흐름은 남아 in_progress다.

`REL-001`·`VAL-001`은 full233/401의 저장 공간 실패로 in_progress다. 현재 dev `4764fc2c`, main/prod `9e9280df`이며 전체 릴리스·MR81 병합·새 운영 배포·네 영역 전체 인수는 미완료다. 앱별 비필수 기능·다중 사용자 범위는 유지한다.

## 2026-10-08 19:12 — native source 전달 뒤 room 초기 읽기

`WB-001/002`·`ENV-001`의 최소 native executor 정의·설치 entrypoint는 독립 검토·필수 리뷰·양쪽 정상 병합·소유 브랜치 정리를 마쳤다. Immutable 운영 cache·실제 설치 enforcement·보호 설정·별도 Workbench 서비스·중단/단절·대표 SDK 도구 체인/개인 앱 전체 흐름은 남아 in_progress다.

`OFF-002B`는 기존 room Source 초기 readOnly의 실제 미구현 red를 확인하고 승인된7경로를 구현 중이다. Source writer·room identity CAS·현재 권한과 COMMIT unknown을 보장하는 초기화/영속화·Docs Source·minimum operational 역할·cutover는 필수 잔여다.

`REL-001`·`VAL-001`은 full235/403의 저장 공간 실패/tests0로 in_progress다. Dev `c7520d05`, main/prod `9e9280df`이며 전체 릴리스·운영 반영·네 영역 전체 인수는 미완료다. 앱별 세부 기능·다중 사용자는 보류한다.

## 2026-10-08 — 재시작 복구와 기존 room Source 초기 읽기 인수

서버 재시작 뒤 Source7·보호62·dev `c7520d05`와 기존 prod `9e9280df`를 확인하고 미완료 단계만 재개했다. 기존 collab 상태를 fresh readOnly Source transaction에서 읽는 명시적 비활성 초기 로더를 인수했다. 앱·edit ACL을 읽기 전후 재조회하고 정리 뒤 동일 auth callable·actor/session 및 server assembly identity를 재검증한다. 동일 paired SELECT의 scene/snapshot/Yjs 합계8MiB를 SQL CASE로 전송 전에 제한하고 detached DTO를 재검증한다. 부분 설정·missing/stale/invalid/초과 상태는 private503/1013으로 거절하며 legacy init/repair로 우회하지 않는다. Global hub persistence와 writer/CAS·COMMIT unknown, Docs Source·최소 operational 역할·cutover는 여전히 필수 잔여다.

OFF-002B의 기존 room readOnly 초기 읽기는 locally_accepted다. Source writer·room CAS·초기화/영속화·Docs·operational 최소 역할·cutover, native immutable 설치/enforcement·SDK 전체 흐름은 필수 잔여다. REL-001·VAL-001은 최신 full 실패로 미완료이며 비필수 앱 세부 기능·다중 사용자는 보류한다.

## 2026-10-08 20:00 — OFF-002B Source 읽기 후속

Whiteboard room readOnly 초기 읽기는 local accepted 뒤 필수 리뷰/양쪽 정상 병합/소유 브랜치 정리까지 전달했다. Docs Source17 ACL·별도 Core writer1 모델/6열 read·공용 guard10경로는 actual red1 뒤 새143개·기존227개 검사 통과이며, 기본 Docs 영향8개도 통과했으며, 첫 실행의 장시간 중단 원인은 미확인이다. 최종 리뷰·전달은 in_progress다. Source writer/CAS·초기화와 저장·Docs 초기 read·operational 최소 grant/cutover는 필수 잔여이며 REL-001/VAL-001은 full237/405 storage 실패/tests0로 미완료다. Native 영구 설치/enforcement·개인 SDK 전체 흐름과 핵심 계약도 유지한다. 비필수 앱 상세 기능은 APP_ISSUES에 남기고 별도 지시까지 보류한다.

## 2026-10-09 01:58 — Docs 읽기 경계 로컬 인수

신규143개·기존227개와 생성 계약·Source Python 검사를 통과했다. 기본 Docs 원7함수/8cases는 첫 장시간 실행 종료 뒤 동일 입력의 bounded 재검사8 PASS/25.49초다. 첫 실행 원인은 미확인이고 VALIDATION에 원본과 제한을 남겼다. 제품10경로·진행 문서6의 최종 독립 freeze 리뷰와 정상 source 전달을 이어간다. Docs initial Source 읽기·writer/CAS·영속화·operational 최소 grant/cutover, native 영구 설치/enforcement·SDK/등록 전체 흐름은 필수 잔여다. 비필수 앱 상세 기능과 다중 사용자는 보류한다.

## 2026-10-09 02:07 — Docs 기존 room Source 읽기 후속 계획

Source ACL/Core writer10경로는 필수238/406 뒤 PR85/MR92 정상 병합·exact tree·소유 원격/로컬 브랜치 정리를 마쳤다. Dev는e25c1934, main/prod9e다. 최신 full239/407은storage 실패24.291815초/tests0로 REL-001/VAL-001 미완료다.

후속 Source6은 기존 Docs initialized row의 readOnly loader·registry/router·새검사·owner2이며, 이전 Source17+DocsCollabDocument=18의 fresh singleEngine Session을 사용한다. Native canonical room key와 page.created_by_id, SQLNULL/JSONnull·YjsNone/빈bytes 의미를 보존한다. Page blocks가None이 아닌데 Yjs/snapshot이None이면 기존 codec/repair가 필요해 거절하며 []를None으로 바꾸지 않는다. 의미 있는 page/snapshot 내용이 있는데 null/빈Yjs인 경우도 빈 room으로 유실하지 않도록 거절한다. 빈nullable 상태는 실제 native positive로 인수한다. WB timestamp stale·suffix 회전·snapshot/page equality 규칙은 추가하지 않는다.

Page/Doc/Collab 단일 projection의 page blocks+snapshot+Yjs합산8MiB를 SQL CASE로 전송 전에 제한하고 detachedDTO를 검증한다. 현재 Source ACL·Core pinned writer·원 auth/actor/session과 captured callback/hub identities를 모든 await 뒤 확인한다. 부분 조립·초기화/복구 필요 상태는 private5031013·무쓰기·무globalfactoryfallback이며 기존 defaultinit/persist/codec/roles/models/ASGI는 그대로다. 새 registry옵션 actual red1 FAIL/0.56초·collection/setup0·networknone·소유cleanup을 Source40b/redtestSHAbea7로 보존하고, prior merge e25로 FF할 때 Source/protected40을 유지했다. 제품 구현과 actual 최소PG/Yjs·권한회수·취소·bounds·default영향 검사는 진행 중이며 green·운영 활성화 완료를 주장하지 않는다.

Source writer/CAS·COMMIT unknown·저장/media/RAG·정확 operational grants/cutover, native 영구 설치/enforcement·SDK 전체 자연어 등록/배포와 별도 Workbench 배포는 필수 잔여다. 앱별 비필수 기능과 다중 사용자는 별도 요청까지 보류한다. 계획·baseline/red는 `.runtime/structural-next-delivery/next-docs-source-room-slice.{md,json}`·`docs-room-source-red-base-integration.json`에서 추적한다.

## 2026-10-09 02:38 — Docs 기존 room Source 읽기 로컬 인수

명시적 비활성 Source18 기존room loader를 구현하고 신규104개·기존370개 및 생성 계약·Source Python 검사를 통과했다. 현재 Source app/edit ACL·Core writer와 auth/session/callback identities를 확인하고, legacy repair가 필요한 상태는 private503/1013으로 거절한다. 합산8MiB를 전송 전 CASE와 DTO에서 제한한다. nullable SQLNULL/JSONnull/YjsNone·빈bytes의 genuine native positive와 native shutdown 후 size검사 시점 교정을 VALIDATION에 남겼다. Source6·추적6을 최종 독립 수락 뒤 일반 source 전달한다. 운영 활성화·Source writes/영속화·전체 플랫폼/Workbench 완료는 미완료다.

## 2026-10-09 02:50 — Docs room 전달과 저장 경계 착수

`OFF-002B`의 Docs Source 기존 room 읽기는 신규104·기존370 PASS와 독립 수락 뒤 필수240/408/PR86/MR93 병합·소유 브랜치 정리를 마쳤다. 다음 기존 Whiteboard 저장 안전성은 actual red 준비 중이다. Board/collab row/key 캡처·조건부 쓰기, repeated cancellation worker join·replacement cleanup·COMMIT unknown 무재실행이 필수 완료 조건이다. 별도 Source writer/Core COMMIT fence·Docs 저장/media/RAG·최소 operational grant/cutover는 후속 필수로 남는다.

`REL-001`·`VAL-001`은 latest241/409 storage 실패/tests0로 미완료다. Native 영구 설치/enforcement·SDK/등록/배포 전체 흐름·별도 Workbench 서비스 인수는 유지한다. 비필수 앱 세부 기능·다중 사용자 범위는 추가하지 않는다.

## 2026-10-09 02:57 — Whiteboard 저장 경계 구현

변경 전 네 actual native red가 모두 call assertion으로 실패해 필수 데이터 유실 경계를 확인했다. Source7·추적6의 구현을 재개하며 기존 assertions·Core/역할/모델·기존 hub/prepared 검사와 앞선 Docs room을 보존한다. 최소 캡처/CAS·취소 worker join·교체 runtime identity·unknown 무재실행을 인수한 뒤 별도 Source writer 권한 경계를 진행한다.

## 2026-10-09 03:53 — Whiteboard 저장 안전성 로컬 검증

`OFF-002B`의 기존 Whiteboard 저장 안전성 하위 범위는 신규48·기존480개 검사를 통과했다. 기존 room이 입장 때 캡처한 board ID·collab 행 ID·room key만 조건부 UPDATE한다. Board SHARE와 정확한 행 조건을 COMMIT까지 유지하고, 취소된 호출도 SQL worker/cleanup 종료까지 flush lock을 보유한다. ACK는 후속 정리 실패로 unknown으로 바꾸지 않으며 unknown은 원 identity/bytes를 보존하고 자동 재저장하지 않는다. 이전 WS finalizer·observer·대기 publish가 교체 runtime을 정리하거나 변경할 수 없고, pending/unknown 동일 identity 재입장은 거절한다.

이번 범위는 기존 trusted Core factory의 저장 안전성이다. 최소 Source writer 권한·현재 Core 사용자 권한의 COMMIT fence·동일 room의 다중 hub 내용 CAS/convergence·영속 unknown 복구·Docs media/RAG 저장·공식 서비스 전환은 필수 잔여다. 기존 readOnly Source/session/auth·모델·role·migration·원 tests를 포함한 보호 입력46개는 동일하다. 운영·별도 Workbench 배포는 없으며 full241/409 storage 실패/tests0를 유지한다. 비필수 앱 기능과 다중 사용자 작업은 별도 요청까지 보류한다.

## 2026-10-09 04:24 — 필수 리뷰의 공유 저장 상한 수정

`OFF-002B` 기존 WB 저장 상한 필수 수정의 로컬 검증은51+480개다. Hub별 고정4개의 shared permit을 private shielded child 시작 전에 얻고 SQL worker·Session cleanup·결과 전달·TaskGroup join까지 보유한다. Permit 대기 취소는 Session0이며 child 시작 뒤 취소는 기존 owned join을 따른다. Permit을 얻은 뒤 terminal/disposing/current runtime/captured identity/YDoc/unknown을 재검사한다. Child 내부 limiter1은 shared token을 재획득하지 않으며 기존 adapter를 유지한다. Process 전체 상한이나 새 설정·운영 적용을 주장하지 않는다.

최소 Source writer/profile·현재 Core 사용자 COMMIT fence·같은 room의 cross-hub content CAS/convergence·영속 unknown/Docs 저장·operational 역할과 서비스 전환은 필수 잔여다. Next service-admission profile은 이번 단계에서 사용하지 않는19표98열 ACL 호환 grant를 미리 주지 않고 board/collab의 고정 최소열과 EXEC부터 독립 인수하도록 계획을 좁힌다. 현재 ACL reader는 보호하며 실제 ACL writer 연결은 후속이다. main/prod9e9280df·full241/409 storage 실패/tests0·새 운영/Workbench 배포0를 유지한다. 앱별 상세 기능과 다중 사용자는 보류한다.

## 2026-10-09 05:08 — 최종 저장 대기 중 상태 보존

`OFF-002B`의 저장 안전성 필수 수정으로 final admission의 unsaved state를 보존했다. 최종 신규54개는 pure16 PASS/7.10s와 native38 PASS/131.44s다. 기존 영향480개는 prepared/auth/composition466 PASS/372.13s·원 Whiteboard6 PASS/25.87s·원 Docs8 PASS/35.69s다. 이전48/51개·재실행 횟수는 더하지 않는다. API architecture/i18n·생성 계약을 통과했다. 최종 문서·Python 검사와 새13파일 독립 인수 및 새 source의 필수 리뷰는 별도 단계다.

현재 dev499aff33·main/prod9e9280df, full241/409 storage 실패/tests0, 새 운영 및 별도 Workbench 배포0다. 다음은 비활성2표 최소 Source service writer/profile이며 Core 사용자 권한 COMMIT fence·Source factory 연결·cross-hub content CAS·영속 unknown 복구·공식 서비스 cutover는 남아 있다. Native SDK/toolchain 실제 pin 검증·설치 및 개인 앱 자연어 전체 흐름도 필수 잔여다. 앱별 비필수 기능·다중 사용자는 보류한다.

## 2026-10-09 05:22 — 저장 안전성 전달과 최소 Source writer 착수

Whiteboard 저장 안전성 최종 Source `ba9fee1e`/tree `fef48496`는 필수244/job412 SUCCESS/94.736405초 뒤 GitHub [PR87](https://github.com/hurxxxx/miy/pull/87)→`2c1cb019`와 내부 [MR94](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/94)→dev `aafbccb2`로 정상 병합했다. 양쪽 tree는 같고 소유 feature 브랜치의 양쪽 원격·로컬 정리를 완료했다. Dev는 persistent integration branch로 유지하며 main/prod는 `9e9280df`다.

새 전체245/job413은30.366867초에 저장 공간 선행조건에서 실패했다. 제품 테스트0이며 필수 최소15GiB/15% 기준을 유지한다. 이 결과를 source 리뷰 성공으로 대체하지 않고 새 운영·별도 Workbench 배포0를 유지한다.

다음 구현은 `aafbccb2` 기준 별도 worktree에서 비활성 Whiteboard Source service writer/profile이다. 실제 migration head `file_effect_20261007`, 기존 migration30개 및 보호85개를 다시 동결했다. 새 migration·service admission·role checker와 새 테스트·owner2, Root 추적6을 분담한다. 두 Source 표의 SELECT8열·UPDATE4열과 제한된 capability 하나부터 인수하며 공급된 LOGIN/NOLOGIN 역할·원래 principal identity·정확한 권한·기존 mapping replay·실제 session_user와 SQL 락을 검증한다. 현재는 구현 착수이며 새 테스트를 실행하거나 인수한 것으로 표시하지 않는다.

Migration은 정상 legacy/hardened 환경에서 비활성 capability만 설치한다. 준비·admission에는 hardened guard가 필요하다. Session/factory/COMMIT/cleanup 수명은 caller가 소유하며 Core 사용자 ACL COMMIT fence·hub Source factory 연결·운영 역할/grant/config/service 전환은 이번 범위가 아니다. Current actor fence, cross-hub content CAS, 영속 unknown 복구와 공식 서비스 cutover는 여전히 필수 잔여다. 기존 skills/harness는 절차로 사용하지 않고 현재 코드·owner·중요 계약만 사용한다. 앱별 비필수 기능과 다중 사용자는 보류한다.

## 2026-10-09 05:59 — 비활성 최소 Source writer 로컬 검증

`OFF-002B`의 비활성 service-admission 최소 profile은 신규79·영향209 로컬 검증을 마쳤다. 부모 경계와 실제 factory/운영 전환은 계속 in_progress다. 새 migration의 정상 legacy downgrade→re-upgrade는 실제 board/collab bytes·기존 source trigger/ownership을 보존한다. Hardened active rollback은 상태/버전/함수/데이터 변경 없이 거절하고, 실제 Core drain 뒤 capability만 제거한다. 변조된 body/overload rollback도 거절하며 기존 role·principal·column ACL·guard·데이터를 보존한다. 신규 revision `wb_source_writer_20261009`는25자로 기존 head `file_effect_20261007` 뒤 하나만 추가했다. 이전30 migration·보호85개는 byte exact이고 원 inventory test는 정확한 새 head 한 항목만 갱신했다.

현재 dev `aafbccb2`·main/prod `9e9280df`, 최신 full245/413 저장 공간 선행조건 실패/제품 테스트0와 새 운영/별도 Workbench 배포0를 유지한다. 이 단계는 Source factory·저장 연결·사용자의 현재 Core/Source ACL COMMIT fence·cross-hub content CAS·영속 unknown 복구·Docs 저장·공식 서비스 cutover를 완료하지 않는다. 다음 actor fence는 현재 사용자 구현 승인 안에서 별도 범위와 보호표를 확정한다. Same-DB SQL 잠금을 실제 separate DB 보장으로 표시하지 않으며, queued Yjs의 credential attribution/expiry와 모든 owner/direct/group/PMS/meeting edit closure가 활성화 전 필수다. Native SDK/toolchain 실제 pin 검증/설치·개인 앱 전체 자연어 흐름도 남아 있다. 앱별 비필수 기능·다중 사용자는 보류한다.

## 2026-10-09 06:22 — 최소 Source writer 전달과 actor-owner 경계 착수

현재 dev는 `746258cd`, main/prod는 `9e9280df`다. 비활성 최소 Whiteboard Source writer/profile은 필수246/job414 성공 뒤 [PR88](https://github.com/hurxxxx/miy/pull/88)·[MR95](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/95)로 정상 병합하고 소유 feature 브랜치를 양쪽 원격·로컬에서 정리했다. 최신 full247/job415는 저장 공간 선행조건에서22.79551초에 실패해 제품 테스트0이며 새 운영·별도 Workbench 배포는 없다.

다음은 별도 worktree의 비활성 Core actor-owner capability다. 실제 원 delegated execution을 별도 auth-only Session에서 캡처하고, 공급된 fresh LOGIN에는 private EXEC1만 허용해 사업 데이터 SELECT·DML0을 유지한다. 같은 PostgreSQL database의 caller-owned transaction에서 원래 서비스와 현재 사용자·세션·설치·앱 승인·live board owner의 positive witness를 잠근다. Source v1의 SELECT8/UPDATE4 및 auth14표/87열은 확장하지 않는다. 기존31 migration·보호95개를 동결하고 신규 revision `wb_actor_owner_20261009` 하나와 inventory head 한 항목만 추가한다. 구현·테스트 작성에 착수했으며 새 검사 실행·최종 인수·게시·서비스 활성화는 아직 하지 않았다.

이번 owner-only 단계는 전체 Whiteboard ACL·실제 Source 쓰기 연결·운영 전환을 완료하지 않는다. 공유/HR/PMS/meeting 편집 권한, contributor의 원 credential 보존, 같은 connection/transaction의 Source CAS와 actor 검사 조립, cross-hub content CAS·영속 unknown 복구·Docs 저장/media/RAG가 필수 잔여다. 별도 LOGIN 연결 두 개는 하나의 transaction으로 합칠 수 없으므로 후속 최소 combined profile 또는 검토된 capability가 필요하다. 같은 database의 역할·프로세스 분리이며 물리적 별도 DB를 인수하지 않는다. 대기 후 실제 시각의 만료 판정은 decision 시점 보장이고 physical COMMIT-time 만료 보장은 아니다. 사용자 update의 User→AuthSession과 autoflush=False인 reset/delete의 AuthSession→User 역순 잠금 충돌은 bounded private refusal·caller rollback으로 검증하고 보편적 잠금 순서로 주장하지 않는다. Native immutable cache/설치·SDK 전체 자연어 흐름과 별도 Workbench 전달도 남아 있다. 비필수 앱 기능·다중 사용자는 보류한다.

## 2026-10-09 08:38 — actor-owner 구현 검증과 Docker 저장소 이전

진행 중: 비활성 actor-owner 양성 witness의 최종145검증 및 영향167/계약 재검증, 승인된 Docker 루트 저장소 이전, 기존서비스 건강 복구와 정확한 저장 여유 확보, 운영 owner 문서3의 최소 절차 추가다. 완료 조건은 실제 체크섬·목록·건강 확인과 최종 입력에 결속된 검증/리뷰이며, 초기 복사나 진단5 PASS로 대체하지 않는다.

후속 필수: 전체 direct/group/HR/PMS/meeting actor ACL, 실제 같은 Source connection/transaction의 저장 CAS 조립, cross-hub content revision·영속 unknown 복구·Docs 저장, 공식 서비스 cutover, immutable native toolchain·개인 앱 자연어 전체 흐름과 별도 Workbench 전달이다. 앱별 비필수 기능·상세 인수 및 다중 사용자는 보류한다.

## 2026-10-09 09:26 — Docker 이전 완료와 actor-owner 최종 로컬 검증

완료: Docker root-backed 저장소 이전·cold 전체 비교·기존 서비스/CI runner 복구·verified stale source 정리, actor-owner 신규145와 기존 영향167/계약 최종 로컬 검증. 미참조 익명220개는 기원을 확인하지 않은 자료이므로 전체286 볼륨과 함께 보존했으며 prune0이다. Host 재부팅 자체는 수행하지 않았고 fstab/systemd persistent bind 의존성은 검증했다.

진행: 최종16경로 docs/manifest/review와 정상 전달·필수 CI. 실제 operational actor/source 역할·same-connection factory·전체 edit ACL은 활성화하지 않았다. 전체 release/guarded prod/separate Workbench, content CAS/영속복구·Docs 저장 및 native immutable cache와 개인 앱 자연어 인수는 여전히 필수다. Home12.85GiB의 별도 공간 제약을 root/Docker52.65GiB 확보와 구분한다. 앱별 비필수 기능·상세 인수/다중 사용자는 보류한다.

## 2026-10-09 09:46 — ACT-CI-01 HOLD 해소를 위한 게시 fixture 검증

`OFF-002B` 최종 전달은 기본 CI의 revision fixture 누락으로 HOLD했다. 이전 영향167 PASS의 Source revision5개는 ignored runtime adapter에서 실행했으므로 기본 Source79개 전체의 성공으로 취급하지 않는다. 게시 전 기본 모듈 동일5개는5 FAIL/11.19초·setup0·cleanup PASS였고, revision 전용 입력을 게시 가능한 fixture로 보완한 뒤5 PASS/11.17초·cleanup PASS로 확인했다. 실패와 기존 범위별 결과를 보존한다.

현재 범위는17경로·보호94개이며 정상 legacy downgrade·원 migration31개 byte-exact 임시 inventory를 선택된5개에만 공급한다. 정확히4개 함수의 단일 간접 매개변수와 `world` 래퍼만 추가하고 원 함수 body/signature/assertion 및 기존 매개변수 순서를 유지했다. Source79개의 수와 나머지74개·actor145개의 최신 head 검증을 유지하며 제품 권한·guard·기존 migration을 수정하지 않았다.

최신 pure7·role31·migration5·계약 검사는 통과했고 기본 Source79·authority52·actor native138 전체가 실행 중이다. 이 재검증의 완료·최종17경로 freeze/독립 리뷰·정상 source 전달과 필수 CI가 다음 조건이며 현재 전체 성공으로 표시하지 않는다. Full release/guarded 운영·별도 Workbench 전달, 전체 actor ACL·same-connection Source 저장·content CAS/영속 복구와 개인 앱 자연어 전체 흐름은 여전히 필수다. 앱별 비필수 상세 기능과 다중 사용자는 보류한다.

## 2026-10-09 09:50 — actor-owner와 정상 CI 호환 최종 로컬 인수 준비

최종17파일 범위에서 신규 actual PG18 native138 PASS/321.13초·pure7 PASS/3.30초 =145개다. 정상 원본 Source 모듈79 PASS/82.18초·원 role31 PASS/24.19초·authority52 PASS/83.77초·migration5 PASS/6.35초 =고유 기존 영향167개다. 진단/반복은 더하지 않는다. ACT-CI-01의 실제5 FAIL/11.19초와 동일5 PASS/11.17초는 보존하며 현재 영향 검증은 ignored Source prior adapter에 의존하지 않는다. 기존45개 함수 본문·signature·assertion, 보호94개·기존31 migration은 동일하다.

Python6·API architecture/i18n·schema/OpenAPI/contract sources를 통과했다. 최종 문서 검사·동결 후 새 독립 인수와 정상 게시/필수 원격 리뷰를 진행한다. 현재 dev746258cd·main/prod9e9280df 및 최신 full247/415 storage 실패/tests0를 유지하며 새로운 commit/push/PR/MR/merge는 아직 없다. Docker 이전/원본 정리·서비스 복구는 완료했고 제품/별도 Workbench 버전 배포는 없다. 전체 ACL·같은 Source connection/transaction 조립·실제 공식 서비스 cutover·Native 전체 자연어 앱 흐름 등 구조상 필수 잔여는 남아 있다.

## 2026-10-09 10:13 — owner 경계 전달 완료와 전체 편집 ACL 착수

- WB-ACTOR-OWNER 전달: 완료. Source `3b39f5b9`, PR89/MR96, 필수248/416 성공, dev `8bf0bbee`, 원격/로컬 임시 브랜치 정리. 비활성 owner-only이며 전체 actor ACL/Source 저장 완료가 아니다.
- REL-FULL:249/job417 실행 중. Source dev `8bf0bbee`, target main `9e9280df`. Docker 이전 뒤 실제 전체 gate를 다시 검증한다. 새 제품/별도 Workbench 버전 배포0.
- WB-ACTOR-EDIT SQL: 신규 revision `wb_actor_acl_20261009`/private edit capability 구현 중. 이전32 migration 보호, 현재 resource edit 조건과 선택한 positive witness 잠금, NULL/expiry/lexical proof 계약 유지.
- WB-ACTOR-EDIT role/runtime: 별도 EXEC1/DML0 profile과 server-only original capture를 재사용한 caller-owned primitive 구현 중. 기존 owner/Source/auth profile·factory·운영 역할은 유지한다.
- WB-ACTOR-EDIT 검증: 신규 actual migrated PG18 parity/lock/refusal/replay 테스트 작성 중. 신규 migration을 발견하는 기존 owner revision 테스트도 정상 CI에 version-specific fixture가 필요한지 확인한다. 기존 모든 assertion을 유지하며 ignored adapter만으로 CI 호환을 인수하지 않는다.
- 후속 구조 필수: 같은 actual transaction의 captured-CAS 저장, contributor credential 귀속, durable unknown/restart 복구, cross-hub convergence, 공식 서비스 cutover와 Native 전체 자연어 앱 흐름. 비필수 app 기능·다중 사용자는 별도 지시까지 보류.

## 2026-10-09 10:48 — ACT-CI-02 필수 release 호환 수정

진행: 기존 파일 migration의 버전 전용 여덟 case를 정상 CI에서도 원래 revision 입력으로 실행한다. 네 테스트 모듈과 작은 공통 fixture만 수정하며 기존 assertion·최신 head를 검사하는 나머지 case·현재 제품 권한 계약은 보존한다. 실제 영향 모듈 전체 재검증과 필수 원격 review 후 dev에 통합하고 새로운 source/target에 대해 full release를 다시 실행한다. 기존 full249의 실패를 생략하거나 운영 gate를 우회하지 않는다. 앱별 기능 개선은 이 작업에 포함하지 않는다.

## 2026-10-09 10:54 — 전체 ACL 인수와 후속 계약 범위

전체 edit ACL은 로컬 신규132·기존312 PASS로 최종 문서/독립 리뷰 단계다. 게시 후 같은 실제 Source connection/transaction에서 checked content-CAS 저장, 대기 중 모든 contributor의 원 execution 보존, 영속 revision/attempt 및 unknown outcome 복구를 연결해야 한다. 현재 LOGIN DML0과 inactive migration은 실제 저장/운영 활성화 완료를 뜻하지 않는다.

후속 계약 기록: 현재 GroupUpdateRequest는 source 변경을 허용하지 않지만 DB에는 source 불변 제약이 없다. 현재 capability는 선택 group ID를 유지하고 잠근 현재 source에 따라 local/HR membership을 확인한다. 향후 source 변환 API를 추가한다면 해당 lens의 대기 전 identity 고정/변환 경계와 회귀 검증을 함께 정의한다. Known-other DB 거부 시 private capability 미호출을 직접 관측하는 추가 테스트는 낮은 우선순위로 남긴다. 현재 code ordering 자체는 독립 리뷰에서 확인했다. 앱별 기능·비필수 상세 검증 및 다중 사용자는 별도 요청까지 보류한다.

Release 우선: full249의 기존 파일 revision8개 FAIL을 ACT-CI-02로 수정·정상 review·새 full 검증한다. 운영 gate를 우회하지 않고 별도 Workbench release 및 native 자연어 앱 전체 흐름 인수도 유지한다.

## 2026-10-09 11:05 — ACT-CI-02 로컬 영향 검증 완료

ACT-CI-02의 실제 영향 검증270 PASS와 기존115함수/270assertion 동일을 확인했다. 남은 전달 조건은 최종 문서·독립 인수, 정상 source 게시와 필수 remote review다. 이후 전체 ACL 변경의 새 base 통합 및 최신 source의 full release를 진행한다. 기존 full249의 실패를 우회하지 않는다.

## 2026-10-09 11:23 — 정상 fixture 전달과 ACL 통합 준비

필수 ACT-CI-02 전달은 완료했다(PR90/MR97, review250/418 SUCCESS). 다음은 byte-identical ACL의 새 base 최종 전달·필수 review와 최신 dev full release다. 추가Source 저장 C1은 신뢰된 Core가 payload와 모든 원 contributor를 immutable attempt로 봉인하고, Source DML0 LOGIN이 같은 실제 connection에서 전체 ACL·incarnation/content revision CAS·영속 receipt를 처리하는 최소 비활성 단계다. Source가 contributor를 임의로 빠뜨리거나 last_editor로 대체할 수 없어야 한다. 이후 native apply/relay의 완전한 provenance와 운영 factory/config epoch를 연결한다. 앱별 비필수 기능과 다중 사용자는 여전히 보류한다.

## 2026-10-09 12:20 — 구조 전달 상태

ACT-CI-02는 PR90/MR97로 전달 완료이고 owner/전체 edit ACL은 PR89/MR96 및 PR91/MR98로 전달했다. ACT-CI-03은 full251의 Workbench Ruff I001을 원 테스트 import 순서만으로 고치는 필수 CI 호환 작업이다. Local lint/24 cases PASS, 최종 문서·독립 리뷰/게시·latest full은 남아 있다. 구조 runtime 활성화로 확대하지 않는다.

운영 pending23 private restore/data/old-image compatibility는 통과했으나 final candidate binding/full/before/deploy/after는 남아 있다. 필수 후속은 checked-save C1/C2/C3, 실제 official source/queue/service 전환, Workbench SDK/immutable install 및 개인 앱 UI→DB 자연어 전체 흐름이다. 세부 앱 기능과 다중 사용자는 후속 별도 지시 대상으로 유지한다.

## 2026-10-09 12:55 — 전달 갱신과 다음 비활성 C1

ACT-CI-03은 PR92/MR99/required254-422 정상 병합·소유 feature 정리 완료다. 현재 dev0d259이며 latest full255-423은 실행 중이다. 개발 before/after schema와 private cap·legacy writer/90 guards,18개 app entry/browser logout을 확인했다. Actual prod는 main9e를 유지한다. 운영23 migration의 최종 tree private rehearsal과 독립 인수는 준비 근거이며 actual flags/role catalog/full/deploy를 대체하지 않는다.

`OFF-002B`의 다음 local C1은 Core-sealed immutable complete original contributor/payload attempt + Source EXEC1/DML0 checked CAS + durable original-attempt receipt/lock-and-cancel이다. 현재 ACL 통합 base0d259에서 새 worktree로 계획/정확 column/function ceiling을 동결하고 구현한다. 기본 native/factory/operational role은 유지하고 C2 provenance/C3 activation을 완료로 표시하지 않는다. `WB-001/ENV-001`은 별도 immutable Node/Python/pnpm·SDK cache/verifier/inactive backend를 준비한다. App source/manifest/scripts는 checkout 소유로 유지하며 두 starter graph의 availability를 임의 앱 전체 지원으로 확장하지 않는다. 기존 업무별 상세 기능·다중 사용자는 계속 보류한다.

### ACT-CI-04 — 전체 릴리스 실행 예산

상태: `in_progress` — 후보70/70·독립 소스 리뷰 완료, 게시/필수 리뷰/병합·최신 full 대기. 실제255/job423의3604.73초 timeout과 project3600/Runner7200 근거에 따라 릴리스 job에만2h를 선언한다. 두 YAML과 checker의 현재 계약을 함께 갱신하며 테스트·gate·현재 ref binding·생략 정책은 유지한다. Workbench build/E2E까지 끝난 새로운 current full 성공이 완료 조건이다.

## 2026-10-09 14:20 UTC — 현재 필수 착수 상태

- ACT-CI-04: 필수256/424·PR93/MR100 정상 병합과 소유branch 정리 완료. 최신full257/425는 실행 중이며 운영MR81/배포는 대기.
- OFF-002B/C1: 첫actualnative51PASS/1FAIL/4ERROR를 보존하고 canonicalroom·migrationDSN의 ownedfixture 수정/재검증 중. 권한/source/native기본값 유지, C2/C3 후속.
- WB-001/002·ENV-001: v1actualtest/kernelPASS와 ordinarybuild ENOENT를 구분, v2재현 producer/16MiB scratch/Task profile 구현 중. 실제제품Task·별도Workbench배포 미완료.
- REL-001: 최신tree private23리허설PASS, 독립리뷰 재결속 중. actualfull→MR81→prod FF→guarded image/freshbackup/before/deploy/after 순서 유지.
- APP_ISSUES의 비필수 앱별기능과 다중사용자는 계속보류.

## 2026-10-09 15:25 UTC — 현재 로컬 경계와 릴리스 실패

C1 신규56·기존ACL132·Source110·owner145·authority52는 현재 입력으로 통과했다. 초기51/1/4와 historical drain 실패를 보존했고 원래 migration marker 두 개만 추가해 기존 함수/assertions를 유지했다. SDK v2 설치·정상 공개 입력55개 취득/동일 archive 재현160.761초는 통과했지만 source preflight는 canonical starter의 vendor4와 verifier 필수 README5 불일치로 거부됐다. 이 필수 계약을 보완한 뒤 actual unit/Task를 인수한다. 이전 SDK source170/pure와 독립 리뷰는 보완 전 시점으로 구분한다.

전체257/job425는3198.397초 FAILED다. API6422/1FAIL/3SKIP이며 마지막 shutdown 저장의 실제 status rejected를 확인했다. slow16·migration37·external15 통과는 전체 성공을 뜻하지 않는다. 예외·SQLSTATE·GC 관측만 추가하는 disposable 단독 재현을 준비하며 timeout/검사 면제와 동일 source 맹목 재시도는 하지 않는다. main/prod는9e9280df, 새 운영/Workbench 배포는 없다. 현재23 migration private 리허설과 독립 리뷰는 treec7616793 한정이다. 새 migration 통합 후에는 새 정확 tree/pending 수로 검증한다.

Rejected payload는 현재 caller-held runtime에만 남고 자동 replay는 금지된다. 종료 후 durable owner/handoff 검증은 C2/C3 필수 구조 잔여이며 APP_ISSUES로 넘기지 않는다. 고객 데이터 손실을 관측했다는 뜻은 아니다. Docker는 root117GB에서 약47GB 여유와29/83 실행/전체 컨테이너를 확인했다. 앱별 비필수 기능과 다중 사용자는 계속 보류한다.

## 2026-10-09 16:10 UTC — GC 저장 예산 재현과 통합 순서

원본 shutdown 저장 사례는 진단 wrapper만 추가한 격리 CI 이미지에서 다시 실패했다. 첫 네 저장은 ACK, 마지막 저장은 transaction_rejected/WhiteboardPersistenceDeadline(SQLSTATE 없음)이었다. 마지막 저장의1.24초 구간에 full GC 세 번이 각각 약0.41초 겹쳤다. 원본 assertions·1초 SQL 예산·worker4개를 유지하고 process-wide concurrent reader/exclusive native GC drain을 Docs·Whiteboard 공통 계층에 적용한다. 새 await 뒤 Docs의 원 snapshot/actor capture 시점과 writer fence 재확인도 보존한다. 새 코드의 실제 인수는 아직 대기다.

SDK source 보완185개·두 canonical starter/cache binding은 통과했다. 실제 basic unit의 pnpm test/build·readOnly/cache/외부 graph 거부는 통과했지만 Python/TestClient가 멈췄다. 후속 짧은 진단은 초기화에서 거부되어 Python IPC 원인을 확정하지 않았다. exact owned unit 정리는 통과했다. 제품 Task/model 요청0이며 SDK18개 후보는 이번 API 전달에 포함하지 않는다.

C1·GC·접근 도구를 최신 dev02418067 기반으로 먼저 통합한다. C1의 기존 로컬56/132/110/145/52 증거는 정확 입력과 함께 보존하며 공통 runtime 변경의 영향 검사를 수행한다. 정상 필수 feature review/병합 뒤 새 current full로 이어간다. C1 migration34/pending24의 새 private 리허설과 이전 운영 이미지 호환이 필요하며 기존pending23 증거를 새 head의 완료로 사용하지 않는다. main/prod9e9280df·운영/Workbench 미배포·C2/C3 잔여·앱별 비필수/다중 사용자 보류를 유지한다.

## 2026-10-09 17:43 UTC — 현재 로컬 전달 및 필수 잔여

OFF-002B/C1·공통 저장 drain: 로컬 인수 완료(신규56·권한132/110/145/52·통합20·기존106·구조/생성 계약),31개 경로 게시/필수 review·정상 병합 및 latest full 대기. 기본 native/factory·운영 역할·Source principal0/비활성을 유지한다. C2 원 contributor provenance와 pre-apply durable intake/handoff, C3 원 attempt 관측/복구·명시적 서비스 활성화는 필수 구조 잔여다. terminal rejected/unknown/refused 자동 replay를 금지하며 현재 caller-held bytes만으로 종료 후 복구를 완료로 표시하지 않는다.

WB-001/002·ENV-001: SDK 185/starter/cache·JavaScript와 supported empty allowlist의 실제 Python/IPC23은 인수했지만 기존 Codex controller/SQLite binding 연결·실제 Task·private-notes unit·별도 Workbench 배포는 진행 중이다. REL-001은 새 pending24의 완전한 리허설·이전 이미지 호환·fresh actual evidence/full/guarded delivery가 남아 있다. APP_ISSUES 상세 기능과 다중 사용자 Workbench는 계속 보류한다.

## 2026-10-09 18:03 UTC — 종료 저장 필수 P1 및 잔여

구조 필수 Docs 종료 admission/취소 P1을 이번 전달에서 수정하고 실제4개 포함 focused24·원본106을 통과했다. GitHub94/GitLab101 수정 head의 필수 재리뷰/병합 및 latest full은 아직 남아 있다. C1은 비활성이며 C2 pre-apply durable intake와 전체 원 contributor provenance, C3 원 attempt 복구·서비스 활성화는 필수 잔여다. Workbench의 controller/세션 연결은 별도 검증하며 individual app 상세 기능과 다중 사용자는 계속 보류한다.

## 2026-10-09 18:37 UTC — draining 마이그레이션 필수 P1 수정

필수259/job427(source0059196a)은 C1 migration의 기존행 UPDATE backfill이 draining 상태의 statement writer guard에 걸리는 P1을 발견했다. 빈 테이블도 guard가 실행되므로 기존 trigger/role/ACL을 우회하지 않고 두 column을 owner DDL의 NOT NULL/default로 초기화한다. UUID의 행별 생성 뒤 미래 INSERT default만 기존 sentinel로 복원한다. 기존 SQL 함수·guard·downgrade·22개 테스트 정의와 기본 비활성 경로를 보존했다.

현재 코드의 실제 PostgreSQL18 회귀는 기존56개+legacy/hardened×empty/existing_rows4개로 **60 PASS/179.90909초**다. Setup/call/teardown 모두60/실패·skip·collection error0이며 소유 cluster/container 정리와 입력 전후 검증을 통과했다. Native 입력31 c34454d1·수정3 ddabcea8 및 receipt e988110b를 보존했다. Canonical 문서 서식만 후속 whitespace로 정리했고 코드·테스트·migration bytes는 같다. 현재 입력31 4d19d222·수정3 23abcea3에 결속한 frozen CI Ruff0.16.6 check/format과 owner Markdown도 통과했다. 이전 잘못된 도구 버전 기대와 문서 format RED는 보존하며 검사 결과를 성공으로 덮어쓰지 않는다.

Docs 집중24/기존협업106(208.751168초)은 바뀌지 않은 runtime/test bytes에 한정한 이전 인수 근거다. 과거 C1 권한132/110/145/52는 그 당시 입력으로 구분한다. GitHub94/GitLab101의 새 수정 head 필수 리뷰·정상 병합·새 current full, 새 migration34/pending24 private 리허설과 이전 운영 이미지 호환·fresh backup/guarded 배포가 남아 있다. Dev02418067·main/prod9e9280df는 현재 그대로이며 배포 완료를 뜻하지 않는다.

별도 Workbench 후보는 SDK source22/owned delta11의 신규74 PASS와 영향427 PASS/기존 PostgreSQL legacy fixture5 SKIP 및 독립 소스 리뷰를 마쳤다. 실제 원관리 정책 확인·controller/Task·private-notes와 별도 서비스 배포는 미완료다. C2-1 비활성 provenance3은 실제 native53 PASS와 독립 리뷰를 통과했으며 PostgreSQL pre-apply durable journal/discovery와 C3 원 attempt 복구·서비스 활성화는 필수 구조 잔여다. 앱별 비필수 기능과 다중 사용자는 보류한다.
