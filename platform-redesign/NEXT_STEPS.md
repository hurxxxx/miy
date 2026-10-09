# 후속 구조작업

먼저 C1 비활성 checked-save·공통 native GC drain·실제 수신 주소 접근 보완을 최신 dev 기반에서 통합 인수하고 정상 feature 게시/필수 리뷰/병합한다. 그 수정본의 새 exact-source full artifact를 인수한 뒤에만 운영 전달한다. 기존257/job425의 GC/SQL 예산 실패와 최초 SDK Python/초기화 실패를 보존한다. C1 통합은 migration34/pending24이므로 새 정확 tree의 private restore·구형 운영 이미지 호환·metadata 계약을 다시 인수한다. SDK18개 후보의 Python 및 제품 Task는 별도 진행하며 C2/C3 durable payload owner/handoff는 구조 필수로 남긴다.

2026-10-09 UTC. 사용자 요청에 따라 Source 명령 후속 게시 이후의 필수 작업을
식별했고, PR70 병합 후 사용자 지시로 다음 구현을 재개했다. 현재는 아래
세 경계의 구현·검증·독립 리뷰와 PR71 게시·병합을 마쳤다. 승인된 개발 플랫폼과
별도 Workbench 반영을 확인했다. 내부 리뷰 재인증은 완료했고 리뷰에서 발견한
개인 앱 HTTPS 기본 포트 오류를 수정·검증했다. 후속 실제 리뷰의 색인 전환과
Files hook scope 경계를 보완했으며 운영 DB 복사본 호환 검증을 통과했다.
개발 최신 소스 반영을 확인했고 후속 필수 리뷰의 개인 앱 실행 자원 한도를
수정·검증했다. CLI 출력·HTTP 전체 시간·Docker 로그를 제한하고, 불완전한 release
관측이 사용 중인 앱의 정리 근거가 되지 않도록 했다. 다음 실제 리뷰에서 발견한
기존 runtime 복원·worker 종료 유예를 보완하고 개발에 반영했다. 이후 리뷰에서
발견한 기존 테스트의 projection 진입점·Files FK fixture를 현재 계약에 맞춘 뒤,
`up`의 정상 재기동·자동 복원 조건을 분리했다. 이후 실제 필수 리뷰에서 발견한
Bento의 같은 로그인 화면 이동 시 대기 중 저장 유실을 수정했다. 로그인·credential
변경의 오래된 쓰기 차단은 유지한다. 새 필수 리뷰와 전체 릴리스 검증을 마치고
운영에 반영한다. 새로운 official operational reader/grant나 서비스
cutover를 활성화한 것은 아니다. 게시 추적은
[PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md), 작업 상태는
[WORK_ITEMS.md](WORK_ITEMS.md)가 소유한다. 이 문서는 우선순위·의존성과
다음 착수 단위를 소유하며 별도 작업 대장을 만들지 않는다.

현재 dev는 `02418067`, main/prod는 `9e9280df`다. GitHub94/GitLab101의 최초258/job426 Docs 종료 P1과 후속259/job427 draining 마이그레이션 P1을 보존하고 모두 수정했다. 실제 종료24·기존 협업106과 현재 C1 60개를 통과했다. 수정 head의 필수 review→양쪽 정상 병합→소유 브랜치 정리→새 current full→pending24 private 리허설/이전 이미지 호환→MR81/guarded 운영 순서로 진행한다. 별도 SDK22/owned11은 로컬74·영향427/기존skip5와 독립 리뷰까지 완료했으며 실제 controller/Task 검증이 필요하다. 비활성 C2-1 provenance53은 로컬 인수했고 C2-2 PostgreSQL durable intake/discovery 계약과 C3 복구·서비스 활성화는 필수 잔여다.

동시에 **C1 비활성 checked save**를 현재 인수된 ACL base에서 구현한다. Core만 complete original cohort/payload를 봉인하며, Source는 봉인된 attempt UUID와 digest만 받아 SELECT/DML0·private save EXEC1로 같은 caller transaction에서 모든 ACL/최종 expiry·content incarnation/revision CAS·durable receipt를 처리한다. 기존 Source/auth/actor ceilings·33 migrations·default native/factory를 보존한다. 정확 schema/grant manifest를 코드 작성 전에 동결하고 native PG의 contributor 회수·wait·CAS/ABA·ACK loss/lock-and-cancel·역할 거부를 검증한다. C2 실제 apply/relay의 완전한 provenance와 C3 config/role/drain/recovery는 이어서 진행한다. Workbench SDK toolchain/cache 준비는 별도 경로로 병행하며 사용자 app manifest/scripts를 shadow하지 않는다.

아래 날짜별 이력은 해당 시점의 기록이며 현재 위치를 대신하지 않는다.

## 후속 전체 CI223의 구조 fixture 보완

PR77/MR84는 새 source `1d8cf66e`의 리뷰222/390 후 정상 병합했고 작업 브랜치를 정리했다. 현재 dev는 `c401dd1a`, main/prod는 `9e9280df`다. 후속223/391은 API fast5,556 PASS/1 FAIL/3 SKIP, slow16·migration37·external15 통과 후 실패했다. 권한 회수와 descriptor 대기 테스트의 기대 사유 한 건이며 원 CI의 SQLSTATE는 미관측이다. 실제 단독1 PASS·통제된 느린 연결55P03을 구분하고, 연결 준비를 worker 이전으로 옮기는 fixture 두 파일만 보완한다. 정확 reason·실권한·rollback·제품5초/15초 제한을 유지한다. 실제 focused8조합과 기존 공용 helper2개는10 PASS/23.72초, 동일5.2초 지연 재검증은1 PASS/13.10초이며 독립 코드 리뷰 blocker0이다. 지연 case는 같은8개 중 하나이므로 고유 성공 수로 합산하지 않는다. 새 source 게시·필수 리뷰·전체 CI 뒤 승인된 운영 배포를 이어간다. 실패한 동일 source의 CI를 재시도하지 않는다.

## 현재 전달과 병렬 구조 착수

PR78/MR85의 `d43a46aa`는 리뷰224/392 뒤 양쪽 같은 tree로 병합했고 현재 dev는 `ad42d0bc`다. main/prod는 `9e9280df`를 유지한다. 전체225/393은 저장 공간 검사 실패로 제품 테스트0이며 기준을 낮추지 않았다. 보존 가능한 소유 산출물과 정확한 미사용 cache 정리 뒤에도 실제 여유가 부족하므로 스토리지 확보가 현재 운영 전달의 필수 선행조건이다. 확보 후 정상 full CI→정확 source/target/tree 인수→MR81 정상 병합→fresh backup→guarded prepare/deploy→실제 반영 검사를 진행한다.

별도 로컬 착수는 아래1번의 server-owned 제한 auth factory를 실제 네 HTTP 조회 경로에 조립하는 최소 inactive 변경이다. 새44개·기존 composition10개와 API architecture/i18n·생성 계약이 통과했으며, 최종 독립 리뷰·게시·전체 릴리스 후 나머지 공통 권한 소비 연결을 진행한다. 정확0.160.1의 두 native offline 정책도 선행검사만 통과했고 실제 executor/WS/자원 한도·turn 인수는 남아 있다. 기존14표/87열 reader·Source ACL·기본 legacy/official 경로·비활성 ASGI를 유지하며 scope/credential 선검사, private503과 취소 시 worker admission/cleanup을 인수한다. 새 operational role/grant·서비스 활성화는 후속이다. 아래2번은 정확한0.160.1 공개 패키지/기존 protocol 검사까지 준비했고 offline native helper의 격리 선행조건을 확인한다. 실제 WS·cgroup 한도·turn/resume/history를 이 선행조건으로 대체하지 않는다.

## 현재 판단

공식 UI 12개와 공통 Chatbot의 소스·빌드 소유 이전, 개인 앱의 등록·SDK·
실행/배포 시범 경계, 단일 사용자 Workbench의 SQLite·native 상태·템플릿과
여러 Source/Core 경계는 검증했다. 그러나 네 영역의 독립 실행·릴리스와
자연어 개발→배포→복구 전체 연결은 완료하지 않았다. 파일 기능 하나의
검사를 늘리는 것으로 전체 구조를 인수하지 않는다.

공식 앱은 먼저 하나의 독립 묶음 서비스·릴리스로 완성한다. 앱마다 별도
microservice를 일괄 만드는 것은 선행 조건이 아니다. 공유 PostgreSQL에서
실제 최소 역할·단일 writer·transaction 소유를 분리하는 첫 이행을 유지한다.
개인 앱 데이터 profile과 Workbench의 단일 소유자 SQLite도 현재 계약을
유지하며, 다중 사용자 Workbench는 계속 후속 범위다.

## 우선순위와 완료 조건

P0는 다른 경로의 실행·활성화를 막는 경계, P1은 연결해야 할 필수 구현,
P2는 선행 경계 인수 후의 서비스 전환·최종 통합이다. 서로 독립인 작업은
동시에 진행할 수 있다. 번호는 착수 단위이며 새 상태 ID가 아니다.

| 착수 단위와 기존 작업                                                                 | 우선순위              | 의존성                                                | 구체적 완료 조건                                                                                                                                                                                                                                                                                                                                         |
| ------------------------------------------------------------------------------------- | --------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. 공통 플랫폼 권한과 공식 Source 서비스 경계 — OFF-002B                              | P0                    | 기존 identity bridge·Source guard·제한 역할           | 실제 HTTP/WS 경로에서 현재 사용자·실행·앱·리소스 ACL을 확인하고 suite의 인증/Core 직접 쓰기를 제거한다. launcher 밖 DM·notification·calendar·widget·announcement, content/search·AI approval/audit 소비 경계를 포함한다. 제한 역할의 허용/거부·대기 중 회수와 대표 경로를 인수한다.                                                                      |
| 2. Workbench native 격리 실행 — WB-001/002, ENV-001                                   | P0                    | 검토된 실행 격리 환경·전용 checkout/endpoint          | 현재 namespace/mount 차단을 지원되는 환경에서 해결하고 pinned native client의 readOnly/workspaceWrite·실제 cwd·현재 인증·자원/정리를 검증한다. 호스트·인증 자료·Docker socket·플랫폼 DB 비노출, endpoint 교체/단절 뒤 host fallback·중복 turn 없이 상태 관측을 확인한다.                                                                                 |
| 3. Files aggregate·publication — OFF-002B의 F4                                        | P1                    | 인수된 private root leaf·Source29·bounded PUT/read    | private 폴더/유한 tree부터 정렬 잠금·현재 정책을 확정한다. 원래 ID의 publication header·미확정 same-target hold·prepare/attempt/publish와 File/metadata/grants/진짜 event/terminal의 한 COMMIT을 조립한다. 현재 leaf를 포함한 모든 참가자가 hold를 지켜야 한다. 회사 감사·managed 생성/revival/논리 identity 경쟁·기존 native 전환을 각 범위로 인수한다. |
| 4. Files 버전 입력·효과·복구 연결 — OFF-002B의 F4/F5                                  | P1                    | 3의 published binding·기존 Source request/Core effect | read/preview/archive/parser/cleanup을 정확한 published version에 연결한다. 전체 discovery의 누락 방지, 원 spec/IDs의 효과 전 영속 보관, process loss/unknown의 동일 ID 관측, 최신 Source/Core 일치와 전체 provider deadline/취소를 인수한다. 최신 version 대체·자동 재PUT·가짜 실행 재발급은 사용하지 않는다.                                            |
| 5. 개인 앱의 전체 native 개발·배포 흐름 — CAT-002, APP-001/002, REL-001, WB-003B/004B | P1                    | 2·현재 manifest/SDK·builder/executor·위임             | 실제 선택한 Workbench Task에서 UI 시험 앱 생성/수정→등록→미리보기→검증 빌드→불변 이미지 배포→포털/독립 주소 사용→관측·복구를 연결한다. 이어 DB 시험 앱의 이미지 복구 후 데이터 유지를 확인한다. 앱별 포털 import/router 수정 없이 작동하고 응답 유실·재시작 뒤 기존 요청 조회와 중복 효과0을 확인한다.                                                   |
| 6. 공식 묶음 runtime·queue·릴리스 전환 — OFF-002, MIG-001                             | P2, 활성화 전 필수    | 1·3·4와 Source-only 소비 경로                         | 동일 commit/schema/principal/artifact로 최신 wheel/image를 조립한다. 실제 broker·queue·Beat·lease·routing generation, 구형 writer/consumer drain·stranded attempt와 단일 writer 전환을 검증한다. 승인된 별도 환경에서 대표 업무·권한 회수·unknown 관측·rollback 후 호환 종료 범위를 닫는다.                                                              |
| 7. 최소 자연어 맥락·템플릿 평가 — POL-001~003, WB-003A/B, VAL-001                     | P1부터 각 흐름에 적용 | 사용 가능한 2·5와 1·6의 대표 경로                     | 선택 앱/저장소/환경·핵심 계약을 native Task에 연결하고 생성/수정/테스트/배포/복구/재개·애매한 대상·오래된 지침을 결과로 판정한다. 권한·대상·중복 효과 오류0, success/failed/unknown/stale 구분과 template snapshot 보존을 확인한다. 기존 candidate 검사 관측14/18의 원인을 분리하기 전 품질 향상을 주장하지 않는다.                                      |
| 8. 네 영역 최종 구조 인수 — CAT-002, ENV-002, VAL-001, CLOSE-001                      | P2                    | 위 대표 흐름별 인수                                   | 하나의 정의 원본에서 포털/Workbench 목록·설치·소스의 차이와 미확인을 설명한다. 실제 개발 서버의 preview4+bounded build1, 초과/실패 시 다른 앱 응답·정리와 각 영역의 독립 변경·릴리스·복구를 확인한다. 개인 앱 수정·배포가 플랫폼/공식 전체 재빌드·재시작을 요구하지 않아야 한다.                                                                         |

## 다음 착수 묶음

이번에 인수한 구현 묶음은 다음과 같이 제한한다. 이 묶음의 통과를 위 전체 단위의
완료로 확대하지 않는다.

- **공식 인증:** 기존 앱 세션·승인 binding·현재 입장 판단을 재사용하는
  인증 전용 최소 열 reader를 준비했다. 독립된 fresh read-only Session과 실제
  제한 PostgreSQL 계정으로 검증했다. 다음은 제한 auth factory의 HTTP/WS 적용과
  나머지 공통 권한 소비 연결이며 기본 HTTP 인증과 서비스는 아직 전환하지 않았다.
- **Files:** private native root 폴더와 평면 자식 File 1~16개의 변경을
  128KiB 이내 spec, 정렬 잠금, genuine event와 caller COMMIT으로 구현·검증했다.
  기존 ingress의 삭제된 부모 확인과 publication hold·seal은 계속 필수 잔여다.
- **Workbench:** 선택한 개인 앱의 Task 시작 전에 현재 소스·설정과 pinned
  native endpoint의 연결·버전을 읽기 전용으로 확인하도록 구현·검증했다.
  지연 응답·소스 변경·로그아웃 뒤 Task 생성 차단을 확인했다. 이 확인은 sandbox·계정·실제 turn 검증을
  대신하지 않으며 native 격리 환경과 전체 개발·배포 흐름은 계속 남는다.

구체적 계획·진행·실행 결과는 WORK_ITEMS.md·PROGRESS.md·VALIDATION.md와
각 runtime owner에 기록한다. 이후 사용자 지시로 게시·개발/운영 배포를
승인받았으며 [PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md)에서 별도로
진행한다. 이 배포는 비활성 official cutover나 남은 전체 구조의 완료가 아니다.

멀티에이전트는 다음 세 경로를 분리해서 담당할 수 있다. 공유 권한·잠금·
publication 계약은 한 소유자가 정리하고 Root가 통합한다.

1. **공식 Source:** 인수한 유한 leaf/flat 폴더를 바탕으로 publication
   header/hold/원자 apply와 모든 변경 ingress의 parent-live·hold 준수를
   조립한다. 전체 tree 한도와 회사/managed 정책을 별도로 인수하며 기존
   upload route를 즉시 전환하지 않는다.
2. **Workbench·개인 앱:** 검토된 격리 환경의 실제 native 사전 검사와 UI
   시험 앱 한 개의 등록→native 수정→미리보기 전체 흐름부터 연결한다.
   호스트 정책·서비스 변경이 필요하면 구체적인 대상·결과를 준비하고
   제품 구현과 운영 변경 승인을 구분한다. 같은 경로를 DB 시험 앱에 적용한다.
3. **공통 플랫폼·공식 서비스:** 준비된 auth-only reader를 실제 제한
   인증 factory의 HTTP/WS에 적용하고 source-access/content·AI/audit·
   비-launcher 서비스의 현재 권한 경계를 연결한다.
   이 경계가 준비된 뒤 matched artifact와 실제 worker/Beat 전환을 진행한다.

각 흐름에 자연어 대표 사례를 붙여 비개발자가 대략적인 지시만 해도 현재
대상과 규칙을 지키는지 확인한다. 새 planner/retry engine이나 전체 skill
주입 대신 기존 Codex·현재 owner 계약·작은 고정 진입점과 템플릿을 재사용한다.

## 범위와 근거

앱별 비필수 상세 기능은 [APP_ISSUES.md](APP_ISSUES.md)의 별도 지시 조건을
유지한다. 회사 감사·현재 ACL·managed identity·unknown 외부 효과·원자
publication·단일 queue 소유는 필수 구조이므로 앱 이슈로 넘기지 않는다.
다중 사용자·공유 Workbench 저장소·공식 앱별 일괄 서비스 분리와 아직
요구되지 않은 개인 앱의 임의 worker/object/schema 확장은 선행 조건이 아니다.

GitHub source 게시·병합은 개발/운영 설치·DB/grant·서비스 활성화나 별도
Workbench 배포 완료를 뜻하지 않는다. 실행이나 환경 적용 단계는 현재
승인 범위와 실제 계약을 다시 대조한다. 이전 통과 수를 합산해 전체 구조
인수로 표시하지 않고 바뀐 계약과 중요한 실패 경계만 검증한다.

현재 원본은 [목표 계획](PLAN.md), [Files 단계](FILES_SOURCE_RESULTS.md),
[공식 cutover](OFFICIAL_API_CUTOVER.md),
[Workbench runtime](../docs/apps/codex-console/README.md),
[독립 앱 runtime](../apps/api/src/miy_api/domains/independent_apps/README.md),
[공식 API runtime](../apps/official-suite/api/README.md),
[worker runtime](../apps/worker/README.md)이다.
읽기 전용 검토 근거는 ignored
`.runtime/source-aggregate-publication/FOLLOW_UP_REVIEW.md`에 보관했다.

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

## 2026-10-08 — Native SDK 고정 toolchain 후속 계획

개인 앱 SDK를 실제 격리 환경에서 빌드·검사하는 필수 구조 후속이다. 현재 코어에 설치된 의존성 링크를 실행 환경에 노출하지 않고, 코어가 검증·고정한 템플릿별 Node/Python 의존성과 실행 파일 묶음을 비활성 SDK backend에 공급한다. 기존 Codex lifecycle·RPC·표준 ingress와 권한·자원 계약을 유지한다. 제품 변경 후보는 descriptor·lock·검증기·backend·검사·owner를 포함한8경로이며, 구현·설치·실행 검증 전 계획이다.

Node/pnpm 공개 버전 metadata 확인과 실제 archive hash·Python/ELF/ABI·전체 파일 검증을 구분한다. 아직 descriptor_complete=false이며 테스트/설치0이다. 고정 artifact 확인 뒤 실제 kernel/mount/resource enforcement, 같은 원 Task의 자연어 SDK build/test·플랫폼 등록·개발/운영 반영과 별도 Workbench 배포를 각각 인수한다. 현재 저장 공간 조건을 충족하지 못해 영구 캐시나 서비스를 설치하지 않았다. 상세 계획과 공개 입력은 `.runtime/structural-next-delivery/next-native-sdk-toolchain.{md,json}`에 보존한다.

## 2026-10-09 — Whiteboard 저장의 필수 안전 경계 후속 계획

첫 단계는 기존 factory에서 admission 때 collab row ID와 room key를 캡처하고 조건부 CAS로 REST 방 회전·동일 key의 row 삭제/재생성 ABA를 모두 거절한다. 이전 runtime은 새 상태를 덮어쓰거나 row를 생성/수리/입양하지 않는다. SQL worker 정리가 끝날 때까지 flush_lock을 유지하고, 감소하는 SQL 시간 제한·expected_runtime cleanup·확정 ACK와 불명확 COMMIT 결과를 구분한다. 결과가 불명확하면 debounce/cleanup이 자동 재저장하지 않는다. 제품 변경 후보7경로와 필요한 DTO assertion 경계는 actual red·PG/Yjs/CAS/취소 검증 뒤 인수한다.

Source writer principal·Core current authority의 COMMIT fence·정확 최소 Whiteboard grant profile은 별도 다음 단계다. 기존88표/Files profile을 Whiteboard 최소 profile로 사용하지 않고 same-room content revision CAS·durable ACK history도 미완료로 구분한다. 조사51개·보호42개와 최소 Source 후보는 `.runtime/structural-next-delivery/next-source-writer-cas-plan.{md,json}`에 기록했다. 현재 계획만이며 제품 수정·테스트/운영 활성화0이다. 비필수 앱 기능·다중 사용자 범위는 확대하지 않는다.

## 2026-10-09 02:50 — Whiteboard 저장 안전성 우선 구현

Docs Source room 읽기는 필수 리뷰와 PR86/MR93 병합·소유 feature 정리를 마쳤다. 다음은 현재 Whiteboard 저장의 필수 데이터 유실 경계다. 실제 PostgreSQL/native Yjs로 오래된 room-key 회전·같은 key의 collab row 재생성·반복 취소·교체 runtime 정리를 먼저 재현한다. Admission에서 board ID·collab row ID·room key를 캡처하고 조건부 저장한다. 누락 캡처는 Session 생성 전에 거절하며 오래된 runtime은 새 row를 생성·복구·채택하지 않는다. 저장 중 취소에서도 직렬화 lock은 SQL worker 정리·join까지 유지한다. COMMIT 응답 유실은 unknown으로 보존해 자동 재실행하지 않는다.

이 단계는 기존 저장 안전성 수정이다. 별도의 최소 Source writer 역할과 COMMIT까지의 현재 Core 권한 fence·동일 room 내용 수렴·durable recovery는 후속 독립 단계다. Source 읽기 역할을 쓰기 권한으로 확대하지 않는다. 원본 앱 상세 기능과 다중 사용자는 보류한다. Native SDK/toolchain의 실제 파일·ELF 검증과 영구 설치, 개인 앱 전체 흐름·별도 Workbench 배포도 남는다.

## 2026-10-09 03:53 — Whiteboard 저장 안전성 로컬 검증

기존 room이 입장 때 캡처한 board ID·collab 행 ID·room key만 조건부 UPDATE한다. Board SHARE와 정확한 행 조건을 COMMIT까지 유지하고, 취소된 호출도 SQL worker/cleanup 종료까지 flush lock을 보유한다. ACK는 후속 정리 실패로 unknown으로 바꾸지 않으며 unknown은 원 identity/bytes를 보존하고 자동 재저장하지 않는다. 이전 WS finalizer·observer·대기 publish가 교체 runtime을 정리하거나 변경할 수 없고, pending/unknown 동일 identity 재입장은 거절한다.

신규 pure16 PASS/5.15s·실제 PostgreSQL/Yjs32 PASS/60.64s =48개다. 기존 prepared/auth/composition466 PASS/329.54s·원 Whiteboard 구조6 PASS/16.96s·원 Docs default8 PASS/26.33s =고유 영향480개다. 원 red4의 첫 green과 이전 반복 검사는 더하지 않는다. API architecture/i18n·생성 계약은 통과했다. 최종 문서/범위 freeze와 독립 수락·필수 원격 리뷰/병합은 이후 별도로 기록한다.

다음 최소 착수는 별도 Source writer principal/least-privilege 프로필과 actor authority의 COMMIT 경계 설계/red 인수다. Native SDK immutable toolchain·설치/enforcement와 실제 개인 앱 전체 흐름도 남아 있다. 전체 구조 완료로 확대하지 않는다.

## 2026-10-09 04:24 — 필수 리뷰의 공유 저장 상한 수정

Source6da7c943의 PR87/MR94 필수 pipeline242/job410은 FAILED/115.932917초였다. P2는 flush마다 새 limiter1을 생성해 room 간 전체 SQL worker 상한이 없다는 회귀다. 이 실패를 성공이나 면제로 바꾸지 않고 실제 거절 기록과 기존48·480 성공 receipt를 별도로 보존했다.

Hub별 고정4개의 shared permit을 private shielded child 시작 전에 얻고 SQL worker·Session cleanup·결과 전달·TaskGroup join까지 보유한다. Permit 대기 취소는 Session0이며 child 시작 뒤 취소는 기존 owned join을 따른다. Permit을 얻은 뒤 terminal/disposing/current runtime/captured identity/YDoc/unknown을 재검사한다. Child 내부 limiter1은 shared token을 재획득하지 않으며 기존 adapter를 유지한다. Process 전체 상한이나 새 설정·운영 적용을 주장하지 않는다.

최소 Source writer/profile·현재 Core 사용자 COMMIT fence·같은 room의 cross-hub content CAS/convergence·영속 unknown/Docs 저장·operational 역할과 서비스 전환은 필수 잔여다. Next service-admission profile은 이번 단계에서 사용하지 않는19표98열 ACL 호환 grant를 미리 주지 않고 board/collab의 고정 최소열과 EXEC부터 독립 인수하도록 계획을 좁힌다. 현재 ACL reader는 보호하며 실제 ACL writer 연결은 후속이다. main/prod9e9280df·full241/409 storage 실패/tests0·새 운영/Workbench 배포0를 유지한다. 앱별 상세 기능과 다중 사용자는 보류한다.

## 2026-10-09 05:08 — 최종 저장 대기 중 상태 보존

최종 disposal의 전체 lifecycle을 private shielded child가 소유하고 부모는 SQL·Session cleanup·native 해제·retiring 정리까지 join한다. 기존 flush_lock 아래 prior worker를 먼저 join하고 pending bytes를 admission 전에 보존한다. 최종 flush 전체의 outer cleanup timeout을 제거했으며 SQL deadline은 worker Session이 시작한 뒤, 개별 비SQL cleanup timeout은 각 단계에 적용한다. 일반 permit 대기 취소의 Session0·hub 상한4·기존 captured identity·postwait 검사·ACK/unknown 처리는 그대로다. 첫 수정의 native36 PASS/1FAIL97.94초와 동일 shutdown 진단1FAIL36.94초도 보존한다. 이 실패는 최상위 shutdown gather가 먼저 끝난 다른 취소를 전달해 final ACK보다 caller를 앞서 반환하는 경계였다. shutdown 전체와 마지막 cleanup task 대기도 private shielded owner와 parent join으로 보완했다. 이후 native36 PASS/2FAIL124.57초의 capacity 잠금 관측 실패도 보존한다. 스레드 open 순서를 room 순서로 가정한 fixture를 실제 captured collab ID의 SQL PID로 대응시켰으며 동시성·실제 잠금·상한·취소·교체 기대값을 유지했다. 최초 두 실패의 정확한 인과관계는 입증하지 않았고 unchanged 진단3PASS23.67초도 해결 증명으로 세지 않는다. Hard shutdown이나 network/driver의 강제 종료 보장은 하지 않는다.

기존 PR87/MR94의 정상 후속 commit/push와 새 필수 리뷰 뒤 병합·소유 브랜치 정리를 진행한다. 다음 Source service profile은 불필요한 ACL 선행 grants 없이 최소2표에서 시작한다.

현재 dev499aff33·main/prod9e9280df, full241/409 storage 실패/tests0, 새 운영 및 별도 Workbench 배포0다. 다음은 비활성2표 최소 Source service writer/profile이며 Core 사용자 권한 COMMIT fence·Source factory 연결·cross-hub content CAS·영속 unknown 복구·공식 서비스 cutover는 남아 있다. Native SDK/toolchain 실제 pin 검증·설치 및 개인 앱 자연어 전체 흐름도 필수 잔여다. 앱별 비필수 기능·다중 사용자는 보류한다.

## 2026-10-09 05:22 — 저장 안전성 전달과 최소 Source writer 착수

Whiteboard 저장 안전성 최종 Source `ba9fee1e`/tree `fef48496`는 필수244/job412 SUCCESS/94.736405초 뒤 GitHub [PR87](https://github.com/hurxxxx/miy/pull/87)→`2c1cb019`와 내부 [MR94](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/94)→dev `aafbccb2`로 정상 병합했다. 양쪽 tree는 같고 소유 feature 브랜치의 양쪽 원격·로컬 정리를 완료했다. Dev는 persistent integration branch로 유지하며 main/prod는 `9e9280df`다.

새 전체245/job413은30.366867초에 저장 공간 선행조건에서 실패했다. 제품 테스트0이며 필수 최소15GiB/15% 기준을 유지한다. 이 결과를 source 리뷰 성공으로 대체하지 않고 새 운영·별도 Workbench 배포0를 유지한다.

다음 구현은 `aafbccb2` 기준 별도 worktree에서 비활성 Whiteboard Source service writer/profile이다. 실제 migration head `file_effect_20261007`, 기존 migration30개 및 보호85개를 다시 동결했다. 새 migration·service admission·role checker와 새 테스트·owner2, Root 추적6을 분담한다. 두 Source 표의 SELECT8열·UPDATE4열과 제한된 capability 하나부터 인수하며 공급된 LOGIN/NOLOGIN 역할·원래 principal identity·정확한 권한·기존 mapping replay·실제 session_user와 SQL 락을 검증한다. 현재는 구현 착수이며 새 테스트를 실행하거나 인수한 것으로 표시하지 않는다.

Migration은 정상 legacy/hardened 환경에서 비활성 capability만 설치한다. 준비·admission에는 hardened guard가 필요하다. Session/factory/COMMIT/cleanup 수명은 caller가 소유하며 Core 사용자 ACL COMMIT fence·hub Source factory 연결·운영 역할/grant/config/service 전환은 이번 범위가 아니다. Current actor fence, cross-hub content CAS, 영속 unknown 복구와 공식 서비스 cutover는 여전히 필수 잔여다. 기존 skills/harness는 절차로 사용하지 않고 현재 코드·owner·중요 계약만 사용한다. 앱별 비필수 기능과 다중 사용자는 보류한다.

## 2026-10-09 05:59 — 비활성 최소 Source writer 로컬 검증

새 `whiteboard_source_service_admission_v1`은 두 Source 표의 SELECT8열·UPDATE4열과 실제 session_user에서 출발하는 private capability만 준비한다. 공급된 fresh LOGIN/NOLOGIN과 명시적인 원래 owner OIDs·role OID/name·generation/artifact를 고정하며 기존 broad/부분/회수된 역할을 확장하거나 복구하지 않는다. 정확한 complete replay는 grant/ALTER/audit0이다. 정상 legacy migration은 비활성 capability만 설치하며 실제 준비/admission은 기존 hardened guard를 요구한다. Caller-owned transaction의 SHARE 잠금은 실제 COMMIT/rollback까지 유지하고 caller의 감소하는 SQL deadline·cleanup 소유를 보존한다.

현재 dev `aafbccb2`·main/prod `9e9280df`, 최신 full245/413 저장 공간 선행조건 실패/제품 테스트0와 새 운영/별도 Workbench 배포0를 유지한다. 이 단계는 Source factory·저장 연결·사용자의 현재 Core/Source ACL COMMIT fence·cross-hub content CAS·영속 unknown 복구·Docs 저장·공식 서비스 cutover를 완료하지 않는다. 다음 actor fence는 현재 사용자 구현 승인 안에서 별도 범위와 보호표를 확정한다. Same-DB SQL 잠금을 실제 separate DB 보장으로 표시하지 않으며, queued Yjs의 credential attribution/expiry와 모든 owner/direct/group/PMS/meeting edit closure가 활성화 전 필수다. Native SDK/toolchain 실제 pin 검증/설치·개인 앱 전체 자연어 흐름도 남아 있다. 앱별 비필수 기능·다중 사용자는 보류한다.

## 2026-10-09 06:22 — 최소 Source writer 전달과 actor-owner 경계 착수

현재 dev는 `746258cd`, main/prod는 `9e9280df`다. 비활성 최소 Whiteboard Source writer/profile은 필수246/job414 성공 뒤 [PR88](https://github.com/hurxxxx/miy/pull/88)·[MR95](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/95)로 정상 병합하고 소유 feature 브랜치를 양쪽 원격·로컬에서 정리했다. 최신 full247/job415는 저장 공간 선행조건에서22.79551초에 실패해 제품 테스트0이며 새 운영·별도 Workbench 배포는 없다.

다음은 별도 worktree의 비활성 Core actor-owner capability다. 실제 원 delegated execution을 별도 auth-only Session에서 캡처하고, 공급된 fresh LOGIN에는 private EXEC1만 허용해 사업 데이터 SELECT·DML0을 유지한다. 같은 PostgreSQL database의 caller-owned transaction에서 원래 서비스와 현재 사용자·세션·설치·앱 승인·live board owner의 positive witness를 잠근다. Source v1의 SELECT8/UPDATE4 및 auth14표/87열은 확장하지 않는다. 기존31 migration·보호95개를 동결하고 신규 revision `wb_actor_owner_20261009` 하나와 inventory head 한 항목만 추가한다. 구현·테스트 작성에 착수했으며 새 검사 실행·최종 인수·게시·서비스 활성화는 아직 하지 않았다.

이번 owner-only 단계는 전체 Whiteboard ACL·실제 Source 쓰기 연결·운영 전환을 완료하지 않는다. 공유/HR/PMS/meeting 편집 권한, contributor의 원 credential 보존, 같은 connection/transaction의 Source CAS와 actor 검사 조립, cross-hub content CAS·영속 unknown 복구·Docs 저장/media/RAG가 필수 잔여다. 별도 LOGIN 연결 두 개는 하나의 transaction으로 합칠 수 없으므로 후속 최소 combined profile 또는 검토된 capability가 필요하다. 같은 database의 역할·프로세스 분리이며 물리적 별도 DB를 인수하지 않는다. 대기 후 실제 시각의 만료 판정은 decision 시점 보장이고 physical COMMIT-time 만료 보장은 아니다. 사용자 update의 User→AuthSession과 autoflush=False인 reset/delete의 AuthSession→User 역순 잠금 충돌은 bounded private refusal·caller rollback으로 검증하고 보편적 잠금 순서로 주장하지 않는다. Native immutable cache/설치·SDK 전체 자연어 흐름과 별도 Workbench 전달도 남아 있다. 비필수 앱 기능·다중 사용자는 보류한다.

## 2026-10-09 08:38 — actor-owner 구현 검증과 Docker 저장소 이전

Docker 초기 복사 후 현재 실행29개와 개발·CI 서비스를 정상 중지하고 최종 metadata-preserving 동기화·전체 체크섬 비교를 수행한다. `/var/lib/docker` 경로를 유지한 채 fstab bind source와 systemd mount dependency만 루트 저장소로 바꾼다. Driver와 containerd root는 유지한다. 전체 목록·기존 실행 목록과 실제 건강 상태를 확인한 후 CI runner를 복원하고, 검증된 이전 원본만 정리한다. 새 저장소에서 쓰기가 시작된 뒤 오래된 원본으로 직접 롤백하지 않는다.

최종 formatter 입력과 구현 테스트138 native/7 pure를 동결하고 기존 영향167·API 계약을 다시 실행한다. 이전167 결과 자체는 PASS지만 실행 당시 보조 fixture 입력이 모두 동결되지 않아 새 테스트 해시 차이를 예외로 허용하지 않는다. 최종 소유 문서·현재16경로 manifest·보호95/기존31 migration 검증·독립 리뷰 뒤 정상 commit/push와 필수 리뷰, PR/MR 병합·소유 브랜치 정리로 진행한다. MR81 full release와 fresh backup·guarded 운영 반영은 별도 실제 gate다.

## 2026-10-09 09:26 — Docker 이전 완료와 actor-owner 최종 로컬 검증

이전 완료 증거와 최종145+167/계약 근거를 동결한16경로에 결속하고 Markdown·보호95/이전31 migration·독립 최종 리뷰를 마친다. 정상 commit/push 뒤 필수 exact-source codex_review가 성공해야 GitHub PR·GitLab dev MR을 병합하고 소유 feature를 양쪽 원격/로컬에서 정리한다. Persistent dev/main과 upstream 기본 push 차단을 유지한다.

Docker executor의 validation workspace와 Docker data가 새 root filesystem에서 지속15GiB/15% 조건을 충족하는지 실제 최신 MR81 full CI로 확인한다. Home 가용은12.85GiB이므로 home 경로를 사용하는 별도 검사에는 성공을 가정하지 않는다. 최신 full source/target/tree 성공·fresh PostgreSQL18 backup·guarded 운영 반영과 separate Workbench 전달은 별도 gate다. 전체 edit ACL/direct/group/HR/PMS/meeting, 원 contributor credential과 같은 Source transaction의 CAS/actor 조립, content convergence/영속 unknown·Docs 저장 및 native SDK 전체 자연어 흐름을 이어간다. 앱별 비필수 기능과 다중 사용자는 보류한다.

## 2026-10-09 09:46 — 정상 CI의 Source revision 호환 수정

정상 CI 호환의 ACT-CI-01을 먼저 해결했다. 로컬 ignored Source prior-head adapter에 의존한 인수는 철회하고, 기존 Source 테스트의 정확히5개 revision case에 커밋되는 fixture를 추가했다. 원본79 전체 및 role31·authority52·migration5=167 PASS다. 기존 test body/assertion과 이전31 migration은 유지한다.

최종17파일 native138 및 문서 검사·새 독립 인수를 마친 뒤 정상 commit/push, GitHub feature PR와 내부 feature→dev MR의 필수 리뷰·병합·소유 브랜치 정리를 진행한다. 새 dev source의 full release CI에서 이전된 Docker filesystem의15GiB/15% 기준과 전체 테스트를 확인한다. 성공 전 운영 main 배포를 진행하지 않으며 별도 Workbench release/service도 따로 확인한다. Source+actor 동일 transaction 조립·전체 ACL 등 구조상 필수 잔여는 계속 남는다.

## 2026-10-09 09:50 — actor-owner와 정상 CI 호환 최종 로컬 인수 준비

최종17파일 범위에서 신규 actual PG18 native138 PASS/321.13초·pure7 PASS/3.30초 =145개다. 정상 원본 Source 모듈79 PASS/82.18초·원 role31 PASS/24.19초·authority52 PASS/83.77초·migration5 PASS/6.35초 =고유 기존 영향167개다. 진단/반복은 더하지 않는다. ACT-CI-01의 실제5 FAIL/11.19초와 동일5 PASS/11.17초는 보존하며 현재 영향 검증은 ignored Source prior adapter에 의존하지 않는다. 기존45개 함수 본문·signature·assertion, 보호94개·기존31 migration은 동일하다.

Python6·API architecture/i18n·schema/OpenAPI/contract sources를 통과했다. 최종 문서 검사·동결 후 새 독립 인수와 정상 게시/필수 원격 리뷰를 진행한다. 현재 dev746258cd·main/prod9e9280df 및 최신 full247/415 storage 실패/tests0를 유지하며 새로운 commit/push/PR/MR/merge는 아직 없다. Docker 이전/원본 정리·서비스 복구는 완료했고 제품/별도 Workbench 버전 배포는 없다. 전체 ACL·같은 Source connection/transaction 조립·실제 공식 서비스 cutover·Native 전체 자연어 앱 흐름 등 구조상 필수 잔여는 남아 있다.

## 2026-10-09 10:13 — owner 경계 전달 완료와 전체 편집 ACL 착수

1. 비활성 전체 edit ACL capability를 독립 인수한다. 기존 owner/direct/local·HR group/PMS space·nonarchived task list의 member/admin/owner와 meeting organizer/attendee의 실제 편집 규칙을 따라 current positive witness를 잠근다. Company/admin의 read 권한·unknown target·normal tokenNone link 공유는 write를 허용하지 않는다. Python과 SQL의 strip/lower 차이를 결정적으로 검증한다.
2. 별도 checked captured-CAS 저장 capability를 검토한다. 실제 한 Connection/transaction에서 actor 검사와 board/collab/id/key 조건부 쓰기를 결합하며, LOGIN의 직접 사업 DML0을 우선 유지한다. 다른 Session/factory 호출 두 개를 하나의 COMMIT으로 간주하지 않는다.
3. 대기/relay 변경의 원 execution 귀속과 durable content revision/attempt/unknown 복구를 연결한다. 마지막 editor나 relay의 user ID는 credential이 아니며 모든 미확정 contributor의 원 자격 또는 변경별 확정 경계가 필요하다.
4. 전체 write/relay 경로·최소 role·immutable config/factory epoch·drain/rollback을 인수한 뒤 같은 DB의 제한된 운영 pilot을 진행한다. 물리적 별도 DB는 Core authority→Source COMMIT의 별도 계약이 필요하다.

현재 구현은1번만으로, fresh LOGIN private EXEC1·사업 SELECT/DML0과 후보 owner24표/100 SELECT열/24 잠금열이다. 이전 owner15/74·Source8/4·auth14/87은 확장하지 않는다. Session/SQL deadline/COMMIT/cleanup은 caller 소유이고 실제 Source/Yjs 저장·서비스 활성화는 이 범위에 포함하지 않는다. 현재 full249의 source `8bf0bbee`를 고정하고 성공 후 guarded 운영/별도 Workbench 전달을 별도로 수행한다.

## 2026-10-09 10:48 — 다음 실행 순서

먼저 실제 full249에서 실패한 기존 파일 migration의 revision별 fixture를 정상 CI 수집 경로에 반영하고 영향 모듈 전체를 검증한다. 필수 review 후 dev 통합·새 full release를 실행한다. 성공한 최신 source/target/tree를 확인한 뒤에만 정상 MR81 병합, fresh backup, guarded 운영 prepare/deploy/smoke를 수행한다. 전체 edit ACL 후속 구현은 별도 격리 검증을 유지하며 릴리스 source가 바뀌면 기존 성공 근거를 재사용하지 않는다. 별도 Workbench 배포와 실제 자연어 앱 전체 흐름 검증은 이후 필수 단계다.

## 2026-10-09 10:54 — 검증 이후 구조 작업 순서

전체 ACL의 신규132·기존312 PASS를 최종 문서와 독립 인수에 반영한다. ACT-CI-02 파일 migration fixture 수정은 별도 정상 CI review 후 dev에 먼저 통합한다. ACL 전달 시 새 base의 문서·계약 충돌을 검토하고 실제 tested source/tree를 다시 고정한다. 최신 통합 source의 full release 성공 후에만 운영 병합/backup/guarded deployment를 진행한다. 이어 같은 실제 Source transaction의 checked CAS 저장, 모든 원 contributor 검증과 영속 복구를 구현한다. 별도 Workbench 배포·native 자연어 전체 앱 흐름은 여전히 구조상 필수다.

## 2026-10-09 11:05 — ACT-CI-02 로컬 영향 검증 완료

ACT-CI-02 영향 모듈270 PASS를 최종 문서/독립 인수에 반영하고 정상 필수 review를 거쳐 dev에 먼저 통합한다. 이후 이미 로컬444 PASS인 전체 edit ACL을 새 base에 통합하면서 runtime/fixture 영향과 문서 충돌을 확인한다. 최종 dev source의 새 full 성공 후에만 운영 MR81/backup/guarded 배포를 진행한다. 실제 Source 저장과 별도 Workbench/native 전체 흐름은 그다음 필수 단계다.

## 2026-10-09 11:23 — 정상 fixture 전달과 ACL 통합 준비

파일 revision 수정의 정상 전달은 완료했고 ACL의 최종 통합/필수 review를 진행한다. 최신 source/tree의 full 성공 후 MR81 병합·fresh backup·정확한23 migration/세 비공개 capability 상태를 검사하는 guarded prepare/deploy/smoke를 수행한다. 현재 검증 helper의 과거file_effect 기대값은 배포 전에 최신 candidate에 맞춰 갱신한다.

다음 구현 C1: Core-authoritative immutable save_attempts/contributors, collab incarnation/content revision 및 기존 writer도 덮어쓰기를 검출하는 owned revision trigger, 새 Source EXEC1/DML0·trusted Core seal/resolve EXEC2/DML0 profile을 추가한다. Source는 Core가 봉인한 payload/전체 contributor만 사용하고 같은 실제 SQL transaction에서 모두의 현재 ACL·최종 expiry clock·CAS·receipt를 처리한다. Unknown은 원 attempt 행 잠금으로 committed receipt를 확인하거나 cancelled_not_committed로 봉인하며 자동 재실행하지 않는다.

C1은 합성 완전 cohort의 비활성 capability 인수다. C2에서 실제 Y.apply_update 경계의 원 execution·durable intake·relay 신뢰 receipt 및 bounded pending cohort를 구현하고, C3에서 명시적 factory/config epoch·drain·역할 provision·restart recovery를 조립한다. 공유 last_editor·원 user ID·Python digest만으로 complete cohort를 증명하지 않는다. 물리적으로 분리된 Core/Source DB는 별도 commit protocol이 필요하며 현재 same-DB SQL을 그대로 사용하지 않는다.

## 2026-10-09 12:20 — 현재 필수 순서

ACT-CI-03의 원 Workbench 테스트 import 정렬1개와 현재 추적6을 최종 인수하고 정상 feature 게시·필수 review·병합·소유 branch 정리를 진행한다. 이미 확인된 같은 정렬 오류를 포함한 실행은 최신 수정본의 full 성공을 대신하지 않는다. 새 exact-source full 성공 뒤에만 MR81·clean prod main FF·fresh backup·guarded prepare/deploy/smoke 및 candidate23 전후 metadata를 수행한다. 현재 운영/새 Workbench 배포는 없다.

후속 checked-save C1→native intake C2→factory/drain/recovery C3는 비활성 계약·원 cohort·같은 transaction/CAS/최종 expiry를 먼저 확정한다. Workbench의 immutable cache와 Node/Python SDK toolchain 설치·실제 개인 UI 앱 자연어 생성/등록/preview/build/배포/복구 인수는 전사 앱 전체 cutover와 병렬 준비할 수 있다. 검증된 native-only pilot을 SDK build 가능으로 표시하지 않는다. 이어 DB 앱 권한·데이터 보존과 최소 자연어/템플릿 결과 평가, 네 영역 독립 릴리스/복구를 확인한다. 앱별 비필수 상세 개선·다중 사용자는 보류한다.
