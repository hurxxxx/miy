# Workbench 작업별 개발 환경 개선 계획

기준: 2026-10-11. 사용자 재검토와 선택 후 **로컬 구현과 영향 검사를 마쳤다**. 실제 서버 적용·전체 브라우저 인수는 남아 있다. Git 게시·병합·배포·기존 환경 정리는 이번 실행 권한에 포함하지 않는다. 작업별 상태 원본은 [WORK_ITEMS.md의 WB-ENV 항목](WORK_ITEMS.md#2026-10-11-workbench-작업별-개발-환경)이다. 구현 연결과 검사 기록은 [구현 기록](WORKBENCH_WORKSPACES_IMPLEMENTATION.md)에 남긴다.

## 2026-10-11 재검토 후 확정 — 아래 이전 초안보다 우선

- Workbench 내부 미리보기 화면은 추가하지 않는다. 설치별 포털 실행 링크만 새 탭으로 열고, 성공한 구현 턴의 소스 변경을 기존 빌드/설치 경로로 갱신한다. HMR은 제외한다.
- `개발에 반영`은 정확한 GitLab MR의 dev 병합, 영속 소스 인계, 안정된 개발 설치의 실행 확인까지 포함한다. 이후에만 임시 환경을 정리한다. 운영 배포는 별도다.
- 앱 Project → 여러 Workspace → 여러 Task 관계를 고정한다. Workspace의 operation은 Task 삭제와 독립적으로 보존한다. 동일 작업은 여러 읽기 세션 또는 한 구현 세션으로 제한한다.
- 신규 경로는 `personal-apps/<app-id>/`로 고정한다. 공용 Nx 탐색과 루트 의존성에서 제외하되 격리 앱 검사를 필수 CI에 연결한다.
- 사용자가 PostgreSQL뿐 아니라 OpenSearch·Qdrant **앱 검색 API까지 이번 범위**로 선택했다. 기존 설치별 records만 원본으로 사용하며 optional manifest search 선언, `search:read`, SDK helper, 키워드/의미 검색 gateway를 추가한다. 검색 없는 기존 manifest digest는 유지한다.
- 원본 변경과 projection/outbox를 설치 DB의 같은 트랜잭션으로 저장한다. 삭제/같은 키 재생성을 넘어 유지되는 순서와 현재 DB 권한을 확인한다. Core가 승인한 embedding gateway와 실제 검색 엔진을 사용하며 앱에 엔진 자격증명을 제공하지 않는다.
- 작업별 후보 정의/설치와 통합 정의/개발 설치를 분리한다. 앱별 반영은 버전 확인과 직렬 처리로 늦은 작업의 덮어쓰기를 막는다.
- 준비된 Linux 단일 실행 호스트를 지원한다. Windows/macOS 실행 호스트·다중 사용자·장비 앱 검색 화면·업무 기능 확장은 후속이다.

이전 절에서 검색 adapter를 후속으로 둔 문장, 경로를 제안으로 남긴 문장, dev 앱 갱신을 선택적으로 둔 문장은 위 결정으로 대체한다. 아래 관측과 기존 안전 경계는 유지한다.

## 1. 확정 방향과 적용 범위

MIY 앱 개발은 같은 MIY 저장소의 `dev`를 기준으로 기능 브랜치와 worktree를 만든다. 기존 `dev` 작업 디렉터리·서비스·데이터는 그대로 유지한다. 앱의 실행·배포 분리는 유지하며, 포털에 앱별 정적 import/router를 다시 추가하지 않는다.

사용자는 업무를 설명하고 미리보기를 확인한 뒤 **계속 수정 / 개발에 반영**을 선택한다. Workbench가 소스·환경·세션·MR·정리 상태를 연결한다. `개발에 반영`은 GitLab `origin/dev` 통합이며 운영 배포와 GitHub `upstream` 기여는 별도다.

- 단일 소유자 Workbench와 기존 native Codex 세션·에이전트 관리·SQLite를 유지한다.
- 환경의 수명은 대화 세션보다 긴 **개발 작업**에 연결한다. 같은 작업의 여러 세션은 같은 환경을 이어 사용하며 동시 쓰기는 기존 lease/잠금으로 제어한다.
- 관리자가 한 번 준비한 저장소·실행기·개발 인프라 프로파일을 사용한다. 비개발자가 서버 경로·포트·비밀값을 입력하지 않는다.
- 새 앱 생성과 기존 앱 수정 모두 같은 흐름을 사용한다. 다른 저장소·운영 대상은 자동 추측하지 않는다.
- 기존 독립 저장소 앱·세션은 호환 경로로 유지한다. 이번 MIY 기본 흐름에서 독립 저장소/`main` 자동 생성은 사용하지 않는다.
- 기존 skills나 긴 하네스를 절차로 다시 로드하지 않는다. 필요한 대상·권한·공개 SDK 계약과 현재 작업 요약만 전달한다.

## 2. 관측 근거와 현재 구현의 공백

| 근거 | 현재 사실 | 이번 계획에 필요한 변경 |
| --- | --- | --- |
| [공개 브라우저 검사](BROWSER_ACCEPTANCE.md) | 개발 포털과 운영에 연결된 Workbench의 대상 차이, 생성 root/실행 환경 미설정 | 대상·준비 상태를 시작 전에 확인하고 준비된 개발 프로파일 연결 |
| [장비 앱 시범](workbench-equipment-pilot/STATUS.md) | 별도 저장소 `main`과 운영자 연결을 사용한 대표 업무 성공 | 같은 MIY 저장소의 기능 브랜치 생성부터 병합·정리까지 다시 인수 |
| `codex_console/git.py`, `models.py` | 명시적 격리는 Task별 detached worktree, 브랜치 조회·lease는 이미 존재 | 이름 있는 기능 브랜치와 작업 단위의 영속 환경 연결 |
| `app_source_setup.py`, `app_sources.py`, `remote_environments.py` | 새 저장소 `main` 초기화, 일반 checkout의 실제 `.git` 디렉터리 전제, 앱 executor의 worktree 거부 | 서버가 소유한 linked worktree와 앱 하위 경로를 검증하는 새 경로 |
| `app_checkpoints.py`, `source_tools.py` | 독립 checkout/index/HEAD 잠금에 의존, worktree 제한 | 실제 git-dir/common-dir과 앱 변경 범위를 확인하는 저장 broker |
| `build-native-sdk-toolchain.py`, `verify-native-sdk-toolchain.py` | 현재 SDK는 독립 starter의 lockfile/vendor와 `.git` 디렉터리 구조에 고정 | 기존 검증을 약화하지 않고 managed worktree용 프로파일·의존성 입력 검증 추가 |
| 독립 앱 `contracts.py`, `builds.py` | `source.directory`는 이미 있으나 빌더는 저장소 루트 manifest·일반 checkout 전제 | 기존 필드 재사용, 저장소 commit과 앱 subtree를 연결한 빌드 |
| [앱 데이터 계약](../apps/api/src/miy_api/domains/independent_apps/DATA.md) | 설치 UUID별 DB·역할, 코어 전용 자격증명, 현재 고정 레코드 스키마 | 작업 환경과 preview installation 연결; 임의 SQL/스키마 권한으로 확대하지 않음 |
| Core typed settings | OpenSearch/Qdrant 접두어 설정이 존재 | 접두어 설정만으로 환경 격리 완료로 보지 않고 권한·writer·큐까지 연결 |

앞선 시범의 소스 저장·계획 전달·입력 기본값·중복 키·artifact 권한/첫 화면 검증 보완은 재사용한다. 과거 성공 결과는 당시 소스와 환경의 근거이며 새 worktree 경로 전체의 성공으로 대체하지 않는다.

## 3. 목표 사용자 흐름

| 단계 | 내부 처리 | 기본 화면 |
| --- | --- | --- |
| 새 작업 | 대상 앱/업무 확인, 기준 dev commit 확정, 기능 브랜치·worktree 준비 | 작업명·업무 설명, 준비 상태 |
| 환경 준비 | 프로파일에 필요한 의존성·설정·데이터 공간·포트 준비 | 준비 중 / 사용 가능 / 조치 필요 |
| 개발 | 기존 native 계획·승인·실행·체크포인트 연결 | 대화, 브랜치, 변경 요약, 실행 상태 |
| 미리보기 | 해당 소스의 서버 기동과 readiness 확인 | 미리보기 열기, 실행·중지 |
| 완료 검토 | 검사 결과·원격 동기화·충돌·dev 대비 변경 표시 | 계속 수정 / 개발에 반영 |
| 반영 | 작업 브랜치 push, dev 대상 MR, 필수 리뷰·검사·병합 | 반영 중 / 수정 필요 / 병합 완료 |
| 정리 | 작업 중지·병합 증거·보존 조건 확인 후 소유 자원 정리 | 완료 / 병합 완료·정리 필요 |

새 대화를 열어도 환경을 복제하지 않는다. 환경이 중지되면 기존 작업에서 재개하고, 삭제된 환경의 대화·검사·병합 기록은 조회 가능하게 남긴다. 미리보기는 실제 준비 상태와 대상 환경을 보여주며 서버 기동만으로 최신 코드의 실행을 확정하지 않는다.

첫 사용 안내는 **업무 설명 → 미리보기 확인 → 개발에 반영**의 세 단계로 제공한다. 작업 상단에는 앱·브랜치·준비 상태·미리보기 링크를 항상 표시하고, 경로·포트·자원 목록은 상세 화면에서 확인한다. 로컬 저장/원격 저장/dev 반영/운영 배포의 차이는 각 행동 옆의 짧은 설명으로 알린다. 환경 준비 실패는 다음에 할 수 있는 행동과 함께 표시하며 비개발자에게 비밀값이나 원시 로그 입력을 요구하지 않는다.

## 4. 작업과 환경의 최소 모델

기존 Project/Task/Agent/ResourceLease를 재사용하고 환경 연결에 필요한 작은 영속 모델을 추가한다. 임의의 새 agent loop나 범용 workflow engine은 도입하지 않는다.

- 작업: owner, app/project, repository identity, target `dev`, base commit, feature branch, 저장소 상대 앱 경로, 요청/승인 범위.
- 환경: workspace UUID, worktree 경로, 검증된 git-dir/common-dir, 프로파일 버전, preview installation, 소유 자원 ID, 포트/URL, 마지막 확인 시각.
- 세션: 기존 Task/thread/agent에 workspace ID를 연결한다. 세션 삭제가 환경·브랜치·데이터 삭제로 이어지지 않는다.
- 반영: source commit, 검증 입력, 원격 브랜치, GitLab project/MR, merge 결과·target commit, 정리 단계와 실패 원인.
- 환경 상태와 개발/병합 상태를 분리한다. 예: 환경 `preparing/ready/stopped/cleanup_pending/cleaned/error`, 반영 `not_requested/reviewing/blocked/unknown/merged`.

외부 작업은 기존 operation/request ID와 소유 자원 기록으로 재개한다. 응답 유실 시 같은 요청을 조회해 실제 상태를 확인하고, 새 환경·새 MR·새 배포·삭제를 무조건 반복하지 않는다. 실제 구현 전 기존 모델과 중복되는 필드는 통합한다.

## 5. 소스·브랜치·실행 격리

기본 제안은 `feature/wb-<app-id>-<short-id>`와 `<MIY>/worktrees/<workspace-id>`다. 신규 앱 위치는 저장소 루트의 `personal-apps/<app-id>/`를 제안한다. WB-ENV-01에서 기존 생성기/Nx/workspace 탐색과 충돌 여부를 확인해 고정하고 기존 앱은 등록된 상대 경로를 재사용한다. 작업마다 새 위치를 LLM이 결정하지 않는다.

1. 허용된 MIY 원격 저장소의 `dev`와 실제 commit을 확인한다. 원격 확인 실패를 최신 상태로 표시하지 않고, 현재 dev 디렉터리의 미커밋 변경은 새 작업에 몰래 복사하지 않는다.
2. 신뢰된 서버가 이름 있는 브랜치와 worktree를 만든다. 기존 브랜치·경로 충돌은 덮어쓰지 않고 기존 요청인지 확인한다.
3. linked worktree의 `.git` 파일을 무조건 허용하지 않는다. Git이 보고한 git-dir/common-dir, 서버 소유 worktree 등록·브랜치·경로를 대조한다. 임의 Git 경로·설정·hook 실행은 허용하지 않는다.
4. 현업 앱 AI의 쓰기 범위는 해당 앱 소스다. 호스트 전체와 플랫폼의 `.env`·인증·공통 Git metadata 쓰기를 노출하지 않는다. 체크포인트와 Git 조작은 broker가 앱 변경 범위와 예상 HEAD를 검증해 수행한다. 기존 HEAD tree의 앱 밖 경로를 유지하고 승인된 변경 집합만 제한적으로 저장한다. 현재 독립 앱의 전체 파일 수/크기 제한을 MIY 전체 파일 수에 맞춰 무조건 확대하지 않는다.
5. 코어/공식 앱 수정은 코어 개발자용 작업 프로파일로 구분한다. 앱 기능 요청이 루트 의존성·인증·플랫폼 권한 변경으로 자동 확대되지 않는다.
6. 등록과 빌드는 기존 `source.repository`·`source.directory`를 사용하고 repository commit, 앱 subtree, 필요한 고정 SDK/lockfile 입력을 검증 증거에 결속한다. 전체 저장소를 앱 산출물로 포장하지 않는다.

## 6. 설정·의존성·인프라

### 설정과 실행

개발 `.env`는 선택된 typed 설정의 참고 입력으로만 사용한다. 작업별 설정은 허용 키에서 생성하고 DB/검색/큐/미리보기 값은 환경 연결값으로 대체한다. 호스트·운영·관리 자격증명은 복사하지 않는다. 비밀 설정은 작업 소스 밖의 보호 저장소에 두고 필요한 서버에만 주입한다. 모델·브라우저·로그에는 준비 여부와 비밀이 아닌 연결 식별자만 제공한다.

의존성은 lockfile과 검증된 toolchain/cache를 사용한다. 필요한 설치는 격리된 준비 단계에서 수행하고, 앱 manifest나 package script를 호스트 설치 명령으로 실행하지 않는다. 포트는 실제 점유/경합을 확인해 할당하고 앱 서버·API·Vite/HMR·프록시에 일관되게 연결한다. 로컬과 원격 브라우저에서 도달 가능한 주소를 구분하고, 공유 개발 접근은 준비된 인증/HTTPS 경로를 사용한다. 현재 프록시가 확인되지 않았으면 임의로 외부 공개하지 않는다.

현재 독립 starter SDK를 MIY 전체 worktree에 그대로 사용할 수 있다고 가정하지 않는다. 기존 native controller/exec-server와 격리 unit을 재사용하되 managed worktree 프로파일의 source·Git metadata·의존성 mount 계약을 별도로 검증한다. 현업 앱은 해당 subtree와 명시된 공개 SDK/의존성 입력만 제공받고, 코어 개발 작업은 승인된 저장소 범위를 제공받는다. 공유 캐시는 불변 입력으로 사용하고 쓰기 가능한 `node_modules`·`.venv`·build cache를 작업 간 공유하지 않는다.

### 데이터와 비동기 작업

| 서비스 | 기본 처리 | 필수 경계 |
| --- | --- | --- |
| 앱 PostgreSQL | 전용 앱 데이터 클러스터를 공유하되 작업 preview installation별 DB·역할 | 기존 RLS/owner/설치 계약, 코어 DB 격리, 자격증명은 gateway에만 |
| Core PostgreSQL | 코어 스키마를 바꾸는 작업에만 별도 개발 DB와 Core 실행 프로파일 | 공용 dev에 작업용 migration 적용 금지, 합성 seed 또는 승인된 비식별 데이터 |
| OpenSearch | 필요한 프로파일만 작업별 인덱스·별칭 생성 | 허용 인덱스 권한, 조회·색인·재색인 writer와 원본 DB 일치 |
| Qdrant | 필요한 프로파일만 소수 작업별 컬렉션, 모델/차원 식별 | 서버 경계에서 대상 고정, 필터/이름만 보안 경계로 간주하지 않음 |
| Redis/큐 | 필요한 프로파일만 키·큐·결과 영역/worker 연결 | 다른 작업 큐 소비·전역 flush 금지, scheduler 중복 실행 방지 |
| 객체 저장소 | 필요한 프로파일만 버킷/경로·제한 정책 | 업로드/다운로드/삭제/백그라운드 작업 모두 같은 소유 범위 |

장비 앱 최소 프로파일은 PostgreSQL과 앱 실행만 사용한다. OpenSearch/Qdrant 등을 앱마다 일괄 생성하지 않는다. 현재 지원하지 않는 앱 검색·worker·임의 relational schema 기능은 이번 lifecycle을 이유로 전부 구현하지 않는다. 해당 인프라를 실제 사용하는 지원 프로파일에는 격리·정리 adapter가 필수이며, 미지원 프로파일은 시작 전에 이유를 표시한다.

공통 플랫폼 API만 사용하는 앱은 준비된 dev 플랫폼을 이용한다. 코어 API/스키마/검색 구성까지 바꾸는 작업은 필요한 Core·worker도 별도로 실행한다. 서비스 버전·클러스터 전역 설정을 시험할 때만 해당 인프라 자체를 격리 인스턴스로 띄운다.

환경 ID는 안정된 UUID로 관리하고 브랜치 이름을 DB/인덱스 이름에 그대로 사용하지 않는다. 작업 중지·세션 만료는 데이터 삭제가 아니다. 같은 앱의 여러 작업은 서로 다른 preview installation과 자원을 사용하고, 현재 등록 정의가 한 작업의 commit으로 바뀌어 다른 작업을 덮는 경우를 막도록 source/definition/installation 결속을 함께 설계한다.

현재 app_id당 하나인 Workbench 소스 연결과 registry 정의를 작업별 preview의 쓰기 대상으로 공유하지 않는다. 기존 앱 ID는 유지하면서 작업별 소스 연결·검증된 후보 정의 revision·preview installation을 결속하고 통합된 앱 정의와 구분하는 최소 확장이 WB-ENV-01의 선행 결정이다. 단순한 DB 이름 변경이나 앱 ID 복제로 해결하지 않는다. Redis는 키/작업 큐뿐 아니라 결과 저장과 realtime Pub/Sub 범위까지 확인한다. 기존 고정 공식 포트/큐·Compose의 공용 `miy-dev` 자원을 작업별 자원으로 잘못 기록하지 않는다.

## 7. 반영과 정리의 안전 조건

`개발에 반영`은 대상 앱·브랜치·변경 요약·검사 결과와 dev 통합/임시 자원 정리 범위를 보여주는 하나의 사용자 행동으로 제공한다. 서버는 현재 권한과 저장된 의도를 확인하고 기존 GitLab MR·필수 리뷰·CI를 사용한다. 재시도나 세션 변경으로 같은 승인을 반복 요구하지 않되, 대상·검증 입력·위험 범위가 달라지면 이를 드러낸다. 운영 배포·upstream 기여로 확장하지 않는다.

- 검사 증거는 정확한 소스·의존성·프로파일에 연결한다. dev 변경으로 충돌이나 영향 입력이 달라졌으면 필요한 검사만 다시 수행한다.
- 사용자는 완료 검토에서도 계속 수정할 수 있다. source commit이 바뀌면 이전 병합/검사 준비 상태를 그대로 재사용하지 않는다.
- 병합 완료는 GitLab의 정확한 MR/source/target/merge 결과와 원격 상태로 확인한다. fast-forward·merge commit·squash 방식을 구분하며 단순 ancestry 검사만으로 삭제를 결정하지 않는다.
- 병합 확인 후 Workbench 서버의 소스 관리 기능이 저장소 식별자·앱 상대 경로·검증된 병합 대상 commit을 기준으로 영속 소스 연결을 인계하고, Core 등록 기능이 통합 앱 정의를 검증한다. 기존 `source.directory`와 등록 계약을 재사용한다. 신뢰할 수 있는 Git 객체/소스 snapshot으로 연결하며 다른 변경이 있는 공용 dev checkout을 강제로 전환하거나 초기화하지 않는다. 임시 worktree를 참조하는 영속 연결이 남아 있으면 정리를 보류한다.
- 미리보기의 소스·산출물 검증 기록을 squash 이후 commit의 증거로 바꾸지 않는다. 병합 결과에 필요한 검증은 실제로 달라진 입력에 맞춰 수행하고 원 기록을 보존한다. Git 병합·영속 소스 연결·개발 서비스 반영·정리를 별도 상태로 관리한다. 연결이 실패하면 `병합 완료·원본 연결/정리 필요`로 표시하고 필요한 임시 소스를 유지한다.
- 병합 직후 dev 통합 서비스가 자동 갱신되는지는 기존 전달 절차에 따른다. Git 병합 성공과 실제 미리보기/개발 서비스 반영을 따로 표시한다.
- 활성 모델/worker/빌드·알 수 없는 쓰기 결과·미커밋 파일·병합 후 새 커밋·외부가 점유한 경로가 있으면 정리를 보류하고 원인을 표시한다.
- 정리 순서: 새 작업 admission 중지 → 실행기/preview/worker 정상 종료 확인 → 필요한 기록/보존 데이터 확보 → 해당 작업의 임시 데이터 자원·권한 정리 → worktree 정상 제거 → 정확한 로컬/원격 기능 브랜치 제거 → 최종 상태 확인.
- 임시 테스트 데이터의 병합 후 삭제 정책은 작업 시작 시 안내한다. 보존 표시된 데이터나 용도를 확인할 수 없는 데이터는 남긴다. 개발·운영 데이터로 테스트 행을 합치지 않는다.
- GitLab의 자동 source branch 삭제와 중복돼도 이미 삭제된 정확한 대상이면 완료로 처리한다. 새 commit이 생긴 원격 ref는 삭제하지 않는다. `dev/main`, 타 작업 경로·공용 볼륨·캐시를 보존한다.
- 코드·데이터·자원을 일괄 rollback하는 것처럼 표현하지 않는다. 부분 실패는 `병합 완료·정리 필요`로 남기며 정확한 미완료 단계만 재개한다. 범용 prune/강제 삭제는 사용하지 않는다.

## 8. 구현 순서와 작업 분담

상세 상태는 [WB-ENV 작업표](WORK_ITEMS.md#2026-10-11-workbench-작업별-개발-환경)에만 기록한다.

1. **WB-ENV-01 — 계약과 이행 기준:** repository/branch/app-directory/workspace/preview/권한 모델 확정, 기존 작업 보존과 앱 등록 원본·병합 후 영속 소스 연결 계약 확정.
2. **WB-ENV-02 — worktree와 앱 소스:** 이름 있는 브랜치, 작업 수명, linked Git metadata, 제한 checkpoint, subtree 등록·빌드 연결.
3. **WB-ENV-03 — 환경 준비:** 설정 생성·고정 의존성·필요 인프라와 포트/프록시·preview 실행·중지·재개 연결.
4. **WB-ENV-04 — 세션 UX:** 기존 브랜치/변경/세션 UI 재사용, 환경 상태·미리보기·준비 오류·기록의 일관된 표시.
5. **WB-ENV-05 — 검토와 dev 반영:** 자연어/버튼을 같은 제한된 서버 작업으로 연결, GitLab MR·리뷰·CI·병합 상태 관리와 영속 소스 연결 인계.
6. **WB-ENV-06 — 병합 후 정리:** 자원 소유 기록과 merge 증거를 이용한 안전 종료·삭제·실패 재개.
7. **WB-ENV-07 — 기존 장비 앱 이행과 묶음 인수:** 사업 기능은 유지하고 새 흐름으로 재연결, 사용자 대표 흐름과 실패 경계 확인.
8. **WB-ENV-08 — 전달:** 변경 owner 문서/INSTALL 갱신, 정상 리뷰·게시·별도 Workbench 전달. 실행 권한은 해당 시점 사용자 요청을 따른다.

구현 시 독립 에이전트는 소스/Git, 환경·Core, UI를 겹치지 않는 경로로 맡는다. 01의 공통 계약을 먼저 합의하고 migration·설정·생성 계약은 주 담당자 한 명이 통합한다. 별도 agent가 배포·비밀·삭제를 임의 수행하지 않는다.

## 9. 기존 결과 보존과 이행

- 현재 dev의 미커밋 공용 보완과 다른 사용자 변경을 목록화하고 분리한다. 전부 새 기능 브랜치의 변경으로 자동 채택하거나 버리지 않는다.
- 장비 앱의 기존 독립 저장소·로컬 commit·등록·preview·데이터를 보존한다. 새 worktree에 사업 소스만 옮기는 승인된 이행으로 다루며 중첩 `.git`이나 비밀 파일을 복사하지 않는다.
- 새 repository/directory/commit의 등록과 검증은 새 근거로 생성한다. 기존 e3fcab9의 release를 새 MIY commit의 검증 결과로 바꾸지 않는다.
- 이행 인수는 별도 가상 데이터로 시작한다. 기존 시범 DB를 자동 이동하거나 초기화하지 않는다. 기존 앱은 새 경로 인수 후 별도 보존·종료 판단을 한다.
- 실행 owner 문서·생성기·앱 안내의 독립 checkout 전제를 새 경로에 맞춰 동시에 갱신한다. 기존 skills 전체를 다시 주입하지 않고 실제 충돌 규칙만 축소·교체한다.

## 10. 묶음 검증과 완료 기준

계약별 필수 단위/경계 검사는 구현하면서 작성하되 반복 전체 실행을 피한다. 후보 통합 후 영향 검사를 한 묶음으로 수행하고 필수 CI는 기존 계약에 따른다. 같은 입력의 유효한 결과는 재사용하며 실패 시 원 실패와 직접 영향만 다시 확인한다.

대표 인수는 장비 앱 한 개로 **작업 시작 → 이름 있는 브랜치/worktree 확인 → 자연어 수정 → 실제 미리보기 → 세션 재접속 → 계속 수정 → 검토·MR·dev 반영 → 자원·worktree·로컬/원격 기능 브랜치 정리 → 기록 조회**를 확인한다. 실제 원격 mutation은 승인된 검증 범위에서 수행한다. 구현 완료 보고 시 로컬 대역·실제 GitLab·공개 서비스 반영을 구분한다.

필수 실패 경계를 같은 묶음에 포함한다:

1. 두 작업의 경로·포트·DB·필요 검색/큐 공간 충돌 및 서로의 데이터 접근 거부.
2. `.git` pointer·공통 metadata·경로·symlink 위조, 앱 밖 파일 변경, 비밀값 유입 거부.
3. 부분 환경 준비 실패·서비스 재시작·응답 유실 후 기존 작업 확인/재개. 모호한 쓰기를 자동 반복하지 않음.
4. dev 갱신·충돌·리뷰/CI 실패·source 변경·병합 응답 유실 시 잘못된 병합/정리 거부.
5. squash 병합, 병합 후 추가 commit, 미커밋 파일, 실행 중 session, 정리 일부 실패에서 기록·소스·타 작업 자원 보존.
6. 실제 일반 사용자 권한의 허용/거부를 제품 경계에서 확인. Workbench 다중 사용자 구현과 구분하며 관리자 역할 시뮬레이션으로 대체하지 않음.
7. 기존 dev/prod 서비스·소스·데이터 보존과 작업 삭제 후 해당 소유 자원만 사라졌는지 확인.
8. squash를 포함한 병합 대상 소스로 연결한 뒤 worktree를 정리하고, 앱 목록에서 다시 선택해 새 작업을 만들 수 있는지 확인. 영속 연결 인계 실패 시 정리를 보류하고 기존 검증 기록을 보존.

새 지원 프로파일의 실제 격리/정리 근거가 없으면 해당 프로파일을 완료로 표시하지 않는다. 장비 업무의 세부 기능 전수 검사, 반복 모델 벤치마크, 수용량/부하 검사는 이 완료 조건에 추가하지 않는다.

## 11. 후속 범위와 참고

다중 사용자 Workbench, Kubernetes/다중 서버 스케줄링, 모든 언어/SDK/인프라 자동 지원, 상세 운영 대시보드, 광범위 하네스 벤치마크, 장비 앱 기능 확장은 기존 [후속 문서](FOLLOW_UP_ENHANCEMENTS.md)와 [앱 이슈](APP_ISSUES.md)에 남긴다. 위 필수 생성·표시·재개·병합·정리는 고급 UX 항목으로 미루지 않는다.

공식 사례는 설계 참고이며 MIY의 사용자 합의를 덮어쓰지 않는다:

- [Git worktree](https://git-scm.com/docs/git-worktree): 같은 저장소의 여러 작업 트리와 공유 metadata.
- [Backstage 템플릿 설정](https://backstage.io/docs/features/software-templates/configuration/): 새 저장소 및 기존 저장소 PR/MR 경로.
- [Retool Source Control](https://docs.retool.com/source-control/quickstart): 앱 변경·브랜치·리뷰·반영 상태 연결.
- [PostgreSQL DB 분리](https://www.postgresql.org/docs/current/manage-ag-overview.html), [OpenSearch 권한](https://docs.opensearch.org/latest/security/access-control/users-roles/), [Qdrant 분리](https://qdrant.tech/documentation/manage-data/multitenancy/): 공유 서비스와 데이터·접근 범위의 구분.
