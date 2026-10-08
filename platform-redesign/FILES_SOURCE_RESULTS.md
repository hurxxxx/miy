# Files Source 결과 경계 구현 계획

2026-10-07 UTC. [공식 API 전환 계획](OFFICIAL_API_CUTOVER.md)의 필수 구조 하위 작업이다. 개별 앱의 업무 기능 개선이나 운영 활성화 계획으로 확대하지 않는다. 현재 코드는 기본 legacy 조립을 유지하며, 새 경계는 명시적인 내부 조립에서 검증한다.

## 변경 목적과 단계

파일의 추출 상태·원문 checksum·text·blocks·metadata는 Files Source가 소유한다. Core 검색 워커는 이미 승인된 Source 결과를 읽어 파생 색인을 만들며, 파일 저장소를 열거나 파싱·OCR·Source 상태 수정을 하지 않는다. 기존 Core의 역방향 쓰기를 제거하는 것이 완료 조건이다.

| 단계 | 구현 범위                                                                                                                   | 현재 상태                |
| ---- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| F1   | 실제 Core event/head와 준비된 Source artifact를 읽는 reader, 명시적 not-ready, Source 쓰기 없는 callback, 최소 DB 조회 권한 | 로컬 내부 경계 인수 완료 |
| F2   | 기존 파일의 고정 Source 요청·claim·input·결과·terminal receipt, local parser, 동일 ID 관측                                  | 로컬 내부 경계 인수 완료 |
| F3   | Files pending/ready/delete의 별도 Core 수락, partition 잠금, stale 검색 후보 차단                                           | 로컬 내부 경계 인수 완료 |
| F4   | Source 파일 트리 잠금, managed/default partition 예약, 불변 입력·업로드 publication, Source bootstrap                       | 구현 중                  |
| F5   | 현재 인증·app/ACL·감사·AI routing과 서비스 권한 조립, 실제 queue/Beat·불확실한 remote 복구                                  | 활성화 전 필수           |

F1 최종 검증과 초기 실패·범위는 [VALIDATION.md](VALIDATION.md)에 기록했다. 현재 runtime 계약은 [Files Core projection owner](../apps/api/src/miy_api/domains/files/CORE_PROJECTION.md)가 소유한다.

단계별 통과는 해당 경계의 근거다. 전체 독립 공식 서비스의 배포·운영 완료로 표시하지 않는다. 앱별 상세 기능 이슈는 [APP_ISSUES.md](APP_ISSUES.md)에 보존한다.

## F1 인수 조건

실제 Core event/head/checksum/partition과 Source의 ready artifact를 검증하고, 전체 serialized artifact·metadata·blocks에 고정 상한을 적용한다. Artifact metadata가 권위 checksum·파일 식별·공개 external metadata를 덮어쓰는 입력은 거부한다. 기존 parser의 정상 결과는 유지한다.

`None`은 실제 없거나 삭제된 Source에만 사용한다. pending·failed·unsupported·invalid·checksum 불일치는 명시적 제어 결과다. 실행 전 preflight의 보류는 provider 생성·파생 삭제·Source 실패·자동 재시도를 막고 attempt를 환원한다. 실행 이후 같은 종류의 오류가 발생하면 effect unknown으로 원 attempt와 job identity를 보존해 명시적 조정을 요구한다.

Core reader role은 선언한 table/column SELECT만 받는다. Source DML·COPY·row lock, credential·provider·AI 권한을 받지 않는다. old ready artifact에는 storage-key provenance가 없으므로 F1 검증을 최신 입력 attestation으로 확대하지 않는다.

알려진 FAILED 상태의 저장을 실제로 관측한 경우에만 기존 Beat claim 대상에서 제외된다. hold COMMIT 응답이 불명확하면 processing이 남을 수 있으며, 같은 ID로 조회하고 worker의 추가 retry를 중단한다. 기존 scheduler의 expired-processing 복구 전체를 차단했다는 의미는 아니다. 운영 effect admission과 Beat 소유권은 F5의 필수 조건이다.

## F2 구현 범위

첫 구현은 이미 존재하고 Source partition에 binding된 파일의 local parser 처리다. 새 public endpoint·전역 Session 설정·자동 bootstrap·task/Beat 등록·provider 호출·운영 role 적용 없이 고정 Source 명령을 구현한다.

- 요청·result·result event의 UUID와 입력·parser policy digest를 처리 시작 전에 유지한다. 같은 ID와 digest는 수렴하고 다른 입력의 같은 ID는 충돌한다.
- Source 파일과 요청을 정해진 순서로 잠그고 actual Source writer·현재 actor·Files app admission·Source resource ACL을 DB에서 다시 확인한다. 전달된 사용자 객체나 LLM 결정이 권한을 부여하지 않는다.
- 배타적인 durable claim token을 Source COMMIT한 뒤에만 입력을 읽는다. lease 만료로 claim을 훔치거나 응답 부재를 새 요청·token·provider 호출의 근거로 사용하지 않는다.
- 첫 local-only profile의 입력 상한은 10MiB다. 기존 bounded selected-object reader의 총10초·각IO2초·retry 없음·redirect 거부·exact size·response 해제를 재사용하고 실제 bytes SHA-256을 결속한다. legacy parser의120MiB 기본 상한은 유지한다. captured storage key가 불변 bytes를 보장한다는 주장은 하지 않는다.
- prepare는 현재 파일에 이미 존재하는 진짜 active/no-checksum pending Source intent의 ID와 digest를 입력에 결속한다. 새 pending event나 네 번째 UUID를 만들지 않는다. 입력 읽기와 결과 적용 전 현재 Source tip을 다시 확인한다.
- Source는 bounded result와 현재 input CAS를 검증한 후 ready/unsupported의 canonical artifact·terminal 결과·실제 Source intent를 같은 transaction에 저장한다. known local failed는 failed/error와 terminal history만 저장하고 삭제나 새 intent를 만들지 않는다. 기존 pending intent는 남는다. Core receipt/head/job은 이 transaction에서 쓰지 않는다.
- 입력 CAS는 결과 적용 전 fingerprint와 비교한다. artifact 적용으로 변경되는 `updated_at`과 accepted 결과의 provenance를 분리한다. terminal apply는 항상 거부하고 별도 observe만 유지한 result ID/digest의 역사적 receipt를 반환한다. 변경된 computed payload를 과거 결과로 받아들이지 않으며 파일·intent를 재작성하지 않고 현재 접근 권한은 다시 확인한다.
- 별도 `result_recorded` 상태나 원문 payload 복제는 만들지 않는다. 적용 전 프로세스가 종료되면 durable claim/input은 남고 명시적 조정 대상이다. receipt의 동일 token 관측은 새로운 compute 권한이 아니며 자동 재파싱·claim 재발급을 하지 않는다.
- local parser는 기존 구현을 사용한다. OCR이 필요한 분기에서 dispatch 전에 명시적으로 보류하며 기존 OCR 예외의 degrade 경로에 삼켜지지 않도록 한다. ready·failed·unsupported를 만들거나 claim을 재발급하지 않는다.
- 새 Source transport는 독립 `source_scope` FK/check와 별도 고정 trigger/profile을 사용한다. 기존 canonical90 guard, 두 company capability body, 이전 migration과 기존 principal exact replay를 보존한다. 새 권한은 명시적인 새 profile 준비에서만 적용한다.

각 명령은 새롭고 변경이 없는 READ COMMITTED outer Source Session에서 시작하며 COMMIT은 caller가 소유한다. 첫 profile은 Engine-backed Session만 허용한다. Connection-backed bind와 외부 join mode는 Source SQL·autobegin 전에 거부해 외부 transaction의 ACK를 Source COMMIT으로 오인하지 않는다. runner는 명시적으로 받은 새 Session factory만 조립한다. 이미 시작한 transaction·pending ORM 변경·nested transaction과 sync runner의 running event loop는 처리 시작 전에 거부한다. 자동 thread 우회나 privileged Session fallback을 추가하지 않는다.

input-bind는 actual Source writer admission과 파일/current-input 잠금을 실제 bounded 저장소 읽기·응답 해제·raw SHA·byte count 결속·COMMIT까지 유지한다. local parser는 DB 잠금 밖에서 실행한다. apply는 fresh Source transaction에서 현재 권한·입력·tip을 다시 검증한다. 따라서 모든 I/O가 잠금 밖이라는 설계가 아니며, 저장소 읽기의 상한이 필수다.

새 Source profile의 Core 조회는 현재 정책에 필요한 users7·roles2·app/group 고정 column과 AuthSession의 id/user_id/expires_at/revoked_at/impersonator_user_id 다섯 column으로 제한한다. 실행 reference는 신뢰하는 서버 조립이 이미 인증한 session을 가리키며 새 인증 방식이나 credential이 아니다. wait/I/O 뒤 fresh clock으로 실제 만료·회수·같은 actor를 확인하고 첫 범위의 impersonation은 거부한다. terminal history는 같은 actor의 새 인증 session으로 조회할 수 있지만 원 execution reference·producer provenance는 바꾸지 않는다. 전체 HTTP 인증·감사 조립은 F5에 남는다.

제한된 non-admin Source 계정에서 공통 app/group 정책의 `EXISTS`가 `SELECT *`로 생성되어 허용하지 않은 User column까지 요구하던 문제를 실제로 재현했다. 권한을 확대하지 않고 기존 조건을 유지한 명시적 ID column 조회로 고쳤다. 기존 SQLite 정책35개와 수정된 실제 제한 Source의 native/managed 권한 경계를 별도 검증했다.

새 고정 read-only admission capability와 최소 NOLOGIN guard owner를 별도로 준비한다. 기존 producer capability·role profile·SQL owner는 바꾸지 않는다. 결과 digest는 고정 PostgreSQL JSONB envelope로 생성·검증하며 Python JSON과 같다고 가정하지 않는다. 첫 atomic apply는 File/outbox의 실제 outer transaction witness를 검증하고, savepoint apply는 Source 쓰기 전에 거부한다. terminal 뒤 같은 transaction에서 canonical artifact나 Source tip을 다시 바꾸는 경우도 COMMIT의 고정 deferred 검증으로 거부한다. 새로운 결과 본문이나 일반 검증 프레임워크는 추가하지 않는다.

최종 SQL 경계 검토에서 raw Source client가 `SET CONSTRAINTS ... IMMEDIATE`로 deferred 검증을 앞당긴 뒤 같은 transaction의 File/tip을 바꾸는 우회를 실제 재현했다. 새 private fixed seal은 같은 top transaction의 terminal 이후 File·같은 stream의 outbox append·SourceMetadata의 이전/새 file binding·corpus binding/scope 변경을 거부한다. AFTER terminal에서 실제 request row도 top-XID여야 하므로 File/event는 outer인데 terminal만 savepoint인 우회도 거부한다. 기존 최소 owner read closure와 Source EXEC ceiling을 유지하고 새 상태/본문 복제는 없다. 수정된41개 실제 검사와 mandatory270·독립 검토까지 마쳐 이 비활성 로컬 F2 경계를 인수했다. 정상 runner의 앞선74개와 각 실행의 중복·시점은 [VALIDATION.md](VALIDATION.md)가 구분한다.

ready/unsupported intent append의 retained event-ID 잠금 대기 뒤에도 현재 actor/app/session/Source ACL을 다시 확인한다. 대기 중 인증 만료·회수는 File/intent/terminal을 함께 롤백하며 새 result ID·자동 재실행을 만들지 않는다.

한 번의 durable 새 claim ACK만 원래 runner의 local compute를 허가한다. 같은 token의 receipt를 새 프로세스에서 관측하는 것은 재계산 권한이 아니다. ACK가 불확실하면 유지한 ID로만 관측하며 관측되지 않은 결과를 새 claim이나 compute의 근거로 사용하지 않는다.

Data 에이전트는 migration·model·SQL guard·별도 profile·실제 제한 PostgreSQL을, Delivery 에이전트는 Source 명령·DTO·local parser runner를 소유한다. 합의한 전이는 `prepared → claimed → input_bound → ready | unsupported | failed`이며 `ocr_required`는 input_bound의 hold reason이다. 독립 `file_extraction_requests`는 본문을 복제하지 않는다. Structure 에이전트는 shared artifact 계약 구현 뒤 Data/Delivery의 독립 실패 경계를 검토하고, 자신의 artifact 구현은 Root가 검토한다. Root는 최소 현재 정책 query와 통합을 소유한다.

실제 제한 PostgreSQL에서 concurrent prepare/claim, 잘못된 token/input/result, writer 교체·권한 회수·삭제, bounds, artifact+terminal+intent 원자 rollback, terminal replay, 실제 COMMIT 전후 unknown의 동일 ID 관측을 확인한다. 정상 local parser와 OCR zero-dispatch도 확인한다. F1 권한 전수를 변경 없이 반복하지 않고 영향 경계를 검증한다.

## F3 구현 범위

F2 최종 수정·동결·영향 검사와 독립 검토 뒤 아래 경계를 구현하고 로컬 비활성 범위로 인수했다. Data는 별도 Core capability/profile/migration을, Delivery는 고정 Files ingress/consumer를, Structure는 Source current-content helper·hydration/RAG seam을, Root는 공통 retrieval/keyword와 Files search/chat 연결·통합을 소유한다. 작성자와 다른 검토자가 각 구현을 검토했다. 실제 제한 PostgreSQL과 native 영향 검사189개 및 기존 권한·migration·Recording·fixture 영향167개를 통과했으며 중복은 합산하지 않는다. 정확 실행·초기 실패·입력 시점은 [VALIDATION.md](VALIDATION.md)가 소유한다. Source extraction/parser와 기존 세 앱의 경계는 이 F3 인수 시점에 보존했다.

- Core는 이미 COMMIT된 진짜 Files Source event만 수락한다. pending/no-checksum은 실제 head와 receipt를 전진시키되 keyword/vector job을 만들지 않는다. ready/checksum과 genuine delete에서만 기존 파생 작업을 만든다. 이전 revision은 superseded receipt로 수렴하고 같은 event ID/digest 관측은 Source mutation을 반복하지 않는다.
- 기존 Files/RAG 운영 gate가 닫혀 있어도 검증된 control head/receipt는 전진하고 파생 작업은 만들지 않는다. 수락 receipt는 index readiness가 아니다. gate 활성화 후 backfill은 F4/F5의 명시적 준비이며 새 Source event나 자동 replay를 만들지 않는다. known failed/OCR hold가 남긴 진짜 pending/no-checksum tip도 no-job fence로 수락한다. 삭제나 ready 결과를 합성하지 않는다.
- 기존 Docs/PMS/회의의 고정 capability와 이전27 migration을 바꾸지 않는다. Files의 별도 고정 partition SHARE capability와 명시적인 새 최소 Core profile을 준비한다. 현재 active `files` namespace·company candidate partition과 Source binding을 확인하고 COMMIT까지 잠금을 유지한다. private native 파일의 resource ACL은 company candidate partition과 독립이다. 기존 principal을 자동 확대하지 않는다.
- Files 전용 수락·한 번의 consumer·동일 event 관측 진입점을 둔다. 기존 세 앱의 Source resource set·discovery를 확대하지 않으며 새 최소 Files Core role이 다른 앱을 자동 발견하지 않는다. caller resource/namespace 선택·task/loop/자동 등록은 추가하지 않는다.
- Source의 현재 ready/SHA/partition/추출 시각과 index candidate의 원래 content envelope를 비교하는 Files 소유의 작은 읽기 helper를 사용한다. 같은 원문 SHA라도 재추출 결과가 달라질 수 있으므로 기존 `extracted_at`을 UTC microseconds로 정규화한 결과 표식이 필수다. pending·failed·unsupported·deleted·체크섬 누락/불일치·partition 이동·결과 표식 누락/변경은 후보에서 제외한다. 현재 Source 값으로 후보 envelope를 덮어쓰지 않으며 이 검사는 ACL을 부여하지 않는다. ORM cache 대신 실제 현재 여섯 column 조회를 사용하고 Source/Core DML·object read·parser·provider는 수행하지 않는다.
- 공통 keyword·직접 RAG·통합 retrieval·Files search/chat 경로 모두 같은 content admission을 적용한다. 실제 keyword의 row-level partition과 vector의 projection metadata SHA가 응답 변환에서 사라지지 않도록 유지한다. RAG는 rerank 전에 후보를 좁히고 최종 ACL/grounding 전에 다시 확인한다. Files search/chat도 Source 재조회·ACL 이후 snippet/has_more/evidence 구성 전에 확인한다.
- 먼저 오래된 내용이 통과하는 실제 실패를 합성 소유 데이터로 재현한다. 수정 뒤 정상 ready 후보·다른 resource 보존, 현재 변경/삭제/pending·stale ORM·checksum/partition drift, rerank 이전 stale text 제외·이후 변경, page refill와 chat evidence, 제한 Core의 Source SELECT-only·partition 잠금·pending/ready/delete·동일 ID COMMIT unknown을 검증한다. 앱별 업무 기능 인수나 실제 provider/queue/Beat 활성화를 추가하지 않는다.

이 검사는 현재 canonical Source와 candidate envelope의 일치다. backend의 임의 본문에 대한 암호학적 검증이나 storage key의 불변 bytes 증명으로 확대하지 않는다. 기존 색인의 결과 표식 누락은 현재 Source 값을 대입해 보완하지 않는다. F4/F5의 명시적 재색인·coverage·전환 gate가 필요하며 자동 bootstrap이나 서비스를 활성화하지 않는다. 불변 입력·업로드/교체 publication은 F4의 필수 조건이다. 새로운 일반 검색 프레임워크나 자동 복구 하네스를 만들지 않는다.

## F4 구현 순서와 필수 구조 조건

F3 인수 입력을 보존한 뒤 다음 범위를 분리하여 진행한다. 전체 파일 저장소의 완료나 운영 전환을 작은 내부 경계의 통과로 대신하지 않는다.

1. Source runner가 이미 사용 중인 Engine-backed Session을 거절하면서도 닫아 호출자의 작업을 잃게 하는 결함을 실제 트랜잭션으로 재현·수정한다. fresh Session의 소유권을 확인한 뒤에만 runner가 정리한다. 외부 transaction join을 허용하지 않는다.
2. 이미 binding된 파일1~100개의 명시적 workset을 Source-only로 관측한다. 현재 입력 fingerprint와 기존 F2 요청을 비교하고 같은 actor/original execution에만 유지한 identity를 반환한다. probe 자체는 request 생성·compute·storage/Core 접근을 하지 않으며 global complete·high-ID cursor·SKIP LOCKED를 사용하지 않는다. 불확실한 prepare는 기존 세 UUID로만 관측한다.
3. 별도 Files Source UUID-only descriptor SHARE capability와 명시적인 fresh opt-in profile을 append migration으로 준비한다. Core의 default/managed setup은 유지한 UUID/type/version으로 별도 실행·관측한다. 기존 Source/Core profile이나 고정 세 앱 capability를 확대하지 않는다.
4. Core materializer가 같은 원문 SHA의 새 추출 결과를 과거 event의 결과로 사용하는 공백을 막는다. 최신 genuine Source tip과 수락한 Core event/current head의 일치를 canonical read 뒤와 effect 전에 확인하는 최소 경계를 먼저 검토한다. serving 결과 표식만으로 event provenance를 증명하지 않는다.
5. 불변 입력은 실제 backend에서 증명할 수 있는 write-once 또는 모든 read/cleanup의 pinned object version 중 하나로 구현한다. Source publication admission·동일 ID unknown 관측과 aggregate/tree serialization을 갖춘 뒤 upload/replace를 조립한다. 임의 UUID key나 unconditional PUT을 불변성으로 간주하지 않는다.

현재 하위 경계: runner의 caller transaction 보존은 실제51개와 독립
검토로 인수했다. retained UUID Core setup은 실제30개와 독립 검토로,
별도 Source descriptor capability는47개 고유 집중 검사·173개 schema/role
영향과 독립 검토로 인수했다. 명시적 Source workset은 모든 corpus를 정렬해
파일보다 먼저 잠그도록 보완하고 실제34개를 통과했다. 기존 단일 파일
명령/runner 영향51개와 작성자 외 검토도 마쳐 유한 관측 경계를 인수했다.
전체 Source discovery/완료 coverage는 이 유한 workset의 결과와 구분한다.

최신 Source tip/accepted receipt/current Core event와 하나의 bounded snapshot을
검사하는 별도 strict reader와 새 최소 읽기 profile을 인수했다. 최종 동작55개와
실제 제한 PostgreSQL의 genuine Source→Core 상관관계34개 고유 검증을
분리하고, temp-table shadow의 actual 실패 뒤 현재 affected12개의 통과를
확인했다. Root가 작성자 밖에서 helper/profile을 검토했다. 기존 F1/F3 profile을 확대하지 않는다. 실제 effect
조립 전에는 partition lifecycle SHARE와 첫 외부 시도 전에 남는 durable
unknown identity를 확정해야 한다. 기존 generation validation_details나
job 성공 상태를 임의 effect ledger로 재사용하지 않는다. 다음 고정 schema와
lifecycle/unknown 조립은 [FILES_EFFECT_BOUNDARY.md](FILES_EFFECT_BOUNDARY.md)가
소유한다.

고정 Core armed/complete record와 새 effect profile/SQL guard를 구현 중이다.
Root의 inactive 실행 조립은 기존 batch/cursor/RAG API를 재사용하고, 실제
Source/Core/operation/job SQLite 행과 synthetic PG authority/header seam의
96개 동작 검사를 통과했다. 별도 기존 generation/helper 영향110개도 통과했으며
Source snapshot의 누락된 extracted_at 전달을 구조 통합 오류로 수정했다.
이 수를 실제 PostgreSQL 권한/동시성 인수나 provider 실행 한도로 주장하지 않는다.
기본 Engine 외 mapper/table의 빌린 연결·다른 Engine을 거부하는 Source/Core
ownership 보완과 실제 append30 인수는 진행 중이다. 실행 계약은
[FILE_EFFECT_EXECUTION.md](../apps/api/src/miy_api/domains/retrieval/FILE_EFFECT_EXECUTION.md)가
소유하며 실제 provider 전체 budget, 불변 Source publication과 서비스 cutover는
필수 잔여다.

첫 실제 effect 권한59개와 Source ownership/명령72개는131 PASS로 확인했다.
세대 전환·동일 target의 다음 event 차단·역사적 관측과 기존 schema 영향은
후속 검증한다. 독립 리뷰에서 세션 정리의 취소가 known COMMIT ACK 또는
원래 unknown receipt를 가리는 경계 오류를 재현해 rollback/close 격리만
좁게 보완했다. 최초96/131은 그 시점의 근거로 보존하고 최신 controlled
capture로 현재 composition을 다시 검증한다.

현재 고정 Core effect 로컬 비활성 인수는 actual Data83·Source72·mandatory175와
최신 controlled102를 구분해 완료했고 독립 리뷰 blocker0을 확인했다. 원본46
계약과 SQL4개 본문을 보존했다. 영속 caller checkpoint 구현이나 실제 provider
전체 deadline을 인수한 것은 아니다. Source TEMP 인증 shadow와 취소 결과
보존은 최신 실제81개·현재243개 입력과 독립 리뷰로 인수했다. 준비된 vector
한도 adapter도 고유118개·기존 경로39개와 독립 리뷰로 인수했다. 후자의
최신 affected14는 이전11개와 신규3개이며 이전115를 합산 재실행한 결과가
아니다. 유한 동기 요청 한도와 강제 전체 취소는 구분한다.
불변 publication·tree/bootstrap·full Source auth/audit와 F5 서비스 전환은
필수 구조 후속으로 유지한다.

불변 입력은 **명시적 object version 고정**으로 선택했다. 기존 bounded
transport의 내부 `read_pinned_object`를 추가해29개 TCP/presigner 검사와
실제 소유 MinIO의 overwrite/delete-marker/exact-delete 경계를 통과했다.
Source의 unique storage_key→file/version/SHA/size publication binding과 모든
prepared read/cleanup 연결은 후속 필수다. 기존14-field F2 입력/고정 SQL을
변경하거나 저장소 실패 뒤 latest로 대체하지 않는다. 첫 I/O 전에 원
publication/operation IDs를 보관하고, ACK 불명확은 같은 ID 관측만 허용한다.
미관측 또는 여러 version을 새 PUT·새 key·삭제의 근거로 사용하지 않는다.
[publication 업로드 구현 계획](FILES_PUBLICATION_STORAGE.md)의 작은 비활성
adapter는 현재68개·actual0/small/250MiB version/SHA와 missing-Version2 case,
작성자 외 리뷰로 인수했다. 런타임은
[PUBLICATION_STORAGE.md](../apps/api/src/miy_api/domains/files/PUBLICATION_STORAGE.md)가
소유한다. 다음은 고정 Source aggregate 명령과 최소 publication record·원자
apply이며, transport 인수를 전체 Source 업로드 이전 완료로 표시하지 않는다.

구현별 소유 경로·입력·검증은 별도 기록하며 shared DB/role/service·worker/Beat·배포는 변경하지 않는다. 새 일반 하네스나 자동 복구 프레임워크 대신 기존 Codex 및 고정 계약의 작은 진입점을 사용한다.

## 다음 Source 구조 구현 순서

첫 고정 명령의 작은 범위는 [FILES_SOURCE_AGGREGATE.md](FILES_SOURCE_AGGREGATE.md)의
기존 private native root File 한 개 soft-delete·동일 ID 역사적 관측이다.
작성자41·실제 제한 Source 고유30·기존 영향81개와 독립 리뷰를 통해 로컬
비활성 인수를 마쳤다. 공유 Session의 선택적 TextClause Engine 분리는 SQL
전에 거부하도록 필수 보완했다. 현재 runtime은
[SOURCE_MUTATIONS.md](../apps/api/src/miy_api/domains/files/SOURCE_MUTATIONS.md)가
소유한다. 이것은 아래1의 전체 폴더/tree·회사 정책 또는2의 publication hold와
seal까지 완료한 것이 아니다. 실행·입력·한계는 [VALIDATION.md](VALIDATION.md)에
기록하며 이 첫 명령은 Source 후속 PR70으로 게시했다.
실제 게시 추적은 [PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md)가 소유한다.

PR70 이후 후속 명령은 private native root Folder와 명시한 평면 File
1~16개를 128KiB canonical spec으로 한 transaction에서 변경하는 범위다.
정렬 File/stream/UUID 잠금·genuine File DELETE outbox·현재 회수·같은 ID의
역사적 관측을 pure21/실제 Source26과 독립 리뷰로 로컬 비활성 인수했다.
기존 Source4/authority48은 그대로이며 이 새 코드는 로컬 미커밋이다.
FK로 보호되는 것은 transaction 안의 membership뿐이다. COMMIT 뒤 삭제된
부모에 들어오는 기존 upload/move/child-folder 참가자의 live-parent 확인,
모든 hold 참가자와 SQL terminal seal은 필수 잔여다. 전체 tree/회사/managed
정책과 아래 publication을 이 인수로 완료하지 않는다.

1. 고정 Source aggregate 명령을 먼저 조립한다. fresh Engine-backed Source
   stage와 canonical namespace, 실제 actor/session/app·각 작업의 현재 정책,
   정렬된 Source corpus→standalone tree gate→partition reader→부모/File 잠금을
   사용한다. descriptor 생성이나 Core 테이블 직접 쓰기로 되돌아가지 않는다.
   private 폴더·leaf 변경의 작은 첫 범위와 전체 tree의 명시적 작업/깊이/시간
   한도 및 회사 공개 감사가 필요한 범위를 구분한다.
2. bounded PUT 인수 뒤 Source publication header·최소 active File hold와
   prepare→attempted→published 전이를 구현한다. 원래 ID·현재 Source producer,
   같은 파일의 이전 unknown, immutable store/key/version/SHA/size를 결속한다.
   canonical File·metadata/grants·진짜 Source event와 terminal을 한 COMMIT으로
   저장하고 상위 transaction seal과 current 정책 재검사를 검증한다.
3. managed 최초 생성·revival·기존 native 파일 전환은 각각 현재 정책과 별도
   before-state를 유지한다. 최초 managed 생성은 다른 File ID로 같은 외부/
   source identity를 선점하는 경쟁도 막아야 한다. absent-native create나
   기존 managed replacement만으로 전체 업로드 이전을 완료 처리하지 않는다.
4. prepared read/preview/archive/parser가 published binding의 exact version을
   사용하고 cleanup/보존도 version별로 동작하도록 연결한다. 기존 회사 공개
   확인·감사는 고정 Core-owned seam으로 원자성을 유지하며 Source에 generic
   Core audit INSERT를 주지 않는다. 이 뒤 matched schema/principal/artifact와
   구형 writer drain·F5 실제 서비스 조립을 검증한다.

Source의 부모7·corpus7·grant4 필드와 same-File active hold는 현재 코드에 따른
최소 설계 후보이며 구현·정확 SQL/권한 검증 전에 schema가 승인됐다고 표시하지
않는다. [Data 인터페이스 검토](../.runtime/official-files-source-results/F4_PUBLICATION_DATA_INTERFACE_REVIEW.md)와
[active target 검토](../.runtime/official-files-source-results/F4_PUBLICATION_TARGET_HOLD_REVIEW.md)가
근거를 소유한다. 중요한 회사 감사·managed identity 경쟁·기존 파일 전환은
앱별 보류 이슈로 넘기지 않는다.

업로드·교체의 pending Source event는 Core head를 앞으로 이동시켜 이전 쓰기를 fence해야 한다. Core는 checksum이 없는 active pending에서 vector/keyword job을 만들지 않고, 실제 ready 결과 event에서만 작업을 만든다. pending을 삭제로 바꾸거나 event를 생략하지 않는다. 현재 검색 후보도 Source ready/checksum을 재확인해 과거 색인 bytes를 새 Source metadata로 노출하지 않아야 한다.

F2의 기존 파일 처리는 새 업로드의 불변 object/version·불확실한 저장소 publication, Files partition 예약·고아 retirement, Source 트리 잠금이나 전체 bootstrap 완료를 뜻하지 않는다. 기존 SKIP LOCKED/high-file-ID scan의 누락 문제는 durable anti-terminal discovery로 해결해야 하며 Source coverage와 Core watermark를 구분한다.

향후 remote OCR은 같은 operation ID의 권위 receipt/관측 계약이 먼저 필요하다. 현재 HTTP POST와 audit ID만으로 재실행 안전성을 주장하지 않는다. broker·Beat·old consumer drain·matched schema/principal/artifact 및 전체 인증/감사 조립도 활성화 전 필수다.

현재 인수 기록은 [STATUS.md](STATUS.md), 정확 검증은 [VALIDATION.md](VALIDATION.md)가 소유한다. 구현 이후 실제 runtime 계약은 해당 Source/Projection owner 문서에서 관리한다.
