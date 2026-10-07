# 재설계 진행 기록

## 2026-10-07 — Docs/PMS/Meeting의 원본·코어 전달 분리 착수

공식 UI 12개 통합을 마친 뒤 다음 서버 구조 변경을 확정했다. 기존 원본 변경·코어 검색 작업의 동일 Session bridge를 기본 legacy 실행에서는 유지하되, 명시적으로 준비한 제한 원본 Session에서는 원본과 실제 outbox만 같은 transaction에 기록한다. 코어는 커밋된 동일 event ID/digest를 별도 transaction에서 수락하며 결과를 검색 완료로 표시하지 않는다. 응답 유실은 동일 ID로 관측하고 업무 변경이나 외부 요청을 자동 반복하지 않는다.

코어가 Docs/PMS/Meeting의 회사 기본 파티션을 준비한다. 원본에는 코어 table SELECT/DML을 주지 않고 현재 원본 principal·소유 세대·artifact를 확인하는 고정 읽기/SHARE capability가 일치하는 UUID만 반환한다. KEY SHARE는 비키 상태 변경을 막지 못하므로 SHARE를 원본 COMMIT까지 유지한다. 누락·비활성·namespace/범위/기존 binding 충돌은 보정이나 권한 fallback 없이 거부한다. Files의 관리 파티션·트리 잠금·추출 결과 명령은 별도 필수 범위다.

구현 전 계획은 `.runtime/official-partition-files-review/PLAN.md`, 읽기 전용 조사와 42개 입력은 같은 경로의 `REPORT.md`·`inputs.json`에 보관했다. Delivery는 Python 소유 경계, Data는 신규 migration·최소 capability 역할과 실제 제한 PostgreSQL 검증, 독립 에이전트는 검토를 담당한다. 비활성 official composition·기본 runtime 설정·실제 DB/서비스·운영 배포는 변경하지 않는다. 준비된 내부 조립이며 전체 auth/ACL/audit·worker/routing 활성화 완료를 주장하지 않는다.

집중 실제 PostgreSQL은 Data41·Delivery29의 **70 PASS/36.46초**, 입력58개 before==after와 소유 자원 정리를 확인했다. 원본/Core 각각의 metadata SHARE와 Source drain 대기는 실제 blocker PID로 검증했다. 초기 combined66 PASS/2 fixture FAIL은 관측 transaction의 통계 snapshot과 Source에 없는 DELETE의 오류 예상값 문제로 보존하며 제품 권한을 늘리지 않았다. 기존 원본90개·Recording·역할·migration·legacy의 현재 schema 회귀는 **343 PASS/4 fixture FAIL** 뒤 해당 세 테스트 파일의 **102 PASS/16.52초**로 교정 검증했다. 제품·권한·이전25 migration은 그대로이며 최종1,101개 입력이 같다. 독립 읽기 검토의 bounded blocker는0이다. 실제 runtime·서비스 전환과 Files/Planner·auth/ACL/audit·broker/Beat는 필수 잔여다.

주요 결정과 구현 이력을 기록한다. 현재 작업 상태는 [WORK_ITEMS.md](WORK_ITEMS.md), 중단·재개 위치는 [STATUS.md](STATUS.md), 실행별 정확한 근거와 한계는 [VALIDATION.md](VALIDATION.md)가 소유한다.

## 2026-10-07 기록 정정

중단 점검에서 이 파일에 `WORK_ITEMS.md` 내용이 중복 저장된 것을 발견했다. 기존 텍스트의 별도 사본은 확인하지 못했으므로 아래 이력은 남아 있는 계획·검증·소유 문서에서 확인 가능한 내용으로 재구성했다. 이전 원문을 그대로 복구한 것은 아니다. 수정 전 중복본은 `.runtime/pause-checkpoint/progress-duplicate-before-repair.md`에 보존했다. `D-001`~`D-007` 등 기존 검증 ID와 실행별 결과는 `VALIDATION.md`에 남아 있다.

## 2026-10-06 계획·검토·구현 착수

- 사용자 요청에 따라 문서를 `docs/` 대신 루트 `platform-redesign/`에서 관리한다. 공통 플랫폼·전사 앱·개인 앱·Workbench 네 영역을 분리하고, Workbench는 기존 native Codex 체계를 유지하는 단일 사용자 도구로 개선한다. 다중 사용자 Workbench는 후속 범위다.
- 최초 문서화 `DOC-001`, 공식 웹 근거 20개·발견 사항 8개의 재검토 `REV-001`, 권고의 목표 설계·정책·검증 반영 `DOC-002`를 완료했다. 근거는 [REVIEW.md](REVIEW.md) 및 `VALIDATION.md`의 `D-001`~`D-007`이다.
- 사용자의 구현 승인과 멀티에이전트 요청으로 로컬 구현·검증을 시작했다. 기존 하네스·스킬은 이번 개발 절차로 적용하지 않고 최소화 검토 대상으로 취급한다. 일반 절차 스킬과 자동 수정·종료 검사를 줄이고 필수 서버 권한·Git·생성 계약 보호를 유지했다. native 비교 36회의 결과를 품질 향상이나 비열등성 증거로 확대하지 않는다.
- 기존 앱 목록 누락·표시·전체 페이지 조회를 보완했다. 지정 원격 프로젝트의 dev/prod 등록은 읽기 전용으로 대조했으며 원격 앱이나 서비스를 변경하지 않았다.
- 독립 앱의 정의·릴리스·설치·PKCE 앱 세션, SDK/포털 호스트, 검증된 Git 소스 연결과 스타터, 로컬 제한 컨테이너, 불변 이미지 배포·unknown 관측·복구와 독립 데이터 앱을 구현하고 범위별로 검증했다. 작은 앱의 로컬 수용량 검사를 실제 개발 서버 전체 성능으로 일반화하지 않는다.
- Workbench의 작업별 입력·첨부·선택·대화 위치, 저장 결과와 native 관측의 구분, 소스 준비·등록 초안·상태 비교·배포 도구를 개선했다. SQLite를 유지하고 별도 릴리스 후보를 검증했다. 실제 서비스 설치·기동·운영 배포는 하지 않았다.
- 공식 묶음의 별도 UI build와 API composition·비활성 image, source inventory·writer fence·Docs WS drain·역할 준비를 추가했다. 최초 manifest/도움말·Diagrams·Bento·Mail 업무 소유 이전과 Planner까지 15개 원본 보호는 실행별 근거를 남겼다. 전체 API·DB·worker 서비스 분리는 완료되지 않았다.

## 2026-10-07 추가 구현과 검증

- 최초 앱 등록의 제한된 1회 위임, 현재 source/Task/session 확인, 응답 유실 복구를 Core·포털·Workbench에 연결했다. SQLite 0008 이관과 후보별 검증을 구분했다. [REGISTRATION_AUTHORIZATION.md](REGISTRATION_AUTHORIZATION.md)가 계약과 범위를 설명한다.
- 소유자의 최초 개발 미리보기·권한 설정을 현재 세션·자기 설치·generation/digest/revision CAS로 제한했다. 설정 저장을 앱 실행 준비나 배포 완료로 표시하지 않는다. [OWNER_PREVIEW.md](OWNER_PREVIEW.md).
- SDK의 테마/언어와 명시적 앱 이동 제안, 사용자가 선택한 한 파일의 제한 읽기를 구현했다. 파일은 기존 MIY/앱 세션·목적별 짧은 서명·현재 Files ACL/버전에 묶고 최대 10 MiB로 제한한다. 실제 환경 키 미적용·live MinIO 미검증·동기 DB 선점 없는 기한의 한계를 기록했다. [SDK_NAVIGATION.md](SDK_NAVIGATION.md), [SDK_FILES.md](SDK_FILES.md).
- Planner 개인 일정 편집기/API, Video 목록/API, Meeting API/선택기, Files workspace의 실제 소유를 공식 library로 옮겼다. 공용 Context/API/time/선택기/download/format/media는 platform library가 소유한다. 기존 객체 identity와 호환 경로를 유지하고 재현한 세션·화면 수명 결함만 좁게 보완했다. 전체 업무 화면과 root adapter는 일부 남아 있다.
- Files·선택 파일의 최종 통합은 portal 브라우저 27개, official 브라우저 11개와 각 production build를 통과했다. 이후 PMS 변경을 포함한 최종 build 근거로 사용하지 않는다. 최신 Workbench 후보 `8d8b5fa8…`는 입력 241개·payload 409개, SQLite/vault/backup/두 스타터와 packaged Unicode 검사로 검증했다. 이전 후보의 browser/native 결과와 구분한다.
- Docker 복구 후 pinned Codex 초기 연결은 되지만 제한 컨테이너의 namespace syscall은 차단된다. 상위 seccomp와 후속 AppArmor 경계를 기록했으며 호스트 보안 정책이나 서비스를 변경하지 않았다. 격리 native 실행·전체 자연어 개발 흐름은 미완료다.

## 2026-10-07 사용자 요청에 따른 중단 준비

현재 PMS 공개 API·선택기 소유 이전과 DM 네 원본 보호/첨부 저장의 응답 유실 보완을 기존 집중 검증·기록까지 마무리한다. 새로운 구현 범위나 PMS 최종 production build/브라우저는 시작하지 않는다. 해당 검사와 전체 자연어 시범·공식 서비스 분리는 재개 이후 범위다. 최종 중단 시각과 결과는 [STATUS.md](STATUS.md) 및 아래 후속 기록에 남긴다.

### 중단 확정

PMS는 실제 소유 이전과 집중 회귀·타입·경계 검사를 마쳤다. 최종 두 build/브라우저·독립 리뷰 완료는 재개 후로 남긴다. DM은 실제 PostgreSQL 218 PASS·외부 MinIO1개 제외·독립 리뷰까지 마쳐 보호 범위를 19개로 갱신했다. 모든 담당 에이전트가 종료했으며 소유 임시 DB·검사 프로세스도 정리했다. 커밋·게시·운영 배포나 새 업무 범위는 시작하지 않았다. 사용자와 중간 점검 후 명시적인 재개 요청을 기다린다.

## 2026-10-07 중간 점검: 구조 완성 우선으로 범위 조정

사용자가 구조에 필수인 변경과 치명적 문제는 함께 해결하되 비필수 앱 개선·상세 기능 검증은 이슈 대장에 남기고 별도 요청 때 수행하도록 지시했다. `PLAN.md`에 판단 기준과 구조 인수 조건을 확정하고 `POLICY.md`·`WORK_ITEMS.md`·`VALIDATION.md`·`STATUS.md`·안내/PMS 계획에 같은 범위를 반영했다. `APP_ISSUES.md`를 만들어 기존 근거에서 확인되는 앱별 추가 인수 미실시 항목5개를 `검증 대기/deferred`로 기록했다. 확인된 결함으로 오인하지 않으며 기록을 위해 새 테스트나 제품 수정을 시작하지 않는다.

공식 API/worker·데이터 소유, 남은 UI 의존성, native 격리, 전체 자연어 개발·독립 배포와 권한·데이터 보존은 구조 완료에 필요한 현재 작업으로 유지한다. 이전의 수정·검증 결과를 되돌리거나 필수 CI/릴리스 경계를 면제하지 않는다. 후속 앱 이슈는 구조 작업의 의존성에 넣지 않고, 일반 “계속” 요청으로 자동 실행하지 않는다. 이번에는 문서만 변경했으며 제품 구현 중단을 유지한다.

## 2026-10-07 구조 우선 구현 재개

사용자가 구현을 재개하도록 지시했다. 중간 점검의 구조 필수·치명적 문제 기준을 유지한다. 부모는 PMS 공개 계약의 현재 소스로 두 production build/대표 브라우저를 확인하고 통합한다. 독립 에이전트는 공식 UI의 실제 소유·공통 의존성, 전체 공식 원본88개의 DB guard, 공식/플랫폼 worker·Beat·queue 경계를 맡는다. 기능 확장과 앱별 상세 검증은 이슈 대장에서 계속 보류하며 커밋·서비스·공유 DB·운영 배포는 수행하지 않는다.

### 개발 사이트 오류 우선 수정과 PMS 최종 연결

사용자보고의AppRoot import오류를우선해결했다. 실행중Nx Vite경로cache와새sourcealias의불일치였으며ownedVite설정에서명시한경로로자동reload됐다. 실제개발호스트/로컬의브라우저렌더와24resolver계약을검증하고필수웹구조CI에연결했다. 이어PMS최종두build·각대표브라우저6개를통과했다. 작업은공식UI실제소유·전체공식sourceguard·worker분리로이어가며앱별상세개선은보류한다.

### 공용 module·전체88개 source·worker 기반 완료와 다음 구조 범위

재개 뒤 공용 routing/recovery/types와 실제 화면을 이미 옮긴 Diagrams·Bento·Mail의 module 조립도 소유 library로 옮겼다. 두 composition build와 각6개·실제dev4개 대표 브라우저, 독립 리뷰를 통과했고 선택 입력1389개 불변·dist hash를 기록했다. Vite resolver 검사도 새 public entry를 포함한29개로 확장했다.

전체 공식 원본88개 guard와 frozen19→88 migration, Files/DM unknown commit의 bytes 보존·Recording 중간 commit 뒤 guard·Meeting spool 삭제·revoke 순서의 critical 보완을 최종 PG210개와 독립 리뷰로 확인했다. worker는 task14/14·Beat6/3의 비활성 profile·소유 queue를 만들고 전체78개와 producer3개, matching wheel3개를 검증했다. 원본 guard·비활성 artifact를 실제 서비스 분리 완료로 표시하지 않는다.

다음은 Whiteboard 전체 업무26개·기존spec16개·asset5개와 공용 realtime/directory/users6개를 실제 소유로 옮기는 작업이다. 다른 에이전트는 공식 worker의 durable claim·실행 세대·외부 효과와 source outbox의 플랫폼 전달 경계를 읽어 bounded 구현 범위를 정한다. 세부 앱 기능 인수는 이슈 대장에서 계속 보류하며 커밋·운영 변경은 수행하지 않는다.

### Whiteboard 구조 인수와 worker 후속 경계

Whiteboard 전체 실제 source와 공용 realtime/directory/users를 옮기고 교차 앱 공개 entry를 연결했다. 부모 독립 비교에서32개 body·5개 asset이 보존됐으며, 실제 두 composition 브라우저에서 공식 root의 Realtime Context 누락을 추가 발견했다. 포털의 actual editor는 열렸지만 공식은 useRealtime 오류로 실패했다. 공식 root에 offline(token=null) 실제 Provider를 제공하고 기존 실시간 traffic 비활성 상태를 유지해 각11개·실제dev7개 최종 검사를 통과했다. 앱의 상세 편집/공유 기능은 확장하지 않았다.

Files cleanup worker의 claim 이후 외부 삭제도 재현 뒤 같은 Session에서 writer와 exact claim을 재확인하도록 보완했다. actual PG13·worker78·deadline11과 독립 리뷰를 마쳤다. 기록된120/90초가 실제 task에 적용되지 않던 keyword만 해당 범위에서 정정했다. 나머지 worker의 긴 외부 효과·발행·Beat는 아직 미완료다.

다음 병렬 범위는 Community 전체 UI와 전용 Markdown, 공용 auth/media/locale 및 namespace catalog의 실제 소유 이전, Mail worker의 processing claim과 remote phase, 기존 projection event/head를 재사용하는 고정4종 source outbox와 Core receipt다. 각각 로컬 합성 fixture에서 failure boundary를 확인하며 새로운 일반 하네스·실행 엔진·서비스 활성화를 추가하지 않는다.

### Community 전체 소유 인수와 Mail phase 경계

Community 실제 module/화면/전용 editor/event·CSS와 공용 auth/media/date/locale를 옮겼다. root 단일 i18next 초기화와 namespace catalog composition을 유지하고, 실제16개 구현·syncLocale·CSS·전체 ko/en data의 동일성을 독립 확인했다. suite370/platform100/root33·타입/구조, 두 build·각13개/실제dev9개와 owner67개 freeze를 마쳤다. 초기 browser의 명시 채널 fixture1개만 정정했으며 채널 오류 표시의 후속 확인은 APP-ISS-006으로 보류했다. 앱 게시·업로드 기능을 개선하지 않았다.

Mail은 stale attempt의 완료 덮어쓰기와 DB 제어오류의 provider retry를 실패 우선 확인한 뒤, 불변 claim·같은 Session의 단계별 source/row/ACL guard로 보완했다. actual PG63·권한29·worker80과 독립 리뷰를 마쳤다. 기존 commit·정상 provider retry를 유지하고 불명확한 commit 뒤 추가 쓰기를 중단한다. broker·Beat·ASR lifetime은 완료라고 표시하지 않는다.

다음 UI는 Recording/Planner가 의존하는 실제 Docs 전체34개 구현·localbarrel2개와 해당 catalog다. 기존14spec은 suite로, 실제 ko/en publication 통합1개는 root에 둔다. 다음 worker는 Recording의 두 동기 common-gateway phase로 좁히며 authoritative audit와 기존 progress COMMIT은 유지한다. 고정4종 source outbox/Core receipt의 최종 shared-schema 검증도 병렬로 마무리한다. 새로운 일반 하네스·서비스·배포나 앱별 상세 인수를 추가하지 않는다.

### Source outbox와 Core 수락의 로컬 구조 인수

고정 Docs/PMS/Meeting/Files intent·append-only outbox와 Core receipt를 기존 projection/job 체계에 연결했다. 원본88개와 transport1개 권한을 분리하고 현재 DB principal의 provenance·연속 source revision·exact event replay를 SQL에서도 확인한다. 최종 actual PG240·입력96개·이전22migration 불변·owned cleanup과 독립 읽기 리뷰를 마쳤다. 테스트 DB reset만 exact2 immutable trigger를 transaction 안에서 복원하도록 보완했다.

현재는 legacy의 같은 transaction emit→accept bridge다. source-only 서비스 wiring/consumer, Docs의 남은 visibility event, partition 생성/repair, Core Files extraction 역방향 쓰기는 완료 조건으로 남긴다. 기존 head/version·최종 ACL을 바꾸거나 새 일반 eventbus/하네스를 추가하지 않았다. 다음 bounded source 경계를 읽기 분석하며 shared DB/role/service는 변경하지 않는다.

### 2026-10-07 — Recording 요약/검증의 source effect 경계

두 동기 common gateway 단계에서 기존 heartbeat를 유지하면서 같은 Session의 source SHARE와 exact attempt/version/owner/current ACL을 호출·결과 COMMIT까지 결속했다. pool DB 오류가 gateway의 모델 오류 wrapper를 거쳐 retry가 되던 실제 실패를 worker의 direct SQLAlchemy cause 경계에서 수정했다. 최종 actual PG27·worker81·입력153개 불변과 독립 리뷰를 마쳤다. 실제 Hermes/MCP/감사 경로와 ASR·persist는 유지한다. pool3 양성/pool1 bounded 거부이며 source-only 서비스 활성화·긴 remote 효과의 취소·broker/Beat는 완료로 표시하지 않는다. 상세 증거는 VALIDATION의 해당 기록이 소유한다.

### 2026-10-07 — Docs 전체 UI 소유 이전과 최종 조립

Docs 실제 구현34개·export2개·해당 한영 catalog와 교차public소비자19개를 suite 소유로 이전했다. 기존34구현 body와 export/전체번역 동등성·suite473/root73/coldinit15·타입/구조·독립 리뷰를 확인했다. 두 고정 build의 포털15+1/공식16·실제dev12개가 모두 통과했고 owner132개·selected1,492개가 최종 불변이다. primary/source 추가 capture 시점과 잘못된 testfilename의 한 개 보완, I/O teardown은 VALIDATION에 구분 기록했다. 전체 UI transition은6개이며 다음은 Recording source/catalog/고정 서비스워커의 actual 소유 이전이다. 운영이나 Workbench 후보를 배포하지 않았다.

### 2026-10-07 — Docs 권한 변경의 source visibility intent

신규 visibility 생산점 네 곳에 기존 source intent/Core bridge를 연결하고 원본과 projection 작업을 같은 transaction에 보존했다. intent 누락 4 FAIL과 동시 grant의 FK 잠금 승격 오류 40P01을 먼저 재현했고, PK를 바꾸지 않는 FOR NO KEY UPDATE로 후자를 보완했다. 최종 PG 78개, 입력 125개와 이전 migration 23개의 불변성, 독립 리뷰를 확인했다. RAG 설정, 현재 trash 상태, 캡처한 ID와 현재 ACL을 보존한다. 구형 queue, source-only consumer, partition, Files 역방향 쓰기와 공식 서비스 활성화는 필수 구조 작업으로 남긴다. Recording UI 소유 경로 metadata는 이 검사 뒤 생성했으며 이전 PG 결과에 소급하지 않는다.

### 2026-10-07 — ASR COMMIT 인계와 결과의 현재 소유자 보존

진행률의 durable COMMIT 뒤 callback을 반환하기 전에 원래 source claim과 현재 ACL을 같은 Session에서 다시 확인한다. transcript와 persist 최종화도 원래 attempt/key/version에 결속했다. 인계와 persist retry의 3 FAIL, 잘못된 task 옵션을 먼저 재현하고 PG 63개와 보강 7개, worker 집중 검사 15개, 입력 157개와 owner 11개의 불변성, 독립 리뷰를 확인했다. 기존 summary/gateway 함수 18개와 Core backend bytes는 보존한다. 원격 요청의 불명확한 수락 뒤 재시도, broker, Beat와 현재 runtime generation은 필수 후속 구조 작업이다. 새 dispatcher나 서비스 배포는 없다.

### 2026-10-07 — Recording 전체 source와 고정 SW 소유

업무 구현 25개, catalog와 624 bytes SW, 공용 app-links/concurrency 두 개를 실제 소유자로 이전했다. 본문·번역·asset 비교 29개, suite 523/platform 102/root 43개와 alias 51/asset 4개, 타입·경계·독립 리뷰가 통과했다. 기존 고정 URL과 default scope는 설치된 Vite의 한 파일 adapter로 유지한다. 최종 두 build에서 같은 SW bytes와 브라우저 각각 19개, 실제 dev 15개를 확인했다. 두 build 전에 캡처한 입력 1,526개와 owner 87개는 최종 검사 뒤에도 같다. 이 시점에는 전체 UI 전환 다섯 개가 남는다. Planner가 Meeting UI를 소비하므로 다음은 Meeting의 의존 경계다. 제품 배포·원격 Git 변경·실제 녹음은 없다.

### 2026-10-07 — Meeting 이전과 구형 Docs 작업의 변환 계획

Meeting의 업무 구현 39개, 공개 export 파일 한 개와 공용 기능 다섯 개를 기존 본문·초기화·지연 로딩 계약을 유지하며 옮기는 작업을 진행한다. canonical source 경로와 manifest 검사 20개를 실제 소유 경로로 갱신했다. 실제 dev 주소에서 합성 API로 목록, 상세 화면의 Docs 입장 거부, Meeting 입장 거부와 Planner의 lazy 회의 창 네 개를 확인했다. 최종 전체 검사·두 production build·소스 불변성 확인은 별도로 마무리한다.

구형 Docs scope/RAG/keyword 작업은 Core가 현재 source를 SELECT로 확인하고 실제 repair event와 후속 작업을 원자 저장하도록 설계했다. job receipt와 target receipt 두 표로 원래 작업과 실제 이벤트의 FK를 보존한다. 작업당 최대 100개를 한 transaction에서 변환하고 초과 범위나 실행 중인 구형 작업은 명시적으로 거부한다. 이는 구현 중인 계획이며 검증 완료 결과가 아니다. source 권한 확대나 partition 자동 생성, 가짜 source event는 허용하지 않는다. Recording broker는 source 실행 기록과 Core 발행 기록을 나누는 읽기 설계를 마쳤으며 현재 API와의 연결을 검토 중이다.

### 2026-10-07 — Meeting 전체 소유 인수

Meeting 본문·공개 export·전체 번역 46개 동등성과 suite 582/platform 122/root 44/date 27개, 타입·경계·독립 리뷰를 확인했다. 최종 두 build와 브라우저 포털 23/공식 23/실제 dev 19개가 통과했다. 두 build 전에 고정한 선택 입력 1,599개와 owner 126개는 최종 불변이다. 기존 초기화·같은 객체·lazy 창을 유지했으며 새 private API 테스트는 경계 예외 없이 실제 앱 owner 아래로 옮겼다. 전체 UI 이전은 여덟 개이며 다음은 Planner와 공식 업무 calendar의 실제 소유 이전이다. 세부 앱 기능 인수나 서비스 배포는 포함하지 않는다.

Recording legacy 발행은 브로커가 접수한 뒤 응답을 잃었을 때 attempt를 지우는 실패를 실제 PG로 재현했다. 원 attempt와 저장한 오디오를 보존하고 불명확한 수락 뒤 새 작업을 만들지 않는 보완을 진행한다. 재시도 리뷰에서 reset COMMIT와 attempt 배정 사이의 현재 권한 공백도 발견해 함께 수정한다. managed command/Core 발행 두 표 설계와 현재 기본 API의 보완은 별도 범위다.

### 2026-10-07 — Planner 소유 이전과 개발 화면 재검증

Planner/calendar의 업무 구현과 순수 공용 helper를 실제 소유자로 옮기고 본문·CSS·전체 번역 33개, 소비자 본문 8개의 동등성을 확인했다. suite 666/platform 124/root 45개와 타입·경계·독립 리뷰, 두 build·browser 포털 26/공식 26/실제 dev 22개가 통과했다. API fallback이 Vite 소스까지 막던 테스트 한 개만 정정했으며 제품 등 1,633개는 두 build 전부터 불변이다. 최종 입력 1,634/owner 106개와 이전 spec 17개 부재를 확인했다. 전체 UI는 아홉 개이며 다음은 PMS, 이어 Files·Video Chat이다. 별도 릴리스 활성화나 앱 기능 개선은 포함하지 않는다.

### 2026-10-07 — 구형 작업과 Recording retry의 구조 인수

Core Docs repair는 source SELECT만으로 고정 세 종류의 구형 작업을 최대 100개씩 원자 변환한다. 기존 event 불변성과 FK를 재사용해 불필요한 snapshot 초안을 제거했고 actual PG 238개·입력 107/최종 읽기 116개·과거 migration 23개와 독립 리뷰를 확인했다. 원 ID 조회로 COMMIT 불확실성을 처리하며 generic retry나 source 쓰기를 만들지 않는다. 구버전 drain과 source-only/partition/Files 후속은 남는다.

Recording legacy 발행은 원 attempt·오디오를 보존하고, 두 retry의 현재 권한 검사·reset·attempt를 한 COMMIT으로 묶었다. accepted-error와 권한 공백을 먼저 재현한 뒤 actual PG 68개·입력 164/owner 6개와 독립 리뷰를 확인했다. 기본 API·Canvas·worker/schema/설정은 유지한다. 다음은 고정 네 단계의 durable source command와 Core publication 두 표다. 로컬 비활성 코드로 구현하며 원격 접수 여부가 불명확한 오류를 자동 retry로 분류하지 않는다. 운영 queue·GRANT·서비스·배포는 승인 범위에 추가하지 않는다.

### 2026-10-07 — 서버 재시작 전 사용자 요청으로 일시중단

새 범위를 시작하지 않고 이미 실행 중이던 PMS 순차 검사를 끝냈다. 현재 PMS 275개 입력·부모 metadata 다섯 개와 이전 54개 경로 부재를 고정했고 소유 Vite 자원을 정리했다. 새 PMS production build·browser·부모 독립 비교는 아직 수행하지 않았다.

Recording managed는 actual PG pipeline 25개와 후기 pure wire 11개까지 기록하고 동결했다. 별도 authority 검사는 23 PASS/1 fixture FAIL이며 Data가 필수 artifact 인자 누락으로 분류했다. 중단 뒤 수정·재실행은 하지 않았다. 독립 리뷰·legacy 영향 통합·운영 schema/principal 준비는 완료로 표시하지 않는다. 소유 PG 컨테이너와 검사 프로세스를 정리하고 모든 에이전트를 종료한다. 관련 작업은 커밋하지 않았으며 shared DB·서비스·queue·배포를 변경하지 않았다. 재개 원본은 RESTART_CHECKPOINT.md다.

### 2026-10-07 — 긴급 백업 후 구조 구현 재개

사용자 지시로 별도 비공개 GitHub snapshot을 보관한 뒤 구조 구현을 재개했다. 기존 dev HEAD·index·파일은 유지하며 추가 게시·서비스 변경을 실행하지 않는다. PMS 275개·Recording authority 108개·delivery 12개 동결 입력이 모두 현재 파일과 같다. PMS 구현 94개와 소비자 본문 다섯 개, 도움말 HTML·전체 ko/en catalog의 부모 독립 비교가 일치했다. 새 production build·화면 통합은 이 이후 별도로 검증한다. Recording 권한 검사 fixture의 누락 artifact 인자를 보완해 실제 restricted-Core drain lock 검사를 통과했고 잔여 history·동시 실행·legacy 영향과 독립 리뷰를 진행한다. 앱별 상세 개선·검증은 계속 보류한다.

### 2026-10-07 — PMS 부모 통합과 마지막 공식 UI 소유 의존성

PMS 94개 구현/export·소비자 본문 다섯 개·HTML·전체 catalog 부모 비교와 두 build를 마쳤고 production browser 각 31개가 통과했다. 실제 dev의 새 PMS 다섯 경로도 통과했고 전체 30 PASS/1기존 Meeting read-count fixture FAIL은 APP-ISS-007로 남겼다. 선택 입력 1,734개 중 제품 등 1,733개와 owner 275개는 불변이며 후기 E2E 하나의 기존 GET mock·calendar fixture만 보완했다. 전체 UI source 인수는 열 개다.

Video Chat의 남은 세 구현과 locale/module 소유, Files의 공용 Chatbot 의존성을 다음 구조 범위로 잡았다. 공용 Chatbot closure는 root 역참조·platform→업무·runtime cycle 0인 projected scope를 확보했다. 공용 구현을 실제 platform owner로 옮기고 사용되지 않는 Meeting helper는 삭제 없이 공식 owner에 보존한다. 단일 root Context/i18next·Portal Map/Set·SSE·HTML isolation과 기존 public 객체를 유지하며 앱 기능을 확장하지 않는다.

### 2026-10-07 — Recording managed의 로컬 비활성 권한·legacy 인수

고정 네 단계 Source command와 별도 Core publication을 실제 제한 LOGIN 계정으로 검증했다. 두 Core 준비가 같은 command를 동시에 INSERT하던 경쟁을 실패 우선 재현하고 고정 ON CONFLICT 후 기존 binding·issuer·현재 producer 권한을 재확인하도록 보완했다. 불명확한 COMMIT을 재시도하거나 binding/token을 덮어쓰지 않는다. 실제 pipeline 37 PASS와 installed Celery wire11·worker 등록/비활성 profile/현재 권한/deadline23, API 구조736/3250을 확인했다. source result·terminal·고정 successor는 한 COMMIT이며 running/remote unknown은 원래 token과 attempt를 보존한다. 기본 HTTP는 legacy를 유지하고 CLI는 준비·상태·같은 ID 조정만 제공한다.

영향 legacy 통합의 첫 실행은 빈 Core publication COPY에서 현재 권한 guard가 fixture 계정을 거부해 122 setup ERROR를 남겼다. 제품 SQL/권한은 그대로 유지했다. 초기 baseline에서 고정 두 protocol 표가 비어 있음을 확인하고 빈 COPY만 제외했으며, 테스트 DB truncate+복원을 한 owned transaction으로 묶었다. 실제 실패 주입 뒤 데이터·history trigger·ownership seed 복구와 다음 복원, direct empty COPY 거부를 6 PASS로 확인했다. 중간 내부 FK trigger 계수·비원자 복원 실패와 일찍 시작한 capture의 test 입력 변경도 각각 실패 근거로 보존했다.

수정 후 영향 legacy dispatch·ASR/persist·실제 summary gateway/audit·publisher는 125 PASS, 58.26초·입력180개 before==after였다. 최종 authority·이전 schema·원본88개·Alembic·fixture는 95 PASS, 23.73초·입력785개 before==after이며, 89→90 drain 전환·기존 principal grant 불확대·신규 principal의 전체 guard 선행 검사·이력/downgrade 거부를 포함한다. 이전24migration은 불변이고 소유 PG 자원을 정리했다. 별도 authority/Docs/outbox/role175와 중복 검사를 합산하지 않는다. 독립 읽기 리뷰 17개 입력이 동일하며 추가 차단 product 결함은 없었다. [VALIDATION.md](VALIDATION.md)와 [Recording 소유 문서](../apps/api/src/miy_api/domains/recording/PIPELINE.md)가 실행 증거·현재 계약을 소유한다.

이 PG 동결 뒤 부모가 Files·Video Chat UI 소유 경로를 생성했다. 현재 authority785와 비교하면 Core app_contracts_generated.py와 suite ownership.json 두 경로, legacy180과 비교하면 생성 Core metadata 한 경로만 다르다. 변경은 UI management/source 소유 목록이며 API·원본88개 model·worker·stage/writer·SQL/roles/managed 프로토콜은 그대로다. managed37의 captured180에는 후기 conftest 수정도 존재하며 별도 복원/legacy 근거로 검증했다. 과거 실행 당시의 불변성은 보존하되 후기 metadata를 소급한 최신 전체 source 동일성은 주장하지 않는다.

현재 공식 UI source/build 소유와 최종 두 composition 통합 인수는 12/12개다. Files·Video Chat의 부모 비교·두 build·브라우저 근거는 아래 최종 조립 기록과 구분한다. 이 Recording 범위는 비활성 로컬 프로토콜 인수이며 서비스 전환 완료가 아니다. source-only wiring/consumer·partition·Files extraction 역방향 쓰기, matched schema/principal/artifact와 현재 app/ACL·AI/audit·credential 권한, 실제 bounded broker/ACK/queue·Beat, running remote unknown의 receipt·취소·복구 및 legacy stranded attempt 조정은 필수 구조 후속으로 남긴다. 공유 DB migration/GRANT·provider/broker·서비스·배포는 수행하지 않았다.

### 2026-10-07 — 공식 UI 12개 source/build 최종 통합

Files·Video Chat의 남은 실제 구현과 공용 Chatbot을 각 소유 library로 옮겨 공식 UI 12/12개의 source/build 이전을 마쳤다. 부모 비교는 Files/common 본문74개·전체 ko/en catalog·CSS·좁은 Files 공개 API, Video의 의도한 Room lifetime 수정 외 helper14개와 LiveKit CSS를 확인했다. 기존 로그인·route의 늦은 join/action이 현재 화면에 연결되던 critical 경계만 보완했으며 synthetic SDK probe29개·독립 리뷰를 실제 미디어/provider 인수로 확대하지 않는다. Files owner254개와 Video review35개는 최종 입력에서도 동일하다.

최종 두 build는 포털8,567 modules/26.23초·공식7,833 modules/22.81초로 통과했다. 고정 artifact의 합성 Chromium은 포털37개·공식36개의 고유 PASS이며 official의 portal-only Chatbot skip1개를 구분한다. 처음 명령에서 빠진 Whiteboard 한 검사를 각 같은 artifact에 별도로 실행한 결과를 포함하고 batch 수에 중복 합산하지 않는다. 기존 실제 dev 주소에서는 selected Files4·Video2의 6 PASS/11.9초를 확인했다. 이전 Meeting read-count fixture APP-ISS-007은 여기서 재실행하거나 통과로 재분류하지 않았다. 초기 dev fixture/locator 실패와 source resolver 실패도 보존하고 제품 수정 없이 기존 계약에 맞춰 정정했다.

선택 입력1,823개는 두 build 이전부터 최종 브라우저 뒤까지 불변이고 PMS HTML·Recording SW의 고정 bytes/URL도 유지했다. 해당 검사는 synthetic API로 실행했고 고객 데이터·실제 모델·파일 쓰기·미디어를 사용하지 않았다. 상세 실행과 범위는 [VALIDATION.md](VALIDATION.md)가 소유한다. source/build 완료는 독립 runtime/release 또는 전체 portal 업무 제거 완료가 아니다. 다음 구조 구현은 공식 API/worker source-only 실행, Core/source 데이터·queue/Beat·현재 identity/ACL/audit 경계와 Workbench native 연결에 집중하며 앱별 상세 기능 검증·서비스 배포를 추가하지 않는다.

### 2026-10-07 — Files Core 읽기 전용 경계 착수

Docs/PMS/회의 내부 전달·현재 schema 영향 검증을 마친 뒤 Files의 첫 경계를 확정했다. 준비된 Core는 Source의 ready artifact와 실제 event checksum만 읽고 storage/parser/OCR·Source 상태 변경·Source intent 발행을 하지 않는다. pending/failed/invalid ready를 파일 부재와 구분해 vector 삭제를 막으며 provider 생성 전 preflight와 전체 text/blocks/metadata 상한을 둔다. 기존 legacy 실행은 유지한다.

구현 전 계획은 `.runtime/official-files-source-results/PLAN.md`다. Structure는 canonical reader/context/검증, Delivery는 기존 adapter·worker·Core callback, Data는 fresh 최소 reader role·공개 owner-label 컬럼·실제 제한 PostgreSQL 검증을 맡는다. 이 단계에는 새 Source transport/migration이나 기존90 guard/function/role 확대를 넣지 않는다. 아직 제품 검증 완료가 아니다.

이어지는 Source의 고정 durable request/claim/input/result·동일 ID 복구는 필수 구조 범위로 남긴다. old ready artifact에는 storage-key provenance가 없고 현재 object key 자체도 immutable bytes 증거가 아니다. Source writer/현재 actor·app·ACL, prebound Files partition·tree locks, pending Source event의 Core 수락, 실제 OCR 응답 유실 receipt·worker 등록·bootstrap·서비스 조립은 별도 완료 근거가 필요하다. Core 읽기 전용 단계로 이를 완료했다고 표시하거나 앱별 후속 이슈로 미루지 않는다.

### 2026-10-07 — Files Core 읽기 전용 경계 인수

실제 event/head/checksum과 bounded canonical Source artifact만 읽는 Core 조립, 최소 column reader role, Source 쓰기 없는 callback을 구현했다. pending/invalid를 파일 부재와 구분하며 metadata의 체크섬·공개 Source 필드 덮어쓰기를 실제 재현 후 거부했다. 기존 plain/HTML parser 결과도 호환된다. 워커는 실행 전 no-effect hold와 실행 후 unknown을 구분하고, hold 저장의 COMMIT ACK 유실을 일반 provider retry로 보내지 않는다. unknown 이전 processing claim의 live Beat 복구는 운영 전 필수 gate다.

최신 reader65+재현1·final worker47과 actual role40/강화1을 확인했다. 최신 제한 native/external2를 포함한 영향 API는96 PASS/4 FAIL이었다. bootstrap의 실제 removed-setting 참조를 owned 실행-local import로 고치고 partial SQLite fixture를 existing owned PG로 옮긴 뒤 해당7개만 통과했다. 앞서 통과한3개와 중복하므로100개 고유 수락이다. 최종1,148개 before==after==current, 이전대비 bootstrap 제품/test2개만 변화, 이전26 migration 불변과 독립 검토를 기록했다. 세부 횟수와 한계는 [VALIDATION.md](VALIDATION.md)가 소유한다.

다음 F2는 단일 Source 요청의 durable IDs/claim/input과 원문 중간 복제 없는 atomic 결과 적용이다. Data가 새 transport/guard/최소 profile을, Delivery가 Source 명령·local parser를, Structure가 shared pure artifact 계약과 독립 경계 검토를, Root가 current policy 조회 축소·통합을 맡는다. 구현 전 세부 interface를 확정하며 shared DB·env·운영 profile·provider·배포는 변경하지 않는다. 앱별 상세 기능 작업은 계속 보류한다.

### 2026-10-07 — Files F2 구조 구현과 최소 공통 계약

F2의 기존 prebound/pending 파일 local-only Source 처리를 승인하고 구현을 시작했다. request/result/event 세 UUID와 기존 진짜 pending event tip을 결속하며 protocol에 추출 본문을 복제하지 않는다. ready/unsupported는 canonical+terminal+intent의 atomic outer Source transaction, known failed는 삭제·새 intent 없이 failed/error+history로 확정한다. claim/input 관측으로 compute 권한을 재발급하지 않고 OCR은 dispatch 전 hold다. 새 source_scope transport·고정 capability/최소 guard owner와 별도 opt-in profile만 추가하며 old canonical90·이전26 migration·existing principal replay는 보존한다.

기존 bounded selected-object reader를 재사용해 첫 입력 상한10MiB·total10초·perIO2초·exactsize·no retry/redirect를 적용한다. actual Source writer/File/input 잠금은 read·close·input bind COMMIT까지 유지하고 parser는 잠금 밖에서 실행한다. fresh outer Session·sync runner pre-loop refusal과 실제 current actor/app/ACL/AuthSession5 최소 조회를 구현 조건으로 확정했다. 전체 Source HTTP/audit/서비스 활성화는 후속 범위다.

Structure가 순수 shared artifact validator를 분리했고 기존 reader65+metadata 재현1+공개 계약10은76 PASS다. Root는 작성자가 아니며 새 module/reader/외부 metadata 경계를 읽고4개 동결 파일과15개 context/external 본문 동등성을 따로 확인해 이 순수 계약을 인수했다. Root 소유의 current-policy3 query 변경은 기존 Files external/corpora/PMS authority 동작35 PASS이며 실제 SQLite·envfile/network0·선택11개 불변이다. 이것을 새 제한 Source role 인수로 확대하지 않는다. Data와 Delivery는 SQL/role 및 Source 명령/runner를 각각 구현하고 Structure는 이 두 owner의 실패 경계를 독립 검토한다. 개별 앱 상세 기능 작업·공유 DB/role·서비스·provider·추가 publication은 진행하지 않는다.

### 2026-10-07 — Files F2 제한 Source 통합과 실패 교정

현재 Source 명령·local parser·native/managed ACL·profile replay와 F1 native/external을 실제 제한 PostgreSQL에서74 PASS/51.99초로 확인했다. 현재 source/test795개는 실행 전후 같고 소유 컨테이너를 정리했다. 처음72 PASS/25 FAIL·51 PASS/19 FAIL과 별도 non-admin1 FAIL은 보존했다. app admission/실제 parser 출력/managed checksum fixture를 보완했고, 실제 `SELECT *` 정책 조회 결함은 기존 app/group predicate를 유지한 ID column 조회로 고쳤다. 권한을 늘리지 않았으며 기존 정책35개 회귀도 통과했다.

outer transaction의 terminal 이후 File/tip 재변경은 고정 deferred guard로 COMMIT에서 거부한다. fresh Engine-backed Session만 허용해 외부 Connection의 join/savepoint ACK를 Source COMMIT으로 해석하지 않으며 caller transaction은 보존한다. 동일 claim 관측은 새 compute를 허가하지 않고 terminal apply는 거부하며 현재 권한으로 역사적 receipt만 관측한다. 이전 schema/role·Recording·전체 원본·fixture 영향 검사와 독립 검토를 마친 뒤 F2를 인수하고 F3의 pending/ready Core 수락·stale 후보 차단으로 이어간다. 서비스 활성화·배포나 개별 앱 상세 기능 인수는 포함하지 않는다.

최종 검토에서 deferred 제약을 immediate로 바꾼 뒤 File을 재작성하는 실제 SQL 우회를1 FAIL로 재현했다. 한 private fixed seal과 네 Source trigger로 같은 top transaction의 terminal 뒤 File/outbox/metadata/corpus 입력 변경을 막고 실제 terminal request도 top-XID로 제한했다. 새 상태·본문 복제·old guard/role 변경 없이41 PASS/30.20초·793개 불변·owned cleanup으로 확인했다. event-ID 잠금 대기 뒤 인증 재검사·원자 rollback도 포함하며 앞선74에 합산하지 않는다. 현재 mandatory schema/role/Recording/fixture 영향 검사 뒤 독립 검토를 마무리한다.

### 2026-10-07 — Files F2 인수와 F3 착수

mandatory PG는268 PASS/1 old migration-test FAIL이었다. 정확한 owned migration retirement guard 검사로 테스트만 정정하고 동일 완료 File/metadata/corpus/다음 event의 후속 transaction·원 receipt 불변 양성을 추가해 targeted2 PASS를 확인했다. mandatory270 고유 수락이며 최종797 map의 차이는 그 두 test 경로뿐이다. 제품/권한/기존26 migration과5 owner는 그대로이며 독립 검토의 이 비활성 Source 경계 blocker는0이다. 실행 수·시점·이전 실패는 검증 문서가 구분한다.

F3는 별도 Files Core ingress/consumer, 고정 Core partition SHARE·새 최소 profile, Source current-content helper·keyword/vector/RAG hydration과 공통 retrieval/Files search/chat 연결로 나누어 착수한다. pending/failed/OCR의 진짜 noSHA tip은 no-job fence이며 closed gate에서도 control head/receipt만 수락한다. ready 후보의 원 SHA/partition을 현재 Source와 비교해 rerank/grounding/snippet/evidence 전에 좁히고 마지막 사용 전 다시 확인한다. 기존 세 앱 Source resource·discovery와 legacy/Source parser 본문을 유지한다. Source immutable upload/allocation/트리·HTTP/audit·queue/Beat·서비스 활성화와 앱별 상세 기능은 이번 인수에 포함하지 않는다.

### 2026-10-07 — Files F3 현재 결과 표식과 응답 경계 연결

같은 bytes의 재추출은 SHA가 같아도 출력이 달라질 수 있어 기존 Source `extracted_at`을 canonical UTC microseconds 결과 표식으로 채택했다. 새 version table·본문 복제·일반 framework는 추가하지 않는다. keyword/vector builder가 표식을 보존하고 chunk metadata는 이를 바꾸지 못한다. 표식 없는 구형 후보는 fail closed이며 명시적 재색인과 전환 coverage를 필수 gate로 남긴다.

Root는 공통 retrieval의 AI 입력 전/최종 use 검사, keyword의 매 refill page 및 최종 검사, Files search/chat의 Source·ACL 이후 검사와 bounded page refill/has_more를 연결했다. 7 FAIL/1 PASS 재현 뒤 현재 결과·Source 응답 경계/keyword policy 41 PASS를 확인했다. 실제 DB 권한·Source→Core transaction과 기존 HTTP/RAG 영향 검사는 별도 에이전트/실행으로 진행하며 아직 F3 전체 인수로 표시하지 않는다. 앱 세부 기능은 계속 별도 요청 범위다.

### 2026-10-07 — Files F3 비활성 경계 인수와 F4 착수

실제 제한 Source/Core PostgreSQL의 F3 통합은79 PASS 뒤 fixture1 FAIL/2 ERROR를 테스트만 정정했고, corrective3개와 현재 native 영향10개 파일을 함께 검증해189 PASS·6 외부 통합 제외·입력812개 불변을 확인했다. 별도 mandatory 권한·migration·Recording·fixture 영향167 PASS·입력813개 불변이며 두 실행을 합산하지 않는다. 모든 소유 PG를 정리했다. 독립 리뷰는 bounded F3 blocker0이고 Root는 serving 작성자의 구현을 별도로 검토했다. Source/parser·이전27 migration·기존 세 앱 경계 보존은 이 인수 시점의 근거다.

F4는 기존 Engine-backed caller transaction을 runner가 거절하면서 close하는 결함부터 시작한다. 실제 PostgreSQL stage5 PASS/runner5 FAIL로 호출자 작업 손실과 savepoint cleanup SQL을 재현했다. 이어 명시적 기존 File workset의 Source-only probe, 별도 Source descriptor SHARE capability와 retained UUID Core setup을 분리해 구현한다. immutable object publication·aggregate/tree serialization·최신 genuine Source tip과 Core materializer event의 결속은 필수 후속이다. 앱 세부 기능·shared DB/role/service·worker/Beat·배포는 작업 범위에 추가하지 않았다. F3 frozen map을 F4 변경 뒤 current 전체와 같다고 표시하지 않는다.

### 2026-10-07 — Files F4 관측·권한·불변 읽기 경계

runner 소유권 보완51개와 independent review, retained UUID Core setup30개와
작성자 외 리뷰를 마쳤다. 별도 Source descriptor SHARE capability는47개
고유 집중 검사·173개 기존 schema/role 영향과 Root 독립 검토로 로컬
비활성 범위를 인수했다. 기존 profile의 replay는 grant/audit 없이 유지한다.

다중 파일이 역순 corpus에 연결되면 per-File 잠금이 tree 참여자와 순환할 수
있어 실제 PG의 기대 성공1 FAIL을 보존했다. 모든 정렬 corpus를 먼저 잠그고
association drift는 예상 밖 corpus 잠금 전에 거부하도록 수정해 workset34개가
통과했다. shared 단일 파일 명령/runner 영향과 독립 검토는 후속으로 분리한다.
작은 workset의 관측을 전체 bootstrap 완료로 표시하지 않는다.

명시적 object version 고정 전략을 선택해 기존 bounded transport를 재사용하는
read_pinned_object를 구현했다. TCP/presigner29개와 실제 소유 MinIO에서 덮어쓰기·
delete marker 뒤 원본 읽기, exact-version 삭제 뒤 거부를 확인했다. Source의
불변 publication binding과 모든 read/cleanup·unknown 처리 연결은 다음 필수다.
최신 genuine Source tip/accepted Core event의 strict paired reader와 별도 최소
SELECT profile도 구현했으며 실제 제한 계정 통합 검증을 진행한다. effect
조립은 lifecycle와 durable unknown identity 계약부터 확정한다. 과거 인수와
현재 변경의 hash/검증 시점을 구분하고 실제 서비스는 변경하지 않았다.

F4의 후속 관측 인수도 마쳤다. Source workset34개와 기존 commands/ownership51개,
작성자 외 리뷰를 확인했다. strict READ의 초기84개 합동 검사는 Source51/
reader27 통과와 reader fixture6 실패로 보존하고, genuine revision 순서만 고친
실패6 target이 통과했다. 별도 실제 TEMP File shadow1 FAIL 뒤 strict-only
LOCAL namespace 보완과 affected12 PASS를 확인했다. 현재 reader34 고유 PG
검사·동작55개, Root 독립 검토와 API 구조756/3376·i18n은 통과다. 기존
role/Source/F1 권한을 확대하거나 전역 TEMP를 변경하지 않았다. 다음 경계는
FILES_EFFECT_BOUNDARY.md의 fixed Core armed/complete record와 ordered lifecycle
SHARE이며, Source publication은 별도 후속으로 유지한다.

2026-10-07 14:13 UTC — fixed Core effect 조립을 구현했다. 기존 batch/cursor를
세 protected hook으로 재사용하고, 신규 acknowledged arm의 원래 live permit만
한 번 사용한다. 같은 operation/digest의 역사적 관측은 재실행하지 않는다.
두 backend와 refresh ACK 뒤 ledger/jobs를 한 COMMIT으로 저장하고, Source가
비어도 unresolved armed가 있으면 validation/caught_up을 거부한다. 기존
generation/helper 영향110개와 현재 신규 controlled96개는 통과했다. 초기4개
실패 중 canonical model 등록 fixture1종과 실제 Source snapshot의 결과 표식
누락을 구분해 보존·수정했다. 실제 PostgreSQL/권한·잠금 인수와 Source/Core
mapper/table 단일 Engine ownership 보완은 다음 단계다. 앱별 세부 기능이나
shared service/provider/role은 변경하지 않았다.

2026-10-07 14:39 UTC — append30의 실제 제한 PostgreSQL 첫 검증은131 PASS다.
effect 권한59와 Source 소유권/명령72를 구분하며 입력831개 불변·소유 자원
정리를 확인했다. 신규 세대/target 재사용·역사적 관측과 기존 schema 영향
검증은 추가 진행한다. 독립 리뷰에서 세션 정리의 취소가 COMMIT ACK나 원래
unknown receipt를 가리는 필수 경계 오류를 실제 재현해 rollback/close만
BaseException 격리로 수정했다. 수정 후 독립3개는 통과했고 controlled 최신
회귀가 진행 중이다. 과거96/131을 후기 소스에 소급하지 않는다. API 구조
760/3407·2계약과 i18n도 통과했다. 전체 F4·live provider·서비스 cutover는
완료하지 않았으며 앱별 세부 기능은 계속 보류한다.

2026-10-07 15:06 UTC — 고정 Core effect SQL/최소 권한·lifecycle·역사적 관측의
로컬 비활성 인수를 마쳤다. 실제 고유 Data83·Source72·mandatory175와 최신
controlled102를 구분하며 독립 리뷰 blocker0, 원본46개 불변·소유 PG 정리를
확인했다. selective fixture3와 old29 대상 지정 fixture1은 실패 기록을 보존하고
해당 검사만 수정·재실행했다. 권한이나 기존 guard를 완화하지 않았다.
다음 vector 한도 adapter는 공개 RAG API·legacy source를 유지하는 별도
준비된 경로로 승인해 구현을 시작한다. Source TEMP 인증 shadow와 취소
receipt 보존은 추가 실제 재현 후 필요한 최소 수정만 한다. durable caller
retention·불변 publication·tree/bootstrap·F5 서비스 조립은 여전히 필수이며
앱별 비필수 개선/상세 기능 작업은 하지 않는다.

2026-10-07 15:26 UTC — Source pooled TEMP가 실제 revoked execution 조회를
가리는 인증 경계 오류를 실제 제한 LOGIN으로 재현해 transaction-local
canonical namespace로 수정했다. Source 취소가 원래 refusal/COMMIT unknown·
known ACK를 덮는 오류도 좁게 수정했다. actual TEMP1·ownership41·commands39의
81 PASS, 현재243개 불변·원본46 계약 보존과 독립 리뷰 blocker0을 확인했다.
전체 Source HTTP·권한 활성화나 불변 publication 완료로 확대하지 않는다.
준비된 vector adapter는 SDK·loopback·RAG 통합·private logging·유한 response
accounting 검증을 마치고 최종 작성자 외 리뷰 중이다. 현재 API 구조761/3410·
2계약과 i18n은 통과했다. 추가 앱 기능·게시·서비스 변경은 하지 않았다.

2026-10-07 15:48 UTC — 준비된 vector 한도 adapter의 작성자 외 리뷰를 마쳤다.
고유118개(이전115·신규 selector3)와 기존 경로39개를 구분해 인수하며 최신
affected14·선택29개·owned4개 불변을 확인했다. raw payload 예외3개는 red를
보존하고 stable control로 수정했다. Source 최신81 인수와 함께 계획 상태를
갱신했다. 다음 불변 Source publication의 prerequisite인 bounded direct PUT을
작은 별도 adapter로 구현한다. 계획·작성·실제 소유 MinIO0/small/250MiB 검증·
독립 리뷰를 분리했으며 Source schema/role나 shared 서비스를 변경하지 않는다.

2026-10-07 16:23 UTC — Source publication의 작은 비활성 PUT transport를
인수했다. 현재 focused68·selected21 불변, 실제0/small/250MiB PUT·exact version
GET SHA/size·old version 보존과 작성자 외 리뷰 blocker0을 확인했다. actual
unversioned/suspended의 header missing2 case는 HTTP200/remote bytes 존재에도
같은 IDs의 Unknown이며 재전송·삭제가 없었다. probe fixture 실패·case-level
인수와 전체 실행 상태를 구분하고 literal null의 실제 검증을 주장하지 않는다.
전송 후 Base 중단·EOF close·정리 무한 대기·표준 Host 구성을 red 뒤 좁게
수정했다. 기존 reader/storage3은 그대로고 API 구조762/3411·2계약과 i18n도
통과했다. Source aggregate→publication/apply→전체 read/cleanup·회사 감사와
managed 생성/기존 파일 전환의 후속 순서를 보완했다. Source schema/role나
서비스는 활성화하지 않았고 앱별 세부 작업은 계속 보류한다.

2026-10-07 23:45 UTC — 최신 사용자 지시에 따라 원본 GitHub main으로 현재
재설계 checkpoint를 커밋·push·PR·병합하기 위한 준비를 진행했다. 로컬 dev와
GitHub main의 시작 committed tree는 같지만 이력이 달라, GitHub main을 부모로
한 동일 snapshot 작업 브랜치를 사용해 내부 과거 이력을 PR에 섞지 않는다.
병합 후 이번 PR 브랜치만 원격·로컬에서 정리하고 영구 dev/main을 유지한다.
이전 UI 검사가 자동 CI에서 누락되는 구조 오류를 독립 검토에서 발견해 필수
owner CI·dual build·release selector를 보완했고 실제 owner1207·typechecks·
ownership와 설정55개를 통과했다. 새 생성 계약·SDK/등록 검사와 exact API 타입
비교도 통과했다. 초기 API wrapper의 격리 package manager bootstrap timeout은
별도 실패로 보존한다. task-owned launcher 설정을 바로잡은 최종 공식 API
--check --no-sync도8.03초에 통과했고 선택859 입력은 불변이다. 최종 게시 근거는
PUBLICATION_CHECKPOINT.md가 소유한다.
실제 환경·인증 파일·runtime 로그는 게시하지 않는다. 서비스 배포 없이 병합 뒤
고정 Source aggregate 명령부터 이어가며 앱별 비필수 기능은 계속 보류한다.
