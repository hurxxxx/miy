# GitHub 게시 체크포인트

## 후속 세 경계 게시·개발/운영 반영

2026-10-08 사용자가 이번 변경의 커밋·push·upstream PR·병합과 개발/운영
배포를 명시적으로 지시했다. 대상은 auth-only 준비 reader, private flat
폴더 명령, Workbench 연결 확인 UX와 관련 검증/owner/진행 문서다.
GitHub 작업 PR과 내부 dev→main release_validation을 각각 확인한다.
플랫폼의 guarded immutable image 배포와 별도 Workbench 릴리스·백업·교체·
직접/공개 health 및 실제 UI 반영을 구분해 기록한다. 기존 operational
DB/grant/서비스의 official cutover를 이 코드 배포로 활성화하지 않는다.
실제 결과와 SHA는 PR/MR 기록과 후속 receipt가 원본이다.

### 중단 후 재개 — 2026-10-08 UTC

사용자가 필수 리뷰 계정의 공식 재인증을 완료했다. MR80 pipeline207의
job373에서는 인증 오류 없이 실제 코드 리뷰가 실행됐으며 개인 앱 runtime의
암묵적 HTTPS upstream 포트를80으로 변경하는 P2 하나로 MERGE_BLOCKED됐다.
명시된 포트는 보존하고 생략된 HTTPS는443, HTTP는80을 사용하도록 수정했다.
관련 검사42개 통과·기존 opt-in Docker 검사1개 skip과 API architecture/i18n
검사 통과를 확인했다. 동일 source의 실패 job을 재시도해 우회하지 않고
수정 source의 새로운 필수 리뷰를 받는다.

운영 플랫폼은 여전히 기존 릴리스를 유지한다. 보호된 일관성 DB backup을
완료했으며 격리 복사본의 append migration20개와 이전 불변 이미지의 호환성을
검증한다. 이 검증과 dev→main 전체 release_validation을 통과한 뒤 guarded
배포를 진행한다. 현재 수정은 Workbench 제품 소스를 바꾸지 않아 별도
Workbench 재배포 대상은 아니다. 앞선04:00 결과는 당시의 기록으로 보존한다.

ignored `.runtime/independent-runtime-https-port/`와
`.runtime/production-compatibility-review/`가 해당 실행의 범위·결과를 보존한다.

### 실제 리뷰의 추가 수정 — 2026-10-08 UTC

[PR73](https://github.com/hurxxxx/miy/pull/73)의 HTTPS 포트 수정을 일반 병합하고
해당 원격·로컬 작업 브랜치를 삭제했다. 내부 pipeline208/job374는 인증 오류
없이 실행됐으나 기존 색인의 결과 표식 전환 P1과 재사용 Files controller의
범위 변경 상태 P2로 MERGE_BLOCKED됐다. 이 실패는 기존 인증 실패와 구분한다.

Files의 strict SHA·partition·결과 표식 비교는 유지한다. 새 배포 전환 검사는
기존 generation verifier로 실제 Source와 keyword/vector 결과를 대조하며,
누락된 Source 표식과 재색인 전의 기존 envelope를 거부한다. 검사만으로 재색인,
paid compute나 서비스 profile을 활성화하지 않는다. forward deploy/up은 기존
API·worker·scheduler 중지→migration→검사→새 런타임 인계를 사용한다.
실패한 deploy는 이전 이미지, 실패한 up은 같은 기존 이미지로 복원을 시도한다.

controller는 기존 현재 범위 검사와 실제 페이지의 keyed session을 보존하면서
자체 scope가 바뀔 때 일시 상태를 정리한다. 이전 응답이 새 작업을 해제하지
않는 deferred 회귀를 검증했다. 실제 페이지는 이미 keyed remount를 사용하므로
초기 리뷰의 페이지 생명주기 가정과 재사용 hook의 수정 범위를 구분한다.

보호된 DB backup의 격리 복원·append20·기존 데이터 보존과 이전 불변 이미지의
모델·인증·cooperative writer 검증은 통과했고 소유 자원을 정리했다. 새 수정본의
필수 리뷰·전체 release_validation과 실제 운영 배포는 여전히 별도 완료 조건이다.
ignored `.runtime/files-ui-scope-fix/`와 배포 전환 검사 근거가 정확 입력·초기 실패·
최종 결과를 보존한다. 구조 전체와 기존 비활성 official cutover는 완료로 표시하지 않는다.

### 개인 앱 런타임의 실행 한도 보완 — 2026-10-08 UTC

Files 전환·scope 수정은 `58489bf61d62828ce5df4304cefac1511be569b8`로 커밋·
push했으며 [PR74](https://github.com/hurxxxx/miy/pull/74)를 생성했다. 개발
supervisor를 한 번 재시작해 최신 소스를 반영했고 직접/공개 readiness,
API 로그인·bootstrap18·로그아웃과 실제 브라우저 런처12개·script error0을
확인했다. health revision은 `unmanaged`이며 정확 SHA의 health 증거로 쓰지 않는다.
Workbench 제품187파일은 별도 배포 소스와 동일하므로 다시 배포하지 않았다.

내부 pipeline209/job375는 인증 오류 없이 실제 리뷰를 완료했으나 개인 앱
runtime의 P2 세 건으로 MERGE_BLOCKED됐다. Docker CLI stdout/stderr의 무한
buffer, 지속적으로 데이터를 보내는 HTTP의 전체 시간 한도 부재, Docker
기본 로그의 디스크 한도 부재를 수정한다. 독립 검토에서는 release 관측의
통신 실패를 미활성으로 처리해 실제 사용 중인 앱의 정리를 허용하는 경계도
명령 stub으로 재현했다. 불완전한 관측은 불확실한 실패로 유지하고 정리를
거부한다. 이 경계들은 비개발자 앱을 공통 호스트에서 실행하기 위한 필수
자원·정리 권한 계약이다. 앱별 비필수 기능 개선은 추가하지 않는다.
최소 수정의 고유77개, 기존 Docker opt-in1 SKIP와 API 구조·번역·소유
format/lint 검사를 확인했다. 제품은 모든 통과 시점에 동일하며 후기 테스트
보완은 실행 시점별 입력으로 구분한다. 최종 소유3 입력 일치와 독립 검토
차단0을 확인했으며 수정 source를 게시한다.
같은 source를 재시도하거나 실패 리뷰를 우회하지 않는다. PR74와 MR80의
수정 source를 갱신한 뒤 새 필수 리뷰·전체 release_validation을 진행한다.
운영은 기존 정상 이미지와 schema를 유지한다.

ignored `.runtime/dev-platform-deployment/latest-20261008T054025897841Z/`와
`.runtime/delivery-resume-monitor/job375-safe-diagnosis.json`이 최신 실행을
보존한다. 진단은 고정 분류·공개 코드 위치만 기록하고 원문 prompt·trace·
자격정보는 저장하거나 출력하지 않았다.

### 반영 결과 — 2026-10-08 04:00 UTC

- [PR71](https://github.com/hurxxxx/miy/pull/71)은 03:37:23 UTC에 일반 merge했다.
  GitHub source는 `a7e71d40a3d2a6a53cbab71eb03b847d1094b9ee`, merge는
  `22f6f522d6ae383a57c04e4a241784048df5a668`이다. 로컬 구현 commit은
  `0c1bf0fe6406ba42445a25e6ea470ac4dabbb31c`, 내부 게시 source는
  `c5c3556fb89724977fe3943507a39b23a8eb00b2`다. GitHub와 내부 게시 tree의
  일치를 확인했고 GitHub 작업 브랜치는 원격·로컬에서 삭제했다.
  영구 dev/main, 미병합 내부 작업 브랜치와 upstream push-disabled는 유지한다.
- 개발 플랫폼은 기존 개발 Redis의 중지·네트워크 연결 누락을 복구한 뒤 기존
  supervisor를 한 번 재시작했다. 기존 volume·설정을 보존하고 운영 Redis는
  변경하지 않았다. append migration 5개를 적용해 `file_effect_20261007`이며
  API·web·worker·Beat, 직접/공개 readiness와 실제 로그인·런처·로그아웃을
  확인했다. health revision은 여전히 `unmanaged`이므로 정확한 health SHA
  증명을 주장하지 않는다. 재시작 소스와 게시 tree의 일치는 별도로 확인했다.
- Workbench는 별도 `20261008-0c1bf0fe` 릴리스로 교체했다. consistent backup과
  복사본 rehearsal 뒤 모든 세 역할을 중지하고 SQLite0003→0008을 적용했다.
  기존 작업·native 이력·세션·첨부·설정과 고정 CLI를 보존하고 두 릴리스 링크를
  교체해 세 역할을 재시작했다. 직접/공개 health, 배포된 JS 일치, 실제 공개
  로그인·여섯 화면의 heading/선택 메뉴·로그아웃401을 확인했다.
  설치된 새 조회 handler의 missing-project404는 실제 연결 실행 증거가 아니다.
  등록 프로젝트가 없어 새 프로젝트 pre-Task UX와 실제 native/sandbox 실행은
  운영 실증하지 않았으며 기존 잔여를 유지한다.
- **운영 플랫폼은 아직 미배포다.** 내부 MR80의 필수 `codex_review`가 pipeline206의
  job370과 재시도371에서 `refresh_token_reused` 인증 오류로 실패했다.
  코드 리뷰의 MERGE_READY/BLOCKED 판정은 없다. 실제 리뷰 계정의 홈에서 공식
  browser 재인증을 마친 뒤 최신 source/target의 필수 리뷰와 dev→main 전체
  `release_validation`을 통과해야 한다. 운영 설정 사전 점검과 PostgreSQL18
  검증 이미지는 준비했으며 운영 checkout·image·DB는 기존 릴리스를 유지한다.
- 공식 Source/Core 서비스 전환, 새로운 operational reader/grant, 전체 tree·
  publication/원자 apply와 native 실행 경계는 이번 코드 설치로 활성화하지 않았다.
  상세 앱 기능 개선은 계속 별도 지시를 기다린다.

민감한 자료를 제외한 로컬 근거는 ignored `.runtime/structural-next-delivery/`,
`.runtime/dev-platform-deployment/`, `.runtime/workbench-deployment/`와
`.runtime/source-aggregate-next/ci-review-diagnosis/`에 보존한다.
이후 결과 문서의 게시 commit은 제품 릴리스 source와 구분한다.

2026-10-08 UTC. 사용자 지시에 따른 변경의 커밋·push·PR·병합 기록이다.
설계·후속 범위는 [PLAN.md](PLAN.md), 현재 구현은 [STATUS.md](STATUS.md),
상세 검증은 [VALIDATION.md](VALIDATION.md)가 소유한다.

## 게시 범위와 기준

- 공통 플랫폼·공식 앱·독립 앱·단일 소유자 Workbench의 구조 변경과 계약,
  템플릿·생성 산출물·필수 회귀 검사·소유 문서·하네스 최소화를 게시한다.
- 대상은 원본 GitHub `hurxxxx/miy`의 `main`이다. 일회성 작업 브랜치에서
  PR을 생성하고 실제 요구되는 검사·리뷰를 우회하지 않고 병합한다.
- 로컬 통합 브랜치 `dev`를 유지한다. GitHub `main`의 기준 commit은
  `1a59524400cda2b4fab8f03e98aa32357c320b50`, 로컬 시작 HEAD는
  `449d1417afbf6a2eb978c1465c765e26ef43c5dc`이며 두 committed tree는 같다.
  PR은 GitHub 기준에서 현재 변경만 포함하고 내부 이력 차이는 가져오지 않는다.
- 병합 뒤 이번 PR 브랜치만 원격과 로컬에서 삭제한다. 영구 `dev`·`main`,
  다른 작업과 별도 긴급 백업은 유지한다. `upstream`의 push-disabled 설정도
  유지하며 이번 명시적 승인에 한해 GitHub 작업 브랜치 URL로 push한다.
- 서비스·운영 배포와 공유 DB·계정·환경 변경은 이 게시에 포함하지 않는다.

## 검증과 한계

게시 전 독립 구조 검토에서 이전된 공식 UI 검사가 기존 CI의 `web` 대상에서
빠지는 문제를 발견했다. 새 소유 프로젝트 세 개의 typecheck·test·ownership을
`ci:web`/`ci:all`과 contract CI에 연결하고 portal·official 두 build를 유지했다.
옮겨진 source도 기존 필수 web release gate로 분류한다.

| 근거                 | 결과와 정확 범위                                                                                                                                                                        |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 새 소유 CI           | `pnpm ci:owner-web` 통과. platform269·official library933·official app5 검사, 세 typecheck·ownership 통과. 선택911 입력 불변                                                            |
| release gate 회귀    | 설정·선택기 관련55개 통과. 초기 red와 수정 후 결과를 구분                                                                                                                               |
| 기존 공식 UI 통합    | 공식 UI12/12 소유 이전, portal·official 두 build, portal37·official36(별도 skip1)·실제 dev6 경로의 기존 인수 근거 유지. 과거 UI1822 중1821은 현재 동일하고 package 한 개는 이번 CI 보완 |
| Files Source         | 실제 제한 PostgreSQL81개와 선택243 불변, TEMP 인증 shadow·취소 결과 보존의 독립 검토 통과. 서비스 활성화 완료를 뜻하지 않음                                                             |
| Core file effect     | 실제 Data83·Source72·schema 영향175와 최신 controlled102의 범위를 구분해 인수. durable caller checkpoint는 잔여                                                                         |
| 준비된 vector        | 고유118개와 legacy39 영향 검사 인수. 유한 동기 budget은 강제 전체 취소가 아님                                                                                                           |
| Source PUT transport | 최신 집중68개, 실제 소유 MinIO0·small·250MiB의 exact version/SHA/size·old version 보존, missing Version2 case와 독립 검토 인수. Source publication SQL/apply는 후속                     |
| 게시 파일 점검       | 실제 `.env`·인증 자료·runtime 증거를 게시하지 않음. 소스 내 credential 형식 후보는 synthetic fixture·UI placeholder·개발 예제인지 별도 확인                                             |

새 app definition·독립 앱 schema·starter bundle·auth realtime·Workbench OpenAPI·
pinned CodeRemote·contract source artifact 검사는 통과했다. app contract7·SDK44·
normalization46·queue/profile9 검사도 통과했다. API는 runtime 초기화 없이401개
경로의 스키마·계약 검사를 통과했고, 설치된 pinned openapi-typescript7.13.0의
공개 CLI가 생성한 타입이 canonical 산출물과 정확히 일치했다. 초기 통합 wrapper는
격리 HOME에서 패키지 매니저 버전 설치를 시도해90초 timeout으로 남긴다.
이 실패를 생성 산출물 불일치나 전체 CI 통과로 바꾸어 기록하지 않는다.
task-owned launcher에서 공개 package-manager config를 바로잡은 최종 공식
`node scripts/generate-openapi-client.mjs --check --no-sync`도8.03초에 통과했고
선택859 입력은 불변이다. 제품 source나 generator를 수정하지 않았다.

상세 로컬 실행 로그·입력 해시·실패 재현은 ignored `.runtime/`의 증거다.
문서의 해당 링크는 로컬 증거 위치이며 GitHub에서 내려받는 파일이 아니다.
이 체크포인트는 민감한 로그·원문·설정 값을 게시하지 않고 검증 범위만 기록한다.

## 초기 게시 결과 — PR69

- [PR69](https://github.com/hurxxxx/miy/pull/69): 2026-10-07 23:46:53 UTC 병합.
- GitHub main merge: `26ca57677d9440d74362403c3fa1499bada4a632`.
- 로컬 dev snapshot: `a387f402584f7e0a349887fb4b283f7390dc1b48`.
  동일 tree의 GitHub feature snapshot은 `b5c6d7109350969c22ee190ef7bbe76b7f50fa97`.
- 로컬 dev는 merge `45190645ffa169e42db8675274975e0ee490bbe4`로 main 이력을
  통합했고, 두 최종 tree가 같고 작업 디렉터리가 clean임을 확인했다.
- `feat/platform-redesign-foundations-20261007` 원격·로컬 삭제를 확인했다.
  영구 dev/main과 다른 작업은 유지했다. upstream push-disabled 설정은 그대로다.
- 실제 GitHub ruleset·필수 리뷰/검사 요구가 없고 PR이 CLEAN/MERGEABLE임을
  확인해 일반 merge로 처리했다. GitHub 자동 CI 실행을 주장하지 않는다.
- 서비스·운영 환경은 변경하지 않았다. 아래 후속 구현과 이 병합 결과 기록은
  병합 뒤 로컬 변경이며 추가 게시된 것으로 표시하지 않는다.

## 병합 후 구현

[고정 Source aggregate slice](FILES_SOURCE_AGGREGATE.md)의 기존 private native
root File 한 개의 Source-only soft-delete·동일 event 관측과 공유 Session
routing 보완을 로컬 비활성 범위로 구현·인수했다. 작성자41·실제 Source 고유30·
기존 Source 영향81개와 독립 리뷰의 차단 결함0을 확인했다. 이 코드와 후기
상태 문서는 PR69 이후 변경이며 PR69에 포함됐다고 표시하지 않는다.
현재 사용자 지시에 따른 별도 후속 PR의 게시 대상이다.

다음은 유한 tree 명령과 publication 고정 record·same-target active hold·
canonical/event/terminal의 한 COMMIT apply 조립이다. 회사 감사·managed identity
경쟁·기존 파일 전환도 필수 구조 범위이며 앱별 비필수 개선은 보류한다.

현재 게시와 runtime 배포는 서로 다른 단계다. Source/Core/schema/principal/
artifact 조립·구형 writer drain·실제 queue/Beat·독립 Workbench 릴리스와 전체
자연어 흐름 인수는 [WORK_ITEMS.md](WORK_ITEMS.md)에 남아 있다.

## Source 명령 후속 게시

게시·병합 추적은 [GitHub PR70](https://github.com/hurxxxx/miy/pull/70)이다.
PR의 실제 병합 여부·시각·merge SHA는 GitHub 기록이 원본이며, 로컬 결과
영수증은 아래 ignored 경로에 남긴다. 이를 개발/운영 배포 상태로 해석하지 않는다.

2026-10-08 사용자가 후속 변경의 커밋·push·GitHub PR·병합과 후속작업 식별을
명시적으로 승인했다. 기존 private native root File의 비활성 명령·동일 event
관측, 공유 Session routing 보완, 관련 검사·owner·진행 문서를 별도 PR로
게시했다. 서비스 활성화나 새 후속 기능 구현은 이번 게시에 포함하지 않는다.

첫 로컬 dev commit은 `851e3b660f2bd6f6ef0f61b03ec39bd000590300`, 동일
tree의 GitHub commit은 `1ef57d4fd4404fb60828265530960e5aa308e952`다.
GitHub main `26ca57677d9440d74362403c3fa1499bada4a632`를 부모로 삼아
현재 변경16개만 게시했고 내부 dev 이력은 추가하지 않았다. 이 문서·현재
상태의 PR70 추적 링크는 뒤이은 문서 commit으로 같은 PR에 포함한다.
작업 브랜치는 `feat/file-source-mutations-20261008`이며 dev/main과 다른
작업은 유지한다. upstream의 push-disabled 설정도 유지한다.

검증된 Source4와 실제 영향 검사 입력253개가 그대로인지 다시 확인했다.
기존 작성자41·고유 실제30·영향81개 및 독립 리뷰의 bounded 인수 근거를
사용하며 같은 검사를 반복하지 않았다. 모델·migration·grant·설정·생성
산출물·skills·CI 변경은 없다. GitHub ruleset과 main 보호 요구를 다시
조회했으며 현재 추가 필수 검사·리뷰가 없다. 실제 PR의 최종 상태를 확인해
일반 merge하고 이번 작업 브랜치만 원격·로컬에서 정리한다.

게시 대상·검증 입력·최종 commit/PR/merge/정리 결과의 로컬 영수증은 ignored
`.runtime/source-aggregate-publication/`에 기록한다. 커밋하지 않는 로컬
근거이며 민감한 로그나 환경 값을 GitHub에 올리지 않는다. 후속작업의
우선순위·의존성과 완료 기준은 [NEXT_STEPS.md](NEXT_STEPS.md)가 소유한다.
