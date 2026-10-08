# GitHub 게시 체크포인트

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

## 게시 결과

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

2026-10-08 사용자가 후속 변경의 커밋·push·GitHub PR·병합과 후속작업 식별을
명시적으로 승인했다. 기존 private native root File의 비활성 명령·동일 event
관측, 공유 Session routing 보완, 관련 검사·owner·진행 문서를 별도 PR로
게시한다. 서비스 활성화나 새 후속 기능 구현은 이번 게시에 포함하지 않는다.

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
