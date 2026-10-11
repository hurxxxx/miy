# 시범 과정과 결과 관측

현재 최종 업무 인수1회는 `passed_with_unverified_secondary_account`다. 브라우저43개TRUE/별도 정상 계정2개NULL·미확인 작업0/차단된 쓰기0, 실제 PG 읽기 전용12개PASS와 fresh release16개TRUE/필수 Core5gate exit0을 서로 구분한다. 실제 로그인은 기존 administrator이고 비개발자는 업무/조작 역할 시뮬레이션이다. 앱 e3fcab9d…clean/Root 사업 쓰기0이며 최초500/관측 중단3회와 미검증 한계를 보존한다. 원문/비밀/업무 payload는 기록하지 않는다.

## 무엇을 관측으로 인정하는가

| 종류 | 남길 내용 | 구분 |
| --- | --- | --- |
| 사용자 요구/결정 | 대략적 목적, 빠진 업무 결정, 확인한 답변의 요약 | 예상 시나리오와 실제 답변 구분 |
| 적용 행동 | 실제 브라우저에서 선택/입력/실행한 기능과 대상 종류 | 클릭 의도와 실제 요청/적용 구분 |
| native 도구 결과 | 실행된 도구 종류·상태·변경 범위·공개 오류 코드 | 호출하지 않은 도구를 호출했다고 설명하면 불일치 |
| 화면/적용 결과 | 관측한 화면 boolean·상태 전이·동일 앱/설치 여부 | LLM 완료 설명과 독립적인 적용 근거 |
| LLM 자기 설명 | 완료/실패/질문/추정 여부를 짧게 요약 | 설명 자체는 성공 증거가 아님 |
| 한계 | 미관측·unknown·중단 이유와 다음 최소 행동 | 앞선 성공으로 덮지 않음 |

Prompt 원문·대화 transcript·작업 로그·계정/세션/token·실제 사람/고객 데이터·응답 payload는 기록하지 않는다. 스크린샷이 필요하면 가상 앱 화면만 사용하고 사용자/계정 정보가 포함되는지 운영자가 확인한다.

## 관측 이력

각 행은 해당 시점의 기록이다. 이후 독립 관측이 상태를 갱신하더라도 이전 실패/미관측은 보존한다. 최신 단계는 상단과 STATUS를 기준으로 읽는다.

| ID | 시점·출처 | 적용 행동/도구 결과 | 판단 |
| --- | --- | --- | --- |
| OBS-001 | 2026-10-10 착수 시 Root 전달 | 허용 소스 roots0·executor configured0, 개발 포털과 Workbench 연결 대상 차이. 문서 담당자의 live 조회·변경 없음 | 실제 앱 시작 전 운영자 준비가 필요. 앱 개발 실패나 LLM 실패로 단정하지 않음 |
| OBS-002 | 2026-10-10 추가 실제 발견의 Root 전달 | 개발한 소스의 dirty 상태, 최초 등록의 clean HEAD 요구, checkpoint의 등록 허용 요구와300초 TTL이 충돌 | 정상 개발→기록→등록 순환을 막는 필수 장애. 소유자 로컬 기록과 실제 등록 허용을 분리하되 원본/권한 검사 유지 |
| OBS-003 | 2026-10-10 운영자 준비 방향의 Root 전달 | 기존 공개 Workbench/운영 연결 보존. 별도 시범 Workbench·새 SQLite·개발 MIY와 지정 새 소스 공간 준비 예정 | 계획과 실제 적용을 구분. 아직 새 환경/경로 생성 성공 관측 아님 |
| OBS-004 | 2026-10-10 UX 검토 착수의 Root 전달 | 비개발자 흐름의 필수 앱 ID·저장소·허용 경로 입력을 소유 에이전트가 검토 | 최소 기본값/준비된 선택지가 필요한지 실제 흐름으로 인수. 기술 필드 삭제나 권한 자동 확대를 완료한 것으로 쓰지 않음 |
| OBS-005 | 2026-10-10 실제 Chromium baseline의 Root 전달 | 별도127.0.0.1:19369·fresh SQLite/schema0008·native 비밀번호 로그인200·shell/page errors0. 업무명·대략 요구 입력 후 시작 클릭은 앱 ID/`reuse_notes` HTML required로 POST0/Task0/메시지0 | 접속/화면 로드와 실제 앱 시작 결과를 구분. 비개발자의 업무 설명만으로 시작 불가 재현 |
| OBS-006 | 2026-10-10 환경 준비의 Root 전달 | 지정 앱 root 생성 완료, 빈 root/앱 소스0. 별도 시범 상태 공간 사용, 기존 공개/운영 변경0 | 운영자 준비 결과. 실제 소스/앱/Task 생성 성공이 아님 |
| OBS-007 | 2026-10-10 담당 에이전트 baseline의 Root 전달 | 등록 checkpoint 순환의 dirty fixture에서409/도구 실행0 확인 | 직접 실패 fixture 근거이며 현재 시범 앱의 실제 native 실행 결과와 구분. 원본/dirty 검사 완화 없이 분리 보완 필요 |
| OBS-008 | 2026-10-10 로컬 기록 도구 소유 에이전트 전달 | Dirty→등록 초안409와 개발 Task의 native 도구 목록 비어 있음 재현. 로컬 소유자 기록 도구 후보 구현·직접 영향 검사 진행 중 | 로컬 후보이며 검사 완료·시범 Workbench 반영·새 Task 실행은 아직 미관측. 등록/배포 권한과300초 기한을 해제한 것으로 쓰지 않음 |
| OBS-009 | 2026-10-10 실제 브라우저 계획 진행의 Root 전달 | 운영자가 앱 ID/기존 앱 검토 근거를 보완해 프로젝트200·Task200. 비개발자 역할의 대략 요구 한 건 messages200, native 구독 코딩 클라이언트의 읽기 전용 계획 진행 | 운영자 보조된 시작 성공. 최초 required 실패를 덮거나 단독 비개발자 흐름 해결로 확대하지 않음. 계획 실행/코드 수정0 |
| OBS-010 | 2026-10-10 실제 native 질문/답변의 Root 전달 | 두 차례 각3개 업무 질문과 UI 답변200. 담당자 한 명/가상 직원·개별 물품/직접 등록, 선택 예정일·직원 이름/선택 부서, 전체 이력·중복 대여/대여 중 삭제 거부·반복 반납 중복 금지 확인 | 실제 계획 기준 확인. 대화 원문을 보관하지 않으며 앱 구현·업무 흐름 성공과 구분 |
| OBS-011 | 2026-10-10 실제 계획/관찰 경계의 Root 전달 | 앱 소스 연결 전 계획에서 기존 `miy-app-delivery` skill 자동 참조. 관찰자의 '추가 답변' selector와 실제 '직접 답변' 불일치로 관찰 helper 실패, 실제 native 답변 UI200 | Host skill 자동 유입은 IMP-006으로 최소 분리 보완. Selector 실패는 제품 오류가 아니며 native 답변 성공 근거만 인정 |
| OBS-012 | 2026-10-10 로컬 기록 도구 소유 에이전트 검사 전달 | 첫 영향 묶음118PASS/28FAIL. pinned native ThreadStart 스키마의 도구 `type: function` 누락으로 분류해 후보 수정, 실패 영향 재확인 중 | 검사 실패와 기존118PASS를 보존. 등록/배포 권한 gate 완화 없음. 최종 검사 통과·실제 시범 적용은 아직 미관측 |
| OBS-013 | 2026-10-10 로컬 기록/앱 맥락 후보 동결의 소유 에이전트 전달 | 수정 후 직접 실패 subset53PASS/19.63초, Ruff/format/diff check PASS. 가상 fixture로 dirty→local checkpoint→clean HEAD→새 등록 동의 확인, 실제 등록0 | 코드 후보 검사 근거. 최초 baseline1FAIL/0.50초와118PASS/28FAIL/57.02초 보존. 실제 시범 서비스 반영/새 Task native 실행/앱 기능은 아직 미관측 |
| OBS-014 | 2026-10-10 별도 개발 플랫폼 준비의 Root 전달 | 전용 Core API172.17.0.1:19400와 포털127.0.0.1:19401 healthy/development, 동일 개발 registry 사용. 보호 설정은 host에서만 사용, 기존 개발/운영 설정·서비스 변경0 | 개발 대상 준비 결과. 새 앱 등록/설치·업무 기능의 적용 증거가 아님 |
| OBS-015 | 2026-10-10 앱 데이터 준비의 Root 전달 | 새 PostgreSQL `miy-equipment-pilot-data`/전용 볼륨·loopback19402, 보호 경로0700/파일0600. postgres/template DB의 기본 PUBLIC CONNECT/TEMPORARY 회수, 이전 클러스터 변경0 | 운영자 격리 준비. 설정 내용/비밀번호를 기록하지 않으며 실제 앱 데이터 연결/ACL 성공으로 확대하지 않음 |
| OBS-016 | 2026-10-10 실제 소스 준비 UI의 Root 전달 | `equipment-inventory-pilot` basic 소스 준비200. 관찰자 exact select label timeout으로 private-notes 선택은 실패해 basic 사용. `business.py` placeholder 유지, Root 직접 업무 코드 작성0 | 템플릿 준비 성공과 장비 기능 개발을 구분. 관찰자 selector 실패를 제품/다른 템플릿 결함으로 단정하지 않음 |
| OBS-017 | 2026-10-10 소스 실행 준비의 Root 전달 | SDK cache verify PASS/packages executed FALSE, 새 소스 node_modules 준비. 시범용3systemunits 설치/시작, 운영자 unit pattern placeholder 오검지를 수정 | 실행 준비 결과. 실제 native 장비 앱 작업/모델 turn·데이터 기능 성공 근거가 아님 |
| OBS-018 | 2026-10-10 후속 업무 질문/답변의 Root 전달 | 마지막3개 질문 답변API200: 담당자 한 명/100대 이하, 번호 직접 입력·중복 금지, 이력 있으면 archive/미사용만 delete. 첫 계획 확정 요청 | 실제 계획 기준 추가. 구현 승인/계획 실행/코드 변경을 했다고 쓰지 않음 |
| OBS-019 | 2026-10-10 비개발자 UX 후보 동결의 소유 에이전트 전달 | 업무명/요구만 필수, 앱 ID/로컬 저장소 식별자/허용 root 선택 후보. UI3파일27PASS·API8PASS, Ruff/ESLint 오류0·타입/빌드PASS/11.41초 | 로컬 후보 검사. 실제 같은 persona 행동 재확인·원격 저장소/백업·모델/Task 실행 성공은 아직 아님 |
| OBS-020 | 2026-10-10 앱 안내 빈틈의 Root 전달 | 준비된 README의 데이터 안내가 작업 공간 밖의 없는 링크를 가리키며 AI 기능 계약 파악에도 빈틈 발견. 필요한 공개 문서의 독립 안내 보완 중 | IMP-007 필수 계약 접근 보완. 자격증명/host 설정이나 기존 전체 skills를 제공할 근거가 아님 |
| OBS-021 | 2026-10-10 문서 담당자의 좁은 source 도구 읽기 검토 | 현재 callback의 exact Task/thread/turn/generation/executor·DB 소스 연결·구현 승인·HEAD CAS 전 재확인과 로컬 전용 입력 확인. 별도 코드/검사/live 조회0 | 이 범위에서 새 blocker 미발견. 단일 소유자 Workbench 계약을 전제로 하며 실제 새 Task/native 실행·등록 성공 증거가 아님 |
| OBS-022 | 2026-10-10 공개 계약 starter 후보 동결의 소유 에이전트 전달 | Basic/private-notes에 작업 공간 안의 `PLATFORM_CAPABILITIES.md`·README 로컬 링크·AGENTS 필요 시 pointer 후보. Baseline1FAIL/0.79초→starter10PASS/0.52초, formatter 후 exact byte2PASS/0.22초·generator/lint PASS. manifest/business/vendor/cache/profile byte 변경0 | 문서/생성 bundle 후보 검사. 현재 시범 앱에 문서만 추가하는 실제 반영은 Root 후속. 새 데이터 record key 제안은 미구현이며 후보는 기존 계약만 설명 |
| OBS-023 | 2026-10-10 native 계획 완료의 Root 전달 | 최종 native 계획1/revision1 생성, Task idle/pending0. 계획에서 번호 중복 방지를 위한 일반 record key 조건부 생성/키 조회 필요 제안 | 실제 계획 완료. 신규 서버 기능/앱 구현/등록 성공은 아니며 IMP-008의 후보 결과와 별도 |
| OBS-024 | 2026-10-10 SDK 최초 시작 장애/운영자 최소 보완의 Root 전달 | ProtectHome=yes 아래/home 소스 bind의 nested bwrap permission denied 실제 재현. 공식 systemd 설정 계약 근거로 해당 backend만 ProtectHome=tmpfs+exact source bind 보완 후 backend/socket active | 최초 실패 보존. Host WS19621/private namespace19622·cap0/NNP/private network·`.git` 읽기 전용과 기존 공개 service/proxy 경계 유지. 실제 native 앱 실행은 아직0 |
| OBS-025 | 2026-10-10 보호 연결/문서 반영의 Root 전달 | 전용 Core UI API key201·읽기2scope, 비밀은 운영자0600 설정만. 실제 native 개발 로그인200과 subject/origin pair 일치. 신규 공개 기능 문서 정확한 파일만 소스에 복사, 사업 코드0 | 운영자 bootstrap/공개 안내 반영. 읽기 연결을 최초 등록/배포 권한이나 native 앱 실행 성공으로 확대하지 않음 |
| OBS-026 | 2026-10-10 접속 호스트 분리 준비의 Root 전달 | WB/포털 localhost19369/19401로 맞추고 예정 앱runtime127.0.0.1:19403로 별도 host 설계. 외부 공개 변경0 | localhost owner 쿠키의 앱127host 전달을 피하는 계획. 아직 앱이 없어 실제 쿠키/iframe 경계 검증은 미실행 |
| OBS-027 | 2026-10-10 계획 참고 도구 후보 동결의 소유 에이전트 전달 | 소스 생성 후 새 bound 개발 Task의 계획 단절 baseline1FAIL/0.63초→source_tools21PASS/9.43초·lint/formatPASS. 이전 동일app/project native 최종 계획 최신1개만 UTF8 최대16KiB/truncated/reference_only/execution_authorizedFALSE | 현재/미래/다른앱/Core/manual/raw prompts/items 제외, approved revision 복사0. 별도 후보 round이며 이전53PASS를 재실행 proof로 쓰지 않음. 실제 새 Task context/native 인수는 Root 후속 |
| OBS-028 | 2026-10-10 일반 데이터 후보 진행의 Root 전달 | Optional opaque record key 조건부 생성/키 조회 후보8PASS, API handler fixture1FAIL 수정 중. 기존 schema/checksum/PK·RLS·CAS 유지 방향 | 앱별 특별 동작 아닌 공용 후보. 검사 최종 통과/실제 앱 사용·등록·배포를 가정하지 않음 |
| OBS-029 | 2026-10-10 실제 source-bound Task 시작의 Root 전달 | Studio 개발 이어가기→실행 연결 검사→Task POST200/source bound TRUE. Native 구독 클라이언트가 정확한 앱 cwd/read-only plan에서 commands10·소스 읽기, UI page errors0 | 실제 native source inspection. 사업 구현/등록/빌드0이며 초기 native 실행0 기록을 현재 상태로 재사용하지 않음 |
| OBS-030 | 2026-10-10 native 읽기 적응의 Root 전달 | 최초 `ls/find/git/rg` 각각 exit127/not found, Python으로 읽기에 적응. Immutable SDK 변경0 | IMP-011 사용 가능 명령 공개 안내 보완. 업무 기능 결함이나 전체 실행기 실패로 확대하지 않음 |
| OBS-031 | 2026-10-10 도구 관측 한계/실제 계획 재사용의 Root 전달 | 직접 RPC 응답 후 handler 조기 return·opaque 항목의 저장 제외로 SQLite items/dynamic tool 표시0이 호출0 증거가 아님. 실제 AI 본문은 담당자1/100대 이하/등록·대여·반납·전체 이력 조건 반영 | context invocation independently unobserved; settled prior decisions reflected. 확정 결정의 반영만 인정하고 context 호출이나 승인 승계를 추정하지 않음 |
| OBS-032 | 2026-10-10 실제 질문 대기의 Root 전달 | 기존 공개 안내에는 key 기능 지원이 없어 native 질문1/waiting/pending1. 질문은 플랫폼 선행 기능의 시점/범위이며 기존 업무 결정을 다시 묻지 않음 | 기능 후보/문서의 전용 대상 반영 후 답변 예정. Root의 답변 selector timeout은 관찰자 실수로 제품 실패 기록 대상이 아님 |
| OBS-033 | 2026-10-10 일반 key 후보 동결의 Root 전달 | Fixture handler 실패 최소 수정/명시 auth override 후 unique 직접9PASS, 소스 동결. Public 문서/generator 마무리 중 | 앞선8PASS/1FAIL 보존. 후보 통과는 전용 Core 반영·실제 native 앱 활용·업무 검증과 별개 |
| OBS-034 | 2026-10-10 이전 계획 전달의 독립 native 관측 Root 전달 | 정확한 현재 thread의 native 사건에서 DynamicToolCall·miy_app_source/action context·completed/success TRUE. Result의 prior plan present TRUE/version1/reference only TRUE/execution authorized FALSE/truncated FALSE | OBS-031의 당시 독립 미관측을 갱신. 실제 이전 계획 전달 성공, 구현 승인 승계/앱 업무 성공은 아님. Raw 로그/응답 복제·공개0 |
| OBS-035 | 2026-10-10 일반 key 후보 완료의 소유 에이전트 전달 | Optional printable UTF8≤256bytes key·data read by-key, 인증된 source user/설치/컬렉션/key 식별. 동시 하나 성공/다른409·overwrite0. PG17/NGINX9검사·API/starter generator/check PASS | 원사용자의 현재 키 행만 고유, 전사 고유/영구 요청 이력 보장0·삭제 후 재생성 가능. Schema/checksum/PK·RLS·CAS 유지. 실제 pilot Core/앱 활성화는 Root 후속, 사업 코드0 |
| OBS-036 | 2026-10-10 공개 계약/전용 Core 실제 반영의 Root 전달 | 공개 doc SHA3205c475… 정확 파일만 기존 앱 doc에 복사·사업 code0. 전용 Core service만 재시작 active, native OpenAPI200/by-key 있음 TRUE·포털 health200/development TRUE. Native 모델이 갱신 key 지원 확인 | 후보의 전용 대상 반영. 기존 개발/운영 영향0. Root가 사용한 잘못된 `/api/v1/health`404는 검사 URL 오류이며 제품 결함이 아님 |
| OBS-037 | 2026-10-10 새 최종 계획/기존 starter 검사의 Root 전달 | Native 최종 bound 계획revision1/저장 revision2 생성, idle/pending0. 기존 starter pnpm test2PASS 자체 설명과 native 명령 결과 관측, 업무 범위 유지 | 실제 계획 완료와 기존 템플릿 검사만 인정. 새 장비 기능/회귀/데이터 검증이 아님 |
| OBS-038 | 2026-10-10 실제 실행 승인 UI의 Root 전달 | 실행 버튼→승인 dialog(default ask/SDK ask only/yolo0)에서 명시 승인, implement POST200. Native Task running/implement·approved revision2·permissions ask, AI 구현 시작 선언 | 실제 서버 승인/실행 상태. AI 선언과 업무 파일 적용/기능 완성 구분, Root/협업 에이전트 직접 사업 코드 작성0 |
| OBS-039 | 2026-10-10 브라우저/관찰 경계의 Root 전달 | 새 실제 브라우저 page errors0. 이전 브라우저 정상 close로 서버 Task 중단0, 새 인증값 출력0. 한국어 SDK CLI 공개 안내 정확 반영/존재 확인 | 관찰자 세션/앱 실행 상태 구분. 안내 범위 해결, 업무/모든 SDK 명령 검증 성공으로 확대하지 않음 |
| OBS-040 | 2026-10-10 개발 배포 안내 UI 후보의 소유 에이전트/Root 전달 | Exact development·delivery configured FALSE에서 disabled 배포 계획/소유자 미리보기 사용 동의→관리자 연결 요청 안내. Stale/unavailable 현재 대기 단정 없음, configured TRUE/production 동작 보존. 직접6PASS·타입/빌드PASS/9.98초 | Local dist 후보 검사이며 실제 시범 UI 인수는 아직 없음. 완전 비개발자 자가 배포의 소유자 동의→server private grant 인계 UI는 별도 미구현 개선 |
| OBS-041 | 2026-10-10 17:35 실제 native 쓰기의 Root 전달 | Manifest web-api-postgres profile/권한 요청3개, business.py418줄 변경과 새 inventory/inventory-copy 웹 파일 관측. Native UI trace file change2/command16, Task running/implement/ask·승인 revision2·pending0 | Root/협업 에이전트 사업 쓰기0, 실제 Workbench native AI의 구현. 아직 mid-write로 호환성 최종 판정 전·업무 test/등록/build0. Manifest 요청을 권한 부여로 쓰지 않음 |
| OBS-042 | 2026-10-10 실제 비개발자 입력 재확인의 Root 전달 | 별도 가상 입력 확인 프로젝트에서 업무명/요구 두 항목만 입력·advanced 입력0. HTML valid TRUE·프로젝트 POST200/Task POST200·자동 app ID 유효, idle/unbound Task·messages0/source prepare0 | 최초 required 실패의 입력 시작 범위 해결. 주 앱의 운영자 소스 준비/개발과 분리, 앱 생성/등록/배포 전체 성공으로 확대하지 않음 |
| OBS-043 | 2026-10-10 source form/관찰 재개의 Root 전달 | 별도 probe source form의 advanced collapsed/root selected/default local repo/valid TRUE·page errors0. 최초 observer strict locator의 버튼2개 오류 뒤 기존 probe 정확 ID를 재조회해 form만 읽기 재개 | 제품 실패/새 프로젝트 재생성이 아님. Receipt는 생성 상태가 이전 run 관측이고 두 번째 run은 form only임을 구분, 소스 prepare 실행0 |
| OBS-044 | 2026-10-10 native AI 후보 검사/직접 수정의 Root 전달 | 최초 Python collection exit2/tzdata와 Node 병렬 exit1/PID64 경계 발생. Native AI가 UTC+9 stdlib/test concurrency1로 직접 수정 후 Python28PASS·Node10PASS·Vite buildPASS | 최초 실패 보존, Root 사업 수정0. 후보 검사·후보 프런트 빌드이며 실제 플랫폼 typed build/업무 브라우저/배포 인수는 아님 |
| OBS-045 | 2026-10-10 독립 읽기 검토 snapshot의 Root 전달 | Business SHA d3779739…/Inventory SHA58886824…에서 현재 장비와 과거 operation result 구분·저장 PUT 응답·화면 reload GET 확인, 해당 blocker0 | 현재 snapshot 읽기 경계만 확인. 실제 API/PG 데이터·대여/반납·권한 흐름 성공으로 확대하지 않음. Mid-write/새 변경이면 snapshot 범위 한계 유지 |
| OBS-046 | 2026-10-10 실제 SDK mount/namespace 관측의 Root 전달 | 활성 프로세스의 source RW/Git metadata RO/SDK RO·host Codex home mount 없음·private network 유지 확인 | 실제 실행 환경 경계 관측이며 침투 테스트가 아님. Raw mount/log/env 공개 없이 안전한 경계만 기록 |
| OBS-047 | 2026-10-10 현재 단계/typed builder 한계의 Root 전달 | Native Task running/implement/ask·승인2, 명령31/file change12. Core trusted builder 고정 node --test에는 package 직렬 옵션 미전달 | 실제 typed build는 미검증. Source checkpoint/등록/배포/업무 브라우저 인수 미완료, 후보 직렬 PASS를 builder 통과로 쓰지 않음 |
| OBS-048 | 2026-10-10 실제 구현 완료/로컬 checkpoint의 Root 전달 | 개발 Task idle/review. 비개발자 역할의 로컬 저장 요청/명시 승인 뒤 native source context/checkpoint/context 각각 completed/success TRUE. 앱 HEAD e3fcab9d668615f5aef57a45ce77f0e48484369b·clean Git | 실제 승인된 로컬 기록 근거. Core Git/원격 배포0, 등록 grant/동의/TTL 별도 유지. 최종 구현/저장 receipt는 안전한 native history 메타데이터만 보관 |
| OBS-049 | 2026-10-10 최종 native AI 검사 보고의 Root 전달 | API adapter mock gateway/응답 유실 검사 추가 후 Python37PASS·Node10PASS·Vite buildPASS·한국어/영어 static renderPASS 보고 | 최종 AI 검사 보고와 직접 관측한 도구 완료/저장 범위를 분리. 앞선28/10/Vite 실제 후보 결과 보존, 실제 업무 API/데이터/typed build/배포 성공으로 확대하지 않음 |
| OBS-050 | 2026-10-10 실제 새 등록 Task 시작의 Root 전달 | Studio 새 등록 작업/실행 연결 확인→등록 Task47b702a9…POST200/message200·bound read-only plan. 기술 초안 제거 후 비개발자 업무 언어로 저장 내용 확인/등록 계획 먼저 요청 | 등록 계획 시작이며 owner 동의·실제 등록/설치/배포/브라우저 결과0. Fresh native 로그인/page errors0·Core 개발 owner 로그인200은 별도 연결 근거 |
| OBS-051 | 2026-10-10 실제 최초 등록/receipt의 Root 전달 | MIY UI 최초 등록 한 번 허용 뒤 Workbench ask/implement200. 등록 Task idle/review, native AI context/clean checkpoint→register/status 성공 보고. 동일 operation6f5938…DB receipt의 app equipment-inventory-pilot/install1d7b74e7-d118-484a-9653-a542cbc94dd8/digest9a7e687c…/HEAD e3fcab9d… 일치 | 실제 등록 metadata/receipt 근거. AI 보고와 실제 일치를 분리, 설치 runtime/typed build/배포 성공은 아님 |
| OBS-052 | 2026-10-10 실제 사용 동의/미연결 UI의 Root 전달 | Owner 포털 exact setup에서 허용·신원·데이터 read/write 네 항목 선택/설정 저장. Workbench 미연결 미리보기 버튼 disabled 실제 DOM/page errors0 | 등록 동의와 앱 사용 설정/미리보기 준비를 구분. Disabled 관측은 전체 자가 배포 UI 완료가 아님 |
| OBS-053 | 2026-10-10 운영자 보호 허용/개발 target 준비의 Root 전달 | Normal owner/session-bound 개발 read/sync/build/deploy 허용POST201·하루 이내. Secret은 server0600 설정만, token UI/model/source 노출0. Exact typed target validate·immutable image 로컬 존재·consumer 활성, dedicated Core/WB만 재시작 | 운영자 bootstrap이며 실제 build/deploy 인수 전. 공용 서비스 변경0. 앱별 private 인계 반복은 DEF-001 핵심 공백으로 유지 |
| OBS-054 | 2026-10-10 실제 새 미리보기 배포 계획 Task의 Root 전달 | WB 앱 관리의 미리보기 계획→새 source-bound Task09d942d0…POST200/message200·read-only plan | 실제 계획 시작. Typed build/배포/업무 브라우저 pending, 운영자 준비를 비개발자 전과정 자가 서비스 완성으로 쓰지 않음 |
| OBS-055 | 2026-10-10 실제 고정 builder/배포 결과의 Root 전달 | Core build37b69a1e-d41f-517a-8c06-803459c2e4a6 succeeded/releasef45a89ec-765f-4a28-938b-d3d99b002d10, deploy23111ba5-91ab-5e02-85a2-4059e060b5d5 succeeded/install ready generation3·권한3 | 실제 작업/metadata 상태이며 아래 브라우저 실패와 함께 해석. Native Task idle/review·private SDK localhost 접근 거부로 화면을 정직하게 미검증 보고 |
| OBS-056 | 2026-10-10 최초 실제 포털 실패/원인 확인의 Root 전달 | Owner portal iframe Internal Server Error500·app API requests0/session0. Owned Docker UID1000 stat에서 workspace0755 root·dist0700 root/index PermissionError, api.py0644 읽기 가능 | 공통 unpack의 파일만 정규화/umask0077 directory 권한 원인. 내부 artifact0755/private parent0700 유지+HTML profile 첫 UI gate 수정 중, 앱 사업 코드/HEAD0변경 |
| OBS-057 | 2026-10-10 검사 보고의 직접 native 보강 관측 Root 전달 | 정확한 native command history의 안전 marker/exit0에서 Python37·Node10·Vite 성공 직접 확인. Raw logs/prompts 복제/출력0 | OBS-049의 AI 보고를 직접 명령 근거로 보강. 실제 앱 DB/API/브라우저 업무 성공 증거는 아님 |
| OBS-058 | 2026-10-10 수정/검사 범위의 Root 전달 | 같은 HEAD 새 신뢰 build/새 명시 deploy 예정. 정확히 변하지 않은 revision 검사 재사용·필수 Core gate 유지 맥락/Workbench owner 문서 후보는 아직 새시범 reload/영향 검사 미수행 | 원래 succeeded IDs 보존, 불확실한 작업 자동 재실행 아님. 배포 succeeded를 사용 성공으로 바꾸지 않고 앱 고도화 범위 확대0 |
| OBS-059 | 2026-10-10 공통 권한/첫 UI 후보 동결의 소유 에이전트/Root 전달 | 최초 umask3FAIL→직접3PASS, 최종 영향50PASS/5.299초·Ruff/formatter/owner README format PASS. 8소스: 내부 public dir0755/private parent0700·immutable declared UI path/200HTML/nonempty bounded prefix/no redirect/global deadline | 앱 최종14SHA 불변. 과거 UI None receipt는 원identity/health-only 한계 유지·production receipt strict. 후보 통과를 현재app500 해결/실사용 성공으로 쓰지 않음 |
| OBS-060 | 2026-10-10 전용 서비스 반영/정책 영향의 Root 전달 | Idle 전용 Core/consumer/Workbench만 재시작 all active, 기존 결함 app runtime은500 유지. 동일 revision 검사 재사용/필수 Core gate 정책2PASS/19deselected·2.34초·Ruff PASS/Workbench reload | Public Workbench·기존 dev Core 설정·운영 변경0. 원래 deploy succeeded 이력 보존, 새 app runtime 반영/브라우저 재인수는 아직 없음 |
| OBS-061 | 2026-10-10 실제 새 명시 재인수 계획 Task의 Root 전달 | Bound Taskf7557c90…POST200/message200·read-only plan. 자연스러운 업무 언어로 첫 UI 공통 수정/같은 source 로컬 검사 재사용/기존 결함 artifact 재사용 금지/새 platform build 요청 | 실제 fresh build/deploy/업무 흐름은 pending. Root 지원 paired pilot 한정, 완전 비개발자 자가 서비스/온보딩 완료는 아님 |
| OBS-062 | 2026-10-10 새 명시 작업 실행/신뢰 build·deploy의 Root 전달 | Taskf7557c90…native 계획v1/저장 승인revision6 실제 실행 완료. Fresh build98a54fd1-5bf5-5ea2-8f91-38647b8c5a4b succeeded/releasecbc22ef4-f990-4100-8820-9c959cd6075d/deploy66c29a00-cf8e-534b-983a-522ca13f7687 succeeded·installready generation4 | Source e3fcab9d…불변·로컬 앱 검사 재실행0·기존 결함 artifact 재사용0. 최초 succeeded/500 이력 보존, 업무 사용 인수와 분리 |
| OBS-063 | 2026-10-10 실제 새 runtime 첫 화면/초기 API의 Root 전달 | Dist/assets0755·index0644 UID1000 읽기 가능/rootHTTP200. 실제 native 포털 iframe SDK /api/config·/api/session/exchange·/api/me·/api/equipment 모두200 | IMP-014 fresh artifact/첫 화면 장애 범위 해결. 업무 데이터 쓰기0·대표 업무/전체 인증·권한·데이터 지속성 브라우저 인수는 pending |
| OBS-064 | 2026-10-10 최초 업무 묶음 관측 도구 중단의 Root 전달 | 정상 WB 로그인200/native cookie 있음·Core bootstrap200/account 조건 확인 뒤 normal_login의 selector unique FALSE로 종료. Core 로그인 dispatch0·앱 HTTP0·업무 쓰기0·미확인 작업0 | Bootstrap 뒤 DOM 대기 전 count한 관측 race 의심. 제품 장애로 분류하지 않음. 원 ledger/receipt 보존, 정확한 앱 실행 전 조건 확인 후 별도 재개 준비 |
| OBS-065 | 2026-10-10 RESUMED 관측의 Root 전달 | 정상 WB/Core 로그인 각각200, generic iframe count1이나 exact app iframe origin FALSE로 종료. 인증 작업2개만 확인·미확인 작업0·native 앱 launch/exchange0·업무 쓰기0 | 포털의 다른 공식 widget iframe을 고른 관측 selector 오류 의심. 제품 장애/업무 반복 검사 PASS가 아님. 두 실패 기록 보존, 정확한 앱 origin 선택·실행 전 조건 확인 후 별도 FINAL 묶음 준비 |
| OBS-066 | 2026-10-10 fresh release 저장 근거의 Root 읽기 전용 전달 | 16flagsTRUE·current verification TRUE/source e3/definition digest·immutable image pair 일치/gen4/runtime UI path '/'가 manifest와 일치. resource_limits/profile/test/build/package5Coregate exit0 | Source/archive bytes 불변·sourcearchivebc45fd8a…/newartifact855e2fd8…/builderprofile9eaf93e0…. 과거 artifact/profile과 다르고 old receipt의 UI admission path 없음/health-only 한계 유지. Live UI/업무DB/auth proof와 별도 |
| OBS-067 | 2026-10-10 최종 실제 대표 업무1회의 Root 전달 | EQUIPMENT_ACCEPTANCE_BUSINESS 결과 passed_with_unverified_secondary_account/43TRUE·secondary2NULL·미확인 작업0/차단된 쓰기0. 가상1등록201·중복409/version 불변·대여200/검색·반납200/이력·포털 reload 저장 물품/이력 | 실제 업무는1회. 앞선 관측 도구 중단 총3회는 업무POST0·ledger 불변이며 성공수에 더하지 않음. 앱 HEAD clean/Root/에이전트 사업 코드 쓰기0 |
| OBS-068 | 2026-10-10 동시/재요청·보관 상태의 실제 Root 전달 | 동시2대여200+409/승자1명, 원래 반납의 동일 ID replay200이 현재 새 대여 보존, 두 번째 반납200, 보관 종료/복원200·이력 보존 | Prepared 기록과 committed 이력의 구분 유지. 물품 삭제는 실행하지 않았고 개별 수정/삭제 CRUD 전체는 미검증 |
| OBS-069 | 2026-10-10 실제 인증/호스트 경계의 Root 전달 | 미로그인401·portal bearer 앱401·app bearer 임의 존재하지 않는 설치401. localhost WB native cookie는127 앱 미전달/알려진 bearer HTTP URL 부재TRUE | 기존 administrator 개발 로그인을 사용했고 대리급 비개발자는 역할 시뮬레이션. 가상 직원은 payload이며 employee auth 아님. 별도 정상 계정 same-install403/일반 직원 자가 등록 미검증·계정/권한/메일 변경0 |
| OBS-070 | 2026-10-10 정확한 새 PostgreSQL 읽기 전용 Root 전달 | 12PASS: RLS enabled/forced·gateway actor 없는 조회0/임의 foreign actor0·ownerexact6records·bounded role·crossDB connect deny·PUBLIC connect 없음·원본 marker1/migrations2. 물리 equipment1/equipment_history5(동시 실패 prepared1 포함) | UI committed 이력4와 물리 prepared 합계는 다름. Payload 공개0·DB쓰기/정리0, committed 재조회 확인 결과는 대기. 모든 직원/공격/운영 검사를 뜻하지 않음 |
| OBS-071 | 2026-10-10 5분 세션 만료·복구의 Root 전달 | 고정5분 앱 세션 만료/SDK expiry cleanup 뒤 Connect 정상 재연결→exchange/me/equipment200·업무 데이터 쓰기0 | 의도된 TTL 동작. 자동 갱신/입력 상태 유지는 미구현 후속 UX이며 TTL 확대/SDK·앱 사업 코드 변경0 |
| OBS-072 | 2026-10-10 host 계획과 bound SDK 격리의 Root 읽기 검토 전달 | Unbound host read-only 계획은 host private 파일 읽기를 물리적으로 차단하지 않는 single-owner trusted native client. Bound SDK만 blank home/private network/source-only 경계 | 현재 즉시 Core gate 결함/SDK 누출 발견0이나 침투 테스트 아님. 다중 사용자 전에 필요한 별도 격리 설계 DEF-002, 전체 skills 차단을 파일 기밀성 증거로 쓰지 않음 |
| OBS-073 | 2026-10-10 최종 GUI 이력 읽기 확인의 Root 전달 | 원 브라우저의 정상 SDK reconnect200·목록/detail/history GET200. Committed UI 이력은 대여2+반납2=4, 물리 history5 중 동시 패배 prepared1은 UI 미노출 | EQUIPMENT_FINAL_UI_HISTORY의 읽기 근거. 업무 인수 tool의 확인된9business attempts 외 Root 업무 쓰기0. 총3관측 중단+업무1회 체인은 각 unknown0. 운영자 지원 단일 소유자 시범 필수 인수 잔여0 |

## 후속 관측 기록 형식

새 관측마다 다음 항목을 채우되, 실제 수행하지 않은 칸은 `미실행/미관측`으로 남긴다.

| 항목 | 기록 내용 |
| --- | --- |
| ID/시각/단계 | OBS 번호, 실제 관측 시각, 계획 단계 |
| 비개발자 요구·답변 | 업무 요약과 실제 확인한 결정 |
| 현재 대상 | 새 시범 앱/개발 설치/소스 연결의 일치 여부. credentials·로컬 민감 경로 제외 |
| 실제 행동 | UI에서 선택/실행한 기능과 적용 범위 |
| native 결과 | 도구 호출 여부·종료 상태·안전한 공개 오류 분류·변경 범위 |
| LLM 설명 | 주장한 완료/질문/추정을 요약 |
| 독립 적용 관측 | 실제 코드/화면/등록/설치/업무 상태를 확인했는지와 boolean/집계 |
| 결과 | 통과/실패/blocked/unknown 및 근거 범위 |
| 불일치·후속 | 설명과 실제 결과의 차이, 필요한 최소 확인, IMP 번호 |

## 묶음 검증 결과 자리

| 확인 범위 | 결과 | 남은 한계 |
| --- | --- | --- |
| 실제 프로젝트/Task·native 계획 | 주 앱의 계획/승인 이후 별도 probe에서 업무명/요구만으로 project/Task200·기본 source form 유효도 확인 | 최초 required 실패 보존. Probe는 idle/unbound/messages0/source prepare0 |
| 실제 앱 소스·native 개발 | Clean checkpoint·candidate37/10/Vite 직접 native marker/exit0·Root 사업 쓰기0 | Static render는 보고 범위. 실제 대표 업무는 아래별도1회, 모든 앱 기능 완성이 아님 |
| 실제 등록·iframe/SDK 연결 | Matching receipt·fresh release16TRUE/Core5gate exit0·gen4 runtime·실제 iframe SDK/API200·정상 재연결 | 최초500/old health-only admission 보존. 완전 비개발자 자가 배포 private grant/target 공백 |
| 물품 CRUD·대여·반납·이력 | 실제1회 등록/검색/대여/반납·reload 저장 상태/이력·보관 종료/복원 확인 | 전체 개별 편집/삭제·별도 보관 위치 필드·전체 자연어앱 E2E 미검증/미구현 |
| 권한·중복 대여·반복 반납 | 중복 등록409/version 유지·동시 대여1승자·원래 반납 replay/현재 새 대여 유지·3종401/쿠키 host 경계 확인 | 정상 별도 계정 same-install403 검사2NULL·실제 nonadmin 자가 등록 미검증 |
| 실제 새 PG/최종 GUI | Read-only12PASS·RLS/role/actor/crossDB/PUBLIC 경계·physical equipment1/history5·GUI committed4/패배 prepared1 미노출 GET200 | Prepared 기록 정리0·hostile attack/다중 사용자/운영 미검증 |

결과의 원본은 각 실제 실행의 적용 근거다. 도구 설명·UI 링크·등록 receipt만으로 업무 기능이나 배포 성공을 확정하지 않는다.
