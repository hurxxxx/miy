# 장비·비품 시범 현재 상태

## 2026-10-11 managed 작업 실제 인수 완료 범위

운영자 지원 단일 소유자의 새 Project → Workspace → native 개발 → 앱 미리보기 → MR117 필수 job482/483 → dev 병합 → feat4 안정된 개발 앱 실행 → 정리를 실제 확인했다. Source `ee3afef`/dev `de88e30`의 브라우저 생성201·reload 유지·임시 데이터 분리를 확인했고, MR121/dev `76ece`·Workbench r21(source `5e6`) 반영 후 원 요청이 `unknown → waiting → 명시적 계속`으로 09:48:05 UTC에 `cleaned`/성공했다. Task18/agent11 이력은 보존했다.

독립38항목은 모두 TRUE였다. 임시 DB/두 역할·런타임/scratch·SDK unit/descriptor·앱/ingress 컨테이너/network·worktree·로컬/원격 앱 브랜치와 tracking 부재, Core 설치 archived/슬롯 회수 및 안정된 개발 DB/역할·앱 실행·정확한 소스 인계 보존을 확인했다. 정리 후 개발 가상 장비 유지·임시 가상 장비 부재·비인증401도 확인했다. 상세 실제 근거는 [작업 환경 배포 인수 기록](../WORKBENCH_WORKSPACES_DEPLOYMENT.md)이 소유한다. 의미 검색(임베딩 서버 없음)·일반 직원 계정·완전 자가 온보딩·다중 사용자·운영 rollout은 미검증이다. 아래는 이전 시범의 중지/보관과 당시 인수 기록이다.

## 2026-10-11 이전 시범 중지·소스 보관

사용자 승인으로 기존 시범 Core/Delivery/Portal/Workbench 4개 user 서비스, 기존 SDK 2개 서비스와 socket, 정확한 앱/ingress 컨테이너 2개를 중지했다. 서비스·컨테이너 중지는 Root가 수행했고 소스 보관 담당자가 7개 unit의 PID·Job·cgroup이 모두 비었음을 읽기 확인했다. 회수된 transient unit 3개는 `not-found/inactive`, Portal은 `failed/exit-code`지만 PID·cgroup 0이었다. 이를 모든 서비스의 정상 종료 성공으로 바꾸어 기록하지 않는다.

기존 소스 `/home/user/projects/miy-apps/workbench-equipment-pilot/equipment-inventory-pilot`의 clean HEAD `e3fcab9d668615f5aef57a45ce77f0e48484369b`를 fresh private Git bundle로 보존하고 native `bundle verify`·HEAD 일치를 확인했다. 이후 동일 파일시스템에서 비공개 archive로 이동해 활성 앱 소스 경로에서 제거했다. 보관 디렉토리는 `~/.local/share/miy-codex-console/archives/equipment-20261011-226d838e4b1c/`이며 bundle·receipt·복구 안내는 0600이다. 앱 사업 코드 내용은 바꾸지 않았다.

PostgreSQL·볼륨·가상 장비/이력, 두 Workbench SQLite, 앱 등록/설치 이력은 변경하지 않았다. 등록 설치 `1d7b74e7-d118-484a-9653-a542cbc94dd8`의 과거 성공을 새 Workspace 방식의 성공으로 쓰지 않는다. 이 보관 시점에는 새 Workspace 방식의 실제 인수가 남아 있었으며 이후 확인은 위 최신 기록과 배포 문서로 구분한다. 아래는 2026-10-10에 완료한 이전 시범의 결과와 한계를 보존한 기록이다.

## 2026-10-10 대표 인수 기록

기준: 2026-10-10 UTC. **운영자 연결을 사용한 실제 대표 업무 1회를 확인했다.** 결과는 `passed_with_unverified_secondary_account`로 브라우저43개TRUE·별도 정상 계정2개NULL·미확인 작업0·차단된 쓰기0이다. 새 build98a54fd1…/releasecbc22ef4…/deploy66c29a00…·gen4와 저장 release16개 확인/필수 Core5gate exit0·실제 PG 읽기 전용12개도 확인했다. 앱 HEAD e3fcab9d…clean/Root 사업 코드 쓰기0·로컬 앱 검사 반복0이다. 최초500/첫 succeeded/관측 도구 중단3회는 보존하며 전과정 자가 배포·세부 CRUD 전체·별도 정상 계정403·다중 사용자/운영 공개는 완료로 쓰지 않는다.

현재 필수 인수 잔여0은 **운영자 지원 단일 소유자 시범 범위**다. 비개발자는 업무/조작 역할 시뮬레이션이고 실제 Core 로그인은 기존 administrator다. 완전 자가 온보딩·일반 직원 권한·공개 운영은 미검증/후속이며, 최종 GUI에서 committed 이력4/prepared 물리 이력5 구분까지 읽기 확인했다.

## 현재 사실과 blocker

| 항목 | 상태 | 근거와 다음 단계 |
| --- | --- | --- |
| 시범 문서 5개 | final_scoped_record | 최초 요구·단계별 실제 결과·실패 이력·후속 개선/미검증을 분리. 최종 정상 게시/리뷰는 Root 소유 |
| 허용 소스 공간 | source_prepared | 착수 roots0/빈 root/basic 준비200 기록 보존. 지정 앱 소스에서 native 구현과 checkpoint/clean HEAD 확인 |
| 앱 실행 환경 | resolved_task_scope | SDK 최초 bind 장애 보완 후 native Task가 정확한 앱 소스에서 읽기/승인된 실제 업무 파일 쓰기를 수행. 실행기 연결 범위 해결, 앱 runtime/데이터/빌드는 별도 |
| 개발 대상 일치 | verified_scoped_flow | 동일 source/설치 gen4·현재 검증/digest/immutable image pair/UI path 원본 일치, 실제 포털 대표 업무 확인. 별도 정상 계정403은 미검증 |
| 별도 시범 환경 | verified_host_boundary | WB/포털localhost19369/19401·앱127.0.0.1:19403에서 실제 native 쿠키가 앱에 전달되지 않음/알려진 bearer HTTP URL 부재. 공격·모든 인증 경계 검사는 아님 |
| 지정 소스 공간 | source_prepared | `/home/user/projects/miy-apps/workbench-equipment-pilot`에서 native 업무 파일 구현/로컬 저장 완료. Root 직접 업무 코드 작성0 |
| 앱 데이터 준비 | verified_readonly_scope | 정확한 새 PG의 RLS/actor/role/crossDB/PUBLIC 등12개PASS. 물리 equipment1/history5, 최종 GUI GET200의 대여2+반납2=4·패배 prepared1 UI 미노출 확인. 읽기 검증이며 준비 기록 정리0 |
| 로컬 개발 기록·등록 분리 | resolved_local_save_scope | 승인된 actual source context/checkpoint/context completed/success TRUE·앱 HEAD e3fcab9d…clean Git. 로컬 기록만 해결, 등록 grant/TTL/서버 동의 별도 유지 |
| 비개발자 새 앱 입력 | resolved_input_scope | 별도 가상 probe에서 업무명/요구만 입력·고급 입력0→HTML valid TRUE·프로젝트/Task200·자동 ID 유효. 소스 form 기본값 유효 확인, 메시지/소스 prepare0·주 앱과 분리 |
| 업무 기준 확인 | confirmed_for_implementation | 새 bound 최종 native 계획revision1(저장 revision2). 한 명·100대 이하·직원 직접 입력·등록/대여/반납/전체 이력·archive 범위 유지, 실제 UI 실행/승인 dialog ask·implement200 |
| 새 앱·Task 시작 | observed | 최초 미리보기 Task09d942…idle/review 뒤 새 bound 재인수 Taskf7557c90…native 계획v1/저장 승인revision6 실제 실행 완료. 첫 실패와 새 성공 범위 분리 |
| 앱 Task의 최소 맥락 | applied_context_scope | 최초 host skill 자동 참조 이후 앱 전용 차단을 반영하고 실제 bounded source context/native 흐름을 확인. 모든 자동 skill 부재의 독립 proof는 없으며, unbound host private 파일 읽기 격리는 DEF-002 후속으로 구분 |
| 앱 공개 계약 안내 | resolved_document_scope | 두starter 문서 검사·정확 파일 반영 이후 native 모델이 갱신 key 계약을 확인. 안내 접근 범위 해결, 업무 데이터/AI 기능 성공은 별도 |
| 계획의 안전한 참고 전달 | verified_reference_only | 후보21PASS 이후 실제 native context completed/success TRUE·prior plan present/version1/reference only TRUE·execution authorized FALSE/truncated FALSE. 실제 계획 참고 전달 확인, 구현 승인/업무 성공과 별개 |
| 번호 중복의 일반 데이터 경계 | verified_owner_row_scope | 후보9PASS/초기fixture FAIL 보존. 실제 등록201/동일 번호409·같은 version, 동시 대여200+409/승자1명 확인. 전사 번호 고유성·영구 요청 이력 보장 아님 |
| 사용 가능한 SDK 명령 안내 | resolved_document_scope | 최초 exit127/Python 적응 보존. Immutable SDK 변경 없이 한국어 공개 CLI 안내 정확 파일 반영·존재 확인, 전체 명령/업무 성공 주장 없음 |
| 최소 앱 개발 | checkpointed_and_scoped_flow_verified | App clean HEAD e3fcab9d…유지. Python37/Node10/Vite 직접 marker/exit0·한/영 static render 보고와 최종 실제 업무1회를 분리. 보관 위치 별도 필드 없이 메모인 최소 구현 |
| 실제 SDK 격리 관측 | observed_bound_sdk_only | Bound SDK source RW/Git RO/SDK RO/host Codex home 없음/private network 확인. Unbound host read-only 계획은 private 읽기 물리 차단 없음/단일 소유자 trusted client. 침투 테스트 아님 |
| 플랫폼 typed build | succeeded_operation | 첫 build37b69a1e…/releasef45a89ec… 이력 보존. 같은 HEAD 새 build98a54fd1…succeeded/releasecbc22ef4…를 확인했으며 기존 결함 artifact 재사용0/로컬 앱 검사 반복0 |
| 개발 배포 다음 행동 안내 | verified_guidance_scope | 미연결 disabled DOM/owner 네 항목 저장·운영자 허용 인계/계획·실행·미리보기 업무까지 확인. 앱별 private grant/target의 self-service UI 미완료 |
| 개발 등록 | registered | Task47b702a9…idle/review, 실제 첫 owner 동의/ask 실행 뒤 operation6f5938…receipt의 앱/설치1d7b74e7…/digest9a7e687c…/HEAD e3fcab9d… 일치 |
| 개발 미리보기 | verified_scoped_business_flow | 첫 deploy23111ba5…/gen3/iframe500 보존. 새 gen4 actual root/SDK/API200 뒤 등록·대여·반납·동시 경계·보관 종료/복원·reload 유지1회 확인. 정상 별도 계정403은 미검증 |
| Artifact/첫 UI 준비 경계 | resolved_first_screen_scope | 후보50PASS·최초 umask3FAIL→3PASS 뒤 새 runtime UID1000 public artifact 읽기/HTTP200 및 대표 업무 확인. 과거 UI path 없는 health-only receipt 한계 그대로 |
| 검사 묶음/재사용 맥락 | applied | 동일 revision 후보 검사 재사용/필수 Core gate 유지 정책2PASS/19deselected·2.34초·linter PASS/Workbench pilot reload 확인. 전체 기능/배포 검증을 대신하지 않음 |
| 대표 흐름·중요 경계 묶음 | passed_with_unverified_secondary_account | 실제 업무1회43TRUE/2NULL·미확인 작업0/차단된 쓰기0. 앞선 관측 도구3중단은 업무POST0/ledger 불변·제품 반복 검사PASS에 더하지 않음 |
| 결과·개선 인계 | documented_scoped_limits | 실제 UI·DB·release proof와 한계를 분리. DEF-001 자가서비스 인계/target 및 DEF-002 다중 사용자 전 unbound 계획 격리 후속 유지 |

준비 상태와 추가 장애는 Root가 전달한 사실이다. 이 문서 담당자가 설정·API·서비스를 추가 조회한 결과로 표시하지 않는다. 기존 Workbench 배포·계정 연결 성공을 새 앱 실행기 준비의 증거로 대신하지 않는다. 소유 에이전트의 구현/검사 결과를 받으면 실제 수행 범위를 구분해 갱신한다.

## 후속과 유지할 한계

대표 업무 인수는 완료한1회로 기록한다. 추가 전체 검사·모델 실행·데이터 쓰기를 자동으로 반복하지 않는다. 최종 GUI의 committed4/prepared5 구분도 읽기 확인했다. 앱 입력14SHA·HEAD가 그대로인 후보 결과는 재사용했고 필수 플랫폼 gate를 유지했다. 최초500/원래 succeeded ID/관측 중단3회와 self-service 보호 인계/target 공백은 보존한다. 이번 운영자 지원 단일 소유자 시범의 필수 인수 잔여는 없고 정상 문서 게시/리뷰는 Root가 담당한다.

대리급 비개발자는 자연어·업무 지식·화면 조작의 역할 시뮬레이션이며 실제 Core 개발 로그인은 기존 administrator 계정이다. 가상 직원은 업무 payload일 뿐 실제 employee 인증이 아니다. 새 계정 생성·권한 변경·메일 발송0이며 일반 직원의 자가 등록 권한/별도 정상 계정의 같은 설치403은 미검증이다. 해당 검사2개는NULL로 유지한다. 일반 rollout 전 기존 정상 테스트 신원으로 별도 확인해야 한다.

세부 수정·삭제 CRUD 전체/hostile attack/다중 사용자/운영 및 공개 배포는 미수행이다. 보관 위치의 별도 필드 없이 메모만 구현했으며 기능 고도화는 이번 완료의 선행조건으로 추가하지 않는다. 2026-10-11 승인된 정리는 기존 실행 중지와 소스 비공개 보관에 한정한다. Prepared 데이터·PG·SQLite·등록 이력 삭제는 수행하지 않았다.

## 완료로 기록할 때

- 사용자 행동, LLM 설명, 실제 도구 결과, 화면/API의 적용 결과를 구분한다.
- 코드 생성·등록·실행·업무 검증의 결과를 각각 기록한다. 어느 한 단계의 성공을 나머지 성공으로 확대하지 않는다.
- 기존 데이터/앱을 건드리지 않고 새 가상 테스트 데이터만 사용했는지 확인한다.
- 실패와 unknown·미검증 한계를 보존한다. 대표 묶음 통과와 전체 자연어 앱 E2E 완료는 다르다.
- 필수 장애가 남으면 해당 blocker를 적는다. 비필수 앱 기능/편의 개선은 IMPROVEMENTS에 보류한다.

## 실행 요약: 최초 상태와 최종 인수 구분

| 실행 | 실제 대상·결과 | 상태 |
| --- | --- | --- |
| 최초 환경 준비 | 당시 별도 Workbench·개발 Core/포털·격리 데이터·native 개발/로컬 저장까지 확인. 등록/runtime 데이터는 그 시점 미완료 | 당시 준비 완료/등록 전 |
| 별도 Workbench UI baseline | 로그인200·shell/page errors0, 업무명/대략 요구로 시작했으나 POST0/Task0/메시지0 | 접속 성공/앱 시작 실패 |
| 비개발자 입력 재확인 | 별도 가상 project/idle unbound Task에서 업무명·요구만으로 프로젝트/Task200·소스 form 기본값 유효, 메시지/소스 생성0 | 입력 범위 해결 |
| Workbench/native 계획 | 최초 계획 후 bound 최종 native 계획revision1/저장 revision2, idle/pending0 | 계획 완료 |
| native 앱 개발 | 개발 Task idle/review·native context/checkpoint/context 성공·clean app HEAD. 최종 AI 검사 보고37/10/Vite/static render와 직접 실행 근거 분리 | 개발 후보 로컬 저장 |
| 플랫폼 typed build | 첫 작업 이력 보존. 같은 HEAD 새 build98a54fd1…succeeded/releasecbc22ef4… | 새 신뢰 작업 성공 |
| 개발 등록 | Owner 동의/ask 실행 뒤 matching receipt·새 installation·등록 Task idle/review | 등록 확인 |
| 최초 iframe 미리보기 | Deploy23111ba5…succeeded/metadataready gen3, 실제 owner iframe500·API/session0 | 최초 실패 이력 보존 |
| 새 iframe 미리보기 | Deploy66c29a00…succeeded/ready gen4·actual rootHTTP200·SDK config/session exchange/me/equipment 모두200 | 첫 화면/초기 응답 확인 |
| 저장 release proof | Fresh16flagsTRUE·현재 검증/원본/digest/imagepair/UIpath 일치·resource_limits/profile/test/build/package5gate exit0 | 읽기 전용 stored proof 확인 |
| 업무·중요 경계 묶음 | 실제1회43TRUE/별도 정상 계정2NULL·미확인 작업0·차단된 쓰기0, 앞선3중단 업무POST0 | passed_with_unverified_secondary_account |
| 새 PG/최종 GUI 읽기 확인 | 정확한 새DB12checksPASS·equipment1/history5 prepared, GUI committed 대여2+반납2=4/패배 prepared1 UI 미노출·GET200 | PG/role/RLS·저장 이력 구분 확인 |
| 앱 세션 만료 후 연결 | 의도된5분 만료 뒤 Connect의 정상 재연결→exchange/me/equipment200·업무 쓰기0 | 정상 복구, 자동 갱신/입력 상태 보존은 후속 |

현재 완료는 운영자 연결을 사용하는 단일 소유자 개발 시범의 native 구현/로컬 저장·등록·새 신뢰 build/deploy·실제 대표 업무1회/읽기 전용PG 경계다. 완전 비개발자 자가 서비스·모든 앱/사용자/공격 경계·운영 rollout은 아니다. 시범용 unit pattern과 관측 selector 오류는 운영자/관측 문제로 구분하며 기존 기록을 유지한다. 문서 담당자는 코드·API·DB·서비스·Git 게시·테스트 실행을 하지 않았다.
