# 재설계 작업 목록

**재시작 뒤 구현 재개:** [RESTART_CHECKPOINT.md](RESTART_CHECKPOINT.md)의 동결 입력을 확인했다. PMS 부모 통합과 Recording managed의 비활성 권한·전달·legacy 영향 검증·독립 리뷰를 마쳤다. 공식 UI source/build 12/12개와 최종 두 build·브라우저 통합을 마쳤다. 독립 API·데이터·worker 서비스와 Workbench native 실행은 필수 잔여다. 일회성 [긴급 백업](EMERGENCY_BACKUP.md)은 완료했으며 추가 게시·배포 없이 로컬 작업을 이어간다.
작업별 상태와 의존성의 원본이다. 목표와 설계는 [PLAN.md](PLAN.md), 현재 위치는 [STATUS.md](STATUS.md), 증거는 [VALIDATION.md](VALIDATION.md)를 참조한다.

**2026-10-07 재개:** 중간 점검에서 정한 구조 우선 기준으로 제품 구현을 재개한다. 공식 UI 전체 모듈 소유권·worker 실행 세대·source outbox 전달 경계를 병렬 진행한다. 원본88개 보호와 비활성 worker profile 기반은 로컬 검증을 마쳤다.

현재 승인 범위는 [구조 우선 기준](PLAN.md#구조-완성-우선과-앱별-후속-작업)의 로컬 구현·검증이다. 앱별 비필수 개선·상세 검증은 [APP_ISSUES.md](APP_ISSUES.md)에 별도로 보류하며 아래 작업의 의존성에 포함하지 않는다. `ready`는 의존성 충족을 뜻하며 커밋·원격 변경·운영 배포 승인을 뜻하지 않는다.

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
