# 독립 앱의 공개 플랫폼 계약

이 문서는 앱 저장소 안에서 읽을 수 있는 지원 기능의 요약입니다. 앱 개발에 필요한 항목만 참조하세요. 설치·권한·실행 환경은 서버가 결정하며, 이 문서나 자연어 지시로 권한을 얻을 수 없습니다. 현재 앱의 선택은 `app.manifest.json`에서 확인합니다.

## 지원 프로필과 저장 방식

| 프로필                | 지원 기능                                                   | 요청할 권한                                |
| --------------------- | ----------------------------------------------------------- | ------------------------------------------ |
| `web-api-v1`          | React/Vite UI, FastAPI, 앱 세션 확인. 영구 데이터 저장 없음 | `identity:read`                            |
| `web-api-postgres-v1` | 위 기능과 Core가 관리하는 사용자별 JSON 레코드 저장         | `identity:read`, `data:read`, `data:write` |

`basic` 템플릿은 `web-api-v1`으로 시작합니다. `private-notes` 템플릿은 같은 앱 구조에 `web-api-postgres-v1`과 데이터 API 예제를 추가합니다. 기본 앱에서 영구 저장이 필요하다면 지원 프로필과 필요한 권한을 명시한 뒤, 소유자 승인과 해당 프로필의 검증된 릴리스·설치를 거쳐야 합니다. 매니페스트 변경만으로 데이터 권한이나 저장소가 생기지는 않습니다.

데이터 프로필은 운영자가 준비한 전용 PostgreSQL에 설치마다 별도 데이터베이스를 사용합니다. 앱에 DB 주소·암호·SQL 실행 권한을 전달하지 않습니다. 데이터 프로필이 준비되지 않았다면 필요한 운영자 연결을 알리세요. 브라우저 저장소, 앱 컨테이너 파일 또는 임의의 외부 DB를 플랫폼의 영구 저장으로 대체하지 않습니다. 개발과 운영의 데이터는 분리되며 코드 배포가 개발 데이터를 운영으로 복사하지 않습니다.

현재 저장 계약은 설치 안에서도 **로그인한 원래 사용자별 비공개 데이터**입니다. 전사 공유, 다른 사용자 데이터 조회, 임의 역할 지정, SQL·사용자 정의 테이블, 여러 레코드에 걸친 사용자 정의 트랜잭션, worker 및 object storage는 이 프로필의 권한에 포함되지 않습니다. 필요한 경우 공통 플랫폼 계약의 확장을 요청합니다.

## 세션과 서버 권한

브라우저는 로컬 `vendor/miy-app-sdk`의 `connectApp`으로 지정된 플랫폼과 정확한 origin·window·설치를 확인합니다. 짧은 일회용 코드와 PKCE로 앱 세션을 교환하며 플랫폼 로그인 bearer는 앱으로 전달하지 않습니다. 앱 bearer는 브라우저 메모리에만 보관하고 URL, 로그, 브라우저 저장소, 모델 입력에 넣지 않습니다.

`GET /api/me`는 기존 앱 서버의 `platform_request`를 통해 Core의 `/session`을 조회합니다. 보호된 업무 API도 매 요청마다 현재 세션과 자원 권한을 확인해야 합니다. 데이터 gateway 자체도 매 요청에 원래 로그인 세션, 설치·audience·generation, 활성 검증 릴리스의 데이터 프로필과 실제 부여된 권한을 확인합니다. 앱에서 받은 사용자 ID, 관리자라는 입력 또는 매니페스트의 권한 선언은 인증 근거가 아닙니다.

## 고정 데이터 gateway 사용

앱의 `business.py`에 앱 소유의 입력 검증과 업무 API를 작성합니다. 기존 `install(app, settings, platform_request)` 확장점을 사용하세요. 호출 대상은 앱 서버가 가진 고정 `platform_request`이며, 아래 경로는 이 함수에 넘길 상대 경로입니다. 함수가 고정 플랫폼 origin과 `/api/v1/independent-apps` 접두어를 붙입니다. 사용자 입력으로 플랫폼 URL·origin·경로를 선택하는 일반 proxy를 만들지 않습니다.

모든 호출은 다음 값을 사용합니다.

- `headers={"Authorization": authorization}`: 현재 요청의 앱 bearer. 플랫폼 로그인 토큰이나 서비스 API key로 대체하지 않습니다.
- `params={"installation_id": settings.installation_id, "audience": settings.origin}`: 앱 서버에 배치된 고정 설치와 앱 origin. 사용자가 보낸 값을 사용하지 않습니다.
- 필요하면 검증한 `after`, `limit`, `expected_version`만 query에 추가합니다. 레코드 소유자 ID는 보내지 않습니다. Core가 인증된 원래 사용자로 결정합니다.

| 동작       | `platform_request`의 method·path         | 추가 입력·성공 응답                                                              |
| ---------- | ---------------------------------------- | -------------------------------------------------------------------------------- |
| 목록       | `GET /_data/{collection}`                | query `after` UUID, `limit` 기본 50·최대 100. 응답 `{items, next_cursor}`        |
| 한 건 조회 | `GET /_data/{collection}/{record_id}`    | 응답 레코드                                                                      |
| 생성       | `POST /_data/{collection}`               | `json={"payload": {...}}`, `success_codes=(201,)`. 선택적으로 `record_key` 추가. 응답 새 레코드 |
| 키 조회    | `GET /_data/{collection}/by-key`         | query `record_key`, `data:read` 권한 필요. 응답 레코드 또는 `404`                  |
| 수정       | `PUT /_data/{collection}/{record_id}`    | `json={"payload": {...}, "expected_version": version}`. 응답 새 version의 레코드 |
| 삭제       | `DELETE /_data/{collection}/{record_id}` | query `expected_version`, `success_codes=(204,)`. 응답 본문 없음                 |

레코드는 `{id, payload, version, created_at, updated_at}`입니다. `id`는 Core가 만든 UUID이고 `version`은 1부터 시작합니다. 컬렉션 이름은 `[a-z][a-z0-9_-]{0,63}`, 레코드 ID와 페이지 cursor는 UUID로 검증합니다. payload는 JSON 객체이며 UTF-8 직렬화 기준 최대 16 KiB입니다. 전체 쓰기 HTTP body는 최대 20 KiB이고 정의되지 않은 최상위 필드는 거절됩니다. 앱의 업무 필드도 앱 서버에서 별도로 검증합니다.

`record_key`는 선택적인 생성 전용 식별자입니다. 정확한 문자열을 사용하며 UTF-8 기준 1~256 bytes, 출력 가능한 문자만 허용합니다. 공백만 있는 값·제어 문자·surrogate는 거절하고 Core가 공백을 제거하거나 대소문자를 바꾸지 않습니다. 같은 원래 사용자·설치·컬렉션·키의 동시 생성은 기존 PostgreSQL 기본 키로 한 건만 `201`이 되며, 나머지는 `409`입니다. 충돌해도 원래 payload/version을 바꾸거나 반환하지 않습니다. 키가 없거나 `null`이면 기존 무작위 UUID 생성을 사용합니다.

생성 응답이 불확실하면 고정 설치·audience와 같은 키로 조회해 실제 결과를 확인하세요. 키 조회도 현재 세션과 `data:read` 권한을 다시 검사하며, 자동으로 쓰기를 재전송하지 않습니다. 키를 `PUT`에 보내면 거절합니다. 이 고유성은 해당 사용자의 현재 존재하는 레코드에 한정하며 전사 전체 고유성이나 영구 요청 이력이 아닙니다. 삭제한 키는 version 1로 다시 생성할 수 있고 기존 키 없는 레코드를 자동 변환하지 않습니다. 업무상 번호 정규화와 키·payload의 일치는 앱의 입력 검증이 담당합니다.

목록은 `next_cursor`를 다음 `after`로 사용합니다. 페이지별 응답 크기를 제한하고, 기존 `platform_request`의 `max_bytes`를 페이지 크기에 맞게 명시하세요. 이 함수의 기본 응답 한도는 32 KiB이며 기본 HTTP timeout은 5초입니다. redirect와 환경 proxy를 사용하지 않습니다. 읽기 또는 쓰기 실패를 성공으로 표시하거나 무한 재시도하지 않습니다.

수정·삭제는 마지막으로 읽은 실제 `version`을 사용합니다. `409`는 다른 변경이 있어 쓰기가 적용되지 않았다는 뜻입니다. 최신 레코드를 다시 보여주고 사용자 결정을 받으며, version을 임의로 올려 강제 덮어쓰지 않습니다. `401`은 재연결이 필요한 세션 문제, `403`은 현재 권한·프로필·입장 거절, `404`는 현재 사용자에게 보이지 않는 레코드입니다. Core는 잘못된 입력·크기 초과를 거절하고 저장 연결 문제는 `503`으로 닫습니다. 기존 starter adapter는 허용한 상태 외의 Core 오류를 `503`으로 제한합니다. 타임아웃 뒤에는 쓰기 결과가 불확실할 수 있으므로 실제 상태를 확인하고 새 생성 요청을 자동 반복하지 않습니다.

## 선택 기능과 개발·배포 경계

SDK의 theme·language 표시 갱신은 읽기 전용 선택 기능입니다. 선택 파일 읽기는 별도의 `files:read-selected` 요청과 설치 승인, 사용자 선택이 필요합니다. 기본·private-notes 템플릿에는 이 권한이 없습니다. 파일 목록·임의 파일 ID·업로드·삭제 또는 제품 AI 실행을 자동 허용하지 않습니다. 제품 AI provider·모델 키·credentials를 앱에 넣지 말고 지원된 공통 계약이 있을 때만 사용합니다.

Workbench가 제공하는 `miy_app_source`의 `context`·`checkpoint`는 승인된 개발 Task의 현재 앱 소스만 로컬 저장합니다. 등록·배포나 데이터 권한을 부여하지 않습니다. 앱 shell의 `.git`은 읽기 전용이며 임의 Git metadata 쓰기나 플랫폼 저장소 수정을 시도하지 않습니다. 최초 등록은 clean Git HEAD 이후 별도 소유자 동의가 필요하고, 개발 배포는 별도의 위임과 검증 릴리스가 필요합니다. `queued`·`unknown`은 완료가 아닙니다. 같은 작업의 상태를 확인하며 새 ID나 새 요청으로 불확실성을 우회하지 않습니다. 운영 배포는 개발 위임으로 승인할 수 없습니다.

현재 고정 개발 환경에서 제공하는 CLI는 `python`, `node`, `pnpm`입니다. `ls`, `find`, `rg`, `git` 등의 명령이 있다고 가정하지 않습니다. 파일 목록·검색은 Python의 `pathlib`와 문자열 검색을 사용할 수 있습니다. 앱 소스의 Git 상태·저장은 shell Git 명령 대신 위의 승인된 `miy_app_source` 도구를 사용합니다. 필요한 명령이 없다면 같은 명령을 반복하거나 패키지·실행 이미지를 바꾸지 말고 지원된 도구로 작업합니다.

이 문서는 canonical app starter 번들에 포함된 공개 계약 요약입니다. 서버 구현은 Core의 independent-apps session·data gateway이며, 설치 환경 준비와 migration·backup·release 관리는 운영자 소유입니다. 해당 연결이 없다면 앱 개발자가 Core 설정, 인증 파일, Docker socket 또는 DB credentials를 읽거나 직접 준비하는 것으로 대체하지 않습니다.
