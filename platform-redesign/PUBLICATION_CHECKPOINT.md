# GitHub 게시 체크포인트

## 최신 전달 — PR94/MR101 정상 병합 후 full261의 필수 보완

Source8b7555a0은 필수260/job428 SUCCESS113.328338초 뒤 [GitHub PR94](https://github.com/hurxxxx/miy/pull/94)(999726a6)·[GitLab MR101](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/101)(1efd2054)으로 정상 병합했다. Tree4b5d8bab이 같고 소유 feature의 두 원격/로컬 브랜치를 정리했다. Persistent dev/main과 upstream 직접 push 차단은 유지한다.

후속 MR81/full261/job429는 API 실패3건으로 종료했다. 두 route 소유 정리와 stale fixture의 최소 수정본은 고유synthetic32·실제 PG26·독립 리뷰를 통과했다. 이 후속 후보의 새 feature 게시/필수 리뷰/병합/current full·fresh private24·MR81/guarded 운영은 남아 있다. Main/prod9e9280df와 기존 image를 유지하며 운영 쓰기0이다. Source1efd의 정상 private24는 인수했지만 후속 source의 완료로 대체하지 않는다. 별도 SDK/C2 후보는 이 전달에 포함하지 않는다. 아래 기록은 날짜별 역사다.

## 후속 세 경계 게시·개발/운영 반영

2026-10-08 사용자가 이번 변경의 커밋·push·upstream PR·병합과 개발/운영
배포를 명시적으로 지시했다. 대상은 auth-only 준비 reader, private flat
폴더 명령, Workbench 연결 확인 UX와 관련 검증/owner/진행 문서다.
GitHub 작업 PR과 내부 dev→main release_validation을 각각 확인한다.
플랫폼의 guarded immutable image 배포와 별도 Workbench 릴리스·백업·교체·
직접/공개 health 및 실제 UI 반영을 구분해 기록한다. 기존 operational
DB/grant/서비스의 official cutover를 이 코드 배포로 활성화하지 않는다.
실제 결과와 SHA는 PR/MR 기록과 후속 receipt가 원본이다.

### 후속 PR78/MR85 병합과225/393 저장 공간 선행조건 — 2026-10-08 UTC

Source `d43a46aaa490fad70957fad11a9d2975d832c923`는 실제 필수 pipeline224/job392 SUCCESS/58.822793초, allow_failure=false 후 정상 병합했다. GitHub PR78은 `cdfa602e000f30ae3a903b661899ba62e0f63b22`, 내부 MR85는 `ad42d0bcd721ab2deb455b764a33158b60da17cc`이며 tree `af422c706c5abe34d92596044a392fabf6ca114b`가 정확히 같다. 해당 feature 브랜치는 원격 두 곳과 로컬에서 exact tip으로만 정리했고 persistent dev/main·disabled direct upstream push를 유지했다.

자동 후속 MR81 pipeline225/job393은 FAILED/script_failure/18.494424초로 저장 공간 검사에서 종료됐다. source `ad42d0bc`, target `9e9280df`이며 제품 테스트는 실행0이다. 운영 반영은 하지 않았다. 실패 소스의 제품 테스트를 우회하거나 fast/skip으로 바꾸지 않으며, 외부 공간 선행조건 해소 후 같은 source의 정상 full 재검증이 필요하다.

현재·이전 운영 이미지와 canonical CI image, 데이터 volume은 보존했다. 소유 inactive image 두 개는25개 고유 layer/config·archive SHA256을 검증해 별도 임시 디스크에 온전히 보존한 뒤 정확한 미사용 ID와 그 private cache만 정리했다. 소유 scratch와 Git/source 보존본은 mode/hash/link를 확인해 원래 경로의 연결을 유지했다. 이 정리의 논리 크기를 실제 free gain으로 표시하지 않는다. Docker filesystem의 실제 여유는 계속15GiB 기준 미달이며 storage owner 조치가 필요하다. 최소15GiB·15%와 retention 정책·daemon/quota/snapshot은 변경하지 않았다.

15:45 실제 운영 검사에서 `9e9280df`와 기존 immutable image의 API/worker/Beat는 healthy, schema는 `artifact_sequences_20261006`, 기존 inactive/empty Files 조건은 그대로였다. 이것은 새로운 deployment나 migration 결과가 아니다. MR81 merge·fresh backup·prepare/deploy와 새 revision의 실제 smoke는 대기 중이다. 다음 구조 P0는 별도 로컬 worktree이며 이 전달 소스에 섞지 않았다. 안전한 증거는 ignored `revocation-feature-{commit,publish,status,merge,cleanup}.json`, `job392-success-receipt.json`, `release225-job393-storage-before-tests.json`, `owned-inactive-images-preserved-retirement.json`, `exact-archived-image-cache-*-retirement.json`과 latest production-before receipt가 소유한다.

### 후속223/391의 권한 회수 fixture 실패 — 2026-10-08 UTC

새 source `1d8cf66ecc1dd14f48576e6ef9e66a22ed89c9ae`는 필수 pipeline222/job390 SUCCESS 후 PR77의 `b12a4acc531fd6c76c744c51ab337901634ee8d2`, 내부 MR84의 `c401dd1a0ed1e88a5b32530c7df6ebe2923e0e55`로 정상 병합했다. 두 병합 tree는 `0ef60b8ab7cd877495fde7687de28dc2ec4613d6`이며 작업 브랜치만 원격·로컬에서 정리했다. 영구 dev/main과 upstream push-disabled를 유지했다.

후속 MR81 pipeline223/job391은 FAILED/script_failure,1,903.144108초다. API fast5,556 PASS/1 FAIL/3 SKIP이며 slow16·migration37·external15는 각각 통과했다. 실패는 `test_actual_lock_wait_rechecks_current_authority_and_rolls_back[session-descriptor]`의701행 reason assertion이다. `source_database_refused`와 기대 `current_execution_denied`의 차이이며 원 CI의 SQLSTATE는 없어 native 원인을 확정하지 않는다. 그 case의 뒤쪽 rollback assertions 실행을 이 실패 결과로 주장하지 않는다.

동일 CI 이미지의 실제 단독1 PASS와 통제된 느린 새 연결1 FAIL/SQLSTATE55P03을 별도로 관측했다. 후자에서 원본 파일·선택 이벤트 없음·Core·권한 보존을 실제 확인했다. fixture 두 파일의 사전 observer/revoker 연결로 한정해 제품 timeout·SQL·정확 reason·기존 assertions를 유지한다. 수정 후 실제8조합과 기존 default helper2개는10 PASS/23.72초이며 동일5.2초 지연도1 PASS/13.10초다. 네 가지 잔여 상태 보존과 SQL 오류 없음을 확인했고 독립 코드 리뷰 blocker0이다. 지연 재검증을 별도 고유 case로 합산하지 않는다. 새 source 게시·필수 리뷰와 전체 release_validation·MR81 병합·운영 배포는 대기 중이다. 운영은 기존 `9e9280df`와 정상 artifact를 유지한다.

### 이전 전체 릴리스의 API 통과와 웹 lint 실패 — 2026-10-08 UTC

- 합성 privacy capture 수정은 필수 pipeline219/job387 SUCCESS 후
  [PR76](https://github.com/hurxxxx/miy/pull/76)의
  `a4c27760c3706209e3beff150b8074a4d7d2a681`, 내부 MR83의
  `fd5038ba6b2821a5a87716b5181f6ff99df92816`으로 병합했다. 소유한 작업
  브랜치만 원격·로컬에서 삭제했고 dev/main은 유지했다.
- MR81 최신 pipeline220/job388은 FAILED/script_failure,2,096.498755초다.
  source `fd5038ba`, target `9e9280df`, source tree
  `827f30f7df504052bdaba96090698479d6001d21`의 관측이며 실행 전후
  source/target ref는 바뀌지 않았다. API fast **5,557 PASS/
  3 SKIP/0 FAIL**, slow16·migration37·external15는 각각 통과했다.
  이후 웹 lint의 `no-restricted-globals`3개로 전체 job이 실패했다.
  `apps/web/e2e/independent-apps.spec.ts`의 `innerWidth`2개와
  `registration-authorization.spec.ts`의 `location`1개가 대상이다.
- 최소 `window.innerWidth`2개·`window.location`1개 qualification을 마쳤다.
  scoped ESLint는3 errors/5 warnings에서0 errors/같은5 warnings로 통과했다.
  Prettier2·직접 E2E 타입 검사와 정확 세 qualification을 제거한 원래 byte
  재현을 확인했다. 새 테스트·lint disable·제품 변경은 없고 원래 assertions와
  동작은 유지한다. 수정 `96a0d7af75bec01b80ff26867d04cb4ed3ab5e1f`를
  [PR77](https://github.com/hurxxxx/miy/pull/77)과 내부 MR84로 게시했고
  필수 pipeline221/job389 SUCCESS를 확인했다. 아직 병합하지 않았다.
  후속 합성 preflight의 Workbench Python773 PASS/25 SKIP과 등록3 FAIL을
  구분한다. 등록 fixture 한 파일에 인증된 initialize-only loopback peer를
  제공했고 기존 readiness15·실제 등록 브라우저3 PASS를 확인했다.
  웹 첫 Hermes evaluate timeout은 동일 입력의 단독 실행에서 통과했고
  전체 웹 브라우저 묶음도 단독42 PASS다. 새 source 리뷰·병합과 전체 release_validation·
  운영 병합과 배포는 아직 완료되지 않았다.
  main/prod는 `9e9280df`이며 새 운영 배포는 없다. Workbench187개 제품 경로는
  별도 배포와 같고 actual native turn, official operational authority 전환과
  네 영역 전체 인수는 계속 남는다.

현재 실패의 안전한 metadata·진단은 ignored
`.runtime/delivery-resume-monitor/job388-failure-receipt.json`과
`.runtime/structural-next-delivery/release388-fixed-{progress,failure-summary,eslint-diagnostics}.json`이
소유한다. 수정·scoped 검사는 `.runtime/release388-e2e-browser-globals/REPORT.md`와
final input receipt가 소유한다. 아래218/386 기록은 당시 실패·로컬 보완 시점의 역사이며 현재
게시 또는 전체 CI 성공으로 소급하지 않는다.

### 이전 전체 릴리스 검증 실패와 로컬 보완 — pipeline218/job386

- 필수 리뷰217/383을 통과했고 [PR75](https://github.com/hurxxxx/miy/pull/75)는
  `1bd8892564656ede91d44dc7686b2418c7e42e46`, 내부 MR82는
  `84245339e63471d7dac96ad79a139ddcb25df7bc`로 병합했다. 소유한 두 작업
  브랜치만 원격·로컬에서 삭제했고 영구 dev/main은 유지했다.
- MR81 최신 pipeline218/job386은 같은 source `84245339`에서 FAILED/
  script_failure다. job1,959.693583초, API1,688.03초의 실제 결과는
  3 FAIL/5,554 PASS/3 SKIP다. 실패는 Qdrant 합성 privacy capture2개와
  publication storage의 unrelated-thread capture1개다. API 전체 성공이나
  이후 릴리스 단계의 통과로 표시하지 않는다.
- Alembic 공개 `fileConfig`는 이미 생성된 HTTP logger를 비활성화하므로
  앞선 단독 capture 통과만으로 whole-suite 상태를 인수할 수 없었다. 두
  테스트 파일에서 정확 emitter4개의 임시 직접 caplog·disabled 해제와 기존
  handler 상태 복원을 보완하고 제품 filters는 유지했다. Qdrant에는 같은 http11의 다른 thread
  positive assertion도 추가했다. 실제 초기3 FAIL과 수정 후 선택3 PASS를
  구분한다. 실제 동일 CI 이미지의 read-only public snapshot에서 common
  security 포함3파일을 전체·역순으로 실행해 각각188 PASS를 확인했다.
  같은188개와 그 안의 선택3개는 중복 합산하지 않는다.
  초기 probe의 teardown2 ERROR는 pytest의 일시 capture handler까지 원래
  handler로 세던 검사 오류다. 원래 handler-list identity·비pytest sentinel·
  filters 검사를 유지해 교정했으며 제품 로그 누출로 분류하지 않는다.
- 준비384/385의 저장소 기준 실패는 별도 역사다. 소유 비활성 official
  build의 exact8 cache 정리 후 실제 기준15.5GiB·15.4% 통과를 확인했다.
  도구 보고6.102GB는 실제 available 증가의 근거가 아니다. 이 캐시 정리는
  image·container·volume·daemon을 변경하지 않았다.
- 수정은 아직 로컬이다. 새 필수 리뷰·게시·MR81 전체 검증과 운영 병합·
  배포는 대기 중이다. main/prod는 기존 `9e9280df`를 유지하고 Workbench187개
  제품 파일은 별도 배포 `0c1bf0fe`와 같아 재배포하지 않았다. 새로운 official
  operational authority나 서비스 profile을 활성화하지 않았다.

아래는 각 실행 당시의 역사적 경과이며 최신 성공으로 소급하지 않는다.

### 최신 중단 지점 인수 — 2026-10-08 UTC

- `24211c5fbbda45c8ae0efd43200e96df7bc4ade5`의 필수 리뷰214/380을 통과했다.
  [PR74](https://github.com/hurxxxx/miy/pull/74)는 `1e3a0f2e`, 내부 MR80은
  `a91b2d38`로 일반 병합했다. 소스·두 병합의 Git tree는 동일하다.
- 소유한 두 작업 브랜치를 원격·로컬에서 삭제했고 영구 dev/main과
  emergency branch, Workbench 작업 경로는 보존했다. upstream 직접 push는
  계속 비활성이다.
- [MR81](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/81)은
  `a91b2d38`의 dev→main 전체 검증이다.215/381이 API 단계3 FAIL/148 ERROR로
  실패했으며 같은 실패 소스의 CI를 재시도하거나 운영에 병합하지 않았다.
  45개의 권한 reader setup/cleanup 오류는 제한 계정의 역할 생성,
  나머지103개 오류는 테스트 worker import다. 실패3개는 필수 writer 인자
  누락과 기존 전역 로그 정책 아래의 합성 로그 캡처2개다.
- 현재 별도 수정 브랜치에서 native 임시 서버·fixture·테스트 진입점을
  보완했다. 실제 같은 메이저 CI 이미지·비특권 서버와 정리를 확인했다.
  권한·데이터57개, 이전 실패 관련207개를 확인했고 공유 상태의16개 fixture
  오류는 수정 후16개 통과했다. native31개 파일에서 새로 드러난4 FAIL/
  37 ERROR는 소유 worker DB 설정과 이전 리뷰 전용 경로를 정정한 뒤
  해당3개 파일 전체125개 통과했다. 중복 성공은 합산하지 않는다.
  공유/운영 계정 권한과 제품 보안 계약은 유지한다. 검증 후 새
  필수 리뷰·통합과 MR81의 최신 전체 검증을 받는다.
- 보완064b2aeb을 [PR75](https://github.com/hurxxxx/miy/pull/75)와 내부 MR82로
  게시했다. 자동 리뷰216/382는 구버전 Docker fallback의 익명 볼륨 정리를
  P2로 차단했다. major별 데이터 경로에256MiB tmpfs를 적용하고 소유
  컨테이너의 익명 볼륨을 함께 제거하도록 최소 수정했다. 실제 PG17·18의
  정상·시작 후 실패·body 예외6개에서 메모리 크기·볼륨0·소유 자원 정리를
  확인했다. 새 소스의 필수 리뷰를 받고 이전 실패 소스는 재시도하지 않는다.
- 개발 실제 로그인·런처·Provider 로그아웃·공개 Vite 제공 소스2개의
  SHA 일치를 확인했다. 기존 backend 서비스는 재시작하지 않았다.
  운영은 이전9e9280df 이미지/스키마를 유지하며 전체 gate 통과 뒤 전환한다.
  Workbench187개 제품 파일은 배포0c1bf0fe와 동일해 추가 배포 대상이 아니다.

실행 원본은 ignored `.runtime/structural-next-delivery/`,
`.runtime/delivery-resume-monitor/`, `.runtime/dev-platform-deployment/`와
`.runtime/release381-{authority-fix,qdrant-fix,docs-fixture,native-fixture}/`가
보존한다. 아래 기록은 각 실행 당시의 역사적 경과다.

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

### 운영 시작·복원 검토 — 2026-10-08 UTC

자원·관측 수정은 `07c72e98ff65e95fa0d86edd15a1b3d6a932a2a3`로 게시하고
PR74와 MR80 설명을 최종 범위로 갱신했다. pipeline210/job376은 인증 오류
없이 실제 리뷰했으나 `up`의 복원 기준 P1과 공통 종료 timeout P2를 지적했다.
이미지 태그만으로 기존 런타임을 증명하면 검사에서 거부한 candidate를
복원 중에 시작할 수 있다. 중지 전에 실제 healthy 컨테이너·불변 이미지·Compose
identity를 캡처하고 새 런타임 시작 전 변경되지 않은 기존 ID만 직접 복원한다.
현재 Compose 파일과 기존 정의가 같다는 보장은 하지 않는다. 변경된 기존 상태는
중지 전에 거부하며 첫 실행은 검사 성공 전에 복원 대상으로 취급하지 않는다.
worker의 기존65분 stop grace를45초로 덮어쓰던 공통 옵션도 제거한다.

개인 앱 자원 한도·관측의 앞선 수정은 보존한다. 관련116개와 소유 syntax·
format·diff 검사를 확인했고 실제 고정 Compose의 미지원 start 옵션과
config hash 해석 차이도 정정했다. 정확 입력은 ignored
`.runtime/prod-app-prior-runtime/`에 기록했다. 최종 소유4 입력 일치와 독립
검토 차단0을 확인했으며 새 source의 필수 리뷰와 전체 release_validation을
진행한다.
기존 실패 source를 재시도하지 않으며 운영 checkout·image·DB는 기존 상태다.

### 최신 개발 반영·기존 테스트 계약 정정 — 2026-10-08 UTC

복원·종료 유예 수정은 `ddb29c318e02c3aaf3b8e0a39fb78ed170a694a6`로 두 저장소의
기존 작업 브랜치에 게시했다. 개발 supervisor를06:41:22 UTC에 한 번 재시작해
그 source와 tree의 일치를 확인했고 API·web·worker·Beat, 직접/공개 readiness,
API 로그인·bootstrap18·실제 브라우저 런처12·script error0·로그아웃을 확인했다.
health revision은 `unmanaged`이므로 source16 해시와 실제 재시작 근거로만
배포를 설명한다. 기존 개발 기록과 Workbench187 제품 파일은 보존했다.

pipeline211/job377은 인증·실행·출력 오류 없이834초의 실제 리뷰를 마쳤으나
기존 테스트 계약 두 건 P1으로 MERGE_BLOCKED됐다. projection 테스트가 제거된
함수·설정의 monkeypatch 대상과 과거 Session 대역을 사용하고, FK-enabled
Files SQLite fixture는 새 writer_scope의 기준 테이블·scope 행을 준비하지
못했다. 제품 권한·schema·FK를 완화하지 않고 현재 projection 전달 경로와
official.suite 제어 데이터를 준비하도록 기존 테스트만 정정한다.

에이전트는 projection 단위 테스트와 Files FK fixture를 서로 다른 파일에서
담당했다. Files15·projection57 로컬 검사와 소유 format/lint가 통과했다.
실제 실패·수정·영향 검증을 보존했고 최종 입력 일치·제품 변경0·독립 검토
차단0을 확인했다. 기존 함수100개와 native lifecycle 단언을 유지하며 새
source의 필수 리뷰를 받는다.
dev→main 전체 release_validation·운영 배포는 아직 진행하지 않았다.
ignored `.runtime/dev-platform-deployment/latest-20261008T064107259159Z/`,
`.runtime/delivery-resume-monitor/job377-safe-diagnosis.json`과
`.runtime/review-fixture-fixes/`가 정확 입력·판정·실행 범위를 보존한다.

### 재기동 허용과 자동 복원 근거 분리 — 2026-10-08 UTC

테스트 계약 정정은 `de1b79cb66c6a89a2522e6298b4242aaf4161402`로 PR74와
MR80에 게시했다. pipeline212/job378은 인증·실행·출력 오류 없이683초에
실제 MERGE_BLOCKED P2 한 건으로 종료됐다. 강화된 기존 건강성 조건이
중지·비정상 컨테이너의 정상적인 forward `up`도 차단하는 경계였다.

이미지·Compose identity는 검증하고 상태 관측 실패는 거부하면서, 관측이
완전한 중지·비정상 상태는 stop→migration→gate→start를 허용하도록 보완한다.
자동 복원 target은 중지 전 정상인 기존3 컨테이너가 모두 확인될 때만 저장한다.
gate 실패로 거부된 candidate를 복원 중 시작하지 않는 앞선 계약은 유지한다.
관련 운영 스크립트139개와 소유 syntax·format·diff가 통과했으며 초기 실패와
Health 정보가 없는 상태의 후기 보완을 각각 보존했다. 최종 입력 일치와 독립
검토 차단0을 확인했다.
같은 실패 source를 재시도하지 않고 수정 source의 필수 리뷰를 다시 받는다.
기존 제품·테스트 fixture는 보존하며 개발 서비스의 추가 재시작은 수행하지 않았다.
전체 release_validation과 운영 배포는 아직 별도 완료 조건이다.

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

### 같은 로그인 화면 이동의 대기 저장 — 2026-10-08 UTC

재기동·복원 조건 수정은 `70d35b7a7924c4f14443faa52a052d256d6f3c98`로
PR74와 MR80 작업 브랜치에 게시했다. pipeline213/job379는 인증·실행·출력
오류 없이546초의 실제 리뷰를 완료했으나 Bento의 대기 중 저장 유실 P2로
MERGE_BLOCKED됐다. 첫 저장 중 추가 편집을 큐에 넣은 뒤 같은 로그인에서
다른 화면으로 이동하면 keyed view의 unmount 검사가 두 번째 저장을 버린다.

데이터 유실은 이번 구조 변경의 필수 수정으로 처리했다. 로그인·credential
세대가 바뀐 뒤 오래된 쓰기를 막는 계약을 유지하면서 같은 로그인 일반 이동의
대기 저장을 보존한다. Bento22·실제 Provider10 clean 검사가 통과했고 소유5
입력 일치·독립 검토 차단0을 확인했다. 작성과 독립 검토를 분리했다.
영향 소비자19개, 정상 설정의 소유·포털 타입4개와 web architecture를 확인했다.
앱별 비필수 기능 개선은 추가하지 않는다. 실패한 source를 재시도하거나
병합하지 않으며 운영은 이전 source·image·schema를 유지한다.

ignored `.runtime/delivery-resume-monitor/job379-safe-diagnosis.json`과
`.runtime/bento-save-queue-fix/`, `.runtime/bento-save-queue-review/`에
고정 분류·공개 코드의 기술적 원인·정확 입력·수정 검증을 기록한다.
원문 prompt·trace·자격정보나 사용자 문서 내용을 저장·게시하지 않는다.

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

## 2026-10-08 — 다음 inactive auth HTTP 로컬 인수

공식 auth-only HTTP의 현재 로컬 검증은 pure31 PASS/8.60초, 실제 PostgreSQL·HTTP13 PASS/27.42초, 기존 composition10 PASS/10.75초다. 서로 다른 선택31+13은 새44개이고 기존10개는 별도 영향 범위다. Raw·반복 host cancellation와 AnyIO 대기/실행 취소에서 worker 종료·Session 정리 전 admission을 반환하지 않는 경계를 확인했다. 네 HTTP GET은 genuine 현재 앱 세션/binding·제한된 auth PostgreSQL 역할·실제 Source ACL을 사용했다. Business Source fixture는 권한 있는 합성 계정이므로 최소 Source operational 역할 전체 인수로 확대하지 않는다. Profile14표/87열과 기존 기본 인증·비활성 ASGI를 유지했고 API architecture/i18n·independent app schema/OpenAPI/contract source --check를 통과했다. Operational role/grant·WS·공식 서비스 전환은 아직 하지 않았다.

이 변경은 별도 `feat/official-auth-http-20261008` worktree의 로컬 미커밋이다. 필수 리뷰·정상 feature 병합과 최신 전체 release 검증을 각각 확인한다. 저장 공간 부족225/393과 운영 미배포 상태를 로컬 통과로 대체하지 않는다.

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

## 2026-10-08 17:31 이후 — WS 정상 전달과 전체229

WS source `7ae28d38cdc68a6459b8baaab6f63febd43d0c78`는 필수228/396 SUCCESS(92.527333초) 뒤 [GitHub PR80](https://github.com/hurxxxx/miy/pull/80)·[내부 MR87](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/87)로 정상 병합했다. GitHub merge는 `0902a239`, 내부 dev merge는 `b4d6445e`이며 tree `5ace83b9f07c1b1a09ee04b996bf9fdc1966cb2d`가 같다. 소유 feature 브랜치의 양쪽 원격·로컬 정리를 완료했고 persistent dev/main·upstream 직접 push 차단을 유지했다.

[MR81](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/81)의 최신 full229/397은 정확 source `b4d6445e`, target `9e9280df`, 같은 tree에서 저장 공간 검사로 FAILED/script_failure(24.481728초), 제품 테스트0이다. feature 필수 리뷰의 성공을 전체 릴리스나 운영 배포로 확대하지 않는다. 추가 공간 확보 후 최신 head의 정상 full 검증이 필요하며 운영은 기존 revision을 유지한다.

## 2026-10-08 18:38 — Workbench cold resume 정상 전달

원 Task/thread의 cold resume 수정 source `2de4b06569e06dae0ad8a032c4d9d39e95c3412b`는 필수230/398 codex_review SUCCESS(53.071164초, allow_failure=false) 뒤 [GitHub PR81](https://github.com/hurxxxx/miy/pull/81)과 [내부 MR88](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/88)로 정상 병합했다. GitHub merge는 `bc5fe231`, 내부 dev merge는 `436c7792`이며 tree `e356a601b2f2329e2aacfdc4ceb0acc597c41694`가 같다. 소유 feature 브랜치만 양쪽 원격·로컬에서 정리했고 dev/main과 upstream 직접 push 차단을 유지했다. 실제 원 Task의 동일 thread 후속 요청까지 완료한 로컬 증거를 사용하며 새 운영 executor 설정·Workbench 서비스 배포는 포함하지 않는다.

MR81의 최신 full231/399는 source `436c7792`, target `9e9280df`, 같은 tree에서 FAILED/script_failure(24.72378초)다. 저장 공간 선행조건에서 실패했고 제품 테스트는0이다. 15GiB·15% 기준은 유지하며 정상 full 성공 전에 main 병합·새 운영 배포를 하지 않는다.

다음 게시 단위는 준비된 Whiteboard Source ACL callback9개와 현재 계획/검증 추적6개다. 기존 기본 경로·운영 역할·ASGI·hub/room을 유지하는 비활성 조립이며 최종 독립 검토와 필수 feature 리뷰·정상 병합은 별도 확인한다.

## 2026-10-08 18:51 — Whiteboard Source ACL 정상 전달

Source ACL source `a6705f0f010ff6c57d03548ba1c7ebdc317b4f2f`는 필수232/400 codex_review SUCCESS(61.914681초, allow_failure=false) 뒤 [GitHub PR82](https://github.com/hurxxxx/miy/pull/82)와 [내부 MR89](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/89)로 정상 병합했다. GitHub merge는 `886b5633`, 내부 dev merge는 `4764fc2c`이며 tree `fd5403ae44f430de22ef091a458f517705983ec8`가 같다. 소유 feature 브랜치의 양쪽 원격·로컬 정리를 완료했다. 준비된 비활성 ACL 조립을 전달한 것이며 Source operational role·room 초기화/영속화·공식 service cutover 완료가 아니다.

후속 full233/401은 source `4764fc2c`, target `9e9280df`, 같은 tree에서 저장 공간 선행조건으로 FAILED/script_failure(22.998495초), 제품 테스트0이다. main/prod는 기존 revision이고 새 운영 배포는 없다. 필수 기준을 낮추거나 반복 수동 retry를 하지 않으며 지속 headroom 뒤 최신 head의 정상 full 검증을 진행한다.

다음 게시 단위는 Workbench의 최소 native executor source6와 설치 entrypoint1·계획 추적6이다. 원 Task의 실제 native 흐름을 검증한 앞선 소스와 재사용 가능한 설정 정의를 구분한다. 새 source-only 정의는 별도 필수 feature 리뷰·정상 병합을 확인하며 설치·운영 설정·Workbench 별도 배포 완료로 보고하지 않는다.

## 2026-10-08 19:12 — 최소 native executor 정의 정상 전달

Source `44e9217b1f1404d3a8822069779bf80310532e1f`는 필수234/402 codex_review SUCCESS(64.006274초, allow_failure=false) 뒤 [GitHub PR83](https://github.com/hurxxxx/miy/pull/83)과 [내부 MR90](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/90)로 정상 병합했다. GitHub merge는 `6ee1faf4`, 내부 dev merge는 `c7520d05`이며 tree `c6856d33488ff5a067b2dd0cda70f8ac97dc363a`가 같다. 소유 feature 브랜치만 양쪽 원격·로컬에서 정리하고 persistent dev/main과 upstream 직접 push 차단을 유지했다.

최소 정의와 설치 entrypoint를 source-only로 전달했다. 영구 cache/unit 설치·실제 mount/자원/native 정책·보호 설정·별도 Workbench 서비스 배포는 남아 있다. 앞선 실제 원 Task 검증이나 source parser 통과를 새 운영 적용으로 확대하지 않는다.

MR81의 최신 full235/403은 source `c7520d05`, target `9e9280df`, 같은 tree에서 저장 공간 선행조건으로 FAILED/script_failure(21.894737초), 제품 테스트0이다. 새 main 병합·운영 배포는 없다. 19:01의 읽기 전용 prod 검사에서는 기존 revision/image의 API·worker·Beat healthy와 schema `artifact_sequences_20261006`을 확인했다.

## 2026-10-08 — 재시작 복구와 기존 room Source 초기 읽기 인수

서버 재시작 뒤 Source7·보호62·dev `c7520d05`와 기존 prod `9e9280df`를 확인하고 미완료 단계만 재개했다. 기존 collab 상태를 fresh readOnly Source transaction에서 읽는 명시적 비활성 초기 로더를 인수했다. 앱·edit ACL을 읽기 전후 재조회하고 정리 뒤 동일 auth callable·actor/session 및 server assembly identity를 재검증한다. 동일 paired SELECT의 scene/snapshot/Yjs 합계8MiB를 SQL CASE로 전송 전에 제한하고 detached DTO를 재검증한다. 부분 설정·missing/stale/invalid/초과 상태는 private503/1013으로 거절하며 legacy init/repair로 우회하지 않는다. Global hub persistence와 writer/CAS·COMMIT unknown, Docs Source·최소 operational 역할·cutover는 여전히 필수 잔여다.

기준 base c7520d0553fde63401ebd03822ba4ea49ff00ec8, main/prod9e9280df, GitHub main6ee1faf4의 로컬 인수 기록이다. Source7·추적6만 정상 commit/push/필수 codex_review/양쪽 PR·MR 병합 대상으로 고정한다. Feature 전달은 dev→main full 성공과 운영 반영을 대체하지 않는다. 재시작 뒤19:39 기존 API·worker·Beat healthy/schema 확인,19:40 공간14.3024GiB·14.5573% free로 두 기준 실패. 추가 삭제·기준 완화·새 main/운영/Workbench 배포는 없다.

## 2026-10-08 20:00 — 기존 Whiteboard room 초기 Source 읽기 정상 전달

Source `f833768973502174d539f25761afef598d1ad7f0`는 필수236/404 codex_review SUCCESS(53.454217초, allow_failure=false) 뒤 [GitHub PR84](https://github.com/hurxxxx/miy/pull/84)와 [내부 MR91](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/91)로 정상 병합했다. GitHub merge는 `e5fef219`, 내부 dev는 `5d909dc3`, tree `865f66a959abad284adda215c7989d0a9cef7b13`가 같다. 소유 feature 브랜치만 양쪽 원격·로컬에서 정리했다. Persistent dev/main과 upstream 직접 push 차단은 유지한다.

MR81의 최신 full237/405는 source `5d909dc3`, target `9e9280df`, 같은 tree에서 저장 공간 실패25.308425초/tests0다. main/prod는 기존9e이고 새 운영·Workbench 배포는 없다. Source-only local65·impact157과 실패 한계는 VALIDATION이 소유한다. 이후 Docs worktree는 red1의 기존c752 입력을 보존하고5d909로 fast-forward했다.

## 2026-10-08 20:30 — Docs Source/Core 분리 전달 준비

Base dev5d909/main9e/GitHub main e5fef219에서 Source10·추적 문서6의 단일 범위로 전달한다. 신규143개·기존219개와 생성 계약은 통과했고, 기본 Docs writer/relay/cancel8개와 최종16개 독립 freeze 리뷰를 마친 뒤 일반 hook commit·원격 feature push·GitHub PR·GitLab dev MR 필수 codex_review·정상 병합·소유 브랜치 정리를 순서대로 진행한다. 후속 source SHA/tree·PR/MR·리뷰 pipeline/job·merge/cleanup은 실제 완료 receipt에서만 인용한다. 이 문서 시점은 커밋/병합 전이다.

Dev→main의 MR81 전체 릴리스 gate를 유지한다.20:28 읽기 전용 측정14.2954GiB/14.5538% free는 저장 공간 기준 미달이며, 새 main/prod 또는 별도 Workbench 배포는 없다. 전체 구조 인수·운영 활성화·SDK/영구 실행기 작업 완료를 주장하지 않는다.

2026-10-09 01:58 후속: 기본 Docs 원8개 bounded 재검사는 PASS/25.49초다. 첫 장시간 실행/exit137와 원인 미확인 한계는 VALIDATION에 보존한다. 최종 Source10·추적6을 freeze하고 독립 리뷰를 완료한 뒤 일반 게시를 진행한다. 이 추가 기록도 커밋/병합 전이다.

## 2026-10-09 02:07 — Docs Source/Core 읽기 전달 완료

일반 hook commit40b450324c203251b469727a5cac4eeb42554d4d/treee7b9e489779c521cad4bd7779d09f2db14a53a4f를 양쪽 소유 feature에 push했다. 필수238/406 codex_review SUCCESS/74.328198초·allow_failure=false·exact source 뒤 GitHub PR85는7242b86542f05d0e0ce285cb38b76c9b2fd771ff, 내부 MR92는e25c1934c7374c46a630dad486f2c5d8bce52e9b로 정상 merge했다. 양쪽 merge tree는 exact e7b9e489이고 primary dev를 fast-forward했다. 소유 feature를 양쪽 원격에서 exact-tip으로 삭제하고 source worktree를 detached 보존한 뒤 로컬 feature를 정리했다. Persistent dev/main과 upstream push disable은 유지했다.

MR81 최신 full239/job407은 저장 공간 선행조건24.291815초 실패·제품 tests0다. Main/prod9e9280df는 그대로이며 새 운영 또는 별도 Workbench 배포는 없다. 최초 default8 검사 장시간 지연 원인 미확인과 실제 bounded8 PASS는 VALIDATION이 소유한다. 후속 기존 Docs room Source6 읽기는 이 merge를 기준으로 red1FAIL/0.56초·collection/setup0을 보존하고 구현한다.

## 2026-10-09 02:38 — Docs room Source 전달 준비

Base deve25c1934/main9e/GitHub7242b865에서 Source6·추적6의 범위로 신규104·기존370 검사와 생성 계약을 통과했다. Native SQLNULL assertion 시점 문제의 원본·실제 진단·기대값 보존 교정은 VALIDATION을 참조한다. Owner format/check와 최종12개 독립 수락 뒤 일반 commit/push·양쪽 PR/MR·필수 Codex review·정상 merge·소유 feature 정리를 진행한다. 이 기록 시점은 커밋/병합 전이고 source/tree·원격ID는 실제 완료 receipt에서 추적한다. Full239/407 storage 실패·main/prod9e 유지·새 운영/별도 Workbench 배포 없음은 유지한다.

## 2026-10-09 02:50 — Docs room PR86/MR93 전달 완료

Source `a9fe6bf85a8c7884d5b8f659b4fc388c336802ea`는 Source6·추적6의 독립 수락 accepted=true/blockers0 뒤 일반 hook으로 커밋했다. 필수 pipeline240/job408은 SUCCESS/56.719112초, allow_failure=false다. [GitHub PR86](https://github.com/hurxxxx/miy/pull/86)은 `667047af4c27b9cc0c8257f360869323b3d8cc66`, [GitLab MR93](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/93)은 `499aff33c451ebaf893939928e497497b78d50ca`로 정상 병합했다. 두 merge tree는 `f3ba8ac08ab9266501e9bf29aa4beb60c6a3fd57`로 같다. 해당 feature만 양쪽 원격·로컬에서 exact tip으로 정리하고 detached 소스 worktree·persistent dev와 upstream direct push 차단을 보존했다.

자동 후속 MR81 전체241/409는 FAILED/script_failure/23.871109초로 저장 공간 선행조건에서 종료됐다. 제품 테스트0이며 dev499aff33/main·prod9e9280df다. 운영 배포·별도 Workbench 배포와 영구 native config 설치는 하지 않았다. 최소15GiB 및15% 기준을 유지하며 지속 여유와 최신 source/target/tree 전체 성공 뒤 릴리스를 이어간다. 원본 실패·로컬 검증은 이전 기록으로 보존한다. 안전한 원본 receipt는 ignored `docs-room-source-feature-{commit,publish,status,merge,cleanup}.json`·`docs-room-source-independent-review.{md,json}`·`release241-job409-storage-before-tests.json`이다.

## 2026-10-09 03:53 — Whiteboard 저장 안전성 로컬 검증

Owned feature `feat/whiteboard-persistence-safety-20261009`, base `499aff33`, Source7+추적6=13개다. 신규 pure16 PASS/5.15s·실제 PostgreSQL/Yjs32 PASS/60.64s =48개다. 기존 prepared/auth/composition466 PASS/329.54s·원 Whiteboard 구조6 PASS/16.96s·원 Docs default8 PASS/26.33s =고유 영향480개다. 원 red4의 첫 green과 이전 반복 검사는 더하지 않는다. API architecture/i18n·생성 계약은 통과했다. 최종 문서/범위 freeze와 독립 수락·필수 원격 리뷰/병합은 이후 별도로 기록한다.

소스 게시·필수 리뷰·정상 양쪽 병합·소유 브랜치 정리는 아직 진행 전이며 승인된 순서로 이어간다. Main/prod는 `9e9280df`다. Source-only 활성화·새 운영/Workbench 배포로 해석하지 않는다.

## 2026-10-09 04:24 — 필수 리뷰의 공유 저장 상한 수정

Source6da7c943의 PR87/MR94 필수 pipeline242/job410은 FAILED/115.932917초였다. P2는 flush마다 새 limiter1을 생성해 room 간 전체 SQL worker 상한이 없다는 회귀다. 이 실패를 성공이나 면제로 바꾸지 않고 실제 거절 기록과 기존48·480 성공 receipt를 별도로 보존했다.

최종 신규 pure16 PASS/5.47s·native35 PASS/90.18s =51개, 기존 prepared/auth/composition466 PASS/311.04s·원 WB6 PASS/15.61s·원 Docs8 PASS/25.19s =480개다. 기존48개 및 첫 통과·재검사 횟수는 더하지 않는다. API architecture/i18n·생성 계약 통과이며 최종 문서 freeze·새 독립 인수·새 필수 리뷰는 별도로 진행한다.

기존 PR87/MR94와 feature 브랜치를 그대로 사용해 정상 후속 commit/fast-forward push·새 필수 review·normal merge 뒤 exact tip cleanup을 진행한다. 원 실패 job을 재시도하거나 우회하지 않는다. 병합·새 운영 배포는 아직 완료하지 않았다.

## 2026-10-09 05:08 — 최종 저장 대기 중 상태 보존

Source705a13dc의 PR87/MR94 필수243/job411은 FAILED/78.614494초였다. P1은 공유 저장 슬롯4개가 포화됐을 때 최종 flush 전체에 적용한 cleanup timeout이 admission 대기를 취소하고 미저장 YDoc을 해제하는 문제다. 이전242/410의 상한 거절과 각각의 실제 실패·이전 로컬 성공을 보존하며 필수 리뷰 실패를 면제하거나 성공으로 바꾸지 않는다.

최종 신규54개는 pure16 PASS/7.10s와 native38 PASS/131.44s다. 기존 영향480개는 prepared/auth/composition466 PASS/372.13s·원 Whiteboard6 PASS/25.87s·원 Docs8 PASS/35.69s다. 이전48/51개·재실행 횟수는 더하지 않는다. API architecture/i18n·생성 계약을 통과했다. 최종 문서·Python 검사와 새13파일 독립 인수 및 새 source의 필수 리뷰는 별도 단계다.

기존 PR87/MR94·feature branch를 재사용한다. 실패 job 재시도·강제 push·gate 우회 없이 새 source로 정상 필수 리뷰를 받는다. 이 기록 시점에는 병합·새 배포를 완료하지 않았다.

## 2026-10-09 05:22 — 저장 안전성 전달과 최소 Source writer 착수

Whiteboard 저장 안전성 최종 Source `ba9fee1e`/tree `fef48496`는 필수244/job412 SUCCESS/94.736405초 뒤 GitHub [PR87](https://github.com/hurxxxx/miy/pull/87)→`2c1cb019`와 내부 [MR94](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/94)→dev `aafbccb2`로 정상 병합했다. 양쪽 tree는 같고 소유 feature 브랜치의 양쪽 원격·로컬 정리를 완료했다. Dev는 persistent integration branch로 유지하며 main/prod는 `9e9280df`다.

새 전체245/job413은30.366867초에 저장 공간 선행조건에서 실패했다. 제품 테스트0이며 필수 최소15GiB/15% 기준을 유지한다. 이 결과를 source 리뷰 성공으로 대체하지 않고 새 운영·별도 Workbench 배포0를 유지한다.

다음 구현은 `aafbccb2` 기준 별도 worktree에서 비활성 Whiteboard Source service writer/profile이다. 실제 migration head `file_effect_20261007`, 기존 migration30개 및 보호85개를 다시 동결했다. 새 migration·service admission·role checker와 새 테스트·owner2, Root 추적6을 분담한다. 두 Source 표의 SELECT8열·UPDATE4열과 제한된 capability 하나부터 인수하며 공급된 LOGIN/NOLOGIN 역할·원래 principal identity·정확한 권한·기존 mapping replay·실제 session_user와 SQL 락을 검증한다. 현재는 구현 착수이며 새 테스트를 실행하거나 인수한 것으로 표시하지 않는다.

Migration은 정상 legacy/hardened 환경에서 비활성 capability만 설치한다. 준비·admission에는 hardened guard가 필요하다. Session/factory/COMMIT/cleanup 수명은 caller가 소유하며 Core 사용자 ACL COMMIT fence·hub Source factory 연결·운영 역할/grant/config/service 전환은 이번 범위가 아니다. Current actor fence, cross-hub content CAS, 영속 unknown 복구와 공식 서비스 cutover는 여전히 필수 잔여다. 기존 skills/harness는 절차로 사용하지 않고 현재 코드·owner·중요 계약만 사용한다. 앱별 비필수 기능과 다중 사용자는 보류한다.

## 2026-10-09 05:59 — 비활성 최소 Source writer 로컬 검증

최종 새 pure10 PASS/0.62s·실제 PG18 native69 PASS/56.98s =79개다. 기존 role/Source ACL/room/저장204 PASS/203.03s·원 migration 함수5 PASS/6.35s =209개는 별도 영향 범위다. API architecture/i18n·생성 API/schema/OpenAPI/contract-source와 scoped Python5 검사는 통과했다. Owner2·Root tracking6의 최종 Markdown freeze와 독립/필수 원격 리뷰·게시/병합은 별도로 진행한다. Network-none·실제 env/credentials0·소유 컨테이너 정리를 확인했다.

현재13개 소유 파일만 별도 feature로 정상 commit/push·upstream PR·내부 MR·필수 review 후 정상 병합과 exact-tip cleanup을 진행한다. 게시/병합 완료와 새로운 full release 성공을 현재 기록으로 주장하지 않는다.

현재 dev `aafbccb2`·main/prod `9e9280df`, 최신 full245/413 저장 공간 선행조건 실패/제품 테스트0와 새 운영/별도 Workbench 배포0를 유지한다. 이 단계는 Source factory·저장 연결·사용자의 현재 Core/Source ACL COMMIT fence·cross-hub content CAS·영속 unknown 복구·Docs 저장·공식 서비스 cutover를 완료하지 않는다. 다음 actor fence는 현재 사용자 구현 승인 안에서 별도 범위와 보호표를 확정한다. Same-DB SQL 잠금을 실제 separate DB 보장으로 표시하지 않으며, queued Yjs의 credential attribution/expiry와 모든 owner/direct/group/PMS/meeting edit closure가 활성화 전 필수다. Native SDK/toolchain 실제 pin 검증/설치·개인 앱 전체 자연어 흐름도 남아 있다. 앱별 비필수 기능·다중 사용자는 보류한다.

## 2026-10-09 06:22 — 최소 Source writer 전달과 actor-owner 경계 착수

현재 dev는 `746258cd`, main/prod는 `9e9280df`다. 비활성 최소 Whiteboard Source writer/profile은 필수246/job414 성공 뒤 [PR88](https://github.com/hurxxxx/miy/pull/88)·[MR95](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/95)로 정상 병합하고 소유 feature 브랜치를 양쪽 원격·로컬에서 정리했다. 최신 full247/job415는 저장 공간 선행조건에서22.79551초에 실패해 제품 테스트0이며 새 운영·별도 Workbench 배포는 없다.

다음은 별도 worktree의 비활성 Core actor-owner capability다. 실제 원 delegated execution을 별도 auth-only Session에서 캡처하고, 공급된 fresh LOGIN에는 private EXEC1만 허용해 사업 데이터 SELECT·DML0을 유지한다. 같은 PostgreSQL database의 caller-owned transaction에서 원래 서비스와 현재 사용자·세션·설치·앱 승인·live board owner의 positive witness를 잠근다. Source v1의 SELECT8/UPDATE4 및 auth14표/87열은 확장하지 않는다. 기존31 migration·보호95개를 동결하고 신규 revision `wb_actor_owner_20261009` 하나와 inventory head 한 항목만 추가한다. 구현·테스트 작성에 착수했으며 새 검사 실행·최종 인수·게시·서비스 활성화는 아직 하지 않았다.

이번 owner-only 단계는 전체 Whiteboard ACL·실제 Source 쓰기 연결·운영 전환을 완료하지 않는다. 공유/HR/PMS/meeting 편집 권한, contributor의 원 credential 보존, 같은 connection/transaction의 Source CAS와 actor 검사 조립, cross-hub content CAS·영속 unknown 복구·Docs 저장/media/RAG가 필수 잔여다. 별도 LOGIN 연결 두 개는 하나의 transaction으로 합칠 수 없으므로 후속 최소 combined profile 또는 검토된 capability가 필요하다. 같은 database의 역할·프로세스 분리이며 물리적 별도 DB를 인수하지 않는다. 대기 후 실제 시각의 만료 판정은 decision 시점 보장이고 physical COMMIT-time 만료 보장은 아니다. 사용자 update의 User→AuthSession과 autoflush=False인 reset/delete의 AuthSession→User 역순 잠금 충돌은 bounded private refusal·caller rollback으로 검증하고 보편적 잠금 순서로 주장하지 않는다. Native immutable cache/설치·SDK 전체 자연어 흐름과 별도 Workbench 전달도 남아 있다. 비필수 앱 기능·다중 사용자는 보류한다.

Source `c1af8e51`/tree `d2ecb389`는 필수246/job414 SUCCESS/76.478189초 뒤 GitHub main `cdadfe96`·내부 dev `746258cd`로 정상 병합했다. 두 merge tree가 같고 protected dev/main·upstream 기본 push 차단은 유지했다. 전달 증거는 `.runtime/structural-next-delivery/whiteboard-source-writer-feature-{commit,publish,status,merge,cleanup}.json` 및 `whiteboard-source-writer-required-review246-job414.json`이다. MR81·fresh backup·guarded 운영 배포는 지속15GiB/15% 여유와 최신 정확 source/target/tree full 성공 뒤 진행한다.

## 2026-10-09 08:38 — actor-owner 구현 검증과 Docker 저장소 이전

현재 actor-owner feature는 아직 commit/push·PR/MR 생성 전이다. Base는 dev `746258cd`; GitHub main `cdadfe96`, 내부 main/prod `9e9280df`를 유지한다. 기존 제품/추적13경로에 승인된 Docker 저장소 이전의 운영 owner 문서3경로(INSTALL·Release README·installation-operations)를 더해 최종 게시 범위를16경로로 명시한다. 일반 플랫폼/공식 앱/Workbench 기능 범위는 확대하지 않는다.

Docker 저장소 이전은 호스트 인프라 유지보수이며 새 제품 이미지·schema·운영 역할·Workbench 버전 배포가 아니다. 이전의 full247/job415 저장 선행조건 실패/제품 테스트0는 보존한다. 지속15GiB/15% 여유를 확보해도 최신 source/target/tree full 성공과 required review를 대신하지 않는다.

## 2026-10-09 09:26 — Docker 이전 완료와 actor-owner 최종 로컬 검증

최종 로컬 검증 범위는 비활성 actor-owner와 Docker 유지보수 owner 문서를 포함한16경로다. Native138·pure7·기존167과 API/Python 검사 PASS이며 정상 commit/push·PR/MR·필수 리뷰·병합은 아직 시작 전이다. Dev `746258cd`, 내부 main/prod `9e9280df`, GitHub main `cdadfe96`를 유지한다.

Docker 이전은 기존18 image objects·83 containers·286 volumes를 그대로 옮긴 서비스 유지보수다. 실제 서비스 코드/schema/role/config flag 또는 Workbench release version을 새 후보로 반영하지 않았다. 기존 full247/job415 저장 실패/테스트0를 새 full 결과로 대체하지 않고 보존한다. 이전 원본 정리 뒤 current target52.65GiB·home12.85GiB와 CI 실제 filesystem의 조건을 구분한다.

## 2026-10-09 09:46 — 정상 CI의 Source revision 호환 수정

이전16파일의 최종 로컬 결과를 인수한 직후 정상 CI 수집의 ACT-CI-01을 확인해 독립 `accepted=false`/blocker1로 철회했다. 정상 원본 모듈의 prior-head5는 실제5 FAIL/11.19초였다. ignored adapter의 성공을 정상 CI 성공으로 대체하지 않는다.

revision fixture를 원본 테스트에 포함해17파일/보호94로 범위를 수정했다. 원 함수 본문·signature·assertion과 이전31 migration은 동일하다. 정상 원본 Source79 전체와 role31·authority52·migration5=167 PASS, pure7·Python·API 구조/생성 계약 PASS다. 최종 native138 재실행·문서 동결·새 독립 인수 후 게시하며 아직 새 commit/push/PR/MR/merge는 없다. Dev746258cd·main/prod9e9280df·최신 full247/415 storage 실패/tests0를 유지한다. Docker 호스트 이전 완료는 새 제품/Workbench 버전 배포를 뜻하지 않는다.

## 2026-10-09 09:50 — actor-owner와 정상 CI 호환 최종 로컬 인수 준비

최종17파일 범위에서 신규 actual PG18 native138 PASS/321.13초·pure7 PASS/3.30초 =145개다. 정상 원본 Source 모듈79 PASS/82.18초·원 role31 PASS/24.19초·authority52 PASS/83.77초·migration5 PASS/6.35초 =고유 기존 영향167개다. 진단/반복은 더하지 않는다. ACT-CI-01의 실제5 FAIL/11.19초와 동일5 PASS/11.17초는 보존하며 현재 영향 검증은 ignored Source prior adapter에 의존하지 않는다. 기존45개 함수 본문·signature·assertion, 보호94개·기존31 migration은 동일하다.

Python6·API architecture/i18n·schema/OpenAPI/contract sources를 통과했다. 최종 문서 검사·동결 후 새 독립 인수와 정상 게시/필수 원격 리뷰를 진행한다. 현재 dev746258cd·main/prod9e9280df 및 최신 full247/415 storage 실패/tests0를 유지하며 새로운 commit/push/PR/MR/merge는 아직 없다. Docker 이전/원본 정리·서비스 복구는 완료했고 제품/별도 Workbench 버전 배포는 없다. 전체 ACL·같은 Source connection/transaction 조립·실제 공식 서비스 cutover·Native 전체 자연어 앱 흐름 등 구조상 필수 잔여는 남아 있다.

## 2026-10-09 10:13 — owner 경계 전달 완료와 전체 편집 ACL 착수

Owner actor Source `3b39f5b9`/tree `68ca858e`의17파일·보호94·이전31 migration과 신규145/영향167을 독립 인수한 뒤 정상 commit/push했다. 필수248/job416 SUCCESS/allow_failure=false·137.448817초를 확인하고 PR89→`55e53403`, MR96→dev `8bf0bbee`로 병합했다. 두 merge tree가 같으며 소유 feature의 양쪽 원격과 로컬은 정리했다. 새 dev source의 전체249/job417이 실행 중이다. 운영 main/prod는 `9e9280df`이며 full 성공/새 운영/Workbench 배포를 주장하지 않는다.

다음 edit ACL은 `8bf0bbee` 기준 별도 worktree와 새 feature다. 현재32개 migration과 기존 owner/Source/auth profile을 보호한다. 구현 중이며 커밋·게시·실제 서비스 활성화는 없고, 현재 전체 릴리스가 검증하는 source를 바꾸지 않는다.

## 2026-10-09 10:48 — owner 전달 완료와 release 재검증 조건

Owner commit `3b39f5b9`의 GitHub PR89·GitLab MR96은 정상 병합했다. 필수248/job416 SUCCESS·allow_failure=false, 양쪽 merge tree `68ca858ec1390e43037fec7d1d277feaec409ad6` 동일이다. dev는 `8bf0bbee`로 fast-forward했고 해당 기능 브랜치만 원격/로컬 정리했다.

MR81의 full249/job417에서 파일 migration 여덟 case가 실패했으므로 현재 source의 운영 병합·배포 근거가 없다. 버전 전용 fixture 수정은 새 필수 review와 새 exact-source full 검증을 거친다. 보호된 dev/main 및 upstream direct-push 비활성 계약을 유지한다.

## 2026-10-09 10:54 — 전체 ACL의 정상 전달 조건

전체 ACL14경로는 신규132·기존312·API/Python 검사 PASS, 보호98개·기존32 migration 동일이다. 원 owner revision4개 fixture를 커밋 범위에 포함했고 원 assertion은 유지했다. 초기3개 테스트 데이터 실패와4개 revision 실패는 보존한다. Root tracking6의 마지막 변경은 Markdown 검사와 최종 독립 리뷰로 별도 동결한다.

현재 owner commit3b39f5b9·PR89/MR96 전달 이후 dev8bf0bbee이며 운영 main/prod9e9280df다. Full249의 file revision8 FAIL은 별도 ACT-CI-02 전달로 먼저 해결한다. 이 ACL은 아직 commit/push/PR/MR/merge되지 않았고 최종 scope·새 base·필수 review를 확인해 정상 전달한다. 운영/별도 Workbench 배포의 증거로 로컬 성공을 사용하지 않는다.

## 2026-10-09 11:05 — ACT-CI-02 로컬 영향 검증 완료

ACT-CI-02는5개 test/helper+root tracking6=11경로다. 정상 원본270 PASS, 원115함수/270assertion 유지, 보호99개·기존32 migration 및 제품786개 동일을 확인했다. 최종 문서와 독립 인수 후 정상 commit/push·양쪽 PR/MR·필수 codex_review를 진행한다. Merge 전 현재 source/target/tree를 다시 확인하고 owned feature만 정리한다. 보호된 dev/main과 upstream direct push 비활성은 유지한다.

## 2026-10-09 11:23 — 정상 fixture 전달과 ACL 통합 준비

ACT-CI-02 commitcdc6103e·GitHub PR90 merge268363f0·GitLab MR97 mergee3e2591c, 필수250/job418 SUCCESS/55.90초/allow_failure=false다. Merge treecc54e4d9 동일, origin/main9e9280df 유지, owned feature만 정확한 tip으로 양쪽 원격/로컬 삭제했다. 첫 GitHub PR 생성 요청 실패는 보존했고 원인은 단정하지 않는다. 재조회에서 기존 PR0을 확인한 뒤 정상 재요청해PR90을 만들었다. ACL은 rebase 후 동일 runtime8+최신head8-case PASS를 확인했으며 최종14경로/독립 통합 인수·필수 review를 새 source에 고정한다.

## 2026-10-09 12:20 — ACL 정상 게시 완료와 CI 린트 후속

PR91/MR98은 exact b3954393의 필수252/job420 SUCCESS 후 정상 병합했고 양쪽 tree93744905가 일치한다. Dev92e77670, main/prod9e9280df이며 소유 feature 양쪽 원격·로컬만 삭제했다. Full251의 실제 실패는 보존한다. 새 ACT-CI-03은 아직 미게시인 test import 정렬1개와 추적6이며 local whole-Python lint/원 module24 PASS다. 현재 full253과 이후 수정본의 latest full 결과는 구분한다. MR81/운영·separate Workbench deployment 성공은 없다.

## 2026-10-09 12:55 — ACT-CI-03 정상 병합·브랜치 정리

Source `22913094ac989f60efa62237e9d40068ceb2a38f`의 필수254/job422 SUCCESS41.729942s 후 GitHub [PR92](https://github.com/hurxxxx/miy/pull/92)는 `762d4c0f191ad0fe7aa3e384633f197baeff10ce`, 내부 [MR99](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/99)는 `0d259c30d6539a523062ec42b69a02e72b17ddbc`로 정상 병합했다. 두 tree는 `04d144c18498c0f0b1df9403f036637b95f7de6e`이며 primary dev를 clean FF했다. 정확 소유 branch fix/workbench-import-order-20261009를 양쪽 원격과 로컬에서 제거했고 owned WT는 source에 detach했다. Persistent dev/main·upstream push DISABLED를 유지한다.

기존 full253/job421 canceled는 원 lint 실패의 반복을 중단한 관측이고 gate PASS가 아니다. MR81 최신 full255/job423이 source0d259/tree04d144에서 실행 중이며 main/prod9e는 유지한다. 개발 runtime/schema·public browser18 진입은 반영 확인했고, 운영은 latest full→정상 MR81→guarded image/23 migration/before-after 순서가 남아 있다. Workbench 별도 runtime 릴리스와 C1/SDK 후속 로컬 구현은 이 CI03 테스트-only 전달에 포함되지 않는다.

## 2026-10-09 13:46 UTC — ACT-CI-04와 실제 SDK pilot

전체255/job423은 프로젝트 기본1시간에 종료되어 실패했다. Runner 최대는7200초다. API6423·별도 slow16/migration37/external15·Web911·WorkbenchWeb183·WorkbenchPython822의 관측을 보존하지만 build/E2E 및 최종 full 성공을 대신하지 않는다. 운영 main/prod는 `9e9280df`, 개발은 `0d259c30`이며 MR81 병합과 운영 배포는 대기한다.

ACT-CI-04는 root/ops의 동일 `release_validation`에 `timeout: 2h`만 추가하고 현재 exact checker 및 누락/1h/24h 거부를 연결한다. 원래 job scripts·전체 선택·실패·artifact·리소스/저장 공간 조건은 유지한다. 동일 immutable 검증 이미지eefe09d5에서 network none·70/70 PASS, source/protected 불변·소유 container 정리를 확인했다. 최초 host YAML dependency 부족과 컨테이너의 host worktree Git 경로 접근 실패는 준비 단계 실패로 구분해 보존했다. 프로젝트/Runner 전역 설정은 변경하지 않는다. [GitLab job timeout](https://docs.gitlab.com/ci/yaml/#timeout)의 지원 계약을 적용하며 후보의 필수 리뷰·게시/병합·최신 full은 아직 남아 있다.

공개 Native 코드는 새 `/opt/miy/miy-native-codex-01601-v1`에49files/446,771,872bytes/고정 executable34개로 설치했고, SDK는 `/opt/miy/miy-native-sdk-20261009-v1`에 정확 inventory를 검사했다. 두 cache는 root-owned readonly이며 모델·기존 Workbench 설정/서비스를 변경하지 않았다. 별도 canonical basic 앱의 실제 finite unit에서 kernel namespace·UID1000/cap0/NNP·CPU1/메모리1GiB/swap0/PIDs64와 읽기 전용 root/cache/Git 및 쓰기 Source를 확인했다. provisioning와 잘못된 bearer 거부·일반 `pnpm test`는 통과했으나 `pnpm run build` exit1의 정확 원인은 미확정이다. 초기 outer bwrap monitor PID 관측과 실제 exec-server child의 PID namespace 인수를 구분했다. 실패 근거를 유지하고3개 임시 unit을 stop/정리했으며, 자동 한도 확대·host fallback이나 실제 제품 Task 성공을 주장하지 않는다. SDK 재현 producer와 실제 Task 환경 profile도 별도 필수 구현 중이다.

C1 checked CAS는 Core sealed cohort/payload·Source EXEC1/DML0·Core EXEC2/DML0와 durable receipt/원 attempt 잠금 취소의 비활성 후보다. 저자·독립 reviewer의 정적/pure 단계 뒤42 native case의 실제 disposable PG와 기존 Source8 최신 head 회귀 검증이 남아 있다. C2 원 provenance·C3 서비스 활성화와 앱별 비필수 기능은 후속 범위를 유지한다.

## 2026-10-09 14:20 UTC — ACT-CI-04 게시·정상 병합

Source47be5881의 필수256/job424 SUCCESS46.626996초 후 GitHub PR93은1eca4c85, GitLab MR100은02418067로 병합했다. 양쪽 treec7616793 동일·primary dev clean FF와 소유 feature 원격/로컬 정리를 확인했다. Persistent dev/main·upstream push DISABLED를 유지한다. 최신 full257/job425 source02418067/target9e9280df는 실행 중이며 MR81·운영 배포는 전체 성공 뒤 진행한다. C1/SDK v2/접근도구 후보는 로컬 미게시이고 별도 Workbench 배포는 없다.

## 2026-10-09 15:25 UTC — 현재 로컬 경계와 릴리스 실패

C1 신규56·기존ACL132·Source110·owner145·authority52는 현재 입력으로 통과했다. 초기51/1/4와 historical drain 실패를 보존했고 원래 migration marker 두 개만 추가해 기존 함수/assertions를 유지했다. SDK v2 설치·정상 공개 입력55개 취득/동일 archive 재현160.761초는 통과했지만 source preflight는 canonical starter의 vendor4와 verifier 필수 README5 불일치로 거부됐다. 이 필수 계약을 보완한 뒤 actual unit/Task를 인수한다. 이전 SDK source170/pure와 독립 리뷰는 보완 전 시점으로 구분한다.

전체257/job425는3198.397초 FAILED다. API6422/1FAIL/3SKIP이며 마지막 shutdown 저장의 실제 status rejected를 확인했다. slow16·migration37·external15 통과는 전체 성공을 뜻하지 않는다. 예외·SQLSTATE·GC 관측만 추가하는 disposable 단독 재현을 준비하며 timeout/검사 면제와 동일 source 맹목 재시도는 하지 않는다. main/prod는9e9280df, 새 운영/Workbench 배포는 없다. 현재23 migration private 리허설과 독립 리뷰는 treec7616793 한정이다. 새 migration 통합 후에는 새 정확 tree/pending 수로 검증한다.

Rejected payload는 현재 caller-held runtime에만 남고 자동 replay는 금지된다. 종료 후 durable owner/handoff 검증은 C2/C3 필수 구조 잔여이며 APP_ISSUES로 넘기지 않는다. 고객 데이터 손실을 관측했다는 뜻은 아니다. Docker는 root117GB에서 약47GB 여유와29/83 실행/전체 컨테이너를 확인했다. 앱별 비필수 기능과 다중 사용자는 계속 보류한다.

## 2026-10-09 16:10 UTC — GC 저장 예산 재현과 통합 순서

원본 shutdown 저장 사례는 진단 wrapper만 추가한 격리 CI 이미지에서 다시 실패했다. 첫 네 저장은 ACK, 마지막 저장은 transaction_rejected/WhiteboardPersistenceDeadline(SQLSTATE 없음)이었다. 마지막 저장의1.24초 구간에 full GC 세 번이 각각 약0.41초 겹쳤다. 원본 assertions·1초 SQL 예산·worker4개를 유지하고 process-wide concurrent reader/exclusive native GC drain을 Docs·Whiteboard 공통 계층에 적용한다. 새 await 뒤 Docs의 원 snapshot/actor capture 시점과 writer fence 재확인도 보존한다. 새 코드의 실제 인수는 아직 대기다.

SDK source 보완185개·두 canonical starter/cache binding은 통과했다. 실제 basic unit의 pnpm test/build·readOnly/cache/외부 graph 거부는 통과했지만 Python/TestClient가 멈췄다. 후속 짧은 진단은 초기화에서 거부되어 Python IPC 원인을 확정하지 않았다. exact owned unit 정리는 통과했다. 제품 Task/model 요청0이며 SDK18개 후보는 이번 API 전달에 포함하지 않는다.

C1·GC·접근 도구를 최신 dev02418067 기반으로 먼저 통합한다. C1의 기존 로컬56/132/110/145/52 증거는 정확 입력과 함께 보존하며 공통 runtime 변경의 영향 검사를 수행한다. 정상 필수 feature review/병합 뒤 새 current full로 이어간다. C1 migration34/pending24의 새 private 리허설과 이전 운영 이미지 호환이 필요하며 기존pending23 증거를 새 head의 완료로 사용하지 않는다. main/prod9e9280df·운영/Workbench 미배포·C2/C3 잔여·앱별 비필수/다중 사용자 보류를 유지한다.

## 2026-10-09 17:43 UTC — API31개 전달 후보의 로컬 인수

이번 후보는 dev02418067 기반 C1·Docs/Whiteboard 저장/GC drain·접근 도구와 추적 문서31개 경로다. 신규 C1 56·기존 권한132/110/145/52와 통합20·기존 협업106 및 구조/생성 계약을 인수했다. SDK18 및 controller 후속은 별도 로컬 후보로 제외한다. 필수 Codex review·GitHub feature PR·내부 dev MR·정상 병합/정리·새 current full은 아직 실행 전이며 이전 full257 실패는 유지한다. Persistent dev/main과 main/prod9e9280df를 보존한다. migration34/pending24의 새 운영 근거와 별도 Workbench 전달도 필요하다.

## 2026-10-09 18:03 UTC — GitHub94/GitLab101 필수 재리뷰

최초858632eb/tree40f560da 게시와 정상 commit/push는 완료했지만 필수258/job426은 Docs 종료 P1로 실패했다. 수정31개 후보는 focused24·원본106을 새로 통과했으며 새 head를 정상 푸시해 필수 리뷰를 다시 받는다. 실패를 면제하거나 이전 검사로 병합하지 않는다. Persistent dev/main과 main/prod9e9280df를 유지하며 SDK/C2 후보는 별도다.

## 2026-10-09 18:37 UTC — draining 마이그레이션 필수 P1 수정

필수259/job427(source0059196a)은 C1 migration의 기존행 UPDATE backfill이 draining 상태의 statement writer guard에 걸리는 P1을 발견했다. 빈 테이블도 guard가 실행되므로 기존 trigger/role/ACL을 우회하지 않고 두 column을 owner DDL의 NOT NULL/default로 초기화한다. UUID의 행별 생성 뒤 미래 INSERT default만 기존 sentinel로 복원한다. 기존 SQL 함수·guard·downgrade·22개 테스트 정의와 기본 비활성 경로를 보존했다.

현재 코드의 실제 PostgreSQL18 회귀는 기존56개+legacy/hardened×empty/existing_rows4개로 **60 PASS/179.90909초**다. Setup/call/teardown 모두60/실패·skip·collection error0이며 소유 cluster/container 정리와 입력 전후 검증을 통과했다. Native 입력31 c34454d1·수정3 ddabcea8 및 receipt e988110b를 보존했다. Canonical 문서 서식만 후속 whitespace로 정리했고 코드·테스트·migration bytes는 같다. 현재 입력31 4d19d222·수정3 23abcea3에 결속한 frozen CI Ruff0.16.6 check/format과 owner Markdown도 통과했다. 이전 잘못된 도구 버전 기대와 문서 format RED는 보존하며 검사 결과를 성공으로 덮어쓰지 않는다.

Docs 집중24/기존협업106(208.751168초)은 바뀌지 않은 runtime/test bytes에 한정한 이전 인수 근거다. 과거 C1 권한132/110/145/52는 그 당시 입력으로 구분한다. GitHub94/GitLab101의 새 수정 head 필수 리뷰·정상 병합·새 current full, 새 migration34/pending24 private 리허설과 이전 운영 이미지 호환·fresh backup/guarded 배포가 남아 있다. Dev02418067·main/prod9e9280df는 현재 그대로이며 배포 완료를 뜻하지 않는다.

별도 Workbench 후보는 SDK source22/owned delta11의 신규74 PASS와 영향427 PASS/기존 PostgreSQL legacy fixture5 SKIP 및 독립 소스 리뷰를 마쳤다. 실제 원관리 정책 확인·controller/Task·private-notes와 별도 서비스 배포는 미완료다. C2-1 비활성 provenance3은 실제 native53 PASS와 독립 리뷰를 통과했으며 PostgreSQL pre-apply durable journal/discovery와 C3 원 attempt 복구·서비스 활성화는 필수 구조 잔여다. 앱별 비필수 기능과 다중 사용자는 보류한다.
