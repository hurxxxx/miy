# MIY Workbench

앱 개발·유지보수·플랫폼 운영을 연결하는 단일 소유자 Workbench다. 개발 실행에는 본인의 ChatGPT 구독으로 로그인한 Codex를 사용한다.
계획과 실행 두 모드로 질문·조사·문서 정리·코딩과 결과 검토를 진행한다.
소스는 같은 저장소에서 관리하며, miy 개인 앱에서 새 탭으로 연다. 콘솔의 실행 프로세스·
로그인 세션·업무 DB는 miy와 분리되어 있다. miy에서 허용된 관리자가 앱 링크를 열면 짧게
유효한 일회용 코드로 별도 콘솔 세션을 만들 수 있다.

## Studio·앱 관리·플랫폼 관리

로그인 기본 화면은 `?view=studio`다. `?view=apps`는 앱 관리 센터, `?view=platform`은 플랫폼 관리다.
앱 선택은 `app` query로 복원하며 기존 작업·템플릿·세션 URL은 유지한다. 표시 이름만 MIY Workbench로
바꾸고 `codex-console` 앱 ID, 환경변수·서비스 이름, 저장소 경로와 기존 인증은 보존한다.

- Studio는 기존 앱 선택, 신규/확장 프로젝트, 재사용 검토 근거, 개발 요청 초안, 관련 작업과 개발 앱 열기를 제공한다.
  프로젝트 등록은 배포나 앱 설치가 아니다. 신규 앱의 코드·등록·생성 계약은 승인된 개발 작업으로 반영한다.
  앱 선택은 작업 문맥이며 파일 접근 격리 경계가 아니다. 작업 실행은 동일한 계획·실행·승인·diff 기능을 사용한다.
- 앱 관리 센터는 개발/설치 리비전, CI 현황, 문제·패치·담당자·목표 일정, 월별 개발/운영 사용량·예산·알림을 제공한다.
  업무 규칙·앱 내부 설정·사용자/그룹·자원 권한 편집은 각 앱과 MIY 공통 관리 기능이 소유한다.
  모든 앱 계약을 발견하며 `management`가 없어도 목록에 표시한다. 앱 설명·기능·소스·배포 단위는
  선택적인 `management`를 읽고, 이름의 `title_translations`와 `icon_key`는 플랫폼과 같은 앱 계약을 사용한다.
  검색은 현재 언어의 이름과 기본 이름·ID·설명·기능을 함께 찾는다.
- 플랫폼 관리는 로컬 Git·최근 커밋·worktree, GitLab의 최근 브랜치·열린 MR·파이프라인, 지침·템플릿·서비스 관측을 연결한다.
  GitLab은 설정된 checkout의 `origin`과 서비스 OS 사용자의 `glab` 인증을 사용한다. 조회당 최대 20개이며 자동 fetch하지 않는다.
  `glab api --method GET`만 사용하고 명령 입력 UI나 범용 HTTP 프록시를 제공하지 않는다.

앱 발견, 소스 연결, 미리보기 연결, 배포 단위 연결은 각각 표시한다. 소스가 없으면 경로나
`miy-app` 배포를 추정하지 않고 연결 설정 검토 작업을 연다. 연결된 경로가 실제 체크아웃에
존재해야 수정 개발을 시작할 수 있으며, 서버도 명시적인 개발 요청에 같은 조건을 적용한다.
미리보기 URL이나 배포 단위 설정은 실행 상태·배포 권한·검증 성공의 증거가 아니다.
로컬 계약 목록에는 앱 수 200개 제한을 두지 않으며 원본 파일의 기존 크기·경로 보안 제한은 유지한다.

### 사용량·패치 검증 계약

개발 사용량은 공식 `thread/tokenUsage/updated`의 누적 토큰에서 관측된 증가분을 UTC 월별로 저장한다.
중복·역순 이벤트는 재합산하지 않는다. 불러온 기존 대화나 처음 발견한 하위 대화는 첫 관측을 기준점으로 삼아
이전 사용량을 현재 월에 부과하지 않는다. 누락 이벤트·처음 관측 이전의 사용량은 추정하지 않으므로 관측 집계로 표시한다.
ChatGPT 구독의 실제 청구 금액은 제공되지 않으며 0원으로 환산하지 않는다.
운영 사용량은 [앱 조회 연계](../../domains/integrations/README.md#앱-관리-조회)의 월별 집계다.
금액 예산은 보고된 비용의 통화가 일치할 때만 비교한다. 현재 MIY는 운영 토큰과 호출 수를 제공하며 금액은 미제공이다.

문제·패치와 예산은 버전 비교로 동시 편집 충돌을 거부한다. 패치의 검증 완료 처리는 정확한 대상 commit에 대한
최신 GitLab pipeline 성공과 해당 설치의 현재 revision을 새로 확인해야 한다. 다른 SHA, 조회 실패, 오래된 캐시는
완료 근거로 사용하지 않는다. 검증 시각·pipeline·설치 SHA를 저장하며 항목 재편집 시 검증 근거를 해제한다.
검증 완료 항목에 새 개발 작업을 연결하려면 항목을 다시 열어야 한다.
CI 성공은 운영 배포 승인 자체를 대신하지 않는다. MIY 앱은 공통 이미지 단위로 배포/롤백한다.
Workbench는 독립 릴리스이며 빌드 시 생성한 `_build.json`의 리비전·변경 여부·산출물 digest를 사용한다.
수정된 소스로 만든 릴리스나 개발 서버는 깨끗한 commit의 설치로 판정하지 않는다.

연동 projection은 SQLite에 보관하고 15초 안의 조회는 재사용한다. 화면은 활성 상태에서 30초마다 갱신한다.
실패한 조회는 마지막 관측과 확인 시각을 함께 표시하고 현재 상태 미확인으로 취급한다. 앱 내부 데이터·프롬프트·
사용자 식별자는 이 projection에 포함하지 않는다. 키·origin 변경은 연동 설정이며 기존 독립 로그인/복구 접근과 분리된다.

### 운영 조회와 개발 화면 연결

기본 Workbench 개발·복구 기능에는 MIY API 키가 필요하지 않다. 운영 집계를 연결하려면 MIY 관리자의
`/admin/api-integrations`에서 **app-catalog:read**, **app-usage:read**만 가진 전용 플랫폼 API 키를 발급한다.
기존 사람의 관리자 토큰이나 디렉터리 전용 키로 대체하지 않는다. 별도 Workbench 환경 파일에 다음 값을 설치한다.

| 설정                               | 용도                                                                         |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| `MIY_CODEX_CONSOLE_MIY_API_ORIGIN` | 연결할 MIY의 정확한 HTTPS origin; 로컬 개발 loopback HTTP 허용               |
| `MIY_CODEX_CONSOLE_MIY_API_KEY`    | 두 조회 scope를 가진 키. origin과 함께 설정하며 서버에서만 사용              |
| `MIY_CODEX_CONSOLE_PREVIEW_ORIGIN` | 선택적인 개발 Web origin. 앱 등록 경로를 새 탭으로 열며 인증을 공유하지 않음 |

키는 0600 환경 파일로 설치하고 출력·대화·브라우저·작업 프롬프트에 넣지 않는다. 외부 요청은 설정된 origin과
고정된 조회 경로만 사용하고 redirect 금지, 응답별 1 MiB·10초 제한을 적용한다.
운영 카탈로그는 페이지당 200개씩 전체를 읽고, 전체 조회에 30초·16 MiB 한도를 적용한다.
각 페이지의 `catalog_revision`·총 개수·순서·중복·누락을 검사하고 하나라도 달라지거나 조회가
실패하면 부분 목록을 현재 관측으로 저장하지 않는다. 실패 시 마지막 완전한 관측을 미확인 상태로 유지한다.
독립 앱 상세의 설치 환경도 같은 제한으로 전체 조회한다. 환경·주소·현재 설치 리비전·산출물과
최신 배포 요청 ID/상태를 표시하며, queued/unknown을 설치 성공으로 표시하지 않는다.
서버의 배포 기록을 현재 서비스 health check로 해석하지 않는다. 조회 실패 시 마지막 관측 시각을
갱신하지 않으며 연결할 MIY origin이 바뀌면 이전 서버의 관측을 넘겨받지 않는다. 이 화면의 조회는
배포·재시작을 실행하지 않고 기존 `app-catalog:read` 권한만 사용한다.
GitLab은 요청별 12초·1 MiB 제한이다.
API 미지원, 권한 거부, 미설정, 연결 실패는 각각 표시한다. 운영 API를 먼저 배포한 후 키를 연결한다.
설정 설치만으로 서비스 재시작을 승인하지 않는다. 실제 전환은 아래 별도 릴리스 절차를 따른다.

### 독립 앱 배포 도구

등록된 독립 앱의 개발 설치 환경에는 별도
[소유자 위임](../../../apps/api/src/miy_api/domains/independent_apps/README.md#workbench-delivery-delegation)을
연결한다. `MIY_CODEX_CONSOLE_APP_DELIVERY_GRANTS`는 `app_id`, `installation_id`, `token`을
가진 배열이며 기본값은 `[]`다. 토큰은 MIY 소유자의 실제 로그인에서 필요한 action만 발급하고
Workbench 서버의 0600 설정에 보관한다. 브라우저·Task·Codex·SQLite 관측에는 원문을 넣지 않는다.
조회용 `MIY_API_KEY`를 쓰기 권한으로 확대하지 않는다. 위임 만료/폐기·원본 로그인/계정·회사 및
앱 권한은 플랫폼이 요청과 실제 실행 시 다시 확인한다.

설치 상세의 점검·미리보기 배포 계획·복구 계획은 정확한 app/installation을 Task에 고정한다.
기본 템플릿 3개도 선택한 앱과 개발 설치 환경을 버전 있는 정의에 저장하며 실행 snapshot을
보존한다. 계획에서 변경 도구를 실행할 수 없다. 원격 환경의 현재 parent thread/turn에 대해
승인된 배포 실행만 로컬 checkpoint→정의 sync→core 검증 빌드→검증된 release 배포를 요청한다.
복구 Task는 기존 상태 조회와 검증된 이미지 rollback에 한정한다. 원본 DB downgrade·Git 게시·
운영 환경 배포는 이 도구의 action이 아니다. 앱이 host 경로·명령·Docker image나 성공 결과를
입력할 수 없고 core 실행기가 실제 산출물과 검증 근거를 만든다.

외부 build/deployment ID는 Task·설치·작업·불변 입력으로 결정하고 제출 전 기존 상태를 조회한다.
응답 유실은 `unknown`과 같은 요청 ID로 남긴다. 확인된 `failed`만 사용자가 명시한
`retry_request_id`로 새 요청에 연결할 수 있으며 running/unknown을 새 요청으로 대체하지 않는다.
queued는 core 실행기 대기, succeeded는 검증된 실행 기록이며 현재 서비스 health와 구분한다.
core CLI나 DB/Docker 자격 증명을 앱 실행 환경에 설치하지 않는다.

`checkpoint`는 연결된 원격 앱 실행 환경의 독립 Git 저장소에서만 제공한다. 현재 named branch의
일반 체크아웃이 필요하며 detached HEAD는 `app_checkpoint_named_branch_required`로 거부한다.
기존 staging이나 충돌을 덮어쓰지 않고, 플랫폼 체크아웃과 Task 범위 밖 변경도 거부한다.
서버는 최대 2,048개 파일·합계 32 MiB(개별 파일 2 MiB)의 안전한 snapshot만 처리한다.
심볼릭 링크·hardlink·FIFO·비밀 경로를 거부하고, 삭제된 tracked 파일은 삭제로 기록한다.
Git hook/filter/서명·외부 설정·네트워크를 실행하지 않으며 고정된 작성자와 메시지로 Git plumbing
commit을 만들고 HEAD CAS와 Git의 prepare/commit ref transaction으로 게시한다.
파일이 바뀌지 않았다면 기존 리비전을 반환한다. 동시 파일/HEAD 변경은 conflict로 드러나며,
강제 종료가 ref와 index 갱신 사이에 발생하면 남은 staged 차이를 숨기거나 자동 복구하지 않는다.
이 기능은 사용자가 승인한 앱 배포 실행 안의 로컬 commit이며 플랫폼 소스 commit이나 Git push를
허용하지 않는다. 실제 빌드와 배포는 별도의
[opt-in 코어 consumer](../../../apps/api/src/miy_api/domains/independent_apps/README.md#optional-core-queue-consumer)가
설정된 설치 환경의 durable intent를 소비해야 진행된다. Workbench가 그 서비스를 설치·시작하지 않는다.
소비자는 중단된 배포를 같은 요청 ID로 관측해 확인된 결과와 정리를 이어간다. 새 배포를
재실행하는 기능은 아니며, 실제 runtime을 확인할 수 없으면 `unknown`과 예약을 유지한다.

### 독립 앱 소스 연결

Workbench 목록은 기본 체크아웃 등록, MIY 운영 카탈로그 전체, 소유자가 연결한 독립 앱을 합친다.
운영에서 발견한 앱은 소스가 없어도 표시하며 개발 대신 연결 상태를 검토할 수 있다. 원격 등록의
이름·번역·아이콘을 그대로 사용한다. 독립 앱의 소스 연결만으로 배포 단위를 추정하지 않는다.
소스 상태와 실행 환경 설정도 구분한다. `execution_status=configured`는 해당 소스에 연결된
서버 설정이 있다는 뜻이며 연결·정책 검사의 성공을 뜻하지 않는다. 실행 환경 설정이 없으면
소스는 목록에 유지하되 개발·설치 조치 버튼을 비활성화하고 새 bound Task의 생성도 거부한다.
실제 연결과 버전은 실행을 시작할 때 다시 검사한다.

`MIY_CODEX_CONSOLE_APP_SOURCE_ROOTS`에 소유자가 관리하는 절대 경로 배열을 설치한다.
예: `["/projects/personal-apps"]`. 기본 `[]`는 연결을 허용하지 않는다. 앱이 매니페스트에서
허용 경로·호스트 명령·자격 증명을 설정할 수 없다. `앱 소스 연결`에서 앱 식별자와 실제 Git
체크아웃 경로를 명시한다. 저장소 루트의 `app.manifest.json`은 공통 생성 스키마에 맞아야 하며,
앱 식별자·`source.repository`·실제 `origin` 저장소가 일치해야 한다. 운영 등록에 소스가 있으면
그 저장소·하위 디렉터리와도 일치해야 한다. 원격 URL은 비교만 하며 자동 clone/fetch하지 않는다.

연결 정보·검증한 매니페스트·버전은 SQLite `console_app_sources`에 보관한다(`console_sqlite_0005`).
새 작업은 그 시점의 소스 경로·저장소 정체성·HEAD를 고정한다. 템플릿의 상대 경로는 이 앱 소스
아래에서 해석한다. 독립 앱은 아래 원격 실행 환경을 별도로 연결하며 자동 host worktree는 거부한다.
연결을 변경해도 기존 작업 경로는 바뀌지
않는다. 재개 시 현재 허용 경로·보호 경로·Git 정체성을 다시 확인하지만 기존 작업은 손상되거나
삭제된 매니페스트를 복구할 수 있다. 새 작업·새 연결은 유효한 매니페스트가 필요하다.

연결 루트는 일반 Git 체크아웃만 허용하며 외부 `.git` 파일·심볼릭 링크·운영 경로·SQLite/
첨부 저장소·Codex 및 SSH 자격 증명 경로와의 겹침을 거부한다. 서비스 환경 파일 등 별도 비밀
경로도 `MIY_CODEX_CONSOLE_PROTECTED_WORKSPACES`에 명시한다. 기존 코어 worktree 작업은
고정한 원본 Git metadata와 작업별 backpointer를 검사한다. 서버의 Git 호출은 hooks/fsmonitor/
외부 diff 및 전송을 비활성화하고 실행 가능한 filter/textconv와 partial/promisor clone 설정은
연결 시 거부한다. 이는 기존 Codex 자체의 작업 실행·승인 정책을 대체하지 않는다.

`console_sqlite_0003`은 프로젝트·유지보수·예산·사용량·관측 테이블만 추가한다. 기존 작업·첨부·템플릿은 보존한다.
전환 전 online backup을 만들고 모든 역할 서비스를 정지한 상태에서 migrate한다. 이전 실행기는 schema가 일치하지
않는 DB로 시작할 수 없으므로 복구 시 이전 릴리스와 전환 전 DB 백업을 함께 복원한다.

#### 프로젝트에서 새 앱 소스 준비

새 프로젝트의 `앱 소스 준비`는 소유자가 명시적으로 요청한 초기 소스만 만든다. 운영자는
`MIY_CODEX_CONSOLE_APP_CREATION_ROOTS`를 설정해야 한다. 기본값 `[]`이며 각 경로는 기존
`APP_SOURCE_ROOTS` 안의 서비스 계정 소유 디렉터리여야 한다. 그룹·다른 사용자의 쓰기 권한,
심볼릭 링크 경로, 코어 checkout·운영·워크트리·SQLite·인증 저장 경로와의 겹침은 거부한다.
기존 읽기/연결 허용만으로 새 디렉터리 생성 권한을 부여하지 않는다.

화면에서 제공된 root와 `basic` 또는 `private-notes` 템플릿을 선택하고 자격 증명 없는 HTTPS
저장소 식별자를 입력한다. 서버는 `${root}/${app_id}`만 목적지로 사용하며 사용자가 임의 경로나
명령을 보낼 수 없다. 새 앱 ID는 공통 독립 앱 계약을 따른다. 기존 프로젝트의 이전 ID는 조회를
유지하되 새 소스 준비에서는 유효한 ID가 필요하다. 저장소 식별자는 로컬 `origin`에 기록할 뿐
원격 저장소를 만들거나 clone/fetch/push하지 않는다. 의존성 설치나 앱 명령도 실행하지 않는다.

템플릿과 SDK는 canonical `templates/independent-app`, `templates/independent-app-data`,
`packages/app-sdk`에서 생성한 `app_starters.generated.json`으로 별도 Workbench 릴리스에 포함한다.
플랫폼 checkout이 없어도 동일한 두 템플릿을 준비한다. `pnpm generate:app-starters`로 생성하고
`pnpm check:app-starters`로 검증한다. 계약 CI·Workbench CI·릴리스 빌드 모두 최신 묶음 여부를
검사하며 기존 플랫폼 scaffold CLI와 같은 원본을 사용한다.

준비 요청의 operation UUID·입력·bundle digest를 `console_app_source_setups`에 먼저 기록한다.
동일 프로젝트/동일 요청은 같은 결과를 조회하거나 재개한다. 응답을 잃어도 상태 GET으로 결과를
확인한다. 기존 파일은 덮어쓰지 않으며, 같은 요청이 만든 inode의 변경 없는 부분만 재개한다.
서비스 계정의 private staging에서 고정 Git 명령으로 첫 commit을 만들고 Git 객체 해시·tree·index와
템플릿 바이트를 검증한다. 호스트 Git 설정·hooks·template·전송은 사용하지 않는다. Linux의 원자적
no-replace rename이 지원되지 않으면 공개하지 않는다. 목적지가 경합 중 생겨도 바꾸지 않는다.
공개 후 응답 유실에서 복구할 때도 같은 소스/commit 검사를 적용한다.

파일 변경·외부 inode·손상된 Git metadata가 확인되면 `conflict`로 보존하고 자동 삭제나 덮어쓰기를
하지 않는다. 디렉터리 생성 직후 inode 기록 전 중단, 부분 파일/metadata 쓰기 중단은 안전한 재개를
입증할 수 없어 운영자 확인이 필요할 수 있다. `ready` 요청의 재조회는 이후 개인 편집을 검사하거나
되돌리지 않는다. 완료 시 기존 소스 연결 계약으로 binding과 ready 상태를 같은 DB 트랜잭션에 저장한다.

이 기능은 **소스 준비·연결까지만** 수행한다. 플랫폼 앱 등록·설치·배포·executor 구성 및 자연어
생성 도구는 별도 단계다. executor가 미구성인 앱은 계속 `execution_status=unconfigured`이며
개발 Task를 시작하지 않는다. 기존 계획 전용 Task도 실행 권한을 승계하지 않는다.

`console_sqlite_0006`은 준비 기록 테이블만 추가하고 기존 프로젝트·Task·연결·템플릿을 보존한다.
업데이트 시 아래 저장소 계약에 따라 백업 후 모든 역할 서비스를 중지하고 migration한다.

#### 현재 소스의 플랫폼 등록 초안

소스가 연결된 새 프로젝트와 확장 프로젝트는 소유자 로그인으로
`GET /api/workbench/projects/{project_id}/registration-draft`를 조회할 수 있다.
이 읽기는 초기 source-setup 결과를 복사하지 않는다. 현재 허용 경로·소스 연결 version·저장소와
디렉터리 식별자·깨끗한 Git HEAD·manifest를 다시 검사하며, 조회 중 binding·경로 inode·HEAD·
manifest가 달라지면 결과를 반환하지 않는다. `assume-unchanged` 등으로 상태 검사에서 숨겨진
manifest 변경도 고정 HEAD의 정규화된 정의와 비교한다. 수정 중인 소스는 `app_source_dirty`,
연결이나 대상 변경은 `app_source_changed`로 표시한다. 파일을 수정하거나 commit하지 않는다.

버전 1 envelope는 `project_id`, `binding_version`, `app_id`, 현재 `source_revision`,
원본 파일 바이트의 `source_manifest_digest`, 정규화된 `definition`과 `definition_digest`를
포함한다. 후자는 Core와 같은 기본값·정렬 JSON·ASCII escape 해시이며 원본 파일 해시와 다르다.
스키마가 선언한 정수 상수는 `1.0` 표현도 `1`로 정규화하며 bool·문자열 버전은 거부한다.
권한 배열의 순서는 보존한다.
로컬 경로·자격 증명·operation UUID·승인 토큰은 포함하지 않는다. 기존 canonical manifest schema와
정규화를 패키지에서 재사용하므로 플랫폼 API checkout을 import하거나 네트워크에 접속하지 않는다.
JSON Schema가 표현하지 않는 Core의 추가 의미 검증은 등록 API가 최종 수행한다. 초안 생성 성공이
Core의 등록 수락을 보장하지 않는다.

이 초안은 현재 등록할 메타데이터이며 소스 빌드 검증이나 실행·배포 권한이 아니다. 조회가 끝난 뒤
소스는 다시 바뀔 수 있고 실제 빌드는 등록된 commit을 별도로 검증한다. 포털의 현재 사용자 권한으로
등록을 확인하는 다음 단계와 별개이며, 이 GET은 Registry·설치·SQLite 상태를 쓰지 않는다.
새 DB migration이나 executor 구성도 필요하지 않다.

#### 등록 초안 파일로 최초 앱 등록

1. 소스 연결이 준비된 프로젝트에서 **앱 등록 초안 내려받기**를 눌러
   `miy-app-registration.json`을 저장한다. 현재 소스가 변경 중이면 먼저 개발 작업을 마치고
   다시 내보낸다. 원본 `app.manifest.json`의 상한은 **64 KiB**이며, 메타데이터를 함께 담는
   내려받기·가져오기 파일의 상한 **256 KiB**와 다르다.
2. 실제 MIY 포털에 앱 소유자로 로그인한 뒤 앱 목록의 **앱 등록** 또는 `/apps/register`를 연다.
   Workbench 로그인만으로 MIY 등록 권한이 생기지 않는다. 파일을 열고 앱 ID·저장소·소스 revision을
   확인한 뒤, 자신이 운영할 앱 전용 개발 origin과 요청 권한 중 허용할 항목을 선택한다.
   플랫폼 origin과 같은 주소는 사용할 수 없다. 등록은 해당 서버의 소유권·가동 상태를 검사하지 않는다.
3. 등록을 확인하면 현재 MIY 사용자의 권한으로 personal 정의와 **비활성 development 설치**를
   한 트랜잭션에 만든다. 대상은 소유자 한 명뿐이며 관리자도 이 화면에서 전사·운영 설치로 확대할 수 없다.
   기존 앱 ID는 충돌로 처리한다. 확장 프로젝트에서 내보낸 초안도 기존 등록을 덮어쓰는 용도로 사용할 수 없다.

포털은 operation UUID만 `?operation=…`에 남기며 초안·origin·권한 선택·로그인 토큰은 URL에 넣지
않는다. 응답을 잃으면 같은 UUID로 결과를 조회한다. 결과가 불명확한 동안에는 제출한 입력을 유지하고
자동으로 다시 등록하지 않는다. 사용자가 재시도를 선택할 때도 같은 UUID와 입력을 사용한다.
조회 404는 최초 요청이 아직 처리 중일 수도 있으므로 새 UUID로 바꾸는 근거가 아니다.
명확한 입력·권한·충돌 거부를 교정할 때도 UUID는 유지한다. 새로고침하면 결과 조회만 수행하며,
완료 기록이 없어서 다시 제출해야 할 때는 원래 파일과 같은 입력이 필요하다.

완료 화면의 receipt는 **최초 등록의 역사적 기록**이다. 이후 설치가 바뀌어도 같은 기록을 반환하며,
현재 실행 준비·설치 활성화·배포 성공을 뜻하지 않는다. 현재 상태는 Workbench의 별도 조회로 확인하고,
개발 executor·배포 위임·코어 실행기 구성 및 실제 빌드·배포를 이어서 준비한다.
검증된 MIY issuer와 등록 receipt가 있으면 Workbench는 해당 설치의 MIY 미리보기 설정을
새 탭으로 연결한다. MIY의 현재 소유자가 초기 개발 설치의 허용/권한을 직접 확인하는 화면이며,
링크 클릭이 권한을 부여하거나 앱을 실행하지는 않는다. 제한 범위와 동시 변경 처리는
[최초 개발 설정 계약](../../../apps/api/src/miy_api/domains/independent_apps/README.md#owner-only-initial-development-preview-settings)이 소유한다.
파일 내려받기·가져오기는 기본 인계 방식이다. 아래의 선택적인 최초 등록 위임을 설정하면
명시적 MIY 승인 뒤 새 등록 작업의 native 도구로 같은 요청을 전달할 수 있다.
이 흐름은 COOP를 완화하거나 새 쓰기 토큰을 만들지 않으며 MIY 로그인 토큰을 Workbench에 넘기지 않는다.
원자 등록·멱등성·권한의 API 계약은 [최초 등록 계약](../../../apps/api/src/miy_api/domains/independent_apps/README.md#atomic-first-registration)이 소유한다.

#### Workbench에서 최초 등록 한 번 허용

기본값은 비활성이다. Core의 `MIY_CODEX_CONSOLE_REGISTRATION_AUDIENCES`에 정확한 Workbench
`origin + base_path`를 허용하고, Workbench에
`MIY_CODEX_CONSOLE_REGISTRATION_AUTHORIZATION_ENABLED=true`를 설정한 경우에만 제공한다.
기존 `MIY_CODEX_CONSOLE_MIY_API_ORIGIN`과 `MIY_CODEX_CONSOLE_SSO_SUBJECTS`의 예상 MIY 사용자
식별자를 사용한다. 조회용 API key·identity-only SSO 코드·기존 설치 배포 위임은 등록 권한으로
승격하지 않는다. 설정 변경·서비스 재시작·배포는 이 로컬 구현 검증에서 수행하지 않았다.

1. 독립 앱 소스와 executor가 연결된 프로젝트에서 **새 등록 작업**을 만든다. 기존 일반 대화에
   등록 도구를 소급 추가하거나 thread를 몰래 재생성하지 않는다. 새 작업은 선택된 앱의 일반
   checkout을 사용하며 코어 checkout으로 대신 실행하지 않는다.
2. 작업의 **최초 앱 등록**에서 본인이 운영할 정확한 개발 앱 origin을 입력하고 **등록 권한 연결**을
   누른다. **MIY에서 승인**으로 현재 MIY 소유자가 고정 app ID·origin·runtime profile·요청 권한을
   확인한다. 승인은 personal/create-only/비활성 development/본인만의 설치 한 번으로 한정하며
   실제 초기 granted permissions는 빈 목록이다. 등록 권한만으로 앱이 활성화되거나 배포되지 않는다.
3. 승인 뒤 같은 작업의 **연결 상태 새로고침**으로 확인하고 작업 구현을 명시적으로 승인한다.
   새 native thread의 `miy_app_registration` 도구는 `context`, `checkpoint`, `register`, `status`만
   받는다. 소스 경로·manifest·origin·권한·명령·operation ID를 모델 인자로 받지 않는다.
   `register`가 현재 Task의 실제 workspace에서 읽은 깨끗한 commit과 canonical manifest를
   고정된 등록 요청으로 제출한다. linked Git worktree의 깨끗한 snapshot 읽기는 지원하지만 기존
   안전 checkpoint broker는 이름 있는 브랜치의 일반 checkout만 지원하므로 연결 worktree의
   checkpoint는 명시적으로 거부한다. 원본 checkout으로 fallback하지 않는다.

등록 정책은 기존 `identity:read`, `data:read`, `data:write`와 선택적인 `files:read-selected`까지
최대 네 권한을 표현한다. 새 파일 권한은 manifest에서 명시해야 하며, 기존 앱·기본 템플릿·메모
템플릿에 자동 추가하지 않는다. 등록 위임의 초기 허용 권한은 여전히 빈 목록이다. 이 권한은 사용자가
포털에서 선택한 파일 한 개의 제한된 읽기에만 쓰이며, Workbench 등록이나 소스 생성이 파일 목록 조회·
파일 선택 승인·앱 실행 권한을 대신하지 않는다.

승인 시작 URL에는 공개 정책·request/operation UUID·S256 challenge·audience만 담는다.
전체 manifest·저장소 URL·승인 코드·bearer·verifier는 넣지 않는다. Core 포털은 짧은 코드를 정확한
`{audience}/api/registration-authorizations/callback`에 form POST한다. callback만 설정된 정확한
MIY Origin·원래 Workbench WebSession의 현재 생존·pending request·PKCE·audience·예상 MIY 사용자로
검증하고, 나머지 요청의 Origin/CSRF 및 COOP/CSP는 그대로 유지한다. cross-site POST에는
SameSite=Strict cookie가 없을 수 있어 callback은 pending에 저장된 세션만 사용하며, 비밀 없는
Task URL로 303 복귀한 뒤 현재 브라우저 세션을 다시 확인한다. 실패한 코드 교환도 확인된 Task로
돌아가 재연결을 안내하며 코드를 자동 재전송하지 않는다.

SQLite `console_registration_intents`(`console_sqlite_0008`)에는 Task별 original session hash,
고정 operation UUID, 승인 참조, 제출 전 고정한 본문과 역사적 receipt만 저장한다. bearer와 verifier는
DB 파일 옆 `registration-credentials`의 서비스 사용자 소유 0700 디렉터리·0600 개별 파일에 보관한다.
경로 구성 요소의 symlink, 잘못된 owner/mode, hardlink와 앱·native mount 영역 중첩은 거부한다.
세 Workbench 프로세스가 같은 저장소를 읽으며 credentials를 Task context·native 도구 응답·브라우저
API·관측·로그에 넣지 않는다. 코드 교환 실패·재연결·로그아웃은 해당 소유 파일만 정리한다.
SQLite 백업만 복원한 경우 credential 파일은 복원되지 않는다. 작업/receipt는 남지만 등록 권한은
새로 연결해야 한다. 이 파일들은 짧은 권한이므로 일반 소스 백업이나 앱 mount에 포함하지 않는다.

POST 전에 등록 본문과 operation을 저장한다. 응답 유실·잘못된 응답은 `unknown`이며 자동 재실행하지
않는다. **동일 등록 작업 결과 조회**는 현재 로그인·승인으로 Core의 고정 operation receipt만 읽으며,
404가 앱 ID 사용 가능이나 새 작업 생성의 근거가 되지는 않는다. 소스가 바뀌거나 사라져도 이미
제출한 요청은 덮어쓰지 않는다. 만료 후 명시 재연결은 기존 정책과 operation을 유지하고, 새 현재
MIY 승인으로 기존 receipt를 조회한다. receipt의 operation·app·정의 digest·revision이 고정 본문과
일치해야 하며, 과거 결과를 현재 소스나 설치 준비 완료로 표시하지 않는다.

다른 Workbench 로그인 세션은 이전 grant를 이어받아 새 turn/쓰기 action을 실행할 수 없다.
예외적으로 **상태 복구**는 현재 로그인한 소유자가 기존 native thread의 정확한 identity와 idle
증거를 확인해 불확실한 Task/lease를 정리하는 읽기 복구만 수행한다. 이전 intent의 세션·grant·본문은
바꾸지 않으며 active/unknown native 상태는 거부한다. 이후 새 turn을 시작하려면 명시적 재연결과
새 MIY 동의가 필요하다. 원격 executor가 실제로 준비되었는지는 별도 조건이며, 이 위임 연결만으로
자연어 앱 생성·빌드·배포 전체가 완료되었다고 보지 않는다. 미설정·구버전 Core에는 기존 JSON
내려받기/포털 가져오기 경로를 계속 사용한다.

#### 소스와 플랫폼 등록 비교

소스를 연결한 프로젝트의 **등록 상태 확인**은 현재 소스를 다시 검사한 뒤
`GET /api/workbench/projects/{project_id}/registration-status`로 플랫폼 등록 메타데이터를
비교한다. 자동 조회나 등록 요청은 수행하지 않는다. 기존 목록에 소스 충돌로 표시된 연결도
재확인할 수 있지만, 변경 중이거나 유효하지 않은 소스는 오류로 표시한다.

결과는 **확인 시점**의 기록이다. `platform_checked_at`과 확인한 소스 커밋을 표시하고,
앱 정의와 등록된 커밋의 차이를 각각 구분한다. 조회 불가·설정 미완료·권한 거부·지원하지 않는
계약 또는 불완전한 메타데이터는 `unknown`이며 미등록으로 판단하지 않는다. 다른 저장소나
소스 디렉터리의 동일 앱 ID는 `collision`으로 표시하고 기존 앱의 수정·재등록으로 연결하지 않는다.

같은 소스의 `matching`·`different` 결과에서 **앱 설치 환경 보기**를 선택하면 기존 앱 관리 화면의
설치 조회로 이동한다. 등록 일치는 설치 활성화·executor 준비·배포 성공의 증거가 아니다.
확인 후 소스를 편집했다면 다시 조회해야 한다. 재조회 중에는 이전 결과를 지우며 프로젝트·앱·
소스 연결 버전이 바뀌면 결과와 진행 중인 요청을 폐기한다. 화면을 떠날 때와 30초 기한에도
요청을 취소하고 늦게 도착한 응답을 무시한다. 이 기능은 기존 조회 권한만 사용하며 자동 polling,
새 쓰기 토큰, COOP 변경 또는 등록·실행·배포 쓰기를 추가하지 않는다.

#### 독립 앱의 native 원격 실행

Studio의 독립 앱 프로젝트는 **계속 개발** 또는 **새 등록 작업** 전에 실행 환경의
연결 메타데이터를 확인한다. **실행 환경 연결 확인**으로 작업을 만들지 않고 같은
조회만 할 수도 있다. 소스가 연결되기 전의 계획 작업과 공식 checkout 작업은 기존
흐름을 유지한다.

`GET /api/workbench/projects/{project_id}/execution-readiness`는 현재 프로젝트의
소스·매니페스트·binding version·HEAD와 운영자가 구성한 환경을 확인하고 아래의
기존10초/64KiB `initialize` 검사로 정확한 버전·cwd를 조회한다. 조회 후 소스나 환경이
달라졌으면 `changed`로 처리한다. SQLite 기록, native thread·turn, 파일·명령 실행이나
설정 변경은 하지 않고 endpoint·capability·원격 오류 원문을 응답하지 않는다.
화면은 프로젝트·소스 버전·선택이 바뀌거나 로그아웃하면 진행 중인 조회를 폐기하고,
동일한 조회 중 중복 클릭으로 Task를 만들지 않는다. 작업을 시작할 때마다 새로 확인한다.

카탈로그의 `execution_status=configured`는 설정 연결 여부이고, 이 조회의
`state=reachable`은 표시된 확인 시각의 연결·버전·cwd 관측이다. 현재 Task 생성·실행
권한, 구독 인증이나 격리 정책 전체의 준비를 증명하지 않는다. 조회 결과는 Task 실행
허가가 아니며 서버는 실제 작업 시 기존 현재 소스·환경·인증·정책 검사를 유지한다.
관측 이후의 연결 교체나 권한 회수에도 호스트로 대체 실행하지 않는다. 아래의 운영
환경 준비·sandbox 검증 조건은 별도로 완료해야 한다.

독립 앱의 수정 작업은 앱별 checkout만 보이는 공식 Codex `exec-server`에 전달한다. 소유자의
구독 인증·thread/turn/하위 agent 수명은 host `app-server`가 계속 관리한다. 앱 Task마다 별도
native 연결을 사용하며 코어 Task의 host 실행과 분리한다. 환경 연결이 없거나 달라지면 실행을
거부하며 host 실행으로 대체하지 않는다. 프로젝트의 소스 연결 전에 만든 계획 전용 Task는
나중에 소스를 연결해도 실행 권한을 승계하지 않는다. 연결 후 새 개발 Task를 만든다.

이 경로는 **Codex 0.160.1 정확 버전**의 실험적 native 환경 RPC를 사용한다. 코어/템플릿의
기존 0.159.2 소비 계약과 별도인 `remote_protocol.generated.json`으로 환경·동적 도구의
스키마도 검증한다. 생성 계약 검사는 `python3 scripts/generate-codex-remote-contract.py --check`다.
app-server의 환경 조회 응답은 executor 버전을 노출하지 않으므로 매 연결·재연결 전에 동일한
capability와 공식 exec-server `initialize`로 원격 0.160.1/cwd를 읽기 전용 확인한다. 이 좁은 검사는
프로비저닝 검사기의 클라이언트를 재사용하며 10초와 응답 64 KiB 상한을 적용한다. 같은 endpoint에서
실행 파일이 교체되어 버전이 달라져도 새 native 연결을 거부한다. 파일 쓰기 검사는 재연결 때 하지 않는다.
`environment/add`와 thread/turn 환경 선택자를 사용하며 local provider는 비활성화한다.
새 app-server의 0.160.1 `thread/resume`은 이전 원격 선택자를 복원하지 않는다. 기존 Task에
저장된 연결 세대가 새 연결과 다르고 원래 thread·cwd가 정확히 일치할 때만 명시적인 빈 선택
배열을 허용한다. 이때 응답 workspace roots는 명시적인 빈 배열 또는 해당 cwd 하나여야 한다.
0.160.1 응답은 요청의 fallback roots가 아닌 현재 선택된 환경의 roots를 보고하므로 빈 선택은
빈 roots로 나타날 수 있다. 누락·null·다른 roots는 거부하는 이 좁은 재개 어댑터에서도 새 thread와
같은 연결의 재개는 정확한 원격 선택자를 계속 요구하며, 누락·null·local·다른 선택자는 거부한다.
다음 `turn/start`는 항상 같은 Task의
원격 환경을 명시적으로 다시 선택한다. 기존 Task·thread·요청을 유지하며 host 실행으로 대체하거나
새 thread로 자동 재시도하지 않는다.
`CODEX_HOME/environments.toml`이 존재하면 공식 TOML provider의 우선순위 때문에 시작을 거부한다.
host hooks·MCP·앱/플러그인·shell snapshot·host skills discovery·로그인 shell을 끄고, shell 환경은
고정 PATH/HOME만 넘긴다. host custom agent config file은 거부한다. 사용자 Codex 설정은 수정하지
않고 child process 설정으로 적용·재확인한다. 인증 파일을 실행 환경에 복사하지 않는다.

운영자는 먼저 앱 전용 개발 checkout을 만든다. 기존 플랫폼/원본 저장소 전체를 container에
mount하지 않는다. 다음 명령은 고정 40자리 commit을 bounded Git archive로 검사하고 비밀 파일·
링크·외부 Git helper를 거부한 뒤 새 Git metadata와 자격 없는 origin을 만든다. 원본 저장소를
변경하거나 앱 코드를 host에서 실행하지 않는다.

```bash
uv run --frozen --directory apps/api python ../../scripts/prepare-independent-app-workspace.py \
  --source /projects/app-original \
  --revision <40자리-commit> \
  --destination /projects/personal-apps/app-development
```

새 경로 자체가 이후의 앱 개발 저장소다. 원본으로 자동 역동기화하지 않는다. 새 checkout의
HEAD는 원본 commit과 다르며 이후 등록·빌드는 새 개발 HEAD/checkpoint를 사용한다. 앱 컨테이너에는
이 checkout만 같은 절대 경로로 쓰기 mount하고 `.git` metadata는 별도 read-only mount한다.
checkpoint는 코어 broker의 좁은 동작으로만 수행한다. 새 앱/동시 작업이 별도 파일 격리를 필요로
하면 운영자가 별도 checkout과 executor를 준비한다. 다중 사용자·자동 환경 할당은 현재 범위 밖이다.

실행 환경의 최소 운영 계약:

- non-root, 모든 Linux capability 제거, no-new-privileges, 읽기 전용 root filesystem,
  제한된 tmpfs·CPU·메모리·PID, 필요한 public Codex vendor 파일만 read-only 제공한다.
- host root/home·인증·환경 파일·Docker socket·플랫폼 DB를 mount하지 않는다. 앱 실행 환경의
  외부/플랫폼 제어망 접근을 차단하고 exec-server는 내부망에만 바인딩한다.
- 코어 소유 ingress만 `ws://127.0.0.1:<1024 이상 포트>`에 공개하며 별도 capability bearer token을
  검증한다. 고정된 native exec-server0.160.1은 `--ws-auth capability-token`과
  `--ws-token-sha256`으로 WebSocket 연결 시 인증할 수 있다. 기존 보호 proxy를 사용할 수도
  있으며, 어느 구성에서도 인증 없는 연결 거부를 실제 검사한다. Loopback만으로 인증을 대신하지 않는다.
  plaintext capability와 보호 ingress 설정은 앱 checkout·mount에서 읽을 수 없어야 한다.
  토큰 변경은 이미 연결된 socket을 자동 회수하지 않으므로 기존 supervisor가 해당 연결과
  executor를 종료해야 한다. 이 지원 옵션만으로 네트워크 격리·자원 제한·실제 turn을 인수하지 않는다.
- bubblewrap의 nested user namespace와 mount를 허용하는 **별도 검토된 confinement profile**이
  필요하다. host kernel/daemon을 자동 변경하거나 privileged/SYS_ADMIN/unconfined로 우회하지 않는다.

현재 검증 호스트의 Docker 기본 seccomp/AppArmor에서는 native `readOnly`/`workspaceWrite`가
bubblewrap namespace/mount 단계에서 실패한다. `--linux-sandbox-pid-namespace inherit`도 해결하지
않으며 legacy Landlock은 upstream에서 socket 격리 때문에 거부한다. 따라서 기본 Docker 환경을
지원 완료로 간주하지 않는다. 계획 모드를 yolo로 바꾸는 우회도 허용하지 않는다. 별도 confinement
profile 설치와 실제 지원 환경의 검증은 운영 준비 작업으로 남아 있다.

2026-10-08 별도 선행검사에서는 이 호스트의 기본 Docker profile을 변경하지 않고,
owned transient systemd supervisor와 표준 `systemd-socket-proxyd` ingress, 선택된 vendor/library만
보이는 outer bubblewrap을 사용해 위 native 정책과 인증·cwd·kernel 자원 한도를 실제 확인했다.
Proxy는 executor의 private network namespace를 공유하며 caller의 host network를 공유하지 않는다.
이 검사는 기존 provisioning verifier를 재사용했고 임시 unit·endpoint를 정리했다.
현재 Workbench 설정/서비스에 적용한 운영 구성이나 실제 모델 Task의 전체 인수는 아니다.
실행별 정확한 범위와 남은 단계는 [재설계 검증](../../../platform-redesign/VALIDATION.md)이 소유한다.

운영자가 위 경계를 갖춘 endpoint를 별도로 준비한 후 다음 사전 검사를 수행한다. token 파일은
서비스 소유자의 regular file/0600이어야 한다. 검사기는 인증 없는 연결 거부, 정확한 버전/cwd,
native 읽기 전용의 파일·명령 쓰기 거부, workspace 쓰기·자식 process, `.git` 쓰기 거부,
synthetic host canary의 비노출과 임시 파일 정리를 확인한다. 모두 통과해야 설정 JSON을 0600으로
새로 생성하며 기존 파일을 덮어쓰지 않는다. 실패·응답 유실·정리 불확실성에는 설정을 만들지 않는다.
이 검사는 확인한 동작의 증거이며 container의 모든 mount/network 정책에 대한 원격 attestation은 아니다.

```bash
uv run --frozen --directory apps/codex-console-api python ../../scripts/verify-independent-app-executor.py \
  --key app-development-v1 \
  --source-root /projects/personal-apps/app-development \
  --exec-server-url ws://127.0.0.1:19391 \
  --token-file /private/app-executor.token \
  --output /private/app-executor.settings.json
```

출력 파일에는 capability가 있으므로 터미널·로그·소스 저장소에 출력하지 않는다. 보호된 서비스
환경 파일의 `MIY_CODEX_CONSOLE_APP_EXECUTION_ENVIRONMENTS`에 이 JSON 배열을 설치하고 해당 checkout을
`MIY_CODEX_CONSOLE_APP_SOURCE_ROOTS` 안에서 연결한다. 기본 배열은 `[]`다. 연결 key/root/endpoint의
fingerprint는 Task 생성 시 고정되므로 설정을 다른 환경으로 바꾸어 과거 Task를 재지정할 수 없다.
이 문서의 검증·설정 파일 생성은 서비스 설치/재시작/운영 배포를 수행하지 않는다.

현재 독립 앱 실행에서는 host 첨부 cache를 사용할 수 없으므로 메시지 첨부 선택을 거부한다.
첨부 cache나 전체 host 디렉터리를 추가 mount하지 않는다. 향후 명시적으로 선택한 입력만
공식 remote filesystem API로 bounded 전달하는 계약을 추가할 수 있다. host skills 선택과 자동
host worktree도 지원하지 않는다. native remote capability discovery와 표준 child agent는 유지한다.

공식 근거: [0.160.1 exec-server](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/exec-server/README.md),
[환경 provider](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/exec-server/src/environment_provider.rs),
[고정 WebSocket 인증](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/websocket-auth/src/lib.rs),
[Docker seccomp](https://docs.docker.com/engine/security/seccomp/).

## 서비스와 작업 현황

주요 영역은 **MIY Studio · 앱 관리 센터 · 플랫폼 관리**다. 세션·작업 템플릿·지침·스킬·모니터링은
같은 작업 엔진을 사용하는 보조 메뉴다. GitLab 상태는 읽기 전용 API로 확인하며,
조사·개발·배포·복구 실행은 기존 Codex 작업과 승인 흐름으로 연결한다.

템플릿·세션·Codex 세션 불러오기·모니터링 조회 화면은 공통 제목·주요 동작·본문 배치를 사용한다.
서비스 목록은 관측 버전·관측 시각을 함께 표시하고 stale/조회 실패 시 이전 버전은 관측값으로만 남기며 현재 상태를 미확인으로 표시한다. 관측 조회와 템플릿 이동만으로 명령을 실행하지 않는다.
조회 본문은 최대 1,180px로 제한하며 카드 타일 대신 열을 맞춘 행과 구분선을 사용한다.
지침·스킬 작업실은 가용 화면 폭·높이를 사용하고 문서 목록과 읽기·편집 본문을 각각 스크롤한다.
템플릿은 이름·설명으로 검색하고, 행에서 실행·이력을 열며 더보기 메뉴에서 편집·복제·보관한다.
세션 목록은 상태·작업명·갱신 시각·동작을 열에 맞춰 표시하고, 하위 에이전트와 실행 설정은 펼쳐 확인한다.
상태 필터와 모니터링 요약은 간결한 한 줄로 표시하며 서버 자원은 표로 비교한다. 작은 화면에서는
행의 보조 정보와 동작을 줄바꿈한다. 실행 이력이 없는 상태와 검색 결과가
없는 상태를 구분해 템플릿 이동 또는 필터 초기화를 제공한다. 작업실은 대화·결과 영역의 독립
스크롤과 입력창 위치를 유지한다.
콘솔은 화면 높이에 맞춰 상단 바와 메뉴를 유지하며, 긴 조회 목록은 본문 영역 안에서 스크롤한다.
목록의 접근성용 숨김 텍스트도 화면 컨테이너 안에 포함해 바깥 문서에 별도 스크롤을 만들지 않는다.

**세션**(`?view=sessions`)은 고정 우선·최근 갱신 순으로 작업 목록을
표시한다. 사이드바는 기능 메뉴만 표시하고, 세션 검색·선택은 본문에서 수행한다. 제목·작업 경로·
날짜·상태·현재 단계를 확인한 뒤 선택하면 작업실에서 해당 대화·결과를 연다. 일반 작업과 템플릿 실행은
기존 작업 ID를 사용하며 목록 조회·선택만으로 실행을 시작하지 않는다. 목록 상단과 사이드바의
**새 작업**으로 만든 작업도 같은 작업실에서 열린다. 작업실 상단 **세션 목록으로**, 세션 메뉴, 브라우저 뒤로 가기로
돌아올 때 해당 페이지 내의 검색어·스크롤 위치를 유지한다. 작성 중인 메시지도 페이지 내에서
세션별로 보존한다. 업로드를 마친 첨부의 선택과 명시한 skill도 현재 페이지에서 작업별로
보존하되, 다시 조회한 해당 작업의 파일/skill 목록에 있는 입력만 전송한다. 로그아웃·새로고침에서는
초안 선택을 초기화한다. 전송 성공 뒤에는 다른 작업에 머물러 있어도 보낸 첨부와 같은 메시지 초안을
다시 제안하지 않는다. 업로드 중인 File 객체·승인·실행 권한은 복원하지 않는다. 제목 검색은 서버의 저장된 작업을 조회하므로 최근 목록 밖의 이력도 찾을 수
있다. 목록은 최근 200개와 추적 대상 작업을 제공하며 더 오래된 이력은 검색으로 좁힌다.
대화 본문도 작업별 읽던 위치와 최신 메시지 따라가기 여부를 보존한다. 과거 내용을 읽을 때는
새 항목으로 강제 이동하지 않고, 마지막 부분에서 읽던 경우만 최신 위치를 따른다. 목록 복귀·
다른 작업·브라우저 뒤로 가기와 모바일 탭/화면 폭 전환에 적용한다. 위치는 현재 페이지 메모리의
최근 100개 작업에 한정하며 로그아웃·페이지 새로고침에서 초기화한다. 지연 로드된 이미지의
높이 변화나 메시지 내용의 재배치까지 의미 단위로 추적하는 기능은 아니다.
전체·진행 중·확인 필요·종료 상태 필터와 일반/템플릿 유형 필터를 같은 목록에서 제공한다.
상태가 바뀌어도 상태별 우선순위로 재정렬하지 않고 고정·최근 갱신 순을 사용한다.
실패로 종료된 작업은 확인 필요와 종료 양쪽에서 찾을 수 있다. 작업별 root·하위 에이전트 트리와
템플릿 실행 당시 설정은 펼쳐 확인하며, 대화·결과 또는 승인·질문 확인은 같은 작업실로 연결한다.
작업을 열었다 돌아와도 검색·필터·스크롤 위치를 유지한다. 조회 실패는 빈 결과와 구분하고
재시도를 제공한다. 실행 서비스 장애·오래된 관측이 있으면 마지막 보고 상태임을 표시한다.
모바일도 같은 목록 화면을 사용한다. 별도의 에이전트 목록 메뉴는 제공하지 않는다.
이전 `?view=agents`와 `?view=history` 링크도 통합 세션 화면을 연다.
**Codex 세션 불러오기**(`?view=sessions&tab=codex`)는 세션 화면에서 접근한다. 원본 CLI 대화의
실행 종료 확인 후 기존 import 절차로 연다. 이전 `?view=workspace&tab=sessions`와
`?view=workspace&tab=codex` 링크도 같은 세션 화면으로 연결한다.

템플릿에는 작업 경로·참고 파일·추가 맥락·공식 skill·프롬프트·입력값·실행 설정을 저장한다.
이름·설명·변수 기본값을 편집하고 복제·보관·복원할 수 있다. 필수 값이 없으면 입력창을 열고,
준비된 템플릿은 클릭 한 번으로 **새 native thread**에서 실행한다. 동일 launch ID 재시도는
기존 작업을 반환한다. 실행 당시 템플릿 버전·입력값·요청·참고 파일 해시·skill·실행 경로를
작업에 보존하여 템플릿 수정이 과거 실행 조건을 바꾸지 않는다. 참조 파일은 실제 실행 시점의
내용을 사용하며, 해시는 파일 자체의 백업을 대신하지 않는다. 없는 참조 파일은 native 세션이나
작업 이력을 만들기 전에 거부하며 빈 파일은 허용한다. 기본 템플릿은 최초 생성 후
사용자의 편집을 덮어쓰지 않는다. `console_sqlite_0004`는 이전 기본값과 완전히 같은 MR 리뷰
템플릿에서만 삭제된 스킬 참조를 제거하고 버전을 올린다. 사용자 수정·복제본과 과거 실행
snapshot은 변경하지 않는다. 코드 검토·테스트 기본 템플릿은 특정 일반 개발 스킬을 요구하지 않는다.
편집 화면은 선택된 스킬이 native 발견 목록에 없으면 제거·교체가 필요함을 표시한다.
실행을 이어갈 때는 시작 당시 참조 파일의 해시와 선택 스킬의 현재 가용성을 비교하여 달라진
조건을 해당 native turn의 맥락에 전달한다. 현재 파일로 과거 snapshot을 덮어쓰거나 새 실행을
자동으로 시작하지 않는다. 해시 비교는 선택된 참조에 한정되며 전체 자동 발견 지침의 백업은 아니다.

템플릿의 **명시적으로 사용할 스킬**은 선택한 스킬을 공식 `UserInput`의 `skill` 항목으로
전달한다. 비활성화되거나 발견되지 않은 선택은 실행 전에 거부한다. 체크하지 않은 스킬도
Codex가 설명과 작업을 대조해 암묵적으로 선택할 수 있다. `agents/openai.yaml`의
`policy.allow_implicit_invocation: false`는 자동 호출을 끄며, 템플릿 체크는 스킬 내부의 모든
절차를 수행했다는 검증이나 권한 상승을 의미하지 않는다.
좁은 작업실에서는 스킬 선택기의 폭을 제한하고 실행 컨트롤을 줄바꿈해 모델·권한 선택과
전송 동작이 겹치지 않도록 한다.

**지침·스킬**(`?view=instructions`)은 원본 파일을 직접 읽고 편집한다. 프로젝트의
`AGENTS.md`·`AGENTS.override.md`와 하위 폴더 지침, 각 폴더의
`.agents/skills/<이름>/SKILL.md`, `agents/openai.yaml`, 스킬 폴더 안의 Markdown 참고 문서를 지원한다.
개인 스킬은 `$HOME/.agents/skills`, 전역 지침은 `$CODEX_HOME/AGENTS.md` 및
`AGENTS.override.md`(기본 `$HOME/.codex`)에서 관리한다. 기존 `$CODEX_HOME/skills`의
사용자 스킬도 지원한다. `/etc/codex/skills`, `$CODEX_HOME/skills/.system` 및 `$CODEX_HOME/plugins/cache`의
스킬 파일은 별도 범위에서 읽기 전용으로 표시한다. 프로젝트의 `CLAUDE.md`·
`.github/copilot-instructions.md` 연결 지침과 스킬 `scripts/` 아래 Python·shell·JavaScript·TypeScript
파일도 읽기 전용이다. 서버가 이 파일의 생성·저장을 거부하며, Codex 수정 요청도 제공하지 않는다.
설치 파일 목록은 활성 플러그인 목록을 뜻하지 않는다. symlink 대상과 인증·환경 설정 파일은
읽기·편집 경로에 포함하지 않는다. 사용자 작성 파일의 원본은 해당
공식 위치이며 별도의 DB 사본으로 Codex의 파일 발견을 대체하지 않는다.

폴더를 접고 펼치는 탐색기에서 지침의 디렉터리 관계와 스킬별 파일 묶음을 확인한다.
폴더의 추가 버튼은 그 위치를 기본 경로로 사용한다. 범위별 경로·설명·본문 검색은
서버에서 200자 이내 검색어로 실행하며 요청당 읽는 본문은 16 MiB로 제한한다.
검색 실패는 빈 결과와 구분하고 늦은 이전 검색 응답은 버린다.
지침·스킬·참고/설정 유형으로 좁히고, 목록에는 이름과 소속 경로를 표시하며 전체 경로는
선택한 문서에서 펼쳐 확인한다. 본문의 상대 문서 링크는 같은 범위의 목록에 있는 문서로
이동하고 초안을 보존한다. 범위 밖 문서는 안내를 표시하며 임의 파일 접근으로 확장하지 않는다.
기존 문서는 Markdown 읽기로 열고, 편집 전환으로 원문을
수정한다. 스킬 frontmatter는 읽기 화면에서 별도로 펼친다. 저장 상태·Codex 수정 요청·저장은
하단에 유지하며 편집 중 `Ctrl/Cmd+S`로 저장한다. 모바일은 목록과 본문을 전환해 작업한다.
적용 방식 도움말은 제목 옆에서 연다. 파일은
64 KiB 이하 UTF-8이며 `SKILL.md` 저장 시 필수 frontmatter 필드의 존재를 확인한다.
스킬의 전체 형식·발견·실행 판단은 native Codex가 수행한다. 저장은 원본 해시로 충돌을
감지하고 디렉터리 잠금·파일 디스크립터·원자적 교체를 사용한다. symlink·하드링크·비정규
파일·보호 경로는 거부한다. 외부 편집과 충돌하면 초안을 유지하며 최신 저장 내용을 함께
확인한 뒤 사용자가 기준 버전과 초안을 선택한다. 디렉터리 잠금에 참여하지 않는 외부
편집기의 최종 교체와 완전한 상호 배제는 보장하지 않는다. 초안은 페이지 내 메뉴 이동에
보존하고 새로고침·탭 종료 시에는 미저장 경고를 표시한다.

문서 범위 패널은 파일 위치에 관련된 상위 지침을 연결한다. 현재 세션에 이미 주입된 지침의
증거로 사용하지 않는다. **Codex 스킬 발견 상태**에서 프로젝트 안의 작업 경로를 지정하고
공식 [`skills/list`](https://learn.chatgpt.com/docs/app-server#skills)를 `forceReload: true`로 호출해
발견·활성·비활성 상태를 확인한다. 이 조회는 세션 서비스의 인증·프로토콜 검사를 그대로 사용한다.
미조회·조회 실패·부분 오류를 구분하고 경로 변경·문서 저장·목록 새로고침 후에는 이전 상태를 무효화한다.
조회 결과는 이름·절대 경로·활성 상태를 각각 표시하므로 같은 이름의 스킬을 하나로 합치지 않는다.
심볼릭 링크 등 편집기가 지원하지 않는 경로의 스킬도 native 발견 목록에서는 확인할 수 있다.
**지침 탐색 설정**은 공식 `config/read`가 작업 경로의 신뢰·설정 계층을 해석한 결과 중
`project_doc_fallback_filenames`와 `project_doc_max_bytes`만 전달한다. 인증·공급자·MCP 설정 원문은
전달하지 않는다. 이 설정 조회가 실패해도 스킬 발견 결과를 유지하고 설정은 미확인으로 표시한다.
세션 서비스가 중단되어도 원본 파일 탐색·읽기·편집은 관리 서비스에서 계속 제공한다.

이 기능의 프로젝트 루트는 `MIY_CODEX_CONSOLE_WORKSPACE`로 지정한 Git 체크아웃이다.
MIY 폴더명·브랜치·스킬 이름·언어·프레임워크를 요구하지 않으며 운영 앱 API 연결도 필요 없다.
한 설치는 한 작업 공간과 그 하위 폴더를 관리한다. Git이 없는 폴더와 UI에서의 여러 저장소 전환은
현재 Workbench 실행 계약에 포함하지 않는다.

공식 사용법과 편집기 범위는 구분한다. Codex는 전역 지침 이후 프로젝트 루트부터 작업 경로까지
폴더별 첫 비어 있지 않은 `AGENTS.override.md` → `AGENTS.md` → 설정된 대체 파일명 순으로
선택한다. 프로젝트 지침 합산 제한은 기본 32 KiB이고 편집기의 파일당 64 KiB 제한과 별개다.
대체 파일명과 Git ignore된 지침은 native 실행에서 사용할 수 있지만 이 파일 탐색기는
모든 대체·ignore 경로를 열거하거나 편집하지 않는다. 파일 목록과 관련 지침은 실제 로딩 증거가 아니다.
`SKILL.md`의 이름·설명은 발견에, 본문·참고·자원은 선택 후 필요에 따라 사용된다.
`agents/openai.yaml`의 `policy.allow_implicit_invocation: false`는 자동 선택을 막으며 명시 선택은
가능하다. 스킬의 활성 여부와 자동 호출 정책은 서로 다른 값이다. 비텍스트 `assets/`는 편집하지 않는다.
발견 목록은 동명 스킬의 경로를 구분하지만 기존 세션·템플릿 실행 선택은 이름을 사용한다.
동명 스킬의 실행 경로를 구분해 선택하는 UI는 제공하지 않으므로 실행용 스킬은 이름을 고유하게 둔다.
현재 Workbench 실행기의 [연결 경계](#상태와-권한)에 따라 플러그인·MCP 실행은 비활성화한다.
플러그인 파일 표시나 `dependencies` 작성만으로 해당 실행 기능을 활성화하지 않는다.

**Codex에 수정 요청**은 저장된 원본 경로와 사용자의 수정 요청으로 새 일반 작업을 만들고,
기존 메시지/실행 API에 전달한다. 계획은 읽기 전용 제안이며 실행은 기존 native 권한·승인·
불확실 상태 복구 절차를 따른다. 전역·개인 경로 쓰기도 sandbox 승인을 우회하지 않는다.
요청 결과·승인·후속 대화는 세션에서 확인하며 파일 편집기로 돌아와 원본을 다시 읽는다.
요청은 커밋·게시·배포를 추가로 승인하지 않는다. 지침 변경은 새 세션에서 검증하고,
스킬 선택·템플릿 catalog는 `skills/list`의 `forceReload: true`로 원본을 새로 확인한다.

공식 발견 순서·스킬 형식은 [OpenAI 지침 문서](https://learn.chatgpt.com/docs/agent-configuration/agents-md)와
[스킬 문서](https://learn.chatgpt.com/docs/build-skills)를 따른다. 별도 지침/스킬 관리 화면의
공개 사례는 [CC Switch](https://github.com/farion1231/cc-switch)의 Prompts/Skills 메뉴다.

각 템플릿의 **실행 이력**은 `?view=sessions&template=<템플릿 UUID>`에서 조회한다.
서버는 저장된 템플릿 ID로 먼저 범위를 제한한 뒤 최근 200개 및 추적 대상 작업을 반환하며,
제목 검색으로 더 오래된 실행을 찾을 수 있다. 같은 이름의 템플릿이나 복제본 이력은 섞이지 않고,
이름 변경·보관 뒤에도 모든 버전의 이력이 연결된다. 선택한 템플릿과 보관 여부를 표시하며
상태 필터·대화·결과·실행 당시 설정을 함께 확인한다. 새로고침과 뒤로 가기에도 템플릿 범위를
유지하고 **전체 세션**으로 해제한다. 기존 `?view=agents&template=<템플릿 UUID>` 링크도 같은 범위를 유지한다.

native agent 트리에서 역할·상태·현재 단계·갱신 시각을 확인한다. 진행률은 임의의 백분율로
만들지 않는다. 승인·질문은 원래 RPC 요청 ID로 응답하고, skill은 공식 `skills/list`와
`UserInput`을 사용한다. 서버 메모리·스왑·디스크·부하·서비스 관측은 읽기 전용이다.

상단 **에이전트 활동**은 모든 메뉴에서 접근할 수 있는 비모달 패널이다. 마지막 보고 기준의 실행 중인
root·하위 에이전트 수와 확인 필요 작업 수를 표시한다. 작업은 확인 필요·실행 중·상태 확인
대기·최근 종료 순으로 표시하고, 현재 단계와 펼칠 수 있는 native agent 트리에서 병렬 작업을
확인한다. 최근 종료 5개에서 원래 작업으로 돌아가거나 **전체 세션**으로 통합 목록을 열 수 있다.
`idle/notLoaded` 하위 에이전트를 실행 중이나 완료로 추정하지 않고, 종료된 에이전트에 남은
과거 승인 flag는 무시한다. 목록은 기존 overview SSE와 10초 조회로 갱신하며 실패하면 마지막
수신 상태임을 명시한다. 이 패널은 작업 제어·lease 판단을 변경하지 않는다.

각 agent의 `observation`은 저장된 실행 결과와 별도로 native 상태의 근거를 보관한다.
`thread_status`는 `notLoaded/idle/active/systemError`, `thread_checked_at`은 마지막으로
직접 `thread/read` 또는 검증된 `thread/status/changed`에서 상태를 확인한 시각이다.
`last_turn`은 실제 turn 시작 응답·이벤트 또는 기존 하위 thread 조회에서 마지막으로 확인한
turn ID·상태·시각이며, 현재 실행 중인 turn이라는 뜻은 아니다. 완료 결과와 `notLoaded`는
함께 존재할 수 있다. `attempted_at`과 정형 `error_code`는 최근 직접 조회 실패를 드러낸다.
상태 이벤트나 `thread/list`의 발견만으로 실패를 지우지 않고, 다음 직접 조회 성공으로 해소한다.

기존 10초 agent 관측 주기에서 진행 중인 root는 `thread/read(includeTurns:false)`로 확인한다.
이는 저장된 thread를 로드·resume하거나 전체 대화를 읽지 않는다. 하위 agent는 기존 조회를
재사용한다. 성공한 상태 관측은 30초 이내 `fresh`, 이후 `stale`로 표시하고, 조회 실패·연결
상실은 `unavailable`, 이전 버전에 관측 근거가 없는 row는 `null/unknown`으로 남긴다.
오래된 관측은 실행 실패의 증거가 아니다. 프로세스 시작·재연결·연결 종료 때 해당 실행기의
관측만 영속적으로 무효화하므로 별도 management 프로세스도 마지막 보고임을 알 수 있다.
이전 연결의 지연 응답은 새 관측을 덮지 않는다. 브라우저 SSE 연결과 native 연결은 별개이며,
새 관측 필드의 저장은 Task의 최근 갱신 순서·권한·승인·lease·중단·복구 동작을 바꾸지 않는다.
브라우저는 새 응답이 없어도 `fresh` 관측을 최대 30초 뒤 오래된 관측으로 표시한다.
서버의 `stale/unavailable`을 임의로 정상으로 바꾸지 않고, 같은 시각의 반복 수신이나
브라우저 시계 역행으로 유효 기간을 늘리지 않는다. 이 표시는 추가 조회나 실행을 만들지 않는다.

일반·템플릿 작업의 새 세션과 이어서 실행하는 턴에는 공식 `developerInstructions`로
한국어 기본 응답 지침을 전달한다. 진행 설명·질문·계획·최종 답변을 한국어로 요청하되 사용자가
명시적으로 다른 언어를 요청하면 따른다. 코드·명령·경로·식별자·인용문 원문은 유지한다.
화면 언어 선택은 UI 번역만 바꾼다. 이미 실행 중인 턴과 과거 답변은 소급 변경하지 않는다.

세 프로세스가 같은 로컬 SQLite를 사용한다. `codex-console manage`는 인증·UI·모니터링·
템플릿 편집과 인증된 요청 라우팅을 담당하고 Codex를 만들지 않는다. `serve`는 일반 작업,
`templates`는 별도 템플릿 작업을 실행한다. 각 역할은 DB당 한 프로세스만 허용한다.
프록시는 모든 요청을 management로 전달하고, management가 저장된 executor에 따라
고정 loopback 포트로 전달한다. 일반 세션의 복구·종료는 템플릿 작업을 변경하지 않는다.

**Codex CLI 호환성 업데이트** 템플릿은 현재 설치 CLI에 맞춰 콘솔 코드·계약·검사·문서를
수정·검증하고, 템플릿의 명시적 권한과 저장소 정책 범위에서 반영한다. 범용 자기개선이나
시스템 CLI 자동 업그레이드는 수행하지 않는다. 실행기는 `template-current`의 별도 콘솔
릴리스와 `MIY_CODEX_CONSOLE_TEMPLATE_BINARY`의 검증된 CLI를 사용한다. 일반 `current`
전환·management/session 재시작 중에는 이 실행기를 재시작하지 않는다. 호환성 확인 또는
템플릿 실행기 자체가 실패하면 오류를 표시하고 수동 복구 안내를 제공한다.

| 설정                                 | 기본값  | 의미                                                                        |
| ------------------------------------ | ------- | --------------------------------------------------------------------------- |
| `MIY_CODEX_CONSOLE_PORT`             | `19365` | 세션 API의 loopback 포트                                                    |
| `MIY_CODEX_CONSOLE_MANAGEMENT_PORT`  | `19367` | 관리 UI/API의 loopback 포트                                                 |
| `MIY_CODEX_CONSOLE_TEMPLATE_PORT`    | `19368` | 독립 템플릿 실행 API                                                        |
| `MIY_CODEX_CONSOLE_TEMPLATE_BINARY`  | 미설정  | 버전별 디렉터리에 설치한 호환 CLI의 절대 파일 경로. `templates` 역할에 필수 |
| `MIY_CODEX_CONSOLE_MAX_ACTIVE_TASKS` | `3`     | 동시에 접수할 root 작업 수, 1~16                                            |
| `MIY_CODEX_CONSOLE_MONITOR_SERVICES` | `[]`    | 소유자가 등록하는 서비스 JSON 배열, 최대 64개                               |

일반 세션과 템플릿 실행기 health는 기본으로 등록된다. 추가 서비스는 `id`, `name`, `environment`와
`health_url`, `unit` 또는 `container`로 등록한다. `unit`과 `container`는 동시에 지정하지
않는다. `user_unit` 기본값은 true다. 예:

```json
[
  {
    "id": "portal-dev",
    "name": "Portal dev",
    "environment": "dev",
    "health_url": "http://127.0.0.1:8001/healthz"
  }
]
```

브라우저는 서비스 ID만 선택하며 probe 주소나 명령을 지정하지 않는다. health URL은 자격증명·
query·fragment 없는 사설/loopback 고정 IP의 HTTP(S)만 허용한다. DNS·redirect를 따르지 않는다.
모니터는 10초 간격으로 최대 4개를 병렬 조회하고 30초 지난 기록은 unknown으로 표시한다.
관측 결과의 SQLite 쓰기는 작업 스레드에서 수행해 다른 요청의 쓰기 잠금을 기다리는 동안에도
세션·관리 서비스의 이벤트 루프가 응답할 수 있게 한다.
SQLite 쓰기 잠금 대기가 만료되면 이전 관측을 유지하고 다음 정기 조회에서 갱신한다.
서비스·호스트 관측의 기존 30초 만료 규칙을 유지하며 다른 DB 오류는 숨기지 않는다.
Workbench의 설치 목록·사용량·GitLab 관측도 같은 방식으로 저장한다. 캐시 저장이 잠금 때문에
실패하면 마지막 관측의 시각을 유지하고 미확인 상태로 응답하며, 설치 주소가 바뀐 경우 이전
설치의 데이터를 반환하지 않는다. 잠금 이외의 DB 오류는 숨기지 않는다.
health 응답은 16 KiB, supervisor 출력은 4 KiB, 개별 probe는 5초로 제한한다. systemd의
`ActiveState` 또는 Docker의 `State.Status`만 조회하며 시작·재시작·복구 명령은 없다.
서비스의 health가 버전을 반환하지 않으면 버전을 추정하지 않는다.

동일 작업공간의 계획 읽기는 병렬로 허용하고 쓰기는 배타적 DB resource lease를 사용한다.
작업 경로가 하위 폴더여도 같은 Git 작업 트리는 하나의 배타 자원으로 취급한다. 분리 시
선택한 하위 경로를 유지하고 변경 파일·diff 표시는 저장소 루트를 기준으로 조회한다.
새 작업의 **작업공간 분리**를 선택하면 별도 detached worktree를 준비한다. 분리된 개발 작업은
병렬 실행할 수 있다. 템플릿의 공용 자원 직렬화 설정을 켠 실행은 공통 operations lease로 직렬화한다.
이는 콘솔 접수 조정이며 Codex의 sandbox·서버 권한·사용자 승인을 대체하지 않는다.
부모가 완료되어도 실행 중이거나 상태가 불확실한 하위 agent가 있으면 lease를 유지한다.
중단은 확인된 root와 하위 thread에 공식 `turn/interrupt`를 전달한다.

공식 [App Server](https://learn.chatgpt.com/docs/app-server)와
[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)의 native
thread/turn/plan/approval을 사용한다. 0.159.2 생성 계약의 `collabAgentToolCall`,
`parentThreadId`, `sessionId`, `thread/list`의 ancestor 필터로 연결을 확인한다.
하위 thread 관찰은 `thread/read/list`만 사용하고 resume하지 않는다. 누락된 알림은 10초마다
조회해 보완한다. 에이전트 생성·역할 배정·재시도 스케줄러는 콘솔에서 구현하지 않는다.
[공식 worktree 기능](https://learn.chatgpt.com/docs/environments/git-worktrees)은 있으나
0.159.2 App Server ClientRequest에는 worktree 생성 RPC가 없으므로 기존의 좁은 Git 준비
helper만 유지한다. 이 helper는 서비스 운영을 실행하지 않는다.

## 실행 경계

- 소유자 한 명, 설정한 Git 개발 체크아웃 하나를 대상으로 한다. 공개 가입이나 팀 공유는 없다.
- 공식 `codex app-server`의 stdio 프로토콜을 사용한다. 기준 계약은 **0.159.2**이며,
  그 이상의 안정 CLI는 콘솔이 사용하는 요청·응답·알림 RPC 스키마가 기준 계약과 같을 때
  자동으로 허용한다.
  **0.160.0**도 사용하는 RPC 스키마가 0.159.2와 동일하므로 이 기준 계약을 유지한다.
  더 오래된 버전·시험판·스키마가 달라진 버전은 실행 전에 차단한다. Codex가 구독 인증,
  토큰 갱신, 원본 대화와 도구 실행을 관리한다. 클라이언트는 인증 파일을 읽거나 복사하지 않는다.
- 이 도구는 개인 코딩 에이전트 클라이언트다. miy 제품 앱의 생성형 호출, 공용 AI 공급자,
  사용자·회사 권한을 대신하지 않는다. 제품 AI 기능에는 기존 등록 workload 계약을 적용한다.
- 현재 서버의 Codex 사용자와 인증 저장소를 사용한다. 웹 비밀번호와 ChatGPT 로그인은 별개다.
  웹 로그아웃·비밀번호 변경은 웹 세션만 폐기한다.
- 공식 프로토콜의 실험적 계획·질문 기능을 사용하므로 기준 버전의 계약을 고정한다. 최소
  안정 버전과 RPC 스키마 검사를 모두 통과해야 실행한다. 업그레이드 때 스키마 재생성,
  계약 테스트, 실제 계정 smoke를 함께 수행한다.
- 개인 클라이언트가 필요한 HTTP 인증·문서 버전·실행 승인과 공식 RPC 사이만 변환한다.
  터미널 화면 파싱, 비공식 ChatGPT 엔드포인트, API 과금 fallback, 별도 OAuth 구현은 없다.

공식 근거: [App server](https://developers.openai.com/codex/app-server),
[Authentication](https://developers.openai.com/codex/auth).

### 개인 CLI 클라이언트와 제품 AI의 연결 경계

miy API의 콘솔 연결 기능은 허용된 소유자에게 브라우저 launch URL만 반환한다. 제품 API나
worker가 콘솔에 생성 요청을 위임하는 경로는 없다. 콘솔은 별도 로그인·설치·DB를 사용하는
공식 [App Server 클라이언트](https://learn.chatgpt.com/docs/app-server)이며 소유자가 직접
입력한 개발 작업을 기존 ChatGPT 구독 세션에 전달한다. 제품 도메인 서비스의 workload와
공통 실행 계약은 [ADR 0005](../../../adr/0005-registered-llm-workload.md)를 따른다.

모델 목록은 공식 `model/list`에서 현재 구독 계정이 제공하는 항목을 읽는다. 새 작업의 화면
선택값은 해당 작업 경로의 공식 `config/read`에 사용 가능한 모델이 설정되어 있으면 그 모델,
그렇지 않으면 `model/list`의 `isDefault` 모델을 따른다. 둘 다 없으면 목록의 첫 모델을
사용한다. 추론 강도는 허용 범위에 있는 Codex 설정값 또는 모델 권장 기본값을 표시한다.
기존 작업은 마지막 native thread 모델과 추론 강도를 표시한다. 사용자가 모델·강도를
변경하면 다음 턴에 공식 `turn/start`·
`collaborationMode.settings`로 전달하고, 이후에는 native thread의 선택을 이어받는다.
콘솔은 별도 모델 선호도를 저장하지 않는다. 공급자·인증·fallback 설정은 제공하지 않으며
API key 인증과 다른 공급자는 계속 거부한다. 제품 앱의 모델 라우팅과 연결하지 않는다.

추론 강도는 콘솔의 허용 목록과 해당 모델의 `supportedReasoningEfforts`가 겹치는 값만
표시·허용한다. 기본 목록은 `none, minimal, low, medium, high, xhigh`이므로 `max`, `ultra`와
새로 추가된 이름은 자동으로 노출되지 않는다. Codex 0.156.0의 강도는 문자열이며 공식
`model/list`에는 수치 순위나 정렬 보장이 없으므로 응답 순서로 상한을 추정하지 않는다.
허용 목록은 낮은 강도부터 높은 강도 순서의 JSON 배열로 설정한다.

| 설정                                          | 기본값                                             | 용도                                                           |
| --------------------------------------------- | -------------------------------------------------- | -------------------------------------------------------------- |
| `MIY_CODEX_CONSOLE_ALLOWED_REASONING_EFFORTS` | `["none","minimal","low","medium","high","xhigh"]` | 콘솔에서 선택·실행할 수 있는 강도. 빈 목록·빈 이름은 거부한다. |

강도를 생략하면 같은 모델의 native thread 강도가 허용 범위에 있을 때 유지하고, 그렇지
않으면 모델 권장 기본값을 사용한다. 권장값도 허용되지 않으면 해당 모델이 지원하는 허용
목록의 마지막 값을 사용한다. 허용되는 강도가 없는 모델은 목록에서 제외하고 새 턴 실행도
거부한다. 이전 작업의 숨겨진 선택값은 다음 실행 설정에서 기본값으로 되돌리며, API에서
명시적으로 요청하면 거부한다. 이미 실행 중인 턴과 과거 실행 기록은 바꾸지 않는다.
설정 변경은 콘솔 서비스 재시작 후 적용된다.

## 실행 설정과 중단 후 계속하기

새 작업은 **계획** 모드로 시작한다. 공식 native plan 모드와 읽기 전용 권한으로 질문,
조사와 계획 수정을 수행한다. **실행**은 native default 모드로 사용자의 직접 요청을 수행한다.
저장된 계획 없이도 실행할 수 있으며, 문서의 **이 계획으로 실행**은 확인한 계획 버전을 함께
전달한다. 확인 창에서 **필요할 때 승인 요청** 또는 **YOLO · 전체 권한**을 선택한다.
새 작업은 승인 요청을 기본으로 제시하고, 실행 접수 후에는 입력창을 실행 모드로 전환해
같은 작업의 후속 요청에 선택한 권한을 유지한다. 취소하면 실행하거나 권한을 바꾸지 않는다.
전송 실패 시에는 선택을 유지해 재시도할 수 있다. 모델·추론 강도·권한은 다음 메시지에 적용한다. 실행 중인 턴에는 보충 지시를
보낼 수 있고 설정 변경은 턴이 끝난 뒤 적용한다.
모델과 추론 강도는 입력창 하단의 현재 선택값에서 여는 팝오버로 변경한다. 팝오버는 입력창
위에 겹쳐 표시되어 열고 닫아도 프롬프트 영역의 높이와 하단 조작 위치를 바꾸지 않는다.

계획 모드는 Codex CLI와 같은 native plan 흐름을 사용한다. App Server의 최종
`item/completed` `plan` item을 권위 있는 계획으로 보고 우측 **계획** 탭에 새 버전으로
투영한다. 질문·조사·확인 질문처럼 `plan` item이 없는 턴은 계획 문서를 만들거나 바꾸지
않는다. 구형 계획 답변 전체를 감싼 `<proposed_plan>` 표시는 문서 본문이나 실행 컨텍스트로
노출하지 않는다. 별도 요구사항 단계와 탭은 제공하지 않는다. 계획은 최대 100,000자로 콘솔 DB에만
저장하며 저장소 파일은 수정하지 않는다. 일반 명령 출력은 마지막 100,000자만 보관한다.

실행 권한의 기본값은 **필요할 때 승인 요청**이다. **YOLO · 전체 권한**을 선택하면 공식
`approvalPolicy: never`, `sandboxPolicy: dangerFullAccess`로 실행한다. YOLO는 서버 계정의
파일·네트워크 접근에 대한 샌드박스 제한과 개별 승인 요청을 없앤다. 서비스 unit은
`NoNewPrivileges=false`로 실행해 해당 OS 계정에 이미 부여된 비대화형 sudo와 그룹 권한도
YOLO에서 사용할 수 있게 한다. 이는 새 OS 권한이나 자격증명을 부여하지 않으므로 설치 계정의
sudoers·그룹·파일 ACL은 호스트에서 별도로 관리한다. 계획 모드는 YOLO 선택과 관계없이 읽기
전용이다. 마지막 모델·강도·실효 권한은 DB에 저장된다.

**현재 실행 상태**는 모드·모델·권한, 현재 명령과 Codex가 보고한 단계별 진행 상황을 표시한다.
페이지 이동·탭 종료·웹 로그아웃 후에도 서버 작업은 계속된다. **중단**으로 실행을 멈출 수 있다.
서버·Codex 프로세스 자체의 종료는 별도다. SSE 재연결과 함께 10초마다 상태를 확인하고
페이지 복귀 때 즉시 갱신한다.

중단된 작업은 입력창에 이어서 수행할 내용을 요청한다. 연결 유실로 접수 여부가 불확실하면
새 메시지를 받기 전에 공식 thread 이력을 조회한다. 기존 턴이 실행 중이면 새 메시지를 보충
지시로 전달하고, 완료됐다면 같은 thread에서 새 턴을 시작한다. 실행 중인 턴은 저장된 turn ID나
원래 메시지의 clientUserMessageId와 연결된 공식 userMessage.clientId로 접수를 검증한 경우에만
재개하며 승인 요청도 이어서 처리한다. 실행 중인 턴과 요청의 모드·권한이나 명시한 모델·추론 강도가 다르면 전송을
거부하므로 턴을 완료·중단한 뒤 새 설정으로 요청한다. 생략한 모델·추론 강도는 기존 값을 유지한다. 조회 중 작업·요청 상태가 바뀌면 오래된 결과를 반영하지
않는다. 불확실했던 원래 요청을 자동
재전송하지 않는다. 동일 요청 ID의 재시도는 확인된 접수 결과를 반환하며 중복 실행·보충 지시를
만들지 않는다. 새 계획 버전으로 실행하는 요청은 기존 턴이 끝나거나 중단된 뒤 제출한다.
**실행 상태 확인**으로 상태만 확인할 수도 있다. 전송 전 실패한 본문은
**전송하지 못한 요청 불러오기**로 복원한다. 필요한 첨부는 다시 선택한다.

실행 중 명령·테스트·파일 접근이 실패하면 공식 Codex가 도구 결과를 받아 계속 판단한다.
콘솔은 오류별 복구 실행기를 두거나 추가 턴을 자동 전송하지 않는다. Codex가 선택한 재시도와
사용자 질문·승인 요청은 기존 대화에서 처리한다. 일반 작업의 시작·재개·완료는 Git 조회나
변경 지문 검사에 의존하지 않으며, 브랜치·diff 조회 실패가 native 실행 상태를 바꾸지 않는다.
완료와 실패는 공식 turn 상태로 표시한다.

Codex 0.156.0은 `thread/resume`에 이전 sandbox와 cwd를 반환할 수 있다. 콘솔이 이전에 부여한
권한만 받아들이고 새 `turn/start`에 현재 경로와 선택 모드의 전체 권한을 지정한다.
권한 전환의 접수가 불확실하면 직전 확인된 sandbox도 DB에 보존해 기존 턴의 복구를 허용한다. 알 수
없거나 기록보다 넓은 권한은 차단한다. 작업 폴더가 삭제된 경우에도 같은 thread와 cwd로
재개한다. Codex는 도구가 반환한 경로 오류를 보고 현재 권한과 저장소 지침에 따라 조치하거나
사용자에게 질문한다. 콘솔이 폴더를 복원·이동하거나 Git 워크트리 등록을 정리하지 않는다.
대화·첨부·문서는 유지한다. **실행 상태 확인**에는 Git 변경 확인 창이 필요하지 않으며
이전 버전이 저장한 변경 지문으로 후속 요청을 차단하지 않는다.

## 브랜치와 작업 공간

작업 상단에는 실제 브랜치와 변경 파일 수를 간단히 표시한다. **브랜치** 탭에서 작업 경로,
HEAD, 스테이징/미스테이징/새 파일·충돌 수, 추적 브랜치와 앞선/뒤처진 커밋 수,
변경 파일과 diff를 확인한다. 이름 없는 워크트리는 **브랜치 없음 (detached HEAD)**으로 표시한다.
상태는 10초마다, 페이지 복귀와 수동 새로고침 때 조회한다. 원격 비교는 로컬 추적 참조 기준이며
자동 fetch하지 않는다. 변경 파일 수만으로 병합 여부를 판단하지 않는다.

병합 대상 선택이나 병합 요청 자동 완성은 제공하지 않는다. 사용자가 실행 모드에서 원하는
Git 작업을 직접 요청하면 Codex가 해당 저장소 지침에 따라 수행한다. 콘솔 자체에 특정
브랜치·호스팅·MR/PR·배포 순서를 넣지 않는다. 실행 모드 선택만으로 커밋·푸시·병합·배포·삭제를
승인한 것으로 간주하지 않는다.

일반 작업은 선택한 작업 경로를 그대로 Codex에 전달한다. 기존 변경의 보존과 필요한 격리는
Codex가 저장소 지침과 사용자 요청에 따라 판단한다. 콘솔은 dirty 상태만으로 작업 경로를
바꾸지 않는다. 사용자가 새 작업의 격리를 선택하거나 템플릿에 `isolate`를 지정한 경우에는
콘솔이 지정한 기준 ref에서 detached 워크트리를 준비한다. 이 명시적 격리는 유효한 Git
저장소와 기준 ref가 필요하다. 다음 설정은 콘솔 전용 환경 파일의 typed 계약이다.

| 설정                                     | 기본값                                       | 용도                                             |
| ---------------------------------------- | -------------------------------------------- | ------------------------------------------------ |
| `MIY_CODEX_CONSOLE_WORKTREE_BASE_REF`    | `HEAD`                                       | 격리 작업의 기준 ref. 실제 커밋으로 검증한다.    |
| `MIY_CODEX_CONSOLE_WORKTREE_ROOT`        | `~/.local/share/miy-codex-console/worktrees` | 설정한 체크아웃 밖의 절대 경로.                  |
| `MIY_CODEX_CONSOLE_PROTECTED_WORKSPACES` | `[]`                                         | 접근 금지할 운영 체크아웃의 절대 경로 JSON 배열. |

miy 서버에서는 기준 ref를 `origin/dev`, 워크트리 경로를 체크아웃 루트의 `worktrees`로 설정하고
실제 `prod` 경로와 dev/prod 제품 DB 이름을 금지 목록에 넣는다. 다른 저장소는 그 저장소의
구성에 맞춘다. 전용 DB는 모든 설치에 필요하며 migration은 기존 비콘솔 테이블이 있으면 거부한다.

## 설치

사전 준비는 [INSTALL.md](../../../INSTALL.md)를 따른다. Node·pnpm과 Python·uv 버전은
저장소의 package.json 및 각 앱의 pyproject.toml/lock을 사용한다. Python 3.12에 포함된
SQLite는 **3.51.3 이상**을 권장한다(공식 수정 백포트 3.50.7/3.44.6도 허용).
[WAL-reset 수정](https://www.sqlite.org/wal.html#walreset)이 없는 런타임은 시작 전에 차단한다.
Python 버전만으로 SQLite 버전을 추정하지 말고 `python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'`로
확인한다. 필요하면 [공식 Python 배포물](https://github.com/astral-sh/python-build-standalone/releases)의
수정된 SQLite 포함 Python 3.12를 별도 영구 디렉터리에 설치하고 release digest를 검증한다.
기존 서버의 공용 Python을 교체하지 않는다. `uv sync --python /absolute/path/to/python3`와
릴리스 빌드의 두 번째 인자로 그 인터프리터를 지정한다.

현재 사용자로 `codex login status`가 성공하는 Codex 0.159.2 이상의 안정 버전이 필요하다.
서비스는 연결 전에 설치된 CLI가 기준 RPC 계약과 호환되는지 검사한다.

1. 소스·워크트리·릴리스 밖의 로컬 영구 디렉터리를 준비한다. SQLite 파일은 0600,
   디렉터리는 0700을 권장한다. NFS/SMB 공유 파일시스템을 사용하지 않는다.
2. `apps/codex-console-api/.env.example`을 무시되는 `.env`로 복사하고 0600으로 보호한다.
   `MIY_CODEX_CONSOLE_DATABASE_URL=sqlite+pysqlite:////absolute/path/to/console.sqlite3`와
   HTTPS origin, 실제 Git 작업 경로, 일반·템플릿 Codex 경로를 설정한다. PostgreSQL URL과
   메모리 DB·상대 경로·심볼릭 링크 DB는 거부한다. 기존 설치는 아래 이전 절차를 먼저 따른다.
3. 저장소 루트에서 아래 명령을 실행한다.

```bash
pnpm install --frozen-lockfile
uv sync --frozen --directory apps/codex-console-api --group dev
pnpm --dir apps/codex-console-web build
cd apps/codex-console-api
uv run --frozen codex-console migrate
uv run --frozen codex-console set-password
uv run --frozen codex-console serve
```

다른 터미널에서 `uv run --frozen codex-console manage`와 `uv run --frozen codex-console templates`도 실행한다. 지속 서비스는 아래의 별도 릴리스 구성을 사용한다.

`set-password`는 보호된 터미널 입력으로 비밀번호를 받으며 기존 웹 세션을 폐기한다.
초기 계정도 이 명령으로 만든다. 세션 API는 `127.0.0.1:19365`, 관리 UI/API는
`127.0.0.1:19367`, 템플릿 실행기는 `127.0.0.1:19368`에 수신한다. 세 포트는 달라야 한다.
서버의 브라우저에서 `http://127.0.0.1:19365/`를 열면 설정한 콘솔 origin과 base path의
화면으로 이동한다. API와 health 경로는 이동하지 않는다. 이동한 화면에서는 기존 세션 또는
소유자 비밀번호로 로그인하며, miy 앱 링크의 자동 로그인 fragment도 브라우저가 그대로 전달한다.
전용 HTTPS 주소는 `ops/codex-console/nginx.conf.example`을 참고해 기존 TLS 프록시에 연결한다.
프록시가 원래 Host를 전달하고 SSE 응답을 버퍼링하지 않아야 한다.

로컬 UI 개발은 origin을 `http://127.0.0.1:19366`으로 설정하고 API와 별도로
`pnpm --dir apps/codex-console-web dev`를 실행한다. HTTP origin은 loopback만 허용한다.

## 개인 앱과 HTTPS 접속 연결

miy 루트 `.env`의 `MIY_CODEX_CONSOLE_LAUNCH_URL`은 브라우저가 열 주소다.
빈 값은 미설치 상태이며 앱을 숨긴다. HTTPS 절대 URL 또는 `/codex-console/` 같은 같은 origin
경로를 사용한다. 로컬 단독 개발에는 loopback HTTP URL도 허용한다. URL에 사용자 정보나
토큰을 넣지 않는다. 같은 개발 서버를 loopback과 원격 주소로 함께 사용하는 경우
`MIY_CODEX_CONSOLE_LAUNCH_URL_BY_HOST`에 API가 받은 `Host` 헤더 값
(호스트와 선택적 포트)을 키로, 해당 Console HTTPS 주소를 값으로 JSON 객체에 등록한다.
Vite 프록시는 브라우저의 `host:port`를 전달하지만, 개발 Nginx는 포트 없는 `$host`를 전달하므로
실제 API에 전달되는 값과 키를 맞춘다. 일치하는 항목이 없으면 기본 launch URL을 사용하고,
기본값도 비어 있으면 해당 호스트의 콘솔 앱을 표시하지 않는다. 매핑된 URL은 비워 둘 수 없다.
설정 변경 후 **개발** API·Web 서비스를 해당 호스트의 감독
서비스로 재시작한다. 운영 miy에 적용하는 작업은 별도 릴리스·배포 절차를 따른다.

```dotenv
MIY_CODEX_CONSOLE_LAUNCH_URL=http://127.0.0.1:19366
MIY_CODEX_CONSOLE_LAUNCH_URL_BY_HOST='{"100.64.0.10:4200":"https://100.64.0.10:19443"}'
```

위 주소는 예시다. loopback miy에서 열면 기본 주소를, 지정한 원격 miy host에서 열면
매핑한 HTTPS 주소를 사용한다. 매핑 목적지도 기본 URL과 같은 검증을 거치며 원격 HTTP,
사용자 정보, query, fragment는 허용하지 않는다.

여러 miy 서버를 발행 origin으로 구분하는 자동 로그인에는 Console뿐 아니라 **링크를 발급하는 miy 사이트도 HTTPS**여야 한다.
HTTP 원격 개발 origin은 자동 로그인 허용 목록에 등록할 수 없다. 기존 HTTP 개발 접속은
유지하고, 기존 TLS 프록시에 충돌하지 않는 별도 HTTPS 포트를 추가해 개발 Web으로 전달한다.
프록시는 `Host $http_host`와 WebSocket upgrade를 전달하고 API·DB는 loopback에 유지한다.
HTTPS 개발 사이트의 `host:port`도 위 launch URL 매핑에 추가하고, 아래 허용 목록에는
그 HTTPS origin과 실제 소유자 UUID를 등록한다. 사설 CA는 브라우저와 Console 서비스의
Python 런타임이 모두 신뢰해야 한다. [HTTPS 신뢰 등록](../../domains/release/installation-operations.md#https-trust)을
따르고 실제 공개 주소에서 인증 교환을 확인한다. 교환 클라이언트는 Python 기본 SSL 신뢰
저장소를 사용하며 서버 인증서·호스트 검증을 유지하고 환경변수 HTTP 프록시는 사용하지 않는다.
전용 CA 파일이 필요하면 서비스 환경의 `SSL_CERT_FILE`로 지정할 수 있다.
실제 HTTPS issuer를 사용하는 TLS 회귀 테스트에는 `openssl` 실행 파일이 필요하다.

콘솔 `.env`의 `MIY_CODEX_CONSOLE_SSO_SUBJECTS`에는 자동 로그인을 허용할 miy의
정확한 origin과 그 환경에서 콘솔을 소유한 miy 사용자 UUID를 JSON 객체로 등록한다. miy 앱
링크는 현재 miy 세션과 Codex Console 앱 권한을 확인해
60초짜리 `cc1_` 코드를 만들고 URL fragment로 전달한다. 콘솔은 fragment를 즉시 지우고
설정한 origin에 있는 고정 교환 API만 호출한다. 코드는 한 번만 사용할 수 있으며 miy
세션이 종료되었거나 앱 권한이 회수되면 실패한다. 교환 응답의 안정적인 사용자 UUID가 해당
origin에 설정된 소유자 UUID와 일치할 때만 콘솔 세션을 발급한다. miy bearer token과 사용자
프로필은 콘솔에 전달하지 않는다. 직접 콘솔 주소를 열거나 교환이 실패하면 기존 소유자
비밀번호 로그인을 사용한다.

| 설정                             | 기본값 | 용도                                                                                                                               |
| -------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `MIY_CODEX_CONSOLE_SSO_SUBJECTS` | `{}`   | 자동 로그인을 허용할 개발·운영 miy HTTPS origin을 소유자 사용자 UUID에 연결한 JSON 객체. loopback HTTP는 로컬 개발에서만 허용한다. |

**같은 miy 서버를 여러 주소로 여는 데모 설치**는 `SSO_SUBJECTS`에 그 서버의 HTTPS origin과
소유자 UUID 한 쌍만 등록한다. 서버가 하나면 모든 로그인 코드를 그 서버에서 확인한다.
브라우저의 `127.0.0.1`, `localhost`, 서버 IP·별칭·HTTP/HTTPS 주소를 개별 등록하지 않아도 된다.
콘솔은 브라우저가 전달한 issuer 주소에 접속하지 않고 모든 코드를 설정한 서버에서 확인한다.
다른 서버의 코드·잘못된 코드·다른 사용자 UUID는 거부하며 소유자 로그인과 CSRF 검증은 유지한다.
miy의 기본 launch URL도 같은 Console HTTPS 주소로 설정하면 접속 호스트별 매핑이 필요 없다.

둘 이상의 miy 서버를 등록한 구성은 기존의 정확한 발행 origin 허용 목록을 사용한다.
이 경우 loopback HTTP 발행 origin도 각각 등록해야 하며 원격 HTTP origin은 등록할 수 없다.

개발 Web 재시작과 무관하게 접속하려면 **전용 HTTPS 도메인**을 사용하고 앞단 프록시를
콘솔에 직접 연결한다. DNS 등록뿐 아니라 프록시의 upstream 주소·포트도 준비해야 한다.

| 설정 위치       | 키                             | 값                           |
| --------------- | ------------------------------ | ---------------------------- |
| miy 루트 `.env` | `MIY_CODEX_CONSOLE_LAUNCH_URL` | `https://codex.example.com/` |
| 콘솔 `.env`     | `MIY_CODEX_CONSOLE_ORIGIN`     | `https://codex.example.com`  |
| 콘솔 `.env`     | `MIY_CODEX_CONSOLE_BASE_PATH`  | 빈 값                        |

실제 도메인으로 바꾸고 `브라우저 → HTTPS 프록시 → 관리/세션 서비스`로 연결한다.
같은 호스트에서 TLS를 종료하면 `ops/codex-console/nginx.conf.example`을 사용한다.
모든 UI·API 경로는 19367로 전달한다. 내부 실행기 포트는
loopback에 유지한다. 다른 호스트의 TLS 프록시는 아래의 전용 연결 지점을 사용한다.
로컬 브라우저 검증은 콘솔 origin을 `http://127.0.0.1:19366`으로 설정하고 세 API와
콘솔 Vite를 실행한다. 관리 포트만 직접 열면 작업 API가 연결되지 않는다. 서버에서 세션 API의
`/`를 열면 설정한 콘솔 화면 주소로 이동한다. HTTPS에는
Secure 쿠키를 사용하고 허용된 loopback HTTP에는 해당 호스트의 세션 쿠키를 발급한다.
원격 PC에서는 공개 HTTPS 주소를 사용한다.

기존 HTTPS 개발 사이트 아래의 경로를 사용하는 대안:

| 설정 위치       | 키                             | 값                              |
| --------------- | ------------------------------ | ------------------------------- |
| miy 루트 `.env` | `MIY_CODEX_CONSOLE_LAUNCH_URL` | `/codex-console/`               |
| 콘솔 `.env`     | `MIY_CODEX_CONSOLE_ORIGIN`     | 실제 개발 사이트의 HTTPS origin |
| 콘솔 `.env`     | `MIY_CODEX_CONSOLE_BASE_PATH`  | `/codex-console`                |

miy Vite 개발·preview는 `/codex-console/api/tasks`·`/codex-console/api/codex`를
포함 모든 `/codex-console` 경로를 19367로 전달한다.
앞단 HTTPS 프록시는 이 경로를 기존 Web으로 전달한다. 별도 프록시에서 콘솔에 직접
연결하는 경우에는 경로를 제거하지 않는 `ops/codex-console/nginx-path.conf.example`을 참고한다.
쿠키는 콘솔 경로에 한정되고 API·정적 파일·SSE도 같은 prefix로 동작한다.
Vite를 통하는 구성은 개발 Web이 멈추면 콘솔 화면 연결도 중단된다. 콘솔 프로세스의 독립성과
브라우저 접속 경로의 독립성은 별도로 확인한다.

DNS 없이 서버 IP로 구성할 때는 IP SAN 인증서와 PC의 CA 신뢰 등록을
[설치 운영 확인](../../domains/release/installation-operations.md#https-trust)에 따라 준비한다.
`https://<서버-IP>:<HTTPS-포트>/`를 launch URL로 사용하며 loopback API 포트를 공개하지 않는다.

이미 사용 중인 주소를 바꿀 때는 실행 중인 콘솔 작업을 먼저 완료·중단한다. 전용 프록시를
준비한 뒤 콘솔 origin·base path를 함께 변경하고 콘솔 서비스를 재시작한다. 새 주소에서
로그인·API·SSE·첨부 업로드를 확인한 후 miy launch URL을 반영하고 개발 서비스를 재시작한다.
`.auth_info`의 콘솔 URL도 갱신한다. 도메인이 바뀌면 기존 웹 쿠키가 전달되지 않으므로 같은
작업실 비밀번호로 다시 로그인한다. 작업·첨부·ChatGPT 인증은 그대로 유지되며 UI 재빌드나
DB migration은 필요 없다.

miy 플랫폼 관리자로 로그인하여 **관리자 설정 → 앱 사용/접근 설정**에서 `Codex 콘솔`을 켠다.
기존 설치에 새 앱을 등록하면 기본 비활성·선택 대상 상태이며 기존 권한을 자동 확대하지 않는다.
등록 계약은 `platform_admin`을 요구한다. 개인 앱의 링크가 표시되더라도 실제 코딩 작업은
콘솔의 별도 비밀번호 인증으로 보호된다. 이 링크는 miy 인증 토큰이나 Codex 자격증명을 전달하지 않는다.

설치 완료 검사는 다음을 모두 포함한다.

1. 콘솔 서비스가 실행 중이고 `/codex-console/healthz` 또는 전용 호스트의 `/healthz`가 성공한다.
2. miy **개인 앱 → Codex 콘솔** 클릭 시 새 탭에 로그인 화면이 표시되고 기존 탭이 유지된다.
3. 작업실 비밀번호로 로그인한 뒤 **구독 연결됨**이 표시된다. 미연결이면 공식 ChatGPT 로그인을 수행한다.
4. 새로고침 후 화면 복원, 로그아웃 후 API 접근 차단, 콘솔 URL 아래의 API·SSE 응답을 확인한다.
5. [.auth_info 관리](../../../INSTALL.md#11-로그인-정보-파일-관리)에 따라 주소·비밀번호를 서버에
   기록한다. 비밀번호·DB 비밀값은 채팅이나 도구 출력으로 전달하지 않는다.
6. 계획 기본값, 질문 후 문서 미생성, 명시적 문서 생성과 이후 확정 변경의 자동 갱신을 확인한다.
   실행 모드의 직접 요청과 저장된 계획 실행, 모델·승인/YOLO 선택, 브랜치 탭을 확인한다.
   검증용 작업 중 탭을 닫았다가 같은 URL로 돌아와 진행·결과가 복원되는지 확인한다.
   중단된 작업은 새 프롬프트로 이어서 진행하고 기존 파일이 보존되는지 확인한다.
7. 파일 두 개를 보관한 뒤 하나만 선택해 메시지를 전송한다. 선택한 파일의 뱃지와 전송 후
   선택 해제, 새로고침 후 파일 목록·첨부 기록 복원, 128 KiB 초과 파일 업로드를 확인한다.

### TLS 프록시가 다른 호스트에 있을 때

`ops/codex-console/nginx-upstream.conf.example`은 서버의 **지정한 사설 IP:19365**만 수신하는
선택적 Nginx 연결 지점이다. 실제 콘솔은 loopback 수신을 유지하고, Nginx는 설정한 도메인과
앞단 프록시의 실제 소스 IP만 허용한다. 템플릿의 주소·호스트를 설치 환경에 맞게 바꾼다.
이 구간은 신뢰하는 사설망에서만 사용하며 신뢰할 수 없는 네트워크에서는 호스트 간 TLS나
인증된 터널을 구성한다. 외부 포트 전달로 이 HTTP 포트를 공개하지 않는다.

Docker가 준비된 Linux 호스트에서는 miy Compose와 별개로 실행할 수 있다. 다음 명령 전
설정 파일을 설치하고 템플릿의 예시 IP·도메인을 실제 값으로 바꾼다. 기존 파일을 덮어쓰지 않는다.
이전 브랜드의 설정 디렉터리가 bind mount로 연결되어 있으면 파일 이동만으로 컨테이너가
새 경로를 사용하지 않는다. 기존 이미지 digest·실행 사용자·네트워크·읽기 전용 설정·권한 제한을
유지하고, 새 경로를 mount한 일회성 컨테이너에서 `nginx -t`를 통과한 뒤 연결 지점 컨테이너를
교체한다. `docker inspect --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}' codex-console-upstream`으로
실제 mount를 확인하고 공개 HTTPS의 로그인·API·SSE까지 검증한다. 실패하면 보존한 기존 설정과
컨테이너로 복원한다. 콘솔의 세 역할 서비스와 SQLite 저장소는 이 프록시 경로 이전에 종속되지 않는다.

```bash
install -m 644 ops/codex-console/nginx-upstream.conf.example "$HOME/.config/miy-codex-console/upstream.conf"
# upstream.conf의 수신 IP, 허용 프록시 IP, 도메인을 서버 편집기에서 설정한다.
docker run --rm --network host --user 101:101 --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,uid=101,gid=101 \
  --mount "type=bind,src=$HOME/.config/miy-codex-console/upstream.conf,dst=/etc/nginx/nginx.conf,readonly" \
  --entrypoint nginx nginx:1.27-alpine -t
docker run -d --name codex-console-upstream --restart unless-stopped \
  --network host --user 101:101 --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,uid=101,gid=101 \
  --mount "type=bind,src=$HOME/.config/miy-codex-console/upstream.conf,dst=/etc/nginx/nginx.conf,readonly" \
  --entrypoint nginx nginx:1.27-alpine -g 'daemon off;'
```

앞단 HTTPS 프록시의 대상은 이 서버의 사설 IP:19365이며 원래 Host를 전달해야 한다.
앞단에도 최소 50 MiB 업로드·120초 요청 시간·SSE 버퍼링 해제와 충분한 읽기 시간을 적용한다.
HTTPS `/healthz`와 로그인, 첨부 업로드를 확인한다. 허용하지 않은 소스나 Host로는 접근되지
않아야 한다. 설정 변경 후 `docker exec codex-console-upstream nginx -t`로 검사하고
`docker exec codex-console-upstream nginx -s reload`로 반영한다. 중지·재시작은
`docker stop codex-console-upstream`, `docker restart codex-console-upstream`을 사용한다.

이 연결 지점과 콘솔은 miy Web·API 재시작에 종속되지 않는다. Docker로 실행하면 Docker
재시작에는 영향을 받는다. 콘솔 저장소는 miy PostgreSQL과 독립적이다. 같은 호스트의 전원·디스크 장애까지 분리하지는 않는다.

## 파일 보관과 메시지별 첨부

- 오른쪽 **파일** 탭에서 모든 형식의 원본을 업로드·다운로드·삭제한다. 파일 보관만으로
  Codex에 자료가 전달되지는 않는다. 확장자 없는 파일·바이너리도 보관할 수 있다.
- 입력창의 **파일 첨부**에서 기존 파일을 선택하거나 새 파일을 올린다. 입력창에 파일을
  끌어 놓아도 된다. 입력창에서 올린 파일은 이번 메시지의 첨부 뱃지로 선택되며, 파일 영역에서
  보관만 한 파일은 선택되지 않는다. 여러 파일과 파일만 있는 메시지를 지원한다.
- 선택한 파일만 새 메시지·보충 지시·계획 생성에 전달한다. 구현 승인 창에도 이번에 전달할
  파일을 표시한다. 전송 성공 시 선택이 해제되고 실패 시 입력과 선택을 유지한다.
- 과거 메시지에는 당시 첨부한 파일의 다운로드 뱃지가 남는다. 선택 해제는 새 요청에 다시
  첨부하지 않는 의미이며 이미 Codex가 읽은 내용은 대화에 남을 수 있다. 실행 중이거나 상태가
  불확실한 작업은 파일을 삭제할 수 없다. 삭제 후에는 기존 뱃지에 **삭제됨**을 표시한다.
- Codex가 서버의 기존 도구로 원본을 직접 읽는다. 콘솔은 파일 형식별 변환·OCR·자동 실행·
  압축 해제를 하지 않는다. 실제 읽기 가능 여부는 파일 형식과 서버 도구에 따라 Codex가 설명한다.

원본은 콘솔 전용 SQLite `console_attachments`에, 메시지별 참조는
`console_message_attachments`에 저장한다. 선택해 전송한 원본의 읽기용 사본만 Git 저장소
밖에 만들며 파일 권한은 `0400`, 디렉터리는 `0700`이다. 작업 디렉터리 전환과 서버 재시작 후
DB에서 사본을 복원한다. 원본을 삭제하면 DB 바이너리와 읽기용 사본을 제거하고 기록용 이름·
크기·참조 정보만 유지한다. 별도 파일 저장 서비스나 OpenAI API 키는 필요하지 않다.

| 콘솔 설정                                     | 기본값                                         | 용도                                                                         |
| --------------------------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------- |
| `MIY_CODEX_CONSOLE_ATTACHMENT_CACHE`          | `~/.local/share/miy-codex-console/attachments` | 소유자 전용 읽기 사본. Git 저장소·릴리스 디렉터리 밖의 고정 경로를 사용한다. |
| `MIY_CODEX_CONSOLE_ATTACHMENT_MAX_BYTES`      | `52428800`                                     | 파일당 50 MiB. 최대 설정값은 100 MiB.                                        |
| `MIY_CODEX_CONSOLE_ATTACHMENT_TASK_MAX_BYTES` | `524288000`                                    | 작업당 활성 원본 500 MiB.                                                    |

작업당 활성 파일은 200개, 메시지당 선택은 20개까지다. 업로드는 원본 바이너리
`PUT /api/tasks/{task_id}/attachments/{attachment_id}`로 전달하고 URL 인코딩한 파일 이름을
`X-File-Name` 헤더에 넣는다. 같은 ID·원본의 재시도는 중복 저장하지 않는다. 읽기·삭제도
콘솔 로그인과 작업별 파일 소속 검사를 거친다. 원본·이름·경로를 로그에 기록하지 않는다.

프록시도 파일당 제한 이상을 허용해야 한다. Nginx 예시는 콘솔 경로에 `client_max_body_size 50m`,
`client_body_timeout 120s`, `proxy_request_buffering off`를 설정한다. 기존 HTTPS → Vite → 콘솔
구성이면 가장 앞의 HTTPS 프록시에도 같은 크기 제한을 확인한다. 용량을 변경할 때 콘솔 설정과
프록시를 함께 맞춘다. 일반 JSON 요청은 128 KiB로 제한한다. 문서 저장은 100,000자,
메시지·보충 지시·구현 지시는 32,000자를 허용하며 해당 경로는 JSON Unicode 이스케이프의 최대
12바이트/자와 나머지 필드 4 KiB를 합친 바이트 제한을 적용한다.

전용 DB 백업에 첨부 원본도 포함되므로 용량·보존 정책을 함께 관리한다. 캐시는 원본 백업이
아니다. 캐시 경로는 원본 Codex 이력의 파일 경로를 유지하도록 업데이트 때 변경하지 않는다.
다른 서버로 복원할 때도 같은 절대 경로를 준비한다. 경로를 바꿨다면 보관된 파일을 다시 선택해
전송한다. 자료 삭제는 기존 Codex 대화나 과거 DB 백업에서 이미 읽힌 내용을 지우지 않는다.

## 서비스로 실행

개발 중인 소스를 서비스가 직접 읽지 않도록 새 릴리스 디렉터리를 만든다.
다음은 사용자의 홈 디렉터리에 설치하는 예다. 이미 존재하는 릴리스는 덮어쓰지 않는다.

```bash
bash scripts/build-codex-console.sh "$HOME/.local/share/miy-codex-console/releases/initial" /absolute/path/to/verified-python3
mkdir -p "$HOME/.config/miy-codex-console" "$HOME/.config/systemd/user"
install -m 600 apps/codex-console-api/.env.example "$HOME/.config/miy-codex-console/console.env"
ln -s "$HOME/.local/share/miy-codex-console/releases/initial" "$HOME/.local/share/miy-codex-console/current"
ln -s "$HOME/.local/share/miy-codex-console/releases/initial" "$HOME/.local/share/miy-codex-console/template-current"
install -m 644 ops/codex-console/codex-console.service ops/codex-console/codex-console-management.service ops/codex-console/codex-console-templates.service "$HOME/.config/systemd/user/"
```

`console.env`를 서버 편집기에서 설정한다. `MIY_CODEX_CONSOLE_BINARY`는 현재 구독
로그인 사용자가 실행하는 Codex의 절대 경로로 지정한다. 서비스 설치 계정도 동일하게 유지한다.
템플릿용 CLI는 검증한 정확한 버전을 별도 디렉터리에 설치한다. 예를 들어
`npm install --prefix /absolute/private/codex-0.159.2 --no-save @openai/codex@0.159.2`로
설치한 뒤 `MIY_CODEX_CONSOLE_TEMPLATE_BINARY`를 그 디렉터리의
`node_modules/@openai/codex/bin/codex.js`로 지정한다. 이 버전도 현재 생성 계약과 실제 구독
smoke를 통과해야 한다. 해당 디렉터리를 일반 CLI 업데이트에 재사용하지 않는다. `.bin/codex`
심볼릭 링크 대신 실제 실행 파일 경로를 지정하며, 패키지의 native 자원 전체를 보존한다.
`MIY_CODEX_CONSOLE_WEB_DIST`는 예시의 상대 경로 `../codex-console-web/dist`를 유지해
서비스 작업 경로의 릴리스를 따라가게 한다. 특정 릴리스의 절대 경로로 고정하면 서비스 전환 후에도
이전 화면을 제공하므로 업데이트 때 API와 웹 정적 파일이 같은 릴리스인지 확인한다.
서비스 활성화 전에 해당 환경으로 `migrate`, `set-password`를 수행한다. dotenv 형식으로
작성한 환경 파일은 릴리스의 API 디렉터리에 `.env` 심볼릭 링크로 연결하면 CLI에서도 읽는다.

```bash
ln -s "$HOME/.config/miy-codex-console/console.env" "$HOME/.local/share/miy-codex-console/current/apps/codex-console-api/.env"
cd "$HOME/.local/share/miy-codex-console/current/apps/codex-console-api"
.venv/bin/codex-console migrate
.venv/bin/codex-console set-password
systemctl --user daemon-reload
systemctl --user enable --now codex-console codex-console-management codex-console-templates
```

user unit의 bus에 연결할 수 없는 셸에서는 설치 계정의 `XDG_RUNTIME_DIR=/run/user/$(id -u)`를
지정하고 사용자 manager가 실행 중인지 확인한다. 다른 사용자나 root의 Codex 인증으로 실행하지 않는다.
로그아웃 후에도 실행해야 하면 관리자가 `loginctl enable-linger <설치계정>`으로 lingering을 설정한다.
사용자 지정 Node·pnpm·uv 설치를 사용한다면 해당 실행 파일 디렉터리를 이 서비스의 `PATH`
drop-in에 명시한다. Codex 바이너리뿐 아니라 코딩 작업에서 사용하는 도구도 서비스 환경에서
해석되어야 한다. 해당 설정은 호스트별 user unit drop-in으로 관리한다.

```bash
systemctl --user is-active codex-console codex-console-management codex-console-templates
systemctl --user is-enabled codex-console codex-console-management codex-console-templates
systemctl --user restart codex-console
systemctl --user stop codex-console
```

세션 unit의 `NoNewPrivileges=false`는 공식 app-server의 YOLO가 서비스 계정의 기존 호스트 권한을
그대로 사용할 수 있게 하는 실행 계약이다. `true`로 바꾸면 `dangerFullAccess`를 전달해도
`sudo` 같은 setuid 권한 상승이 차단된다. unit을 갱신한 뒤에는 `daemon-reload`와 서비스
재시작 후 메인 PID의 `/proc/<PID>/status`에서 `NoNewPrivs: 0`을 확인하고, YOLO 턴에서
설치 계정에 허용된 비대화형 sudo와 필요한 그룹 자원 접근을 검사한다. 계획/승인 실행의
샌드박스 계약은 Codex app-server가 계속 적용한다.

개발 서버의 `./dev.sh`와 콘솔은 서로 제어하지 않는다. 일반 UI/session 업데이트는 검증한
새 릴리스로 `current`만 전환한다. `template-current`와 그 CLI 설치 경로는 유지한다.
템플릿 실행기 업데이트는 그 실행기의 모든 root/하위 작업이 끝난 뒤 별도로 검증·전환한다.
현재 SQLite 스키마는 `console_sqlite_0007`이다. `0007`은 agent의 nullable 관측 JSON만
추가하고 기존 작업·실행 결과·소스 준비 기록을 보존한다. 이전 row의 현재 native 상태를
추정해 채우지 않는다. 스키마 변경이 필요한 배포는 세 역할의
작업을 모두 종료하고 백업·세 서비스 중지·migration을 수행한다. 이때 `current`와
`template-current` 모두 새 스키마를 지원하는 검증된 릴리스로 전환하며, 템플릿용 고정 CLI는
별도 변경이 없는 한 유지한다. 실행 중인 자기 업데이트에서
스키마까지 바뀌면 자동 진행하지 말고 작업을 완료한 뒤 별도 유지보수로 반영한다.

miy 전환에서는 보호된 설정의 키만 `MIY_CODEX_CONSOLE_*`로 이전한다.
기존 SQLite·첨부·워크트리·릴리스 경로는 값으로 명시해 유지할 수 있다. 기본 경로는
`miy-codex-console`을 사용하므로 기존 데이터가 없는 새 경로로 전환하지 않는다.
`console_sqlite_0002`는 기존 템플릿 ID와 작업 스냅샷을 유지하며 알려진 저장소 스킬 참조만
`miy-*`로 갱신한다. PostgreSQL import는 원본 복사·검증 후 SQLite 데이터 migration을 적용한다.
현재 포털과의 순차 배포를 위해 콘솔은 기존 `mty_issuer`/`mty_code` handoff와
`/api/session/mty`를 같은 인증 경계에서 수용한다. 새 발행·표준 계약은 `miy`이며
두 형식을 혼합한 handoff는 거부한다. 데스크톱 링크는 새 `miy-desktop` 설치와 함께 검증한다.

## 독립 저장소와 백업

SQLite는 인증·승인·작업·템플릿·첨부 원본과 관측을 보관한다. WAL, `synchronous=FULL`,
외래키 검사, 5초 busy timeout을 사용한다. 읽기는 같은 스냅샷을 유지하고 쓰기는
`BEGIN IMMEDIATE`로 짧게 직렬화한다. DB 잠금을 잡은 상태로 Codex 응답을 기다리지 않는다.
역할별 OS 파일 잠금은 중복 서비스를 막는다. 다른 호스트의 공유 DB로 확장하는 구성은 지원하지 않는다.

실행 중인 SQLite 본체만 복사하면 WAL의 최신 내용이 빠질 수 있다. 공식 online backup API를
사용하는 다음 명령으로 새로운 파일에 백업한다. 명령은 무결성을 검사하고 기존 파일을 덮어쓰지 않는다.
백업에는 인증·첨부·작업 내용이 있으므로 접근을 제한하고 다른 저장소에도 보관한다.

```bash
.venv/bin/codex-console backup --destination /absolute/private/backups/console-before-update.sqlite3
```

이전 도구가 지원하는 PostgreSQL 스키마는 `console_0009`~`console_0011`이다.
더 오래된 설치는 원본 백업을 별도 비운영 DB에 복원하고, 새 릴리스의 고정 PostgreSQL
migration과 SQLite import를 먼저 검증한다. 실제 이전에서는 기존 서비스와 작업을 모두
중지하고 최신 백업을 보존한 뒤, 보호된 설정에서 읽은 원본 DB URL로
`codex_console.cli.migrate(source_url)`을 실행해 `console_0011`로 올린다. URL·비밀번호는
명령 인수나 출력에 남기지 않는다. 원본 스키마도 변경되므로 이 단계 이전으로 복구하려면
원본 PostgreSQL 백업과 이전 릴리스·설정을 함께 복원해야 한다. import용 0600 설정 파일은
기존 DB URL 값을 유지하되 키를 `MIY_CODEX_CONSOLE_DATABASE_URL`로 지정한다.

기존 PostgreSQL `console_0009`/`console_0010`/`console_0011` 설치를 이전할 때:

1. 진행 중인 root/하위 작업을 종료하고 기존 두 서비스를 중지한다. 기존 env·릴리스와 PostgreSQL
   백업을 보존한다. 원본 DB에 앱을 계속 쓰게 한 채 이중 운영하지 않는다.
2. 기존 0600 env를 `console-postgres.env`로 보존하고, 새 env의 DB URL을 **아직 없는 SQLite 파일**로
   지정한다. 새 릴리스의 CLI에서 다음 명령을 실행한다. 이 경우 `migrate`를 먼저 실행하지 않는다.

   ```bash
   .venv/bin/codex-console import-postgres --source-env /absolute/private/console-postgres.env
   ```

3. 이전 도구는 원본을 읽기 전용 repeatable-read로 읽으며 구버전 서비스의 advisory lock을 확인한다.
   모든 테이블의 행 수·내용 해시·외래키·무결성을 검사한 뒤 새 SQLite 파일을 원자적으로 공개한다.
   웹 비밀번호 해시·세션·작업 ID·첨부를 보존한다. 이전 실패는 기존 원본을 변경하지 않는다.
4. 검증된 새 릴리스·세 unit·management 단일 경로 프록시로 시작하고 로그인·기존 대화·첨부·템플릿을
   확인한다. PostgreSQL 원본과 이전 env는 전환 검증이 끝날 때까지 보존한다.

SQLite 복원은 세 서비스를 모두 중지하고, 기존 파일과 `-wal`/`-shm`을 **함께 격리**한 뒤
검증된 백업을 원래 경로에 0600으로 설치한다. 같은 스키마를 지원하는 릴리스로 재시작한다.
전환 직후 PostgreSQL 롤백은 이전 env·두 unit·프록시·릴리스를 함께 복원한다. 전환 후 SQLite에
새로 기록된 작업은 PostgreSQL에 자동 반영되지 않으므로 이후에는 SQLite 백업을 복원한다.

### 배포 완료 확인

miy 이름 전환은 전용 설정 파일의 환경변수와 별도 서비스 릴리스를 함께 바꾼다.
[릴리스 전환 절차](../../domains/release/README.md#miy-naming-cutover)에 따라 기존 DB·작업·설정의 백업과 경로 이동을 검증한 뒤 아래 순서를 적용한다.

소스 수정·커밋·푸시·dev/main 동기화와 실행 중인 콘솔 업데이트는 별개의 단계다.
miy 개발 서버나 운영 앱만 재시작해도 콘솔에는 반영되지 않는다. 사용자가 화면에 반영할
Codex Console 구현을 요청하면 로컬 변경 또는 검증만으로 범위를 제한하지 않은 한 전용 콘솔
릴리스와 공개 검증까지 완료해야 작업 완료로 보고한다. 실제 소스 통합과 서비스 변경 권한은
루트 `AGENTS.md`를 따른다. 배포 승인이 아직 없다면 검증된 릴리스를 구체적으로 준비한 뒤
서비스 교체 전에 한 번만 승인을 요청하고, 승인 후에는 다음 항목을 중단 없이 완료한다.

1. 실행 중인 서비스의 실제 릴리스 경로와 적용할 소스 커밋을 확인한다. 해당 커밋에서 새
   릴리스를 빌드하고 [검증과 복구](#검증과-복구)의 관련 검사를 수행한다.
2. 위 업데이트 절차대로 root와 하위 agent 작업의 종료를 확인하고 전용 DB를 백업한 뒤,
   스키마 변경 유무에 맞게 서비스 중지·migration·`current` 전환·재시작과 프록시 갱신을 수행한다. 기존 인증과 설정을 유지하고
   이전 릴리스와 DB 백업은 복구용으로 보존한다.
3. 서비스가 새 릴리스를 실행하는지와 직접·공개 주소의 `/healthz`를 확인한다. 실제
   로그인 세션에서 변경된 API 응답과 브라우저 동작도 검사한다. 추론 강도 변경은
   `/api/codex/models`와 실제 선택 목록을 모두 확인한다. 공개 경로의 prefix가 있으면
   각 경로에 적용한다. 쿠키·비밀번호·대화 내용은 검사 출력에 남기지 않는다.
   자동 로그인 변경은 개발·운영 miy 각각에서 앱 링크를 열어 비밀번호 화면 없이 콘솔에
   들어가며 fragment가 주소에서 제거되는지 확인한다.
4. 관리 로그인·서비스 상태·작업 현황·하위 agent 표시를 공개 브라우저에서 확인한다.
   Workbench 전환은 Studio의 프로젝트·기존 작업 연결, 앱 관리의 패치·예산 저장과 재조회,
   플랫폼의 로컬 Git·GitLab·서비스 표시를 확인한다. MIY 연결이 없거나 실패했을 때 미확인
   표시와 독립 작업실 접근을 함께 확인하고, 설정된 연결에서는 설치 SHA와 운영 집계를 검증한다.
   세션 서비스만 중지했을 때 관리 화면은 유지되고 상태가 unknown/unavailable로 갱신되는지
   검증한 뒤 세션 서비스를 복원한다. 템플릿 편집·입력·새 세션 실행·이력과 서버 자원을 확인한다. 일반 CLI 불일치 상태에서도 고정 CLI로 템플릿을 실행하고, management/session 재시작 후 같은 작업과 승인 상태가 유지되는지 확인한다.
5. 배포한 소스 커밋·릴리스 경로·서비스 상태·동작 검사 결과를 구분해 보고한다.
   빌드만 완료했거나 이전 릴리스가 실행 중이면 배포 완료로 간주하지 않는다.

## 상태와 권한

- 웹 인증은 scrypt 비밀번호 해시, DB 세션, HttpOnly/SameSite 쿠키, 정확한 origin과 CSRF
  검증을 사용한다. 로그인 실패 5회는 5분 제한한다. 각 서비스 역할은 한 프로세스만 실행한다.
  보호 API는 본문을 읽기 전에 인증·CSRF를 검사한다. JSON 요청의 본문 전송은 크기 제한과
  전체 30초 제한을 적용하며 시간 초과·연결 중단 때 실행하지 않는다. 오류 응답에도 API의
  `no-store`와 보안 헤더를 유지한다. 파일 업로드는 별도의 120초 제한을 사용한다.
- 역할별 OS 파일 잠금으로 중복 서버를 차단하고 DB resource lease로 충돌을 조정한다.
  작업·계획 버전·승인·요청 중복 방지·화면 projection을 DB에 저장한다. Codex 원본 이력이
  대화의 기준이며 화면 projection을 Codex에 원본 이력으로 되돌려 보내지 않는다.
- 계획 모드는 읽기 전용 sandbox와 승인 불허 정책을 사용한다. 저장된 계획의 실행 버튼은 최신 계획
  버전에 묶인다. 이후 native plan item이 완료되면 내용이 같아도 새 버전으로 저장한다.
  문서 편집 중 서버에 새 버전이 생겨도 입력 내용과
  편집 시작 버전을 유지한다. 충돌하면 저장을 막고 최신 버전을 명시적으로 불러오도록
  안내한다. 유지할 편집 내용은 불러오기 전에 복사한다. 미저장 초안은 열린 페이지 안에서
  작업·결과 탭별로 유지하고, 새로고침이나 페이지 종료 시 브라우저 경고를 제공한다.
  다른 브라우저나 다음 로그인에서도 보존하려면 문서를 저장한다.
- 첫 버전은 외부 쓰기 도구를 제공하지 않는다. 사설 app-server에서 Apps·Plugins를 끄고
  각 thread의 공식 설정 override로 MCP 서버를 비활성화한다. 원래 Codex 설정 파일은 바꾸지 않는다.
- 기본 실행은 작업 디렉터리의 workspace-write sandbox를 사용한다. YOLO의 명시적 선택은
  [실행 설정](#실행-설정과-중단-후-계속하기)을 따른다. 기본 권한 확대는 건별 명령·파일
  승인 또는 표시된 권한을 현재 턴에만 부여하는 승인으로 처리한다. 스레드 생성·재개·턴 시작에서
  공식 `approvalsReviewer: user`를 명시해 기존 자동 검토 설정을 상속하지 않는다. 포괄적인 세션 승인이나
  임의 RPC 전달 엔드포인트는 제공하지 않는다.
- 보호 경로 설정은 기본 workspace뿐 아니라 기존 작업의 저장된 root와 이전 실행 경로에도
  적용한다. Git 조회·격리 준비·복구·보충 지시·승인 응답 전에 현재 설정으로 검사한다.
  보호된 작업도 중단할 수 있으며 실패·접수 결과 기록과 실행 잠금 해제는 차단하지 않는다.
- 작업 경로와 명시적 격리는 [작업 공간 설정](#브랜치와-작업-공간)을 따른다. 기존 변경의
  확인·보존·반영·정리는 Codex가 저장소 지침과 사용자가 요청한 범위에 따라 수행한다.
- 작업 도중 브라우저를 닫아도 실행은 계속된다. URL의 task ID로 새로고침 후 동일 작업을 연다.
  SSE는 DB 변경 알림이며 재접속 때 저장 상태를 읽는다. 로그아웃된 SSE는 다음 주기에 종료한다.
- 요청 준비와 실제 제출 경계를 DB에 구분해 기록한다. 제출 전 실패한 요청은 같은 요청 ID로
  재시도할 수 있고, 준비 중 서버가 종료되면 실행 잠금을 해제한다. 이미 접수된 요청만 중복
  전송에 성공 응답을 돌려주며 접수 여부가 불확실하면 성공으로 처리하거나 자동 재전송하지 않는다.
- 백엔드·Codex 종료 또는 제출 후 접수 응답 유실은 `uncertain`이다. workspace lease를 유지하고
  승인 요청을 폐기한다. **실행 상태 확인**은 공식 thread를 재개·조회한다. 스레드 생성 전에
  중단된 이전 버전의 작업도 실행되지 않았음을 확인한 뒤 잠금을 해제할 수 있다.
  복구가 성공하면 다음에 사용자가 직접 보내는 요청은 새 요청 ID를 사용한다. 복구 실패나
  단순 화면 갱신으로는 ID를 바꾸지 않으며 불확실한 기존 요청을 자동으로 재전송하지 않는다.
  전송 응답을 잃었지만 실제 실행이 계속되는 경우 **중단**은 공식 스레드에서 현재 실행 ID를
  확인한 뒤 중단을 요청한다. 완료 이벤트나 명시적 복구 전에는 작업 잠금을 유지한다.
  완료 알림을 놓친 계획은 공식 이력의 현재 요청에서 최종 native `plan` item을 복원한다.
  실행별 문서 출처로 중복을 막고 이후의 사용자 편집은 보존한다. 작업 목록 검색은 서버의
  전체 작업을 대상으로 하므로 최신 200개 밖의 격리 작업도 제목으로 찾을 수 있다.
  실행 도중 중단되었다면 새 프롬프트로 이어서 수행할 내용을 요청한다. 같은 작업 경로와
  변경사항을 유지하며 현재 파일 상태는 Codex가 확인한다. Git 조회 실패로 완료된 root나
  하위 agent의 실행 잠금을 유지하지 않는다. 이전 CLI 대화는 원래 실행을 종료한 후에만 가져온다.
- 원본 Codex 대화와 DB 작업 기록은 소유자가 유지한다. 자동 삭제는 하지 않는다. 임시 웹 세션은
  만료되고 다음 로그인에서 제거한다. DB 백업·보존은 별도 DB 관리 정책으로 운영한다.
  화면은 최근 항목 2,000개를 표시하며 더 긴 대화에는 생략 안내를 표시한다.
- 서버 로그에 원본 프롬프트·토큰·upstream 오류 본문을 기록하지 않는다. 파일 읽기는 상위
  디렉터리까지 링크를 거부하며, 검사 후 경로 교체도 파일 디스크립터 기반 접근으로 차단한다.
  diff·템플릿 참조 읽기는 하드링크도 거부한다. diff 조회는 비밀 파일,
  경로 이탈·외부 symlink·대형 출력에 경계를 적용한다. 웹 UI는 API 키를 입력받지 않는다.

## 검증과 복구

관리 unit은 `NoNewPrivileges=true`이며 별도 `codex-console-management` 서비스로 유지한다.
세션만 재시작할 때 관리 서비스를 함께 재시작할 필요는 없다.

끊김 진단은 `journalctl --user -u codex-console`에서 `Codex transport stopped`의 안전한
사유 코드·예외 종류·프로세스 종료 코드만 확인한다. 원본 이벤트·명령 출력·오류 본문을 로그에
추가하지 않는다. `codex_event_failed`는 DB/event 처리 실패, `codex_output_limit`는 단일
4 MiB 메시지 초과, `codex_event_overflow`는 2,048개 이벤트 큐 초과,
`codex_protocol_error`는 잘못된 JSON/envelope, `codex_disconnected`는 프로세스/연결 종료다.
응답의 ID 타입·결과/오류 구분과 요청/알림의 method 형식을 검사한다. 잘못된 UTF-8·과도한
JSON 중첩·불완전한 응답도 연결을 종료하며 미완료 요청을 정상 수락으로 기록하지 않는다.
브라우저의 **실시간 표시 재연결**과 native 프로세스 종료를 구분한다. 명령의 초기 출력이
`null`인 정상 이벤트는 빈 문자열로 누적하며 연결을 종료하지 않는다. 이전 프로세스 세대의
늦은 이벤트는 새 연결의 작업 상태에 반영하지 않는다.

```bash
pnpm check:codex-console-contract
pnpm --dir apps/codex-console-web test
pnpm --dir apps/codex-console-web typecheck
uv run --frozen --directory apps/codex-console-api --group dev ruff check .
uv run --frozen --directory apps/codex-console-api --group dev pytest -q
pnpm --dir apps/codex-console-web build
pnpm --dir apps/codex-console-web e2e
```

브라우저 실패 진단은 저장소 루트 `test-results/codex-console/`에 저장하며,
릴리스 CI의 maintainer 전용 artifact에 포함한다. 진행 중 상태 검사는 테스트용 실행기의
완료 신호를 명시적으로 제어하고 실제 요청 수락을 기다린다. 이 제어 경로는 임시 브라우저
fixture에만 있으며 배포되는 API에는 설치하지 않는다.

일반 DB/E2E 검사는 임시 SQLite 파일을 사용한다. 구버전 PostgreSQL migration과 SQLite 이전
검사는 `MIY_TEST_POSTGRES_TEMPLATE_DSN`에 비운영 PostgreSQL 접속 정보를 지정한다. 해당 계정은
임시 `console_test_*` DB 생성·제거 권한이 필요하며, 설정이 없으면 이 검사만 skip된다.
이전 도구 변경을 skip 상태로 전체 통과라고 보고하지 않는다. E2E는 실제 HTTP·SQLite와 테스트
전용 프로토콜 대역을 사용한다. production 앱에는 mock 실행 모드가 없다.

메시지 첨부의 실제 파일 읽기·미선택 파일 제외·공식 메시지 ID 연결은 아래의 별도 구독 smoke로
확인한다. 임시 DB·저장소를 사용하고 원본 대화는 완료 후 archive한다. 파일 내용·대화 본문을
로그로 출력하지 않는다.

```bash
uv run --frozen --directory apps/codex-console-api --group dev python tests/live_attachment_smoke.py
```

Codex 업그레이드 계약은 설치된 안정 CLI가 최소 버전 이상이고 선택된 RPC 스키마와 호환되는지
검사한다. 스키마가 같으면 소스 변경 없이 새 CLI를 사용할 수 있다. 스키마가 다르면 이 검사가
실패하며, 기준 버전과 생성 계약을 함께 검토·갱신해야 한다.

공식 [App Server 스키마 생성](https://learn.chatgpt.com/docs/app-server#message-schema)은
실행한 CLI 버전의 계약을 반환한다. 0.160.0의 `--experimental` 생성 결과는 콘솔이 검사하는
모든 RPC와 그 참조 정의에서 0.159.2 기준과 일치한다. 어댑터와 `protocol.json`은 유지하며,
버전만으로 허용하지 않는다. 시작 경로 회귀 검사는 두 안정 버전의 초기화와 시험판·최소 버전
미달·중첩 권한 정의 변경·누락·잘못된 JSON·스키마 생성 실패의 연결 전 차단을 확인한다.
세션 CLI의 검증·릴리스 전환은 별도 고정 0.159.2 템플릿 CLI와 `template-current`를
교체하거나 재시작하지 않는다.

0.159.2 기준은 공식 CLI의 `--experimental` 스키마로 생성한다. 이전 0.158.0 대비
`CodexErrorInfo`에 `tooManyDenials`가 추가되고, turn의 오류 설명은 중단된 turn도 포함하도록
변경됐다. 요청·승인·샌드박스 스키마는 동일하다. 추가 오류 종류는 기존 일반 실패 경로로 처리하고
중단된 turn은 기존 중단 상태로 표시한다. 호환성 해시는 이 변경도 포함하며 드리프트 차단을 유지한다.
검사·재생성에는 서비스의 `MIY_CODEX_CONSOLE_BINARY`와 같은 CLI가 `PATH`에서 선택되는지
확인한다. 재생성은 `scripts/generate_protocol.py`의 기준 버전과 정확히 같은 CLI에서만 허용한다.

```bash
uv run --frozen --directory apps/codex-console-api python scripts/generate_protocol.py --check
```

실제 구독을 사용하는 선택적 smoke는 별도 DB 설정 없이 아래 명령으로 실행한다.
임시 Git 저장소에서 계획 단계의 읽기 전용 동작과 승인 후 실제 구현·테스트를
확인하며, 종료 시 이 테스트가 만든 Codex 대화만 보관 처리한다. 구독 사용량을 소비한다.

```bash
uv run --frozen --directory apps/codex-console-api python tests/live_smoke.py
uv run --frozen --directory apps/codex-console-api python tests/live_management_smoke.py
```

위 smoke는 기존 코어 native 실행의 검증이다. 원격 환경을 연결하지 않고 독립 앱을 host에서
실행하던 이전 `--independent-app` 옵션은 제거했다. 독립 앱은 [소스 연결 절차](#독립-앱-소스-연결)의
executor 정책 검사부터 통과해야 한다. 해당 검사는 실제 모델의 계획→편집→배포 전체 자연어
흐름을 대신하지 않으며, 현재 기본 Docker 환경에서는 이 전체 흐름의 검증이 남아 있다.

management smoke는 두 root 요청의 동시 접수와 두 native subagent의 완료 projection,
읽기 전용 저장소 보존을 검증한다.

템플릿의 별도 실행기는 아래 smoke로 검증한다. `MIY_CODEX_CONSOLE_TEMPLATE_BINARY`는
검증된 고정 CLI의 실행 파일 경로를 지정한다. 임시 저장소와 SQLite, 서로 다른 세 HTTP
프로세스를 만들고 일반 CLI를 의도적으로 비호환 상태로 둔다. 고정 CLI의 native 작업을 시작한
뒤 관리·세션 프로세스만 재시작해 로그인·thread ID·결과 보존을 확인한다. 실행 중 승인 보존과
다중 프로세스 자원 제한은 `test_templates.py`·`test_standalone.py`에서 별도로 검증한다.

```bash
MIY_CODEX_CONSOLE_TEMPLATE_BINARY=/absolute/private/codex-0.159.2/node_modules/@openai/codex/bin/codex.js \
  uv run --frozen --directory apps/codex-console-api python tests/live_template_smoke.py
```

E2E 대역 통과는 실제 구독 실행
검증을 대신하지 않는다. 로그인 만료는 사용량 창의 **ChatGPT 연결**에서 공식 device-code
로그인을 진행한다. 계정에서 device-code가 허용되지 않으면 서버에서 `codex login`을 완료한다.
인증 파일을 UI로 업로드하거나 내용을 공유하지 않는다.

장애 확인은 `/healthz`, 서비스 상태, UI 오류 코드로 시작한다. DB migration 실패를 `stamp`나
테이블 재생성으로 우회하지 않는다. Codex 호환성 오류는 안정 버전과 생성된 RPC 스키마를
확인하고, 스키마가 바뀐 경우 기준 계약을 검토해 갱신한다.
버전 불일치가 발생하면 화면 상단과 모델 선택에 **Codex 업데이트 필요**가 표시된다.
**업데이트 안내 → 업데이트 템플릿 열기**로 이동해 호환성 업데이트 템플릿을 실행한다.
고정 CLI·실행기 릴리스가 일반 CLI 오류와 management/session 재시작으로부터 작업을 분리한다.
실행기 자체가 사용할 수 없을 때에만 접힌 수동 복구 안내의 프롬프트를 서버 Codex에 입력한다.
배포가 끝나면 페이지를 새로고침해 모델 목록과 실행 결과를 확인한다.
사용량 제한에는 API fallback을 두지 않는다. 비밀번호 분실은 서버의 `set-password`로 복구한다.
