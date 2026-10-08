# Files 파생 색인 효과의 최소 영속 경계

2026-10-07 UTC. [FILES_SOURCE_RESULTS.md](FILES_SOURCE_RESULTS.md)의 F4 필수
하위 구현 계획이다. 사용자가 승인한 로컬 구조 구현 범위이며 서비스 활성화,
실제 AI/provider 호출이나 운영 DB/권한 적용을 추가하지 않는다. 먼저 strict
paired reader의 제한 계정·실제 테이블 조회 인수를 닫고 아래 조립을 진행한다.

## 현재 공백과 선택

기존 generation materializer는 keyword 성공 뒤 vector 실패하거나 마지막
COMMIT 응답을 잃으면 프로세스 밖에서 동일 시도의 정확한 결과를 알 수 없다.
closed enqueue gate에서는 일반 job 자체가 없고 FAILED job은 기존 outstanding
count에서 빠질 수 있다. generation validation_details는 평가/릴리스 증거를
소유하고 단계 전환 시 바뀌므로 개별 외부 시도의 ledger로 재사용하지 않는다.

**Files 전용 Core record 하나**로 원 operation·Source/Core 결과·두 물리
generation을 첫 외부 시도 전에 보존한다. 본문 복제, 일반 이벤트 버스,
새 하네스나 자동 lease/retry 체계를 추가하지 않는다. 기존 F1 reader,
F3 ingress, ordinary worker/job, generation controller의 계약은 유지한다.

## 고정 identity와 상태

호출자는 operation UUID를 시작 전에 보관한다. 고정 header는 실제 Core event
전체 ref, 최신 accepted Source event/revision/digest, 결과 stamp, 두 persisted
generation UUID와 실제 key/physical target/schema version이다. deleted event만
결과 stamp가 없을 수 있다. 원 Core issuer OID/name과 created provenance도
보관한다. 원문, object key/credential, raw error나 provider 응답은 저장하지 않는다.

`(Core event sequence, keyword generation UUID, vector generation UUID)`를 unique로
묶고 header는 불변이다. armed에서는 File와 각 backend generation을 각각
partial unique로 묶어 미해결 E1이 같은 물리 target의 새 E2를 막는다. 후속
head가 생겨도 아직 처리 중일 수 있는 이전 외부 호출을 추월하지 않는다.
상태는 `armed → complete`만 둔다. 첫 provider 생성,
embedding 또는 backend 시도 전에 armed의 COMMIT ACK를 받아야 한다. armed는
이미 보수적인 미해결 상태이며 프로세스 종료·부분 성공·ACK 유실에도 남는다.
같은 identity의 replay/관측은 새 compute/effect permit을 반환하지 않는다.
원래 살아 있는 호출 frame만 acknowledged 새 arm의 once permit을 소비한다.

arm COMMIT ACK가 불명확하면 새 시도를 하지 않는다. 정확한 원 identity만
조회하며 없음도 rollback·새 UUID·재embedding의 근거가 아니다. 별도 실행
단계가 시작한 뒤의 오류/cancellation/cleanup 실패는 같은 armed identity의
unknown이다. known no-effect preflight와 historical status를 구분한다.

## Lifecycle와 잠금

별도 fixed Core-only lifecycle capability를 append migration으로 준비한다.
실제 safe LOGIN/no membership, registered Source OID 또는 name 거부와
READ COMMITTED/nonautocommit을 적용한다. 새로운 explicit effect profile만
선택하며 기존 READ/F1/F3/Source role replay에 GRANT를 추가하지 않는다.

잠금 순서는 genuine Source stream → Files/company active descriptor SHARE →
기존 pair-control advisory의 **공유** 잠금 → 두 실제 generation SHARE(현재
controller와 같은 backend 순서: opensearch, qdrant) → 실제 current Core head
SHARE → effect/job rows다. 서로 다른 File 효과는 pair 공유 잠금에서 병행한다.
head는 관측/동시 쓰기 차단에 SHARE면 충분하며 materializer에 직접
head UPDATE나 receipt/event INSERT를 주지 않는다. private NOLOGIN capability
owner가 필요한 최소 UPDATE column을 row SHARE에만 사용한다. generation은
`baselining` 또는 `replaying`, 실제 UUID/backend/key/physical/schema tuple이어야
하며 descriptor metadata version도 유지한 값과 일치해야 한다.

capability는 실제 Core event sequence에서 File stream/partition을 해결해 같은
정해진 Source advisory key를 먼저 잠그고 고정 lifecycle/head를 잠글 수 있다.
반환은 matched partition UUID뿐이다. caller namespace/resource/function 선택을
허용하지 않는다. 헤더/SQL guard·owner의 정확 column/EXEC ceiling과 최신
schema에서의 retirement 조건을 구현 전 Data와 Root가 고정한다.

UUID 순서만 새로 적용하면 기존 backend 순서의 상태 전환과 충돌할 수 있다.
backend advisory까지 먼저 공유로 잡는 대안도 기존 single-generation의
row→backend gate 순서와 순환한다. 현재 unordered pair 연산은 exclusive
pair gate 아래에 있어 **pair 공유 gate만**으로 차단한다. 이 분석은 정적
schedule이며 실제 deadlock 재현 결과로 표시하지 않는다. Data가 실제 기존
controller 참여자와 확인하고, 새 순서의 loop나 Source row/stream 잠금을
추가하는 controller는 같은 owner 계약을 먼저 갱신해야 한다.

arm 단계와 effect 단계는 각각 fresh owned Session이다. arm의 COMMIT 뒤 effect
단계는 위 잠금을 다시 얻고 strict pair/immutable header를 재검사한다. 잠금
대기 뒤, embedding 뒤/첫 mutation 전, 두 backend ACK 뒤/progress COMMIT 전에도
같은 Source/Core/output과 lifecycle을 확인한다. keyword ACK와 vector 사이에는
COMMIT하지 않는다. Source canonical row lock/쓰기·storage/parser를 하지 않는다.
구형 direct Source 쓰기의 quiescence는 별도 필수 조건으로 유지한다.

## 완료·관측·통합

두 backend의 알려진 ACK와 마지막 fence 이후 complete 및 정확한 기존 job
해결을 같은 Core COMMIT으로 저장한다. generation cursor는 포함한 operation이
durably complete일 때만 전진한다. complete COMMIT unknown도 같은 IDs로만
관측한다. observer는 현재 안전한 Core 권한으로 불변 역사적 identity를
조회하며 오래된 Source가 현재도 ready여야 하는 조건은 붙이지 않는다.

reconciliation/cutover는 해당 generation의 미해결 armed record를 반드시
센다. 일반 job 부재/FAILED, 최신 head의 후속 event나 기존 caught_up flag가
unknown을 숨길 수 없다. backend의 idempotency와 재embedding/수동 복구는 별도
증거가 필요하며 이 첫 경계에는 자동 재시도를 구현하지 않는다.

이를 Source 삭제 뒤에도 강제하도록 새 고정 generation SQL guard는 armed
target의 모든 phase 변경(특히 baselining→replaying), 물리 identity 변경과
watermark 변경을 거부한다. 정확한 no-op만 허용한다. 현재 runner의 empty
inventory 조기 완료도 prepared adapter에서는 실제 관측을 거친다. 기존
observer에 target 인자가 없어 prepared 관측은 모든 Files armed record를
보수적으로 센다. 이전 controller의 Python lifecycle은 복제하지 않는다.

Root가 strict materializer와 기존 runner의 작은 공개 seam을 조립하고 Data가
append schema·고정 SQL/lifecycle·fresh profile을 소유한다. Structure는 작성자
밖에서 해당 경계를 검토한다. 원래 batch/discovery·RAG lifecycle을 복제하지
않고 providers는 preflight 및 acknowledged arm 이후에만 구성한다.

현재 로컬 실행 owner는
[FILE_EFFECT_EXECUTION.md](../apps/api/src/miy_api/domains/retrieval/FILE_EFFECT_EXECUTION.md)다.
세 protected hook으로 기존 batch/cursor 조립을 재사용하며 keyword의
upserted/deleted ACK, RAG callback 정확히 한 번, 실제 chunk 수와 refresh ACK를
확인한 뒤 ledger/jobs를 같은 COMMIT으로 닫는다. 동일 버전 unchanged는 실제
본문/결과 표식 증거가 없어 complete로 인정하지 않는다. 실제 provider 전체
deadline과 Qdrant stale-tail 정리 한도는 추가 필수 구조 gate다.

## 로컬 구현 인수: 준비된 vector 요청의 유한 한도

effect 권한 인수 뒤 별도 `prepared_qdrant.py`로 기존 RAG 공개
호출형과 legacy provider를 유지하며 준비된 vector 요청만 제한했다. 구현 전
[검토안](../.runtime/official-files-source-results/F4_PREPARED_REMOTE_BUDGET_PROPOSAL.md)을
확정했고 Delivery가 provider·focused test·인접 owner 문서를 소유한다.
Structure가 작성자 밖에서 검토한다. Core SQL·역할·operation identity나
provider/worker/service 활성화는 변경하지 않는다.

한 operation-owned REST client에서 최대96요청·raw response 합계64MiB,
개별 response4MiB, page128개·최대64page·총8192 scanned points/delete IDs를
제한한다. 기존 digit-string chunk index 의미는 유지하고 terminal offset을
확인한 완전한 bounded scan 뒤 한 번만 삭제한다. overflow·offset cycle·
불명확한 ACK는 기존 armed operation을 유지하며 cursor를 전진시키지 않는다.
SDK JSON 해석 전 응답 byte 상한·압축 응답 거부와 재시도/redirect/proxy0,
완료된 update ACK를 적용한다. collection은 따로 준비된 대상만 검증하며
자동 생성이나 재인덱싱을 하지 않는다. RAG pre-write callback은 한 번이다.

5초 phase timeout과 공유 monotonic elapsed120초는 다음 요청·응답 처리의
진입 조건이다. 동기 호출 하나의 강제 취소나 전체 wall-clock deadline을
보장한다고 표시하지 않는다. 실제 전체 취소, embedding/gateway/keyword와
factory/cleanup, 출력·요청 allocation 한도는 F5 운영 조립의 필수 gate로
유지한다. pinned SDK의 실제 공개 transport와 합성 응답/clock 및 제한된
소유 loopback TCP를 검증했으며 외부/공유 provider를 호출하지 않았다.

고유 SDK118개(이전115·수정 신규3)와 별도 기존39개의 영향 범위를 인수했고
최신 selected29개·owned4개 불변 및 작성자 외 리뷰 blocker0을 확인했다.
잘못된 chunk payload가 raw 예외로 빠져나오는 실패3개를 재현해 작은 제어
오류 wrapper로 수정했다. 이전115와 최신 affected14의 겹친11개를 중복
합산하지 않는다. 실제 runtime 계약은
[PREPARED_QDRANT.md](../apps/api/src/miy_api/domains/rag/providers/PREPARED_QDRANT.md)가
소유한다. factory·service·provider는 자동 활성화하지 않았다.

## 필요한 검증과 남는 범위

owned PostgreSQL의 genuine Source/F2와 Core/F3 event, synthetic providers로
actual identity/최소 권한, 두 generation/lifecycle non-key UPDATE wait, stale
Source/head/phase/target의 effect0, arm 전후 ACK 유실, keyword ACK 뒤 vector
실패, 마지막 COMMIT 전후 관측, borrowed factory 보존, no-job/FAILED와 unknown
coverage, 이전 migration/function/profile replay 보존을 확인한다. 검사 수는
실행별 범위·초기 실패·해시와 함께 기록한다.

불변 Source object publication, 전체 bootstrap/트리와 matched 서비스/auth/ACL/
AI gateway/audit/worker·Beat 활성화는 다른 필수 단계다. 이 계획을 그 완료로
표시하거나 운영 권한을 미리 적용하지 않는다. 정확 구현·인수 기록은
[VALIDATION.md](VALIDATION.md), 전체 진행은 [STATUS.md](STATUS.md)가 소유한다.
