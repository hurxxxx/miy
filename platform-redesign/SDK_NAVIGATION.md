# 독립 앱 SDK의 플랫폼 탐색 하위 계획

`APP-001`의 테마·언어 다음 범위다. 2026-10-07 현재 해당 하위 구현·단위·독립 리뷰·고정 production 브라우저·starter/Workbench 후보 검증을 마쳤다. 런타임 권한이나 실제 서비스 활성화는 바꾸지 않는다. 최종 SDK wire와 사용법의 원본은 [SDK README](../packages/app-sdk/README.md), 진행·검증은 이 디렉터리에서 관리한다.

## 최소 계약

독립 앱이 다른 앱으로 이동할 **제안**을 보내면 포털이 현재 권한으로 대상을 확인하고 이름과 이동 버튼을 표시한다. 사용자가 그 버튼을 클릭할 때 권한과 원래 연결을 다시 확인하고 포털 화면을 이동한다. 메시지 수신만으로 현재 화면을 교체하지 않는다.

- 공개 SDK 입력은 `offerApp({appId, installationId?})`다. 독립 앱 대상은 정확한 설치 ID가 필요하고, 내장 앱은 canonical entry route만 사용한다. URL·경로·query·hash·외부 launcher 주소는 받지 않는다.
- `connectApp`의 선택적 `onNavigationReady(offerApp)`와 AbortSignal로 연결 수명을 묶는다. 호스트가 버전 1을 협상하고 앱 세션 교환/검증이 성공한 뒤에만 함수를 전달한다. 기존 세션 반환형을 유지하고 구버전 호스트/호출자는 그대로 동작한다.
- 결과의 `offered`는 버튼이 제시됐다는 뜻이다. `busy`·`unavailable`과 구분하며 실제 도착·앱 실행·API 접근 권한을 뜻하지 않는다. 이동 자체로 iframe이 해제될 수 있으므로 도착 확인 응답을 약속하지 않는다.
- exact Origin·window source·설치·연결 nonce·요청 UUID를 확인한다. 양쪽의 pending 수·빈도·대기 시간과 포털 제안 표시 시간을 제한한다. 자동 재시도나 새 창 강제 열기는 없다.

## 기존 권한과 수명

포털의 현재 MIY 로그인으로 기존 complete/revision-checked independent catalog와 앱 bootstrap을 조회한다. 원래 설치의 origin·generation·launchable과 대상 admission을 확인한다. 앱에 로그인 bearer나 다른 앱의 token을 전달하지 않는다. 이 탐색은 새 Core API·권한·DB 상태를 만들지 않는다.

로그인/토큰·원본 설치·화면/연결 변경·popup 종료·만료·Abort 뒤에는 이전 응답과 버튼을 무효화한다. 사용자가 버튼을 누른 뒤의 fresh 조회도 같은 연결인지 확인한다. standalone 방식에서는 로그인에 사용한 포털 popup 자체만 이동하며 앱 opener나 다른 창의 location은 바꾸지 않는다.

## 구현과 검사

SDK·호스트 listener·호스트 표시 UI와 번역·owner README를 한 에이전트가 담당하고 부모가 통합한다. Workbench 후보와 공식 업무 UI 소유 이전은 다른 경로에서 병행한다. 기존 skills를 개발 절차로 사용하지 않는다.

단위 검사는 협상/구버전·잘못된 메시지/대상·중복/빈도·무응답/Abort·현재 계정과 원본 generation·fresh admission·사용자 클릭 이전 이동 0회·한 번 이동을 확인한다. 합성 cross-origin Chromium에서 iframe과 popup 동작을 검증한다. starter에 넣는 경우 canonical SDK와 bundle을 생성기로 함께 갱신하고 기존 starter/별도 Workbench 패키지 경계도 다시 확인한다. 네트워크 목적지·인증 계약이나 파일 선택 기능은 이 범위에 포함하지 않는다.


검증은 SDK 19개·web 집중 60개, portal 실제 브라우저 18개 중 기존/신규 independent 9개와 원래 standalone/iframe 소비자를 포함한다. 현재 등록/설정과 함께 통합한 범위는 [VALIDATION.md](VALIDATION.md)가 소유한다. 파일 선택과 추가 공통 API·전체 자연어 인수는 남아 있다.
