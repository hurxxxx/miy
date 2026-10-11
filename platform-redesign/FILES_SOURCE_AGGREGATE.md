# 고정 Files Source aggregate 명령

2026-10-08 UTC. GitHub [PR69](https://github.com/hurxxxx/miy/pull/69) 병합 후
[Source 구조 순서](FILES_SOURCE_RESULTS.md#다음-source-구조-구현-순서)의 첫 slice다.
**기존 private native root File 한 개의 로컬 비활성 명령·관측을 인수했다.**
전체 tree/publication나 서비스 전환의 완료로 표시하지 않는다. 현재 런타임
계약은 [SOURCE_MUTATIONS.md](../apps/api/src/miy_api/domains/files/SOURCE_MUTATIONS.md)가
소유한다.

## 이번 구현

기존 개인 native root File 한 개를 soft-delete하는 비활성 Source Stage부터
구현했다. 현재 실행·사용자·앱 권한과 소유자가 유효하고, private·corpus 없음·
folder 없음·external SourceMetadata 및 FileAccessGrant 없음·기존 default partition binding·진짜
active Source tip이 있는 경우만 지원한다. 없거나 다른 binding은 거부하며
Core partition을 할당하거나 Core table을 직접 조회·수정하지 않는다.

작은 고정 request에는 File ID, event UUID, 실제 actor/execution, 기대 partition과
canonical 상태/tip 지문을 보관한다. 서버에서 검증한 기대 상태만 변경한다.
File의 삭제·canonical artifact 정리와 genuine DELETE intent를 같은 Source
transaction에 기록한다. intent는 고정 command/spec provenance와 기존 tip을
연결하며 Core receipt/head/job·object 삭제·provider 호출은 하지 않는다.

Stage는 fresh 단일 Engine Session, canonical namespace, 현재 Source admission,
현재 actor/app, standalone Source gate, 기존 제한 partition reader, File lock,
resource stream 순서로 진행한다. 잠금 뒤 실제 상태와 권한을 다시 확인하고,
event UUID 충돌/대기 뒤에도 현재 실행·앱·writer 권한을 재확인한다. caller가
COMMIT을 소유하며 provisional receipt를 commit ACK로 오인하지 않는다.

불확실한 COMMIT 뒤 같은 event/digest의 별도 현재 권한 관측만 허용한다.
관측은 exact immutable DELETE event witness를 읽으며 변경 명령을 재실행하지
않는다. 후속 genuine tip 뒤 현재 File도 삭제 상태라는 보증으로 표시하지 않는다.
이번 caller-owned Stage는 임의 caller가 Stage 뒤 COMMIT 전에 추가 변경하는
경우까지 SQL terminal seal로 금지하지 않는다. trusted caller의 Stage/COMMIT
계약이며 publication/apply의 top-XID seal은 별도 필수 잔여다. 기존
`service.delete_file`와 `rag_sync`는 Core partition 조회와 같은 transaction의
Core 수락을 포함하므로 이 prepared Stage의 구현으로 호출하지 않는다.
인증을 복제하지 않고 기존 Source의 fresh-session/admission/current-actor seam을
좁게 공유한다. 기존 HTTP/default runtime은 이 Stage로 자동 전환하지 않는다.
실제 두 Engine의 TextClause 분리 재현에서 ORM TEMP 인증·File flush와 다른
transaction의 admission/timeout/locks가 갈라지는 문제를 확인했다. owned waiter
cancel 후 rollback/자원 정리를 마쳤으며 receipt나 영구 삭제 성공은 없었다.
공유 fresh validator를 표준 public Session.get_bind 구현으로 제한해 Source SQL
전에 거부한다. 정상 inherited subclass와 same-Engine explicit binds는 유지한다.
수정 후 독립 재현은 SQL·transaction 전에 고정 binding refusal을 확인했고,
현재 실제 제한 계정의 routing 검사와 영향 Source81개도 통과했다. 진단 중
발생한 일반 refusal을 수정 후의 SQL 전 거부 근거로 사용하지 않는다.

## 로컬 인수와 다음 구조 작업

작성자41개, 실제 제한 Source29의 고유30개, 공유 Source 영향81개를 각각
검증했고 작성자와 분리한 최종 리뷰의 차단 결함은0이다. 신규 실제 검사는
최초25 PASS/5 fixture FAIL 뒤 실패한5개만 `.reason` assertion으로 수정해
통과했다. 제품·SQL·권한은 그 fixture 수정으로 바꾸지 않았다. 원본 권한
계약48개와 검사 중 입력의 불변성, 소유 임시 자원의 정리를 확인했다.
[VALIDATION.md](VALIDATION.md)가 정확 실행·입력·한계를 소유한다.

이후에는 정렬 잠금에 참여하는 폴더·전체 tree의 유한 작업 범위와
publication header·same-target active hold·canonical/event/terminal 원자
apply를 조립한다. 현재 leaf에도 publication hold가 도입되면 동일한 hold
검사를 연결해야 한다. durable caller, 회사 감사·managed logical identity,
exact-version read/cleanup과 F5 조립도 필수로 남긴다. 기존 HTTP/default
호출 전환이나 서비스 배포는 이번 인수에 포함하지 않는다.

## 완료 조건과 담당

- Delivery: 고정 DTO·mutation/observer와 필요한 작은 Source 실행 seam을 소유.
- Data: 실제 제한 Source29 PostgreSQL의 원자 commit/rollback, stale 상태,
  동시 변경·잠금 후 권한 회수·TEMP shadow·현재 schema/profile 보존을 검증.
- Structure: 작성자와 분리해서 fresh/routing·현재 권한·same-ID 관측·Core/storage
  무효과·legacy 잠금 호환을 리뷰하고 필요한 red만 재현.
- Root: 통합·owner 문서·검증/진행 상태를 갱신. schema·migration·grant 추가나
  shared 환경/서비스 변경이 필요하면 먼저 실제 계약과 최소 설계를 확정.

새 Source advisory gate만으로 미전환 legacy 전체 tree serialization을 주장하지
않는다. 이 leaf 범위는 legacy tree의 exclusive partition lock과 기존 제한
reader SHARE의 호환을 실제 검증하며, 모든 tree participant의 adoption/drain과
bounded descendant 처리는 후속 필수다. company publication/audit, managed
identity 경쟁, upload/version binding, 물리 version cleanup도 필수 구조로 남긴다.
publication active hold가 추가되면 이 leaf를 포함한 모든 Source mutation도
같은 File/논리 identity의 미확정 publication을 우회하지 못하게 조립한다.
현재 schema에는 해당 hold가 없으므로 그 연동이 구현됐다고 표시하지 않는다.

이 slice의 구현·검사는 사용자 승인에 따른 별도 후속 PR로 게시하며 추가
서비스 배포는 하지 않는다. 게시 추적은
[PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md)가 소유한다.
앱별 비필수 기능 개선은 [APP_ISSUES.md](APP_ISSUES.md)의 별도 지시 조건을 유지한다.
