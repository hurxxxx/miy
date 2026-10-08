# 현재 진행 상태

기록 기준: 2026-10-08 UTC. 작업별 상태는 [WORK_ITEMS.md](WORK_ITEMS.md)가 소유한다.

사용자의 최신 지시로 인수한 세 경계의 게시·개발/운영 배포를 진행한다.
소스 commit·upstream PR과 내부 protected dev/main 릴리스 검증, 플랫폼
immutable image와 별도 Workbench SQLite migration/릴리스를 각각 확인한다.
아래 로컬 인수 기록은 배포 전 시점이며 실제 결과는
[게시 체크포인트](PUBLICATION_CHECKPOINT.md)의 후속 추적에서 구분한다.

## 현재 위치

- 최신 게시·병합 추적: [GitHub PR70](https://github.com/hurxxxx/miy/pull/70)의
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
- 원격 변경: 사용자 긴급 백업 지시로 별도 비공개 GitHub 저장소에 snapshot을 보관했다. [EMERGENCY_BACKUP.md](EMERGENCY_BACKUP.md)가 해당 일회성 범위와 복구 위치를 소유한다. 원본 GitHub PR69 병합과 해당 작업 브랜치의 원격·로컬 삭제를 마쳤다. 영구 `dev`·`main`은 유지했다. 현재 Source 후속 PR은 최신 사용자 지시로 게시·병합·브랜치 정리한다. [PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md)가 게시 근거를 소유한다. 서비스·운영 배포는 포함하지 않는다.
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
4. **Workbench와 native 실행 연결:** 단일 사용자·SQLite·native Codex를 유지하면서 프로젝트·세션·에이전트·템플릿·상태와 위 흐름을 연결한다. 최신 후보 `8d8b5fa8…`의 SQLite/vault/backup/두 starter와 실제 후보 API/UI의 합성 브라우저 아홉 경로를 확인했다. 후보 payload digest와 검사 입력 474개는 불변이며 기존 browser/native 결과와 구분한다. 현재 제한 컨테이너는 상위 syscall filter에서 막힌다. 호스트 보안 정책·서비스를 임의 변경하지 않고 승인 범위 안에서 필요한 실행 경계를 해결한다.
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
