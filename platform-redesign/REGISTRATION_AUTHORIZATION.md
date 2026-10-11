# Workbench 최초 등록 위임 구현 계획

`WB-003B`·`APP-002A/B`의 다음 하위 범위다. Mail 이전과 Planner 15-source/150개 검증 뒤 현재 코드를 읽고 결정했다. 2026-10-07 현재 Core·포털·Workbench adapter와 실제 PG/브라우저/독립 후보의 해당 범위 검증을 마쳤다. 재설계 전체 완료나 운영 활성화를 뜻하지 않는다. API의 계약 원본은 independent-apps README, Workbench의 저장/실행 계약은 codex-console README에 둔다.

## 결정과 범위

현재 JSON 내보내기/가져오기는 유지하며, 별도 opt-in 최초 등록 1회 위임을 추가한다. 초안 중계용 inbox·metadata 쓰기 key·일반 workflow engine을 추가하지 않는다. 기존 `MIY_API_KEY`는 조회 전용이고 `created_by_user_id`는 owner 권한이 아니다. 기존 identity-only SSO 응답/코드를 쓰기 권한으로 해석하지 않는다. 기존 installation delivery grant는 등록 이후의 현재 권한을 그대로 유지한다.

현재 MIY 사용자만 personal/create-only/disabled development/본인만의 등록을 승인한다. app ID·정확한 개발 origin·runtime profile·매니페스트 요청 권한 집합을 고정하고 실제 초기 granted permissions는 빈 목록으로 제한한다. 등록 성공은 설치 활성화·빌드 검증·executor 준비·배포 승인이 아니다. 원본 MIY 세션과 Workbench 현재 세션/Task 수명도 확인한다.

## 세 작업의 소유

- Core: 목적/버전이 별도인 authorization·짧은 코드 교환·철회·delegated bootstrap/receipt와 PostgreSQL migration. 기존 bootstrap의 잠금·현재 owner 검사·원자적 저장·멱등 receipt를 재사용한다.
- Workbench: 기존 private storage 검증을 재사용한 0700/0600 서버 파일, SQLite의 비밀 아닌 참조와 불변 요청, 현재 Task worktree snapshot, 기존 checkpoint broker와 작은 native action adapter. management/session/templates 세 프로세스가 공유하되 token/verifier는 Task context·관측·모델·브라우저 응답에 넣지 않는다.
- Portal/UI와 통합: MIY 현재 사용자의 명시적 승인 화면, Workbench의 명확한 연결/만료/결과 표시, 두 서비스·native 소비 경계·독립 후보 검증. 기존 thread에 새 dynamic tool이 자동 추가된다고 표현하지 않는다.

독립 에이전트는 disjoint source를 소유하고 main agent가 DTO·생성 계약·브라우저·문서를 통합한다. 기존 skills나 일반 하네스를 절차로 적용하지 않는다.

## 합의할 wire 경계

Core의 새 API prefix는 `/api/v1/independent-apps/bootstrap-authorizations`를 사용한다. 요청은 버전 1, Workbench 요청 UUID와 등록 operation UUID, 정확한 Workbench audience(base URL), S256 challenge, 고정 정책으로 제한한다. 승인/철회는 현재 non-impersonated MIY 로그인, exchange는 별도 단기 code+verifier, 실제 등록/receipt는 별도 registration bearer를 사용한다. 등록 body/receipt는 기존 BootstrapInput/BootstrapReceipt를 재사용한다. 최종 세부 DTO는 구현 owner끼리 먼저 합의하고 소비자/생성 검사를 함께 갱신한다.

Core audience allowlist는 기본 비어 있고 Workbench도 기본 비활성이다. 현재 설정된 MIY issuer/expected subject와 승인 actor가 일치해야 한다. 기존 SSO exact 응답과 metadata scope는 변경하지 않는다. 지원되지 않는 서버·미설정·만료는 명시적으로 표시하며 JSON 흐름으로 사용자가 돌아갈 수 있다.

브라우저 시작 URL에는 공개 정책/요청 ID/S256 challenge만 넣는다. 전체 manifest·repository URL·raw code·bearer·verifier를 URL에 넣지 않는다. 승인된 단기 code는 MIY 페이지에서 exact callback으로 **form POST**하고 bearer 교환은 WB 서버에서 한다. WB callback만 설정된 MIY Origin·서버 pending nonce·PKCE·audience·현재 세션을 검증하는 전용 경계로 처리하며 기존 COOP/CSP/다른 경로의 Origin·CSRF 검사는 유지한다. callback 이후에는 비밀 없는 상태 URL로 이동한다. Core portal에서의 기존 CSP/배치 조건도 실제 브라우저로 확인한다.

실제 Chromium에서 HTTPS Core→HTTP loopback Workbench는 기본 referrer 정책일 때 `Origin:null`이 됨을 확인했다. callback에 null Origin을 허용하지 않는다. 부모가 DOM으로 만든 숨긴 동일 출처 iframe에만 `referrer=origin`을 적용하고 script 허용 없이 form을 최상위로 전송한다. 부모 문서 정책은 유지하며 상속한 CSP의 `form-action`을 우회하지 않는다. 별도 CSP가 있는 배치는 정확한 callback을 허용해야 한다. cross-site Strict cookie가 빠지는 것은 정상이며, 서버의 pending 요청에 묶인 원래 WebSession을 확인하고 비밀 없는 303 목적지에서 브라우저 세션을 다시 확인한다.

## 불변 요청과 실패 처리

- 작업의 실제 소스는 `require_task_source → task_workspace`에서 얻는다. Project 원본 checkout용 registration snapshot을 Task에 그대로 사용하지 않는다. 현재 binding·git root/inode·clean HEAD·commit된 manifest·canonical digest를 전후 확인한다.
- 등록 전 필요한 commit은 기존 안전 checkpoint broker를 제한적으로 재사용한다. 새 Git 실행 엔진이나 임의 host 명령을 추가하지 않는다. 기존 구현 승인·native generation·root 검사를 거친 명시적 등록 Task만 새 쓰기 action을 사용할 수 있다.
- POST 전에 operation UUID와 정확한 요청을 저장한다. grant는 승인된 app/정책과 요청에 원자적으로 결속하고 현재 원본 세션·만료/철회·정책을 잠금 전후/flush 후에도 확인한다. 다른 operation/payload로 재사용하지 못한다.
- bootstrap 응답 유실은 unknown과 같은 UUID의 receipt 조회로 처리한다. source가 바뀌어도 과거 요청을 덮거나 새 UUID로 자동 등록하지 않는다. source drift와 이미 접수된 과거 요청의 관측은 구분한다.
- code exchange 응답 유실은 앱 생성 전이므로 명시 재연결과 짧은 만료로 닫을 수 있다. 등록 이후 grant가 만료돼도 새로운 현재 owner 인증으로 기존 operation의 receipt를 복구할 수 있게 하며, 자동 재등록하지 않는다.
- 로그아웃/세션 만료 후 새 작업이 이전 위임을 상속하지 않는다. credential 파일은 앱/native mount 밖에 두고 실패 시 소유 임시 파일만 정리한다. Task/API/validation 오류에서 secret이나 원문을 반환하지 않는다.

## 완료 검사와 한계

Core 실제 PG의 계정/세션/권한/철회/TTL·잘못된 audience/PKCE·동시 소비·same-ID payload 충돌·잠금 대기 중 권한 변경·원자 rollback·응답 유실을 확인한다. WB는 세 프로세스 공유/재시작·파일 권한/링크·세션/Task binding·worktree와 원본 checkout 차이·source drift·기존 checkpoint·새 thread tool 소비·secret 비노출을 검증한다. 실제 Chromium은 MIY 승인→POST callback→WB 상태·기존 파일 fallback과 응답 유실/기존 receipt 복구를 검증한다. 실제 메일/운영 DB/서비스 배포는 하지 않는다.

현재 remote executor의 namespace 차단은 별개다. 이 연결의 단위·서비스·브라우저 검사가 통과해도 실제 원격 자연어 앱 생성 전체 완료라고 주장하지 않는다. SDK 추가 기능·공식 앱 나머지 소유 이전·전체 서비스 전환도 별도 남은 작업이다.


## 해당 하위 범위 검증 완료

Core 실제 PG 154개와 강화한 기존 audience 검사 1개, 포털 unit 48개·HTTPS/loopback 브라우저 4개, Workbench 등록/기존 복구 94개·전체 frontend 159개·기존 브라우저 33개·실제 서버 등록 3개를 확인했다. 각 fixture·실패·재검사의 범위는 [VALIDATION.md](VALIDATION.md)가 소유한다. 동일 frontend를 포함한 별도 SQLite 0008 후보 `6bd4401f…`의 migrations/starters/backup/세 프로세스 private 저장소도 통과했다. 기본 비활성 설정과 실제 배포 권한은 유지한다. 실제 Core 로그인부터 원격 native 모델 실행까지 결합한 전체 자연어 인수는 남아 있다.
