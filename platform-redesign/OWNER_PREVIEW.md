# 소유자의 최초 개발 미리보기 설정

2026-10-07, `APP-002A/B`·`WB-003B`의 등록 이후 연결 하위 범위다. 해당 Core·포털·링크 구현과 실제 PG/고정 브라우저/별도 Workbench 후보 검증을 마쳤다. 등록은 비활성 설치를 만들며, 그 뒤 소유자가 자신의 개발 설치를 허용하고 요청된 접근 중 필요한 것만 선택할 수 있어야 한다.

## 변경 범위

- Core에 owner-only `GET/PATCH /independent-apps/{app_id}/installations/{id}/owner-preview`를 추가한다. 실제 현재 소유자·personal 정의·development·selected·본인 한 명·group 없음 조건을 확인한다. 관리자도 다른 소유자를 대신하는 우회 권한을 얻지 않는다.
- PATCH는 기존 generation·definition digest·source revision과 원하는 enabled/granted permissions만 받는다. origin·환경·대상·소유자·release·source는 바꾸지 않는다. 기존 catalog summary로 누락된 audience를 추정해 범용 PUT 요청을 만들지 않는다.
- 초기 release/runtime이 없는 설치에 한정한다. 배포나 검증 작업이 진행된 설치는 상태를 설명하고 설정을 닫는다. 같은 CAS와 같은 값의 요청은 generation과 audit을 늘리지 않는 no-op이다.
- definition→installation 잠금, 현재 non-impersonated MIY 로그인/계정 권한의 대기 전후와 flush 이후 확인, READ COMMITTED·비-autocommit·짧은 lock timeout을 적용한다. 허용 권한은 현재 manifest 요청의 부분집합이다.

등록 위임·metadata key·Workbench 로그인은 이 API 인증에 사용할 수 없다. 기존 MIY 소유자 로그인에서 명시적으로 설정한다. 허용 설정 자체는 앱 서버 실행·health·배포 성공을 뜻하지 않는다.

## 포털과 실패 처리

포털 전용 설정 경로에서 현재 앱·고정 개발 주소·요청/부여 권한·허용 상태를 읽는다. 앱 등록 receipt와 자신의 개발 설치 목록에서 연결한다. 공식 앱 root에는 이 설정 route를 추가하지 않는다.

처음 조회나 URL 진입만으로 PATCH하지 않는다. 현재 값을 편집한 뒤 저장하고, 응답 유실 시 현재 설정을 GET으로 다시 확인한다. 자동 재전송이나 별도 receipt 엔진은 추가하지 않는다. CAS 충돌은 최신 설정을 다시 읽고 사용자가 재검토하도록 한다. 재조회 값은 현재 관측이며 앞선 요청이 완료됐다는 증명으로 표시하지 않는다. 계정/URL/unmount 뒤 늦은 응답과 성공 알림은 무시하고 요청 시간을 제한한다.

Core/실제 PostgreSQL 검증은 별도 에이전트가, 포털/생성 계약/통합 문서는 부모가 맡는다. 실제 앱·운영 DB·설정·서비스는 바꾸지 않는다. 기존 하네스나 skills를 개발 절차로 적용하지 않는다.


실제 PostgreSQL 158개·UI 영향 78개·포털 실제 설정 브라우저 3개와 독립 리뷰, 최신 별도 Workbench 후보 `3d724785…`까지 확인했다. 정확한 실행/실패/중복 범위는 [VALIDATION.md](VALIDATION.md)를 따른다. 기존 release/runtime·진행 빌드·유효 검증이 있으면 초기 설정을 닫으며 운영 중 권한 변경 도구로 확대하지 않는다.
