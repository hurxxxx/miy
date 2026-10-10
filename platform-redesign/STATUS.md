# 현재 진행 상태

**2026-10-10 필수 구조 구현과 서비스 반영을 진행 중이다.** 개발 first-party 구조는 반영했고 웹 소유 경계 보완을 PR103/MR111로 정상 병합했다. 최신 full285는 API·웹 단계를 통과한 뒤 Workbench backend78 FAIL/1082 PASS로 실패했다. CI의 공개 소스 권한 준비를 GitLab native clone·두 단계 umask022로 보완하며 제품의 엄격한 검사는 유지한다. 운영·Workbench 새 배포는 아직 없고 앱별 상세 기능·고도화는 보류한다.

기록 기준: 2026-10-10 UTC. 작업별 상태는 [WORK_ITEMS.md](WORK_ITEMS.md)가 소유한다.

## 최신 전달 상태와 필수 잔여

- 현재 통합 기준은 dev `4c8b5190`, GitHub main `f6363323`, 동일 tree `8dd50b3e`다. Source `13d6711a`의 required284/job452는 SUCCESS63.086425초/MERGE_READY이며 PR103/MR111 정상 병합과 소유 원격·로컬 branch 정리를 완료했다.
- Full285/job453은 FAILED4750.924746초다. API fast6572 PASS/5 SKIP/0 FAIL·slow16·migration37·external15 PASS, 웹928 PASS 및 두 UI build·browser chain 완료를 확인했다. Workbench backend78 FAIL/1082 PASS이며 이후 Workbench frontend build/E2E는 완료 근거가 없다.
- CI 공개 입력의 쓰기 권한을 바로잡기 위해 release job에 새 clone, checkout 전 native hook의 `umask 022`, main script 첫 `umask 022`만 적용한다. 검증 이미지·의존성·제품 pin/SDK 권한·required review/full gates는 유지하고 별도 chmod 하네스나 Runner 전역 변경은 추가하지 않는다. 실패 job의 실제 파일 metadata는 관측하지 못했으며 격리 재현과 새 CI 성공을 구분한다.
- 동일 CI 이미지의 frozen Console 환경에서 공개 소스 권한 문제를78 FAIL/229 PASS로 재현했고 정상 권한 조건의 같은6파일은307 PASS다. 실제 서비스·모델 실행 없이 실패 경계를 확인했으며 새 전체 CI 성공은 별도로 필요하다.
- 새 후보의 영향 검사를 묶어 확인하고 정상 리뷰·게시/병합·전체 release CI를 진행한다. 이미 통과한 API/웹과 변경 없는 산출물 근거를 로컬에서 반복하지 않는다. 실패한285/283/281과 canceled277은 성공으로 표시하지 않는다.
- 실제 운영9cbf9c5c/image389d·Workbench0c1bf0fe는 유지한다. 최신 전체 성공 뒤 release merge·fresh backup·운영 세 이미지/여섯 서비스·별도 Workbench 세 역할/두 링크·공개 인수를 진행한다. 기존 HTTPS 앞단은 유지하고 Core local gateway가 기존 공개 포트를 인계한다.

## 이전 전달 상태 — full283 시점

- 현재 통합 기준은 dev `c47441d5`, GitHub main `9f8bddd0`, 동일 tree `d7e4de6f`다. API fixture source `dcdf1d5f`의 required282/job450은 SUCCESS54.711084초/MERGE_READY이며 PR102/MR110을 정상 병합하고 소유 원격/로컬 feature·snapshot 브랜치를 정리했다. Protected dev/main은 보존한다.
- Full283/job451은 FAILED3553.621591초다. API fast6572 PASS/0 FAIL/5 SKIP(3005.47초), slow16·migration37·external15 PASS다. 후속 `web:lint`에서 기존 구조 fixture의 browser global1개·빈 함수2개가 실패했다. 해당 두 파일의 표현을 고쳤으며 제품 동작·assertion·lint 규칙·CI/하네스는 유지한다. 이후 web Vitest·두 UI build·E2E와 Workbench는 이 실행의 성공 근거로 쓰지 않는다.
- 미실행 웹 단계를 한 묶음으로 확인해 두 UI 빌드와 브라우저45 PASS를 얻었다. 웹 단위검사는922 PASS/6 FAIL로, 포털이 공식 UI·상세 탐색·Bento background를 실행한다고 기대한 세 fixture였다. 기존 공식 양성 검증을 실제 공식 registry에 보존하고 영향46 PASS를 확인했다. 통과한 API/공통 검사·빌드·브라우저·Workbench의 변경 없는 artifact 근거를 재사용하며 새 source의 필수 리뷰·정상 병합·전체 release CI를 진행한다. 실패한 full281/283과 canceled277은 성공으로 해석하지 않는다.
- 개발 서비스는 06:02UTC에 소유 임시 restart 보류 drop-in만 제거해 `Restart=always`를 복원했다. 서비스 재시작 없이 Main PID가 유지됐으며 정상 Main-only 종료·SIGKILL 금지·warm grace 정책은 보존했다.
- 최신 full CI 이후 Workbench의 세 역할/두 release 링크·fresh SQLite backup·공개 UI 인수, 운영의 정상 release merge·fresh DB backup·세 이미지/여섯 서비스 전환·공개 인수를 완료한다. Workbench 재사용 artifact는 실제 source37ef44ec/digest2ae5a15b 그대로다. 현재 Workbench0c1bf0fe와 운영9cbf9c5c/image389d는 유지한다.

## 구현 후보와 이전 전달 기록

공식 API/worker, 개인 앱 승격 계약, Workbench의 격리 SDK 실행 후보를 통합·리뷰·병합했다. 영향 검사·실제 격리 실행·공통 gateway/배포 도구와 대표 브라우저 검사를 마쳤다. 최신 full CI·후속 fixture 리뷰·새 플랫폼/Workbench 배포와 실제 로그인 인수는 남아 있다. 현재 로컬 결과는 [통합 검사 기록](VALIDATION.md#2026-10-10-필수-구조-통합-검사)이 소유한다.

Python fixture source `61f842c8`의 required276/job444는 SUCCESS33.343359초/MERGE_READY이며 PR99/MR107을 정상 병합했다. Dev `cbde1423`·GitHub `764a5e8c`의 tree555596a5가 같다. 소유 원격/로컬 브랜치를 정리하고 protected dev/main을 보존했다.

개발 서버는 Root가 기존 native worker와 prefork의 warm 완료를 확인한 뒤 API·UI·Beat를 종료했다. 옛 Vite의 상대 경로 실행은 현재 ownership matcher와 달라 Root가 원래 unit·UID·cwd·entry·start ticks를 재확인하고 해당 PID에만 정상 TERM을 보냈다. 강제 종료·큐 purge/revoke/copy/reissue는 없다. 단일 legacy witness를 통한 **publisher-off native exact drain PASS** 후 first-party selection, platform/official worker 각1개·Beat1개를 실제 확인했고 witness는 success/inactive 및 cgroup empty다. 원 unit 백업과 Main-only/no-SIGKILL/unbounded-grace policy를 보존한다.

실제 개발 연결에서 공식 API가 기존 `MIY_DEV_API_HOST`의172.17.0.1로 bind되지만 Vite 공식 API target은127.0.0.1로 고정된 계약 불일치를 발견했다. 이는 앱별 기능과 무관한 필수 구조 경계다. 기존 host 계약을 그대로 쓰도록 보완했고 공개 공식 API500→401 및 정상 개발 로그인·공통 인증 WS·전사 빈 인증 WS 거부 경계를 확인했다. 알려진 불일치가 있는 source의 full277/job445에는 취소를 요청했다. 이 취소를 성공으로 해석하지 않으며 수정 source의 새 필수 리뷰·최신 full release CI는 운영 배포 전에 유지한다.

Workbench의37ef44ec 실제 산출물은 b4fdccb2→cbde1423의 두 fixture/4개 계획 문서가329소비 입력과 비중첩임을 확인해 재사용한다. 전체 hash/build/model/검사 재실행은 없다. Workbench 서비스는0c1bf0fe·운영 main/prod는9cbf9c5c/image389d로 유지되며 별도 서비스 교체·SQLite/운영 DB fresh backup·공개 인수가 남아 있다. 이전 실패와 전달 이력은 아래에 보존한다.

필수 개발 proxy 보완은 기존 strict `developmentListenerUrl`을 순수 공통 모듈과 타입 선언으로 추출하고 `MIY_DEV_API_HOST`+고정18781을 사용하는 최소 변경이다. 기존 UAT public export·공통 proxy 설정·generated patterns·WS/query/timeouts·공식 slice selector는 유지한다. 실제 두 Vite factory의 server/preview host8·invalid5 검사와 기존 listener 검사, runtime helper/type declaration 변경의 full-release 판정은 통과했다. 최초 fixture의 부수 loader metadata assertion 실패는 실제 dependency guard 검사가 대체했으며 해당 실패 사례만 재검증했다.

수정 소스를 고정한 뒤 실제 `https://dev.1punicorn.com`에서 전사 Docs hub는500→JSON401, 정상 native 개발 관리자 로그인은200, 공통 WebSocket 정상 auth/빈 auth1008, 전사 Docs WebSocket 빈 auth4401을 확인했다. 양쪽 health/ready와공식 pairing metadata도 정상이다. 새 문서·Task·모델 turn·편집은 없고 auth secrets/응답/데이터를 저장·출력하지 않았다. 개발은live Vite 모듈·null buildID·runtime_revision unmanaged이므로 운영 immutable build guard 통과로 표시하지 않는다. 기존 disposable 공식 문서를 사용한 Yjs 양성 room/Source ACL 인수는 미검증이며 앱별 상세 기능으로 확장하지 않는다.

외부 TLS 설정을 찾거나 변경할 필요가 없다. 운영에서는 Core gateway가 기존 공개 포트를 인계하며 generated HTTP/WS owner map으로 공통 API18779·공식 API18780에 연결한다. 개발은 기존 Core Vite4200·공식 Vite4201와 두 API를 유지한다.

- 공식 서비스는 기존 서버 auth/ACL·공통 PostgreSQL·안전한 트랜잭션을 재사용하는 명시적인 first-party process 경로다. 이전 비활성 Source-only artifact를 플래그로 열지 않는다. 별도 공식 wheel/artifact·소유 queue·단일 Beat와 generated ingress owner map을 구현했다. 기존 큐와 예약/실행 작업을 확인하고 구형 writer를 종료하는 cutover 및 공식 UI 독립 산출물 연결은 진행 중이다.
- 개인 앱은 같은 control-plane 등록 DB에 있는 성공한 개발 설치의 불변 산출물을 Core 관리자가 운영 installation으로 승격한다. 개발 증거를 운영 증거로 바꾸지 않으며 실제 runtime 관측 전에는 첫 운영 설치를 활성화하지 않는다. 서버 개발 preview도 선택적인 별도 HTTPS 출처·loopback 포트 연결을 지원한다. 설치별 build/state·데이터 분리와 기존 dev-only 위임을 유지한다. 다른 플랫폼 DB 사이의 증거 전송은 ENH-010으로 보류한다.
- Workbench의 기존 단일 소유자 SQLite·native Codex Task/이력/중단·재개를 유지하고 SDK capability/permission UI·캐시 pin·지속 개발용 격리 service 예제를 연결했다. 변경되지 않은 검증 근거 재사용과 최종 묶음 검사를 기본 테스트/리뷰 템플릿에 반영했다. 새 실제 정상 controller 실행은 1회로 제한하고 기존 Task·유실 claim을 재실행하지 않는다.
- 운영 first-party는 Core의 로컬 NGINX gateway가 기존 공개 포트를 받고 공통 API18779·공식 API18780로 전달한다. 외부 TLS 경로를 수동 변경해야 했던 초안을 대체하며 세 이미지·여섯 서비스와 복구를 guarded release에 연결한다. 개인 앱의 별도 HTTPS 설정 예제는 자동 활성화하지 않는다. 실제 서비스 반영은 공개 인수까지 확인해야 완료로 집계한다.

사용자 지시로 이번 범위를 [필수 구조 변경](PLAN.md#이번-범위)에 한정하고 고도화는 [별도 후속 문서](FOLLOW_UP_ENHANCEMENTS.md)로 분리했다. 공통 등록·네 영역 독립 변경/배포·최소 Codex/개인 앱 연결·권한/데이터 보존과 대표 흐름 확인만 완료 조건으로 남긴다. 고급 UX/모니터링·반복 평가·부하 측정·복잡 저장 프로토콜 확장은 인수 의존성에서 제외한다. 이미 구현·검증·배포한 결과는 보존하며 실제 전달은 [게시 체크포인트](PUBLICATION_CHECKPOINT.md)가 소유한다.

**이전 중단 기록:** 사용자 요청으로 2026-10-10 중간 점검에서 중단했으며, 이후 “계획대로 진행” 지시로 재개했다. 아래 날짜별 기록은 보존 이력이다.

## 현재 위치

현재 C2 journal/adapter·Files 확장 후보는 보존하되 모두 자동 필수로 취급하지 않는다. 최소 구조와 안전성을 기존 경로로 확보할 수 있는지 판단하고, 실제 분리 장애·치명적 결함의 최소 부분만 채택한다. 아래 후보별 과거 미완료 목록은 채택 여부에 따라 적용하며 미채택 고도화의 리뷰·통합·활성화를 진행하지 않는다.

- **전달·운영:** PR96/MR103 필수264/432 성공·정상 병합·소유 feature 정리, full265/433 성공, MR81 정상 병합·prod FF·guarded 배포를 완료했다. Dev `c40e7091`, main/prod `9cbf9c5c`, 같은 tree `64e456b4`다. 운영 API·worker·Beat는 새 image `389d1e67…`로 healthy, DB는 `wb_checked_cas_20261009`이며 공개 smoke를 확인했다. 이전 이미지·env·fresh DB 백업을 보존한다. 세부 전달은 [PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md)가 소유한다.
- **개발:** C1 head/API/Vite·로그인/공개 앱 smoke와 AppRoot 공식 앱 import HTTP200을 이미 확인했다. c40은 후속 fixture·문서 변경으로 제품 source가09aaf와 같아 반복 재시작하지 않았다. 사용자 PC·앱별 상세 기능은 보류한다.
- **Workbench:** 원 Task의 계획·구현2턴과 같은 thread의 read-only3번째 인수는 완료했고 추가 턴을 만들지 않았다. 이전 cache timeout·준비 포트 충돌·exclusive 결과 파일 충돌은 보존 이력이다. 재개 후 현재 정상 controller는 모델1회·고정8경로·자동 retry0와 소유 RPC/unit/process/port 정리, Source/Git/native/cache 불변을 실제 확인했다. Backend426/UI56 등 직접 영향 검사는 통과했다. clean37ef 실제 릴리스 산출물의 source/digest·schema0008·고정 CLI를 확인했으며 기존 current/template-current는0c1bf0fe다. 새 후보의 필수 리뷰·별도 서비스 교체·fresh SQLite online backup·정상 공개 로그인/Apps/기존 Task/permissions/AgentTree 인수는 남아 있다. 새 Task·모델 실행과 임의 native unknown 회복은 추가하지 않는다.
- **저장·전환 후보:** C1 checked-save source/schema는 반영했지만 새 factory/role은 비활성이다. C2 provenance·journal·native completeness/cleanup의 이전 근거를 보존한다. 확장 journal35/checkpoint source25f14b24의 실제96 PASS(509.356302초, 오류/skip0·소유 정리/전후 guards)와 별도 비활성 adapter의 합성56 PASS 수정본은 미게시 후보다. 전체 연결·독립 리뷰·native isolation/운영 활성화는 완료하지 않았으며 verifier 부재는 fail-closed다. 이번에는 전체 C2 완성을 기본 필수에서 제외하고 ENH-005로 보류한다. 실제 분리·유실 방지에 필요한 최소 부분만 채택하며 서비스 전환의 권한·구형 writer 정리·데이터 보존·복구는 유지한다.
- **저장 공간·범위:** Docker 실제 경로 `/var/lib/miy-docker-data`와 canonical `/var/lib/docker` bind로 이전했다. 마지막 확인은 root117GiB/약40GiB 여유다. 이전 시 컨테이너83/볼륨286/이미지18 보존·실행29 복구를 확인했다. OS 재부팅은 미검증이고 미확인 orphan220개는 보존한다. 앱별 비필수 기능·다중 사용자·기존 skills/하네스 절차 재사용은 보류한다.

## 이전 단계별 인수 기록

- **최신 로컬 구조 인수:** Docs·Whiteboard의 준비된 WS 조립은 pure16·실제 PostgreSQL/native WS30으로 새46개를 인수했고, 기존 HTTP44·composition10의 영향54개도 통과했다. 시간은 ws_pure: 5.33s, ws_native: 56.40s, ws_compat: 40.57s다. 실제 Source 편집 공유를 read로 회수한4개 recv/send 검사와 current auth·writer fence·private503/1013·제한 reader 취소/permit 경계를 확인했다. 초기 pure13 PASS/3 FAIL은 공개 WebSocket 생성자 fixture를 수정한 동일 선택의 전후 결과이며 고유 성공 수에 합산하지 않는다. 제품 조립 전 Source trap 관측 red1도 보존한다. 첫 계약 검사의 domain→composition-root 역방향 import는 공용 WS 어댑터를 도메인 소유 모듈로 옮겨 수정했다. 그 구조 변경 뒤 영향을 받는 pure/native/HTTP 검사를 재실행한 현재 결과이며 전후 실행을 합산하지 않는다. API architecture/i18n와 생성 API/독립 앱/OpenAPI/contract source 검사를 통과했다. Business Source는 권한 있는 합성 fixture이며 최소 Source operational 역할·전체 Source worker 취소를 인수한 것이 아니다. 14표/87열·기본 인증·비활성 ASGI·hub/codec/room·운영 role/grant를 보존했다. 아직 별도 로컬 미커밋이며 최종 독립 인수·필수 리뷰·정상 게시/병합은 남아 있다.

- **Workbench native 선행조건:** Workbench의 정확 Codex0.160.1은 표준 systemd-socket-proxyd ingress와 owned transient supervisor 안에서 기존 executor_probe로 실제 인증 없는 연결 거부·정확 버전/cwd·native readOnly/workspaceWrite·자식 명령·Git 쓰기 거부·host canary 비노출을 통과했다. Native와 proxy는 같은 private network namespace의 loopback만 사용했고 caller namespace와 달랐다. 실제 kernel 한도는 CPU1·메모리1GiB·swap0·PIDs64, UID1000·capability0·no-new-privileges이며 endpoint와3개 owned unit/process/cgroup 정리도 통과했다. 앞선 합성 ingress37bytes·자원 fork 한도 검사는 각각 별도 선행조건이다. 같은 pin의 공개 JSON schema440개로 기존0.159.2 소비 계약과 별도0.160.1 remote 계약의 호환을 확인했다. 현재 설치된 CLI/템플릿/서비스·설정은 변경하지 않았다. 구독 인증을 사용하는 실제 제품 Task의 계획 승인→수정→같은 thread 재개/history·중단/단절과 재사용 가능한 운영 설정 적용은 남아 있다. Remote app mount에는 인증을 복사하지 않는다. 기존 secured API·Runtime·SQLite·Codex 수명을 재사용한다.

- **현재 전달과 구조 작업:** 공식 auth HTTP `782b9844`는 필수226/394 SUCCESS/177.379623초 뒤 GitHub PR79의 `cf06470b`, 내부 MR86의 `77abc792`로 정상 병합했다. 두 merge tree는 `ecb4ab56c53ea5740fe6475cf201d3ddbddfba70`로 같으며 소유 feature 브랜치를 양쪽 원격·로컬에서 정리했다. Persistent dev/main과 upstream push 차단은 유지했다. 최신 전체227/395는19.517891초에 저장 공간 검사에서 실패해 제품 테스트0이다. 잠깐의15.0GiB floor 통과는 실행 준비 뒤의 지속 여유를 보증하지 않는다. 스토리지 여유 확보와 정확한 최신 source/target/tree 전체 CI가 운영 전달의 필수 선행조건이며 main/prod는 `9e9280df`다. 새 운영 배포는 없다. 다음 OFF-002B 작업은 `77abc792` 기반 별도 worktree의 Docs·Whiteboard WS 인증 조립이다. 기존 제한 auth callable/budget와 public HTTPConnection/Yjs authorize callback을 재사용하고 고정 route scope로 접속·주기·각 recv/send의 current auth→Source ACL/writer fence 순서를 연결한다. Default·비활성 ASGI·14표/87열·room/codec/hub·운영 role/grant를 보존한다. 이 구현은 아직 별도 로컬 작업이며 최소 Source service 역할·검색/AI approval/audit·공식 cutover·네 영역 전체 인수는 남아 있다.

- **최신 저장 공간 선행조건:** 현재 dev는 `77abc792`, main/prod는 `9e9280df`다. PR79/MR86은 리뷰226/394 뒤 병합·소유 feature 브랜치 정리를 마쳤다. 전체227/395는 저장 공간 검사 실패로 제품 테스트0이다. 16:06의 일시적인15.0GiB 통과 뒤 다시 실패했으므로 지속 headroom과 최신 source/target/tree의 정상 full CI가 필요하다. 기준을 낮추지 않으며 새 운영 배포는 없다.

- **이전 전달 기록 — pipeline225:** fixture 두 파일 수정 `d43a46aa`는 필수 리뷰224/392 SUCCESS 후 GitHub PR78의 `cdfa602e`, 내부 MR85의 `ad42d0bc`로 정상 병합했다. 양쪽 tree는 `af422c706c5abe34d92596044a392fabf6ca114b`로 같으며 소유 브랜치만 원격·로컬에서 정리했다. MR81의 전체225/393은18.494초에 저장 공간 검사에서 실패해 제품 테스트를 실행하지 않았다. 최소15GiB와15% 기준은 유지한다. 과거 검증 이미지 두 개는 전체25개 layer/config와 archive hash를 확인해 별도 임시 디스크에 보존한 후, 정확한 미사용 image/cache ID만 정리했다. 과거 scratch와 보존 Git/source backup도 byte·mode·link를 검증해 원래 경로의 연결을 유지했다. 실제 여유 공간은 아직15GiB 미만이며 스토리지 확보 후 필수 전체 CI를 재실행해야 한다. main/prod는 `9e9280df`이고15:45의 실제 API·worker·Beat와 schema 검사는 정상이다. MR81 병합·fresh backup·guarded 운영 배포는 미완료다.

- **이전 구조 P0 기록 — HTTP 로컬 검증:** `ad42d0bc` 기반 별도 worktree에서 공식 auth-only HTTP의 현재 로컬 검증은 pure31 PASS/8.60초, 실제 PostgreSQL·HTTP13 PASS/27.42초, 기존 composition10 PASS/10.75초다. 서로 다른 선택31+13은 새44개이고 기존10개는 별도 영향 범위다. Raw·반복 host cancellation와 AnyIO 대기/실행 취소에서 worker 종료·Session 정리 전 admission을 반환하지 않는 경계를 확인했다. 네 HTTP GET은 genuine 현재 앱 세션/binding·제한된 auth PostgreSQL 역할·실제 Source ACL을 사용했다. Business Source fixture는 권한 있는 합성 계정이므로 최소 Source operational 역할 전체 인수로 확대하지 않는다. Profile14표/87열과 기존 기본 인증·비활성 ASGI를 유지했고 API architecture/i18n·independent app schema/OpenAPI/contract source --check를 통과했다. Operational role/grant·WS·공식 서비스 전환은 아직 하지 않았다. 정확한 Codex0.160.1의 offline native 선행검사에서는 read-only·workspace-write 두 정책을 실제 실행했다. 앱 쓰기 허용/거부·Git/형제 경로 쓰기 차단과 소유 자원 정리를 확인했다. 단독 읽기 전용 재검증은 같은 두 범위 안의 반복이며 추가 고유 성공으로 합산하지 않는다. 기존 live CLI/settings/service는 변경하지 않았다. 이는 현재 도구 환경의 native primitive 검증이며 제품 executor·WS ingress·CPU/memory/PID 강제 한도·실제 인증 turn/resume/history를 대신하지 않는다. 독립 최종 리뷰·게시와 전체 릴리스는 별도 단계다. 전달용 dev/prod는 그대로다.

- **이전 릴리스 위치 — pipeline223:** 새 fixture source `1d8cf66e`의 필수 리뷰222/390 SUCCESS 뒤 PR77은 `b12a4acc`, 내부 MR84는 `c401dd1a`로 정상 병합했다. 두 tree가 같고 작업 브랜치만 원격·로컬에서 정리했다. MR81의 후속 전체223/391은1,903.144108초에 실패했다. API fast5,556 PASS/1 FAIL/3 SKIP이며 slow16·migration37·external15는 각각 통과했다. 실패는 실제 descriptor 잠금 대기 중 세션 회수를 재확인하는 테스트의 기대 사유다. 실제 사유는 `source_database_refused`, 기대는 `current_execution_denied`다. 해당 CI의 SQLSTATE는 없어 원인을 확정하지 않는다. 동일 CI 이미지의 단독1개는 통과했고 통제한 새 연결5.2초 지연에서는55P03을 관측했다. fixture 두 파일에서 observer/revoker를 worker 전에 연결하고 기존 timeout·정확 reason·권한·rollback assertions를 유지한다. 동일 이미지의 실제8조합과 기존 default helper2개는10 PASS/23.72초이며, 같은5.2초 지연 재검증도1 PASS/13.10초다. 두 실행 모두 원본 File·이벤트 없음·Core·권한 보존을 확인했다. 독립 코드 리뷰 blocker0이며 새 source 게시·필수 리뷰·전체 CI와 운영 배포는 대기 중이다. main/prod는 `9e9280df`이며14:25의 API·worker·Beat 정상과 clean main 체크아웃을 확인했다. 공식 operational 전환·실제 native turn·네 영역 전체 인수는 여전히 미완료다.

- **이전 릴리스 기록 — pipeline220:** CI/native fixture와 Docker 임시 데이터 정리 보완은
  필수 리뷰217/383과 PR75/MR82 병합을 마쳤다. 후속 합성 로그 capture 수정은
  필수 리뷰219/387을 통과했고 [GitHub PR76](https://github.com/hurxxxx/miy/pull/76)은
  `a4c27760`, 내부 MR83은 `fd5038ba`로 병합했다. 소유한 작업 브랜치만
  원격·로컬에서 정리했고 영구 dev/main은 유지했다.
  [릴리스 MR81](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/81)의
  최신 pipeline220/job388은 source `fd5038ba`, target `9e9280df`에서
  FAILED/script_failure,2,096.498755초였다. API fast는 **5,557 PASS/
  3 SKIP/0 FAIL**이며 slow16·migration37·external15도 각각 통과했다.
  이후 웹 lint가 E2E 두 파일의 bare browser globals3개로 실패했으므로
  전체 릴리스 성공은 아니다. `window.innerWidth`2개·`window.location`1개로
  최소 fixture 수정을 마쳤다. scoped ESLint는3 errors/5 warnings에서
  0 errors/같은5 warnings로 통과했고 Prettier2·직접 E2E 타입·역변환 byte
  검사를 확인했다. 기존 assertion·동작은 유지한다. 수정 `96a0d7af`는
  PR77/MR84로 게시했고 필수 리뷰221/389를 통과했으나 아직 병합하지 않았다.
  공개 합성 snapshot의 Workbench Python은773 PASS/25 SKIP이며 등록 브라우저
  3개는 실제 metadata listener가 없는 fixture 때문에 Task 시작 전 차단됐다.
  실제 synthetic bearer를 검증하는 initialize-only loopback peer로 fixture
  한 파일을 보완했고 기존 readiness15·실제 등록 브라우저3 PASS를 확인했다.
  웹 첫 Hermes `page.evaluate` timeout은 같은 입력의 단독 재검증에서 통과했고
  전체 웹 브라우저 묶음도 단독42 PASS다. 새 source 리뷰·병합·전체 CI와
  운영 배포는 대기 중이다.
  이전218/386의 API capture3개 실패와 로컬 전체·역순188개 통과는 역사로
  구분한다. 제품 filter·권한·AGENTS·스킬과 기존 assertion은 유지한다.
  준비384/385의 저장소 기준 실패는 역사로 보존한다. 소유 비활성 build의
  exact8 cache 정리 후 실제 기준15.5GiB·15.4% 통과를 확인했다. 도구 보고
  6.102GB를 실제 추가 여유로 해석하지 않는다. 이 캐시 정리에서 image·
  container·volume·daemon은 변경하지 않았다.
  main/prod는 기존 `9e9280df`와 정상 artifact를 유지하며 운영 배포는 하지 않았다.
  Workbench187개 제품 경로는 배포 `0c1bf0fe`와 같아 추가 배포 대상이 아니다.
  official operational authority·서비스 전환, Workbench native turn과 개인 앱의
  전체 개발·배포 및 네 영역 구조 인수는 계속 필수 잔여다. 이전 실패·로컬
  검증의 정확 범위는 게시 체크포인트와 VALIDATION.md에 보존한다. 다음 P0의
  native 환경·실제 turn 인수 준비 문서는 읽기 전용 계획이며 실행 증거가 아니다.

- 앞선 구조 작업 경과: [GitHub PR70](https://github.com/hurxxxx/miy/pull/70)의
  Source 명령·관측과 공유 연결 검증 보완이다. 실제 merge 상태·시각·SHA는
  GitHub PR 기록이 원본이다. 초기 PR69의 main 병합·원격/로컬 작업 브랜치
  삭제와 dev 통합을 마쳤다. 이번 PR의 정확 commit·검증·정리 범위는
  [PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md)가 소유한다.
  병합 뒤 [고정 Source aggregate slice](FILES_SOURCE_AGGREGATE.md)의 private
  native root File soft-delete·동일 ID 관측과 필수 공유 연결 검증 보완을
  로컬 비활성 범위로 인수했다. 작성자41·실제 제한 PostgreSQL 고유30·기존
  Source 영향81개를 구분하고 독립 리뷰의 차단 결함0을 확인했다. 이 후속
  코드는 PR70으로 게시했으며 서비스는 변경하지 않았다. 전체 tree와
  publication hold/원자 apply는 계속 필수 구조 작업이다.
  PR70 이후 공식 인증 전용 최소 조회,
  private 폴더의 유한 변경, Workbench 작업 시작 전 연결·설정 확인을 병렬로
  구현·검증·독립 리뷰를 마쳤다. 각 하위 범위의 차단 결함은0이다.
  이 변경은 PR71로 커밋·게시·병합했고 개발 플랫폼과 별도 Workbench에 반영했다.
  개발 append migration과 Workbench 저장소 이전을 확인했으며 공식 서비스와
  새로운 operational reader/grant는 활성화하지 않았다. 운영 플랫폼은 내부
  필수 리뷰 계정의 Codex 재인증을 완료했다. 실제 리뷰의 P2인 개인 앱 HTTPS
  기본 포트 오류를 수정했으며 관련 검사42개와 API architecture 검사를 통과했다.
  후속 실제 리뷰에서 기존 색인의 결과 표식 전환과 재사용 Files hook의 scope
  상태를 보완했다. DB 복사본의 append20·기존 데이터·이전 이미지 호환 검증은
  통과했다. Files 수정본의 개발 반영도 확인했다. 후속 필수 리뷰는 개인 앱
  runtime의 CLI 출력·HTTP 전체 시간·Docker 로그 자원 한도를 추가 지적했으며
  필수 구조 계약으로 수정하고 고유77개와 구조·번역 검사를 확인했다.
  불완전한 release 관측이 active 앱 정리를 허용하는 경계도 닫았다.
  다음 실제 리뷰의 `up` 복원 증명과 worker 종료 유예를 보완해 관련116개와
  소유 syntax·format·diff 검사를 확인했다.
  `ddb29c31`의 개발 반영과 로그인·런처·worker/Beat를 확인했다. 후속 실제 리뷰의
  기존 projection 테스트 진입점·Files FK fixture를 현재 계약에 맞춰 로컬72개를
  확인했다. 제품 코드는 유지하며 native/client·PG 검증은 전체 CI가 소유한다.
  후속 `up`의 중지·비정상 상태 재기동 허용과 자동 복원 근거를 분리해 관련139개를
  확인했다. Source·fixture·나머지 운영 함수는 보존했다.
  pipeline213/job379는 인증 오류 없이 실제 리뷰를 마쳤으나 Bento의 같은 로그인
  화면 이동 시 큐에 남은 저장 유실 P2를 지적했다. 데이터 유실을 막되 로그인·
  credential 변경 뒤 오래된 쓰기 차단을 보존하는 최소 수정을 마쳤고 Bento22·
  실제 Provider10과 독립 검토 차단0을 확인했다. 영향 소비자19개·정상 타입4개·
  web architecture를 확인했고 새 필수 리뷰와 전체 릴리스 검증을 진행한다.
  새 필수 리뷰·전체 release_validation·
  실제 운영 반영을 이어간다.
  실제 SHA·반영 검사·잔여는 게시 체크포인트의 최신 결과가 소유한다.
  후속 우선순위와 이번 제한 범위는 [NEXT_STEPS.md](NEXT_STEPS.md)에 기록한다.
- 단계: **사용자 지시로 구현 재개**. 재시작 전 동결한 PMS 275개·Recording authority 108개·delivery 12개 입력이 모두 일치함을 확인했다. PMS 부모 통합과 Recording managed의 비활성 권한·전달·legacy 영향 검증 및 독립 리뷰를 마쳤다. 공식 UI 12/12개의 source/build 소유와 Files·Video Chat·공용 Chatbot을 포함한 최종 두 build·브라우저 통합을 마쳤다. 포털37·공식36개의 합성 브라우저와 selected dev6개, 입력1,823개 불변을 확인했다. 독립 서비스·릴리스·전체 portal 업무 정리는 별도 필수 범위다. [RESTART_CHECKPOINT.md](RESTART_CHECKPOINT.md)는 중단 시점의 역사적 근거이며 앱별 비필수 개선·상세 검증은 계속 보류한다.
- 완료: 문서 작업 `DOC-001`·`REV-001`·`DOC-002`, 기존 카탈로그 누락/표시 수정 `CAT-001`, 읽기 전용 관측 표시 `WB-004A`, 공식 앱 경계 조사 `OFF-001`.
- 진행 중: 정책 전환·평가(`POL-001`~`POL-003`), 새 앱 계약(`CAT-002`), 소스 연결·템플릿·세션 경험(`WB-001`·`WB-002`·`WB-003A`), 독립 앱 SDK·실행 환경·수용량·UI 시범 앱(`APP-001`·`ENV-001`·`ENV-002`·`APP-002A`), 로컬 배포·복구(`REL-001A`).
- 추가 진행 중: 설치·배포 관측과 자연어 배포 도구(`WB-003B`·`WB-004B`), 독립 DB·권한 시험 앱과 마이그레이션(`APP-002B`·`REL-001B`), 공식 묶음의 별도 UI 빌드(`OFF-002A`)와 API 인증·쓰기 경계(`OFF-002B`).
- 사용자 요청에 따라 멀티에이전트를 사용한다. Vite import 오류 수정과 실제 개발 주소 검증을 마쳤다. 공식 UI 열두 개의 전체 source/build 소유 이전, 원본 88개 guard, 고정 source outbox/Core receipt와 주요 외부 효과 경계를 로컬 검증했다. Planner 최종 조립, 구형 Docs 작업의 Core 변환과 Recording legacy 발행·재시도 보완도 검증했다. PMS 부모 독립 비교·두 build·브라우저 각 31개와 actual-dev 새 PMS 다섯 경로를 확인했다. 최종 선택 입력 1,734개 중 제품 등 1,733개와 owner 275개는 불변이며 후기 E2E 하나만 fixture 보완했다. 개발 서버의 기존 Meeting read-count fixture 실패 한 개는 APP-ISS-007로 사실을 보존했다. Recording managed의 동시 준비 경쟁과 검사 DB 복원 경계를 보완하고 현재 비활성 프로토콜의 권한·legacy 영향·독립 리뷰를 마쳤다. 실제 서비스·전달·운영 준비는 필수 잔여다. 실행별 범위·초기 실패·입력 해시와 한계는 [VALIDATION.md](VALIDATION.md)가 소유한다.
- Recording managed 로컬 비활성 인수: 제한 Source/Core 계정의 pipeline **37 PASS**, 최종 authority·이전 schema·원본88개·fixture **95 PASS / 입력785개**, 영향 legacy **125 PASS / 입력180개**, 실제 복원·실패 경계 **6 PASS**와 독립 읽기 리뷰 17개를 확인했다. 각 실행의 before==after·소유 자원 정리를 기록했으며 중복 검사 수를 합산하지 않는다. 초기 legacy 122 setup ERROR는 Core의 빈 COPY 거부로 남기고, 원자 복원·명시적 empty baseline으로 수정했다. 제품 권한·guard는 완화하지 않았다. 기본 HTTP는 legacy를 유지하고 official profile은 실행·발행을 거부한다.
- 위 PG 동결 뒤 UI 소유 경로를 생성해 현재 authority785에는 Core `app_contracts_generated.py`와 suite `ownership.json` 두 경로의 차이가 있다. legacy180에는 생성 Core metadata 한 경로만 달라졌다. 각각 UI management/source 소유 metadata 변경이며 API·원본 model88·worker·writer·SQL/roles/managed 프로토콜은 그대로다. 실행 당시 불변성과 현재 source 전체 동일성을 혼동하거나 후기 UI 변경을 앞선 PG 결과에 소급하지 않는다.
- 기존 하네스·스킬은 이번 작업 절차로 적용하지 않고 최소화 검토 대상으로 읽는다.
- Docs/PMS/회의의 준비된 Source-only 전달 경로와 로컬 영향 검증을 마쳤다. 실제 제한 계정의 원본·별도 Core transaction, 두 SHARE capability, 동일 event 복구와 발행 억제는 집중 PostgreSQL **70 PASS**다. 넓은 **343 PASS/4 fixture FAIL** 뒤 실패한 세 테스트 파일만 정정해 **102 PASS**, 최종 입력 **1,101개 불변**과 이전25 migration 보존을 확인했다. 제품·권한은 실패 교정 때 바꾸지 않았고 독립 검토의 bounded blocker는0이다. 전체 Source HTTP/auth/ACL/audit 또는 공식 서비스 활성화 완료는 아니다. 앞선 Recording의 UI metadata 차이 개수는 UI 통합 직후의 비교이며 이번 API 변경 뒤 현재 전체 소스 동일성을 뜻하지 않는다.
- 이전 원격 게시 기록: 사용자 긴급 백업 지시로 별도 비공개 GitHub 저장소에 snapshot을 보관했다. [EMERGENCY_BACKUP.md](EMERGENCY_BACKUP.md)가 해당 일회성 범위와 복구 위치를 소유한다. 원본 GitHub PR69 병합과 해당 작업 브랜치의 원격·로컬 삭제를 마쳤다. 영구 `dev`·`main`은 유지했다. 현재 Source 후속 PR은 최신 사용자 지시로 게시·병합·브랜치 정리한다. [PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md)가 게시 근거를 소유한다. 서비스·운영 배포는 포함하지 않는다.
- 현재 구현: Files F1~F3의 로컬 비활성 경계를 인수했다. F3는 Files-only Core pending/ready/delete 수락·최소 partition SHARE profile과 현재 SHA/partition/결과 표식에 의한 stale 검색 후보 차단이다. 최종 native189개와 기존 권한·migration·Recording·fixture 영향167개, 입력812/813개 불변 및 작성자와 분리한 리뷰를 확인했다. 검사 수는 중복되며 합산하지 않는다. F4의 Source runner 소유권 보완51개, retained UUID Core setup30개와 별도 Source descriptor capability47개·schema/role 영향173개 및 독립 검토를 마쳤다. 정렬 corpus→Files 잠금을 보완한 유한 workset34개와 version 고정 transport29개·실제 소유 MinIO를 확인했고, 기존 명령 영향51개·strict paired reader55개와 새 최소 SELECT profile의 실제34개 고유 검증 및 독립 리뷰를 마쳤다. 임시 테이블 shadow를 실제로 재현·수정했고 durable 색인 효과와 lifecycle 조립을 구현해 신규 controlled96개와 기존 generation/helper110개를 통과했다. append30의 실제 Data83·Source72·schema 영향175개와 최신 controlled102개를 구분해 로컬 비활성 인수를 마쳤고 독립 리뷰 blocker0을 확인했다. 세션 정리 취소의 ACK/unknown 왜곡도 수정했다. Source TEMP 인증 shadow·취소 결과 보존은 최신 실제81개·입력243개와 독립 리뷰로 인수했고, 준비된 vector 한도 adapter도 고유118개·기존39개 영향 및 독립 리뷰로 인수했다. FILES_PUBLICATION_STORAGE.md의 bounded direct PUT도 현재68개·실제0/small/250MiB version/SHA와 missing-Version2 case 및 독립 리뷰로 로컬 비활성 인수를 마쳤다. 다음은 고정 Source aggregate 명령과 durable publication·원자 apply 조립이다. durable caller checkpoint와 강제 전체 provider 취소는 필수 잔여다. 과거 동결 결과와 후기 수정·owner 설명은 구분한다. 불변 storage publication·tree aggregate·materializer의 최신 Source event provenance·전체 auth/ACL·실제 전달과 서비스 활성화는 필수 잔여다. [FILES_SOURCE_RESULTS.md](FILES_SOURCE_RESULTS.md)가 순서를, [VALIDATION.md](VALIDATION.md)가 정확 범위와 시점을 소유한다. 원문 복제·자동 claim 재발급·운영 권한 확대는 없다.

## 중간 점검에서 확정한 범위 조정

2026-10-07 사용자 지시로 **구조 완성에 필수인 변경과 치명적 문제만 현재 구현에 포함**한다. 판단 원본은 [PLAN.md](PLAN.md#구조-완성-우선과-앱별-후속-작업)다. 앱별 비필수 개선·상세 기능 검증은 [APP_ISSUES.md](APP_ISSUES.md)에 보류했고 해당 앱/이슈의 별도 지시가 있어야 착수한다. 일반적인 재개 요청이나 구조 작업 완료로 자동 실행하지 않는다. 범위 조정 뒤 사용자의 구현 재개 지시를 받았으며 구조 작업만 이어간다.

## 작업 기준

- 위치: `/home/user/projects/miy/dev`, `dev` 체크아웃.
- 시작 HEAD: `449d1417afbf6a2eb978c1465c765e26ef43c5dc`.
- 구현 착수 시 변경: 관련 작업인 `platform-redesign/` 문서 8개만 미추적 상태.
- Workbench: 단일 소유자·SQLite·native Codex 유지. 다중 사용자는 후속 범위.
- 하네스 선택: 일반 개발 절차 스킬을 제거하고 특수 기능 스킬 7개만 최소 형태로 유지한다. 자동 세션 스냅샷·수정 후 검사·종료 차단은 제거하고 Git·생성 파일 직접 패치 보호와 native rules는 유지한다.

## 재개 후 다음 행동

1. **공식 UI 전체 모듈 이전:** Diagrams·Bento·Mail·Whiteboard·Community·Docs·Recording·Meeting·Planner의 실제 소유 이전을 로컬 검증했다. Planner 최종 검사에서 본문·CSS·전체 번역 33개 동등성, suite 666/platform 124/root 45개, 두 build와 브라우저 각 26/실제 dev 22개를 확인했다. 선택 입력 1,634개 중 제품 등 1,633개는 두 build 전부터 불변이고, 개발 서버의 소스 URL까지 차단하던 테스트 한 개만 정정했다. 최종 browser 입력 전체와 owner 106개가 같다. PMS 새 두 build·부모 browser 통합을 마쳤다. Files·Video Chat까지 실제 source 소유 이전은 12/12개다. 마지막 두 앱과 공용 Chatbot까지 두 build와 포털37·공식36개의 합성 브라우저, selected dev6개를 통과해 source/build 통합 인수도 12/12개다. 입력1,823개와 Files owner254·Video review35개는 두 build 전부터 최종 브라우저 뒤까지 같다. 이 소유 경계는 유지하며 다음 구현은 아래 공식 API·데이터·실행 경계에 집중한다. 단일 Context·i18next와 교차 앱 공개 API를 유지하고 앱별 상세 기능 인수는 보류한다.
2. **공식 앱 실행·데이터 분리 완성:** 원본 88개 guard, source outbox와 단계별 claim·COMMIT 경계는 기존 근거를 보존한다. 구형 Docs scope/RAG/keyword 작업의 Core 변환은 actual PG 238개와 독립 리뷰를 통과했다. source SELECT만 사용하며 origin/target receipt 두 표, 원 이벤트 FK·불변성, 최대 100개와 동일 ID 복구를 유지한다. Recording legacy 발행·두 재시도 보완도 actual PG 68개와 독립 리뷰를 통과했다. 원 attempt·오디오를 보존하며 현재 권한 검사·reset·attempt는 한 COMMIT이다. 고정 네 단계 source command와 별도 Core publication은 로컬 비활성 구현·현재 권한·영향 legacy·독립 리뷰를 마쳤다. 실제 계정 경쟁을 ON CONFLICT와 동일 binding의 현재 권한 재조회로 보완했으며 기본 HTTP·legacy chain은 유지한다. 다음은 새 schema와 신규 principal/artifact를 맞춘 명시적 서비스 조립, 현재 app/ACL·AI/audit 읽기 권한과 제한된 실제 broker/ACK·queue·Beat 경계다. 원격 요청의 불명확한 수락, broker/Beat, source-only consumer, partition과 Files extraction 역방향 쓰기, 실제 auth/ACL·audit·routing·runtime 분리와 공식 owner 활성화는 필수 잔여다.
3. **개인 앱의 독립 개발·배포 흐름 완성:** manifest 정의→등록→소스/개발 환경→미리보기→불변 산출물 배포→관측·복구를 UI 및 DB 시범 앱으로 연결한다. 포털·Workbench 앱별 수정 없이 동작하는지, 현재 인증·앱 권한·데이터 격리가 유지되는지 검증한다. 이미 구현한 SDK·파일 선택과 최초 개발 설정의 계약 검증은 보존하며 개별 시험 앱의 업무 기능을 확장하지 않는다.
4. **Workbench와 native 실행 연결:** 단일 사용자·SQLite·native Codex를 유지하면서 프로젝트·세션·에이전트·템플릿·상태와 위 흐름을 연결한다. 최신 후보 `8d8b5fa8…`의 SQLite/vault/backup/두 starter와 실제 후보 API/UI의 합성 브라우저 아홉 경로를 확인했다. 후보 payload digest와 검사 입력 474개는 불변이며 기존 browser/native 결과와 구분한다. 기본 Docker profile은 상위 syscall filter에서 막힌다. 별도 owned systemd/private network·outer bubblewrap의 실제 native 정책·인증·자원 한도 선행검사는 통과했다. 다음은 기존 Task의 계획 승인·수정·재개와 운영 설정 적용이며 호스트 보안 정책·기존 서비스는 변경하지 않았다.
5. **구조 통합·인수:** 대표 자연어 생성→등록→개발→실행→배포·실패 복구, 동시 미리보기의 자원·권한 경계와 새 구조의 지침 적용을 검증한다. 실제 배치 환경 검증·설정 미적용·운영 권한 한계를 구분하고 필요한 소유 문서를 갱신한다. 앱별 후속 이슈가 남았다는 이유로 구조 완성을 미루지 않으며 미해결 구조·치명적 문제를 앱 이슈로 넘겨 완료 처리하지 않는다. PR71 게시·병합과 개발/Workbench 반영을 마쳤다. 운영 배포도 승인 범위이며 수정본 필수 리뷰와 전체 릴리스 검증 후 이어간다. 구조 전체 서비스 cutover와 native 실행 인수는 별도 잔여다.

## 확보한 근거와 남은 범위

- 카탈로그 누락·번역·아이콘 공유와 전체 페이지 검증, PostgreSQL 등록·설치·앱 세션, SDK와 별도 origin 포털 iframe/popup 흐름의 집중 검사가 통과했다. 실제 운영 배치의 브라우저 로그인 검증은 별개다.
- SDK는 기존 인증·반환형·구버전 호환을 유지하면서 선택적 테마·언어와 앱 이동 제안을 제공한다. 기본/메모 template와 생성 bundle에 반영했다. 제안은 실행 권한/도착 확인이 아니며 실제 클릭에서도 현재 입장 권한을 재확인한다. 파일 선택의 로컬 구현·검증도 마쳤고 추가 공통 API와 운영 배치 확인은 남아 있다.
- UI 시범 앱의 실제 제한 컨테이너 실행과 프록시 접근을 확인했다. PostgreSQL의 durable intent와 실제 Docker를 함께 사용한 배포→응답 유실→unknown→재실행 방지→reconcile→이전 이미지 복구도 통과했다. DB 앱도 두 불변 이미지 배포·앱 세션·개인 메모 저장·이전 이미지 복구 후 데이터 유지 검사를 통과했다. 운영 환경 적용은 미완료다.
- 자연어 도구는 선택된 개발 설치에만 checkpoint·정의 동기화·검증 빌드·배포·복구를 요청한다. 현재 로그인과 위임 권한은 코어가 매 단계 확인하며, 실패가 확정된 요청만 명시적으로 재시도하고 불확실한 요청은 기존 ID로 조회한다. 실제 native 원격 실행과 전체 연결한 평가는 아직 남았다.
- 공식 묶음은 별도 UI 프로젝트의 production build를 통과했다. 기존 공용 shell/source adapter를 쓰는 첫 단계이며 별도 API wheel·inactive composition과 플랫폼/공식 비활성 worker profile·소유 queue·task/Beat 목록을 추가했다. 공식 API·DB·worker의 서비스 분리나 운영 전환이 완료된 것은 아니다.
- 기존/경량화 하네스 native 비교 36회를 수행했다. 과제 결과·권한 경계는 모두 통과했으나 candidate 검사 명령 관측은 14/18로, 품질 향상이나 비열등성을 주장하지 않는다. 새 독립 앱·배포·재개 전체 자연어 평가는 미완료다.
- 실제 Workbench native 앱 소스 smoke는 재실행과 계측 실행에서 통과했다. 첫 실행의 SQLite lock 원인은 재현되지 않아 해결로 선언하지 않는다. 종료 오류가 다른 자원의 정리를 건너뛰던 별도 문제는 수정하고 실패 주입 검사로 확인했다.
- 로컬 미리보기 4개와 제한된 빌드 1개 병행, 메모리 초과 시 다른 앱의 응답 유지·정리를 확인했다. 작은 UI 앱의 로컬 측정이며 무거운 업무 빌드나 실제 개발 서버의 수용량 검증은 아니다. 공식 UI source/build 이전은 12/12개 완료했으나 API·DB·worker의 독립 서비스 전환과 전체 portal 업무 조립 정리는 미완료다.
- 실제 서비스는 변경하지 않는다. 별도 Workbench 릴리스 준비와 운영 반영은 구분한다.

검증 결과는 [VALIDATION.md](VALIDATION.md), 결정 이력은 [PROGRESS.md](PROGRESS.md)에 기록한다.

## 2026-10-09 03:53 — Whiteboard 저장 안전성 로컬 검증

신규 pure16 PASS/5.15s·실제 PostgreSQL/Yjs32 PASS/60.64s =48개다. 기존 prepared/auth/composition466 PASS/329.54s·원 Whiteboard 구조6 PASS/16.96s·원 Docs default8 PASS/26.33s =고유 영향480개다. 원 red4의 첫 green과 이전 반복 검사는 더하지 않는다. API architecture/i18n·생성 계약은 통과했다. 최종 문서/범위 freeze와 독립 수락·필수 원격 리뷰/병합은 이후 별도로 기록한다.

이번 범위는 기존 trusted Core factory의 저장 안전성이다. 최소 Source writer 권한·현재 Core 사용자 권한의 COMMIT fence·동일 room의 다중 hub 내용 CAS/convergence·영속 unknown 복구·Docs media/RAG 저장·공식 서비스 전환은 필수 잔여다. 기존 readOnly Source/session/auth·모델·role·migration·원 tests를 포함한 보호 입력46개는 동일하다. 운영·별도 Workbench 배포는 없으며 full241/409 storage 실패/tests0를 유지한다. 비필수 앱 기능과 다중 사용자 작업은 별도 요청까지 보류한다.

## 2026-10-09 04:24 — 필수 리뷰의 공유 저장 상한 수정

Source6da7c943의 PR87/MR94 필수 pipeline242/job410은 FAILED/115.932917초였다. P2는 flush마다 새 limiter1을 생성해 room 간 전체 SQL worker 상한이 없다는 회귀다. 이 실패를 성공이나 면제로 바꾸지 않고 실제 거절 기록과 기존48·480 성공 receipt를 별도로 보존했다.

최종 신규 pure16 PASS/5.47s·native35 PASS/90.18s =51개, 기존 prepared/auth/composition466 PASS/311.04s·원 WB6 PASS/15.61s·원 Docs8 PASS/25.19s =480개다. 기존48개 및 첫 통과·재검사 횟수는 더하지 않는다. API architecture/i18n·생성 계약 통과이며 최종 문서 freeze·새 독립 인수·새 필수 리뷰는 별도로 진행한다.

최소 Source writer/profile·현재 Core 사용자 COMMIT fence·같은 room의 cross-hub content CAS/convergence·영속 unknown/Docs 저장·operational 역할과 서비스 전환은 필수 잔여다. Next service-admission profile은 이번 단계에서 사용하지 않는19표98열 ACL 호환 grant를 미리 주지 않고 board/collab의 고정 최소열과 EXEC부터 독립 인수하도록 계획을 좁힌다. 현재 ACL reader는 보호하며 실제 ACL writer 연결은 후속이다. main/prod9e9280df·full241/409 storage 실패/tests0·새 운영/Workbench 배포0를 유지한다. 앱별 상세 기능과 다중 사용자는 보류한다.

## 2026-10-09 05:08 — 최종 저장 대기 중 상태 보존

Source705a13dc의 PR87/MR94 필수243/job411은 FAILED/78.614494초였다. P1은 공유 저장 슬롯4개가 포화됐을 때 최종 flush 전체에 적용한 cleanup timeout이 admission 대기를 취소하고 미저장 YDoc을 해제하는 문제다. 이전242/410의 상한 거절과 각각의 실제 실패·이전 로컬 성공을 보존하며 필수 리뷰 실패를 면제하거나 성공으로 바꾸지 않는다.

최종 신규54개는 pure16 PASS/7.10s와 native38 PASS/131.44s다. 기존 영향480개는 prepared/auth/composition466 PASS/372.13s·원 Whiteboard6 PASS/25.87s·원 Docs8 PASS/35.69s다. 이전48/51개·재실행 횟수는 더하지 않는다. API architecture/i18n·생성 계약을 통과했다. 최종 문서·Python 검사와 새13파일 독립 인수 및 새 source의 필수 리뷰는 별도 단계다.

현재 dev499aff33·main/prod9e9280df, full241/409 storage 실패/tests0, 새 운영 및 별도 Workbench 배포0다. 다음은 비활성2표 최소 Source service writer/profile이며 Core 사용자 권한 COMMIT fence·Source factory 연결·cross-hub content CAS·영속 unknown 복구·공식 서비스 cutover는 남아 있다. Native SDK/toolchain 실제 pin 검증·설치 및 개인 앱 자연어 전체 흐름도 필수 잔여다. 앱별 비필수 기능·다중 사용자는 보류한다.

## 2026-10-09 05:22 — 저장 안전성 전달과 최소 Source writer 착수

Whiteboard 저장 안전성 최종 Source `ba9fee1e`/tree `fef48496`는 필수244/job412 SUCCESS/94.736405초 뒤 GitHub [PR87](https://github.com/hurxxxx/miy/pull/87)→`2c1cb019`와 내부 [MR94](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/94)→dev `aafbccb2`로 정상 병합했다. 양쪽 tree는 같고 소유 feature 브랜치의 양쪽 원격·로컬 정리를 완료했다. Dev는 persistent integration branch로 유지하며 main/prod는 `9e9280df`다.

새 전체245/job413은30.366867초에 저장 공간 선행조건에서 실패했다. 제품 테스트0이며 필수 최소15GiB/15% 기준을 유지한다. 이 결과를 source 리뷰 성공으로 대체하지 않고 새 운영·별도 Workbench 배포0를 유지한다.

다음 구현은 `aafbccb2` 기준 별도 worktree에서 비활성 Whiteboard Source service writer/profile이다. 실제 migration head `file_effect_20261007`, 기존 migration30개 및 보호85개를 다시 동결했다. 새 migration·service admission·role checker와 새 테스트·owner2, Root 추적6을 분담한다. 두 Source 표의 SELECT8열·UPDATE4열과 제한된 capability 하나부터 인수하며 공급된 LOGIN/NOLOGIN 역할·원래 principal identity·정확한 권한·기존 mapping replay·실제 session_user와 SQL 락을 검증한다. 현재는 구현 착수이며 새 테스트를 실행하거나 인수한 것으로 표시하지 않는다.

Migration은 정상 legacy/hardened 환경에서 비활성 capability만 설치한다. 준비·admission에는 hardened guard가 필요하다. Session/factory/COMMIT/cleanup 수명은 caller가 소유하며 Core 사용자 ACL COMMIT fence·hub Source factory 연결·운영 역할/grant/config/service 전환은 이번 범위가 아니다. Current actor fence, cross-hub content CAS, 영속 unknown 복구와 공식 서비스 cutover는 여전히 필수 잔여다. 기존 skills/harness는 절차로 사용하지 않고 현재 코드·owner·중요 계약만 사용한다. 앱별 비필수 기능과 다중 사용자는 보류한다.

## 2026-10-09 05:59 — 비활성 최소 Source writer 로컬 검증

최종 새 pure10 PASS/0.62s·실제 PG18 native69 PASS/56.98s =79개다. 기존 role/Source ACL/room/저장204 PASS/203.03s·원 migration 함수5 PASS/6.35s =209개는 별도 영향 범위다. API architecture/i18n·생성 API/schema/OpenAPI/contract-source와 scoped Python5 검사는 통과했다. Owner2·Root tracking6의 최종 Markdown freeze와 독립/필수 원격 리뷰·게시/병합은 별도로 진행한다. Network-none·실제 env/credentials0·소유 컨테이너 정리를 확인했다.

현재 dev `aafbccb2`·main/prod `9e9280df`, 최신 full245/413 저장 공간 선행조건 실패/제품 테스트0와 새 운영/별도 Workbench 배포0를 유지한다. 이 단계는 Source factory·저장 연결·사용자의 현재 Core/Source ACL COMMIT fence·cross-hub content CAS·영속 unknown 복구·Docs 저장·공식 서비스 cutover를 완료하지 않는다. 다음 actor fence는 현재 사용자 구현 승인 안에서 별도 범위와 보호표를 확정한다. Same-DB SQL 잠금을 실제 separate DB 보장으로 표시하지 않으며, queued Yjs의 credential attribution/expiry와 모든 owner/direct/group/PMS/meeting edit closure가 활성화 전 필수다. Native SDK/toolchain 실제 pin 검증/설치·개인 앱 전체 자연어 흐름도 남아 있다. 앱별 비필수 기능·다중 사용자는 보류한다.

## 2026-10-09 06:22 — 최소 Source writer 전달과 actor-owner 경계 착수

현재 dev는 `746258cd`, main/prod는 `9e9280df`다. 비활성 최소 Whiteboard Source writer/profile은 필수246/job414 성공 뒤 [PR88](https://github.com/hurxxxx/miy/pull/88)·[MR95](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/95)로 정상 병합하고 소유 feature 브랜치를 양쪽 원격·로컬에서 정리했다. 최신 full247/job415는 저장 공간 선행조건에서22.79551초에 실패해 제품 테스트0이며 새 운영·별도 Workbench 배포는 없다.

다음은 별도 worktree의 비활성 Core actor-owner capability다. 실제 원 delegated execution을 별도 auth-only Session에서 캡처하고, 공급된 fresh LOGIN에는 private EXEC1만 허용해 사업 데이터 SELECT·DML0을 유지한다. 같은 PostgreSQL database의 caller-owned transaction에서 원래 서비스와 현재 사용자·세션·설치·앱 승인·live board owner의 positive witness를 잠근다. Source v1의 SELECT8/UPDATE4 및 auth14표/87열은 확장하지 않는다. 기존31 migration·보호95개를 동결하고 신규 revision `wb_actor_owner_20261009` 하나와 inventory head 한 항목만 추가한다. 구현·테스트 작성에 착수했으며 새 검사 실행·최종 인수·게시·서비스 활성화는 아직 하지 않았다.

이번 owner-only 단계는 전체 Whiteboard ACL·실제 Source 쓰기 연결·운영 전환을 완료하지 않는다. 공유/HR/PMS/meeting 편집 권한, contributor의 원 credential 보존, 같은 connection/transaction의 Source CAS와 actor 검사 조립, cross-hub content CAS·영속 unknown 복구·Docs 저장/media/RAG가 필수 잔여다. 별도 LOGIN 연결 두 개는 하나의 transaction으로 합칠 수 없으므로 후속 최소 combined profile 또는 검토된 capability가 필요하다. 같은 database의 역할·프로세스 분리이며 물리적 별도 DB를 인수하지 않는다. 대기 후 실제 시각의 만료 판정은 decision 시점 보장이고 physical COMMIT-time 만료 보장은 아니다. 사용자 update의 User→AuthSession과 autoflush=False인 reset/delete의 AuthSession→User 역순 잠금 충돌은 bounded private refusal·caller rollback으로 검증하고 보편적 잠금 순서로 주장하지 않는다. Native immutable cache/설치·SDK 전체 자연어 흐름과 별도 Workbench 전달도 남아 있다. 비필수 앱 기능·다중 사용자는 보류한다.

## 2026-10-09 08:38 — actor-owner 구현 검증과 Docker 저장소 이전

비활성 actor-owner 구현을 작성하고 실제 PostgreSQL에서 검증 중이다. nullable release/verification 연결의 NULL 우회는 실제 2 FAIL로 재현한 뒤 `IS DISTINCT FROM`으로 수정했다. 첫 전체 native138 실행은133 PASS/5 fixture FAIL이며, 교정한 동일5 진단은5 PASS/29.16초다. 최종 전체138·pure7·영향167 및 계약 검증은 최종 입력으로 다시 확인한다. 새 capability의 실제 서비스 연결·운영 활성화는 아직 없다.

사용자는 Docker 데이터를 루트의 여유104GB 영역으로 이전하도록 승인했다. 기존 `/var/lib/docker`는 `/home/user/docker-data`의 bind이며 실제 데이터 약51GiB가 작은 home 볼륨을 사용한다. 새 실제 저장소 `/var/lib/miy-docker-data`로 초기 복사 중이고 서비스는 기존 저장소에서 계속 실행 중이다. 모든 컨테이너83·볼륨286·이미지18 objects를 보존하고, 마지막 쓰기 중지·체크섬·목록·건강 상태 확인 뒤 전환한다. 이전 완료·원본 정리·릴리스 CI 재개를 아직 주장하지 않는다.

## 2026-10-09 09:10 — Docker 이전 최종 비교 중

Docker 초기 복사의 bulk mknod/ENOENT 오류를 보존했다. Source의237개 char0:0 whiteout을 같은 type/rdev/mode로 누락된 목적지에 보완한 뒤 일반 rsync 전체 재시도는 성공했다. 단일 파일 복사는 오류를 재현하지 못했으므로 최초 원인을 단정하지 않는다. 드라이버·저장 형식은 그대로이며 오프라인 전체 체크섬이 최종 조건이다.

09:03부터 기존29개 실행 컨테이너와 개발/CI 서비스를 중지했다. 강제137/OOM0이며 PostgreSQL2개 exit0, Hermes gateway2개와 GitLab exit1은 별도 복구 확인 대상으로 기록했다. 09:05 최종 동기화는 성공했고 현재 약205만 파일의 checksum/metadata 비교 중이다. 저장소 전환과 서비스 복구·원본 정리는 아직 하지 않았다. 부모 SSH/작업 환경과 두 복사본은 유지된다.

최종 동결16 입력의 실제 native138은138 PASS/480.01초, input==output·소유 컨테이너 cleanup PASS다. Pure7의 최종 hash 검사와 기존 영향167·계약 재검증, 정상 게시·필수 리뷰·운영 release와 별도 Workbench 전달은 남아 있다.

## 2026-10-09 09:26 — Docker 이전 완료와 actor-owner 최종 로컬 검증

Docker 실제 저장소를 `/var/lib/miy-docker-data`로 옮기고 canonical `/var/lib/docker` bind와 fstab/systemd 의존성을 전환했다. 약205만 파일의 전체 checksum/metadata 차이0, 모든 컨테이너83·볼륨286·이미지18 및 참조·이전 실행29·healthy21이 동일하다. 기존 원본은 검증 후 정리하고 CI runner를 복원했다. Docker 여유는52.65GiB/45.22%다. Home 파일 사용량은 약86→35GiB로 감소했지만 가용12.85GiB가 유지된다. 원인을 확정하거나 외부 ZFS snapshot/보관 정책을 변경하지 않았다. Docker executor에는 별도 home `/builds`/`/cache` bind가 없으며 실제 full CI로 새 filesystem gate를 확인한다.

Actor-owner 최종 native138 PASS/480.01초·pure7 PASS/3.24초와 기존105+52+5+5=167 PASS, Python·API 구조/i18n·OpenAPI/schema/generated contract가 통과했다. 기존167 결과에 예외를 적용하지 않고 최종 코드/보조 fixture 해시를 before/after 동결해 재실행했다. 이번은 비활성 capability와 호스트 유지보수 인수이며 새 제품/Workbench 버전 배포0다. 정상 게시·필수 리뷰와 최신 full release, 전체 actor ACL·같은 Source connection/transaction 조립은 남아 있다.

## 2026-10-09 09:46 — 기본 CI의 Source revision fixture 보완

`ACT-CI-01`로 최종 전달을 HOLD했다. 이전 영향167 PASS는 원 Source74개를 최신 head에서, revision 전용5개를 ignored runtime adapter에서 실행한 범위였으며 게시된 기본 Source79개 전체의 성공 근거가 아니었다. 기본 원본 모듈에서 해당5개를 실행하자 최신 actor head가 Source revision 검사의 입력이 되어5 FAIL/11.19초가 발생했다. Setup0·소유 cleanup PASS이며 이전 결과를 삭제하거나 전체 CI 통과로 확대하지 않는다.

Source 검사 파일에 case-scoped `world` 래퍼와 정확히4개 함수의 단일 간접 revision 매개변수를 게시 가능한 형태로 추가했다. 해당5개만 legacy 복제 DB를 정상 Alembic downgrade하고 정확한 Source ancestor31개 임시 inventory를 사용한다. Hardened writer 준비보다 먼저 실행되며 나머지74개와 actor145개는 최신 head를 유지한다. 원본 모든 함수의 body·signature·assertion AST와 기존 decorator 순서는 동일하다. 제품8개와 이전31 migration은 그대로이며, 소유 범위를17경로·보호94개로 명시적으로 갱신했다. 같은 기본 선택5개는5 PASS/11.17초·cleanup PASS다.

최신 입력의 pure7·role31·migration5·API 구조/생성 계약은 통과했고 기본 Source79·authority52·actor native138 전체를 재검증 중이다. 이전 actor145·영향167 성공은 이전 시점의 기록으로 보존하며 이번 최종 freeze 성공으로 대신하지 않는다. 최종 문서/독립 리뷰·필수 source 리뷰와 전체 release/운영·별도 Workbench 전달은 남아 있다. 실제 actor/source 역할·same-connection factory·전체 edit ACL은 활성화하지 않았다.

## 2026-10-09 09:50 — actor-owner와 정상 CI 호환 최종 로컬 인수 준비

최종17파일 범위에서 신규 actual PG18 native138 PASS/321.13초·pure7 PASS/3.30초 =145개다. 정상 원본 Source 모듈79 PASS/82.18초·원 role31 PASS/24.19초·authority52 PASS/83.77초·migration5 PASS/6.35초 =고유 기존 영향167개다. 진단/반복은 더하지 않는다. ACT-CI-01의 실제5 FAIL/11.19초와 동일5 PASS/11.17초는 보존하며 현재 영향 검증은 ignored Source prior adapter에 의존하지 않는다. 기존45개 함수 본문·signature·assertion, 보호94개·기존31 migration은 동일하다.

Python6·API architecture/i18n·schema/OpenAPI/contract sources를 통과했다. 최종 문서 검사·동결 후 새 독립 인수와 정상 게시/필수 원격 리뷰를 진행한다. 현재 dev746258cd·main/prod9e9280df 및 최신 full247/415 storage 실패/tests0를 유지하며 새로운 commit/push/PR/MR/merge는 아직 없다. Docker 이전/원본 정리·서비스 복구는 완료했고 제품/별도 Workbench 버전 배포는 없다. 전체 ACL·같은 Source connection/transaction 조립·실제 공식 서비스 cutover·Native 전체 자연어 앱 흐름 등 구조상 필수 잔여는 남아 있다.

## 2026-10-09 10:13 — owner 경계 전달 완료와 전체 편집 ACL 착수

비활성 owner actor 경계 Source `3b39f5b9`/tree `68ca858e`는 필수248/job416 SUCCESS/137.448817초 뒤 GitHub [PR89](https://github.com/hurxxxx/miy/pull/89)→`55e53403`, 내부 [MR96](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/96)→dev `8bf0bbee`로 정상 병합했다. 양쪽 tree 동일·임시 브랜치 양쪽 원격/로컬 정리·persistent dev 유지·main/prod `9e9280df`를 확인했다. 최종 신규145·고유 영향167과 정상 Source79 전체 통과이며 ACT-CI-01의 기존 원 assertions와 실제 실패/수정 증거를 보존한다.

Docker 이전 완료 후 최신 전체249/job417은 dev `8bf0bbee`에서 실제 테스트를 진행 중이다. 최종 full 성공·운영/별도 Workbench 버전 배포는 아직 없다. 다음은 해당 통합 commit을 기준으로 별도 worktree에서 비활성 전체 edit ACL capability다. SQL, role/runtime, tests를 분담해 구현 중이며 새 검사 실행/인수/게시/실제 쓰기 연결은 아직 하지 않았다.

## 2026-10-09 10:48 — 통합과 운영의 현재 상태

Actor-owner 전달 완료: GitHub PR89·GitLab MR96 병합, 필수 review248/job416 성공, dev `8bf0bbee`. Docker 루트 볼륨 이전 및 기존 서비스 복구 완료. 운영 main/prod는 `9e9280df`이고 새 플랫폼·별도 Workbench 버전은 미배포다. Full249/job417의 백엔드 6,283 PASS/8 FAIL로 운영 release 인수는 보류한다. 기존 파일 migration revision fixture의 정상 CI 호환 수정과 새 full 검증이 우선이다. 전체 edit ACL 후속 구현은 격리된 브랜치에서 검증 중이며 아직 dev에 통합하지 않았다.

## 2026-10-09 10:54 — 전체 edit ACL 로컬 인수 상태

격리 브랜치의 전체 edit ACL은 신규132·기존312와 API/Python 계약 PASS다. 실행 LOGIN DML0·서버 원 execution·caller transaction·현재 app/resource 권한 경계를 유지한다. 최종 문서/독립 인수와 필수 원격 review는 아직 남았으며 실제 Source 저장·factory·운영 활성화는 없다. Dev8bf0bbee의 full249는 기존 파일 migration8 FAIL로 실패했으므로 운영 main/prod9e9280df와 별도 Workbench 버전은 유지한다. ACT-CI-02 수정 및 최신 source의 새 full 검증을 먼저 전달한다.

## 2026-10-09 11:05 — ACT-CI-02 로컬 영향 검증 완료

ACT-CI-02 수정은 로컬270 PASS와 독립 정적 리뷰0 blocker다. 제품 코드·기존32 migration을 변경하지 않았다. 최종 문서·정상 commit/PR/MR·필수 review 및 새 full release는 아직 남았다. 개발 dev8bf0bbee·운영 main/prod9e9280df와 별도 Workbench 버전 상태는 유지한다.

## 2026-10-09 11:23 — 정상 fixture 전달과 ACL 통합 준비

ACT-CI-02는 PR90/MR97 정상 병합·필수250/418 SUCCESS·브랜치 정리 완료다. 현재 dev e3e2591, 운영 main/prod9e9280df다. ACL은 로컬444 PASS의 runtime8을 유지하며 새 base에 rebase했고, 새33-head file revision8도 PASS다. 최종 문서/독립 통합 리뷰 및 필수 remote review는 남았다. Full251은 e3 source로 진행 중이고 ACL 통합 후 최신 source를 확인한다. 새 운영/Workbench 버전 배포와 실제 Source 저장 활성화는 아직 없다.
