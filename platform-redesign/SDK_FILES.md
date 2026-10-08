# 독립 앱에서 사용자가 선택한 파일 읽기

2026-10-07. `APP-001`의 로컬 구현 범위다. Core/Files·SDK·포털·템플릿 구현과 집중 검증을 마쳤다. 최종 리뷰의 Unicode 길이 호환 보완 뒤 두 UI build/브라우저와 새 Workbench 후보 검증까지 마쳤다. 서비스 활성화나 전체 재설계 완료로 표시하지 않는다.

## 목적과 범위

현업 앱은 포털의 파일 선택기를 열고 사용자가 고른 파일 하나를 앱 UI 또는 자체 백엔드에서 읽을 수 있다. 공통 플랫폼은 앱 세션·설치 권한과 선택 동의를 소유하고, Files는 원본 ACL·메타데이터·객체 버전·스토리지 접근을 소유한다. 파일을 플랫폼 데이터로 재분류하지 않는다.

첫 범위는 `files.file` 하나, 최대 10 MiB, 전체 bytes 응답이다. 폴더/일괄/업로드/삭제/HTML 미리보기/Range/장기 백그라운드 작업은 포함하지 않는다. 플랫폼은 별도 영구 사본을 만들지 않는다. 이미 앱에 전달한 bytes는 **회수할 수 없다**. 앱 자체 보관·제품 AI 사용은 기존 데이터/AI 계약을 따라야 한다.

`files:read-selected`를 명시적으로 요청하고 설치에서 허용해야 한다. 기존 `identity:read`도 필요하다. 두 실행 프로파일 모두 사용할 수 있으며 `data:` 권한으로 해석하지 않는다. 기존 앱·starter의 요청/허용 권한은 자동 확대하지 않는다.

## 상태를 추가하지 않는 제한 위임

새 selection DB나 소비 상태 머신 없이 기존 앱 세션에 두 목적의 짧은 서명 claim을 묶는다.

1. 앱 bearer로 읽기 권한 없는 선택 요청 증명을 만든다. 앱 SDK는 인증 교환 완료 이후에만 이를 요청한다.
2. 포털은 정확한 원래 MIY 로그인·설치·요청 증명을 확인하고 Files 목록을 보여준다. 사용자의 명시 선택 뒤에만 읽기 claim을 발급한다.
3. 앱은 같은 앱 bearer와 선택된 파일의 읽기 claim을 함께 제출한다. 서버는 매번 현재 앱/원래 MIY 세션·설치 권한·Files 입장/ACL·객체 버전을 확인한다.

요청 증명은 60초, 읽기 claim은 승인 이후 120초이며 모두 기존 앱/MIY 세션 만료보다 길 수 없다. 두 서명 목적과 버전은 분리한다. 원래 MIY bearer·기존 content grant·스토리지 주소/키는 앱에 주지 않는다. 기존 `/content` 인증 범위도 확대하지 않는다.

claim은 기존 `AppSession.token_hash` selector에 묶는다. 해시는 bearer로 사용할 수 없지만 서명 payload는 암호문이 아니므로 민감한 메타데이터로 취급한다. URL·브라우저 저장소·로그·LLM 맥락에는 넣지 않는다. 다른 앱 세션은 같은 사용자/설치여도 읽을 수 없다.

읽기는 유효기간 내 반복 가능하며 매번 권한을 재확인한다. 개별 claim만 즉시 회수하거나 정확히 한 번만 소비하는 계약은 없다. 원래 로그인/앱 세션 철회, 설치 generation/권한 변경, Files ACL/객체 변경은 후속 읽기를 막는다. 선택 요청 재전송이나 응답 유실 뒤 자동 재승인은 없다.

Core 전용 typed 설정 `MIY_INDEPENDENT_APP_FILE_SELECTION_SIGNING_KEY`는 기본 빈 값으로 이 기능만 비활성화한다. 설정값은 모든 환경에서 비기본·비placeholder 32바이트 이상이어야 한다. 공개 개발 기본키가 있는 기존 content signer를 재사용하지 않는다. 실제 secret/configuration 설정은 이번 로컬 구현에 포함하지 않는다.

## 버전 1 API

기준 경로는 `/api/v1/independent-apps/_files`다. 공통 context는 `schema_version:1`, `installation_id`, 정확한 `audience` origin, `selection_id` UUID다. JSON body 8 KiB·opaque token 4096바이트 상한, strict DTO·추가 필드/불리언 버전 거부를 적용한다.

| 경로                        | 호출 권한                              | 입력/결과                                                                              |
| --------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------- |
| POST `/selection-request`   | 앱 bearer                              | context → context, `selection_request`, `expires_at`, `max_bytes:10485760`             |
| POST `/candidates`          | 현재 MIY bearer                        | context/proof/query≤120/cursor≤2048/limit≤25 → context, items, next_cursor, incomplete |
| POST `/authorize-selection` | 현재 MIY bearer·명시 선택              | context/proof/file_id/**expected_version** → context, file, read_grant, expires_at     |
| GET `/content`              | 같은 앱 bearer + `X-MIY-Selected-File` | 공개 installation_id/audience query → 제한된 전체 bytes                                |

파일 metadata는 `file_id`, `name≤255`, `content_type≤255`, `size_bytes≤10485760`, `version`(Files 객체/ACL binding의 opaque 64hex)만 포함한다. 선택 승인도 목록에서 본 버전이 현재와 같아야 한다. 저장 key·원본 URL·검색 추출문·폴더 전체/총 건수는 노출하지 않는다. metadata 목록은 포털만 받고 앱에는 선택한 한 파일만 전달한다.

후속 승인/읽기는 설치된 trusted release의 요청 권한을 기준으로 한다. 현재 정의만 수정해서 과거 설치 산출물의 권한이 커지지 않도록 기존 app session·현재 설치 grant·effective requested permission을 모두 확인한다.

## Files 소유와 제한

- 기존 source ACL을 공용 owned helper로 재사용한다. 공통 플랫폼에 Files ACL을 복제하지 않는다. 기존 content 다운로드의 동작도 유지한다.
- 페이지 25개·scan 후보 200개·조상 최대 32단계/2초 탐색을 적용한다. 현재 browse의 전체 폴더/파일 materialization을 재사용하지 않는다. cursor는 마지막 조사 후보부터 진행하고 일부만 확인했으면 `incomplete`로 표시한다. 조사가 끝나지 않은 빈 페이지를 파일 없음으로 확정하지 않는다.
- 객체 읽기는 고정 DB-owned key만 사용하며 caller URL/redirect를 받지 않는다. 전용 bounded client/취소 가능한 transport를 검증한다. 기존 MinIO 전역 client의 timeout/재시도는 바꾸지 않는다. 동기 호출을 timeout thread로 버리는 방식은 전체 시간 제한의 근거가 아니다.
- 최대 10 MiB buffer·소수 동시 읽기 제한·실제 크기 일치·전체 deadline과 모든 실패 경로의 close/release를 확인한다. upstream 자원을 정리한 뒤 새로운 현재 DB 관측으로 권한/객체 버전을 재확인하고 응답한다. 네트워크 I/O 동안 DB 쓰기 잠금을 유지하지 않는다.
- 전체 응답은 octet-stream attachment, 정확한 Content-Length, private/no-store/no-referrer/nosniff다. 최종 권한 확인 뒤 이미 전송되는 bytes의 즉시 회수까지 보장하지 않는다.

조회 budget과 소스 권한은 실제 격리 PostgreSQL에서, 저장소의 전체 deadline/취소/EOF는 실제 합성 TCP peer에서 검증했다. upstream 읽기는 10초, 각 I/O는 2초이며 네 개의 ASGI 응답을 실제 send 완료·실패·취소까지 세고 응답은 20초 기한의 협력적 취소와 각 ASGI send 직전 monotonic 검사를 적용한다. 동기 SQL을 선점하거나 절대 벽시계 20초 종료를 보장하지 않으며, 기한이 지난 작업이 돌아온 뒤 새 headers/body를 전달하지 못하게 한다. DB는 별도 statement timeout을 사용한다. 정확한 RSS나 클라이언트 수신 확인의 보장도 아니다. TLS 검증과 기존 MinIO CA 선택을 유지한다. 구현된 source/adapter 계약은 [Files 소유 문서](../apps/api/src/miy_api/domains/files/SELECTED_ACCESS.md)가 소유한다.

## SDK·호스트·템플릿

선택적 `file_picker_version:1`과 `onFilePickerReady`/AbortSignal로 협상한다. 기존 connectApp 반환형·버전·미지원 host의 인증은 보존한다. 함수는 앱 인증 교환 뒤에만 제공하며 selectFile은 URL/파일ID 인자를 받지 않는다.

`onFilePickerReady({selectFile})`는 두 권한이 있는 검증된 앱 세션에만 제공한다. 선택 결과는 `{status:'selected', file:{fileId,name,contentType,sizeBytes,version},readGrant,expiresAt,read}` 또는 `canceled|unavailable|busy` 상태다. `read({signal})`은 ArrayBuffer를 반환하며 앱이 명시적으로 호출한다. opaque readGrant는 자체 백엔드에서도 같은 앱 세션과 함께 사용할 수 있다.

wire는 `miy.app.file-picker.request/result/cancel`이며 Core DTO의 snake_case와 SDK 공개 camelCase를 구분한다. host 주입점은 `selectFile(request,signal,isCurrent)`이고 `{status:'selected',selection:SelectedFileReadOut}` 또는 고정 상태를 반환한다. 한 선택의 취소/timeout은 그 request controller만 종료하며 같은 유효 세션의 후속 명시 선택까지 영구 차단하지 않는다.

메시지는 현재 origin/window/설치/원래 handshake nonce/selection UUID에 고정한다. 한 번에 하나·분당 최대 6개·제한된 대기 시간, popup 종료·새 nonce·로그아웃·해제·만료 뒤 늦은 host 선택 결과를 차단한다. 앱의 재연결은 기존 controller를 abort한 뒤 시작해야 옛 SDK read closure도 닫힌다. 새 nonce 자체가 이미 전달된 서버 claim을 철회하지는 않는다. 포털은 현재 원본 설치/로그인을 사용하고 명시 선택/취소와 읽기 실패를 표시한다. 파일 선택은 자동 읽기나 AI 실행을 뜻하지 않는다.

앱 backend에는 고정 POST `/api/platform-files/selection-request`와 GET `/api/platform-files/content`만 추가한다. installation/audience는 코어가 제공한 고정 설정에서 가져온다. 기존 32 KiB JSON helper를 무제한으로 키우지 않고 binary helper를 분리한다. gateway도 Core의 두 앱 인증 경로만 열고 candidates/authorize/일반 Files API는 열지 않는다.

## 변경 분담과 완료 기준

- Core/Files 담당: strict 계약·권한 max4·서명·현재 세션·원본 adapter·localized 오류·typed 설정·합성/owned PostgreSQL 검사·owner 문서.
- SDK 담당: SDK/host protocol과 수명·형식·호환 검사. 부모: React picker·현재 host 연결·동의/등록/미리보기의 exhaustive 권한 표시·브라우저 통합.
- Template/Workbench 담당: 고정 binary proxy·제한 gateway·Workbench Literal/max4 호환·두 starter 회귀. 생성 schema/OpenAPI/bundle과 새 후보는 통합 시 부모가 조율한다.
- 기존 max3인 Core definition/installation/bootstrap/registration/preview, Workbench policy, 웹 parser/label을 함께 max4로 맞춘다. 등록은 여전히 빈 grant의 비활성 설치를 만든다. 이미 배포된 앱의 권한 변경 UX는 별도 남은 항목이다.
- 실제 owned PG에서 세션·설치/회사/Files 권한·ACL/객체 교체와 post-read 철회, 목적 치환·다른 세션·크기/시간/취소/정리·pagination 제한을 검증한다. 기존 Files/content와 앱 등록/preview 동작도 확인한다.
- 실제 iframe/popup 브라우저와 고정 앱 runtime 경로, canonical starter/bundle 일치를 검증한다. 실행 환경상 불가능한 검사는 미검증으로 남긴다. 운영 설정·서비스·배포는 수행하지 않는다.

초기 읽기 설계와 대안 비교는 `.runtime/independent-app-file-picker-review/REPORT.md`·59개 source inventory에 있다. [RFC 8693](https://www.rfc-editor.org/rfc/rfc8693.html)의 대상/범위 구분과 [MDN postMessage](https://developer.mozilla.org/en-US/docs/Web/API/Window/postMessage)의 origin/source 확인을 참고했으며 OAuth Token Exchange 구현이라고 표시하지 않는다. 고정 [MinIO 7.2.20 공개 source](https://github.com/minio/minio-py/blob/7.2.20/minio/api.py)의 timeout/lifecycle 한계는 실제 adapter 검사로 확인한다.

## 확보한 검증과 설정 상태

- Core/Files: 실제 PostgreSQL 151개 통과, 외부 MinIO 1개는 명시 제외. pure 41개는 이 실행과 겹치므로 합산하지 않는다. 97개 입력 불변·소유 컨테이너 정리와 API architecture/i18n/Ruff를 확인했다. 이후 동기 작업의 기한 초과 후 send를 재현해 막았으며 pure 43개·실제 content route 2개를 별도 통과했다. 이 두 검사는 151개 전체를 재실행한 결과가 아니다. 두 초기 PG 실행의 logging capture 실패와 body 예외 원문 노출 재현/수정은 검증 기록에 보존한다.
- 최종 Unicode 보완: 서버의 255 Unicode code point와 SDK/host의 UTF-16 길이 검사가 달랐던 문제를 실패 우선으로 수정했다. SDK 44개·host 45개·포털 picker 28개가 통과했다. 포털은 255개의 비BMP 파일명도 표시·명시 선택하는 통합 케이스를 포함한다.
- 템플릿/gateway 실제 Docker 1개가 두 고정 경로의 bytes/header 왕복과 portal 전용 경로 거부·교체/복구를 확인했다. Core의 실제 ACL 검사와 구분한다.
- Unicode 보완 전 두 production build에서 portal 24개·official 8개 브라우저가 통과했다. 최종 소스에서는 portal 27개·official 11개가 통과했다. 네 선택 파일 브라우저는 255 code point의 이모지 포함 이름을 사용한다. 새 Workbench 후보 `8d8b5fa8…`도 packaged SDK Unicode/SQLite/starter 검증을 통과했다. 이전 build/후보의 결과와 구분한다.
- tracked example·typed settings 정적 계약은 통과했다. 실제 로컬 설정에는 새 signer/region과 기존 등록 audience 키가 없어 환경 전체 계약 검사는 실패했다. 설정이나 secret을 설치하지 않았다. signer 기본 빈 값은 기능 비활성이고 기존 앱에는 권한을 자동 추가하지 않는다.

서버/API 설정의 현재 원본은 [Core 선택 파일 계약](../apps/api/src/miy_api/domains/independent_apps/README.md#selected-platform-files), SDK 계약은 [SDK README](../packages/app-sdk/README.md)다. 상세 실행·실패·미검증 경계는 [VALIDATION.md](VALIDATION.md)에서 구분한다.
