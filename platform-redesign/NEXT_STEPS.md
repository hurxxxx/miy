# 후속 구조작업

2026-10-08 UTC. 사용자 요청에 따라 Source 명령 후속 게시 이후의 필수 작업을
식별했고, PR70 병합 후 사용자 지시로 다음 구현을 재개했다. 현재는 아래
세 경계의 로컬 구현·검증·독립 리뷰를 마쳤으며 서비스·공유 환경 변경은 하지 않았다. 게시 추적은
[PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md), 작업 상태는
[WORK_ITEMS.md](WORK_ITEMS.md)가 소유한다. 이 문서는 우선순위·의존성과
다음 착수 단위를 소유하며 별도 작업 대장을 만들지 않는다.

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
각 runtime owner에 기록한다. 이번 구현에는 새 게시·배포 권한이 포함되지 않는다.

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
