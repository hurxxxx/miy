# PMS 공개 UI 계약의 실제 소유 이전

2026-10-07. 승인된 `OFF-002A`의 로컬 구현·집중 회귀와 재개 후 최종 production build/대표 브라우저를 마쳤다. 전체 PMS 업무 기능·서비스 분리 완료와 구분한다.

## 범위

기존 PMS `public-api`가 제공하는 업무 구현 6개를 `packages/official-suite-web/src/pms`로 옮긴다.

- API·필터·권한 힌트·사이드바 순서: `api/pms-api.ts`, `pms-filters.ts`, `pms-permissions.ts`, `pms-sidebar-reorder.ts`.
- 태스크 선택기와 순수 모델: `views/TaskPickerModal.tsx`, `task-picker-model.ts`.

공용 순서 계산 `platform/ordering/ordered-reorder.ts`는 platform library가 소유한다. 기존 API/error class·함수·Context의 identity와 기본 번역을 보존하고 기존 leaf/public 경로는 같은 객체를 다시 내보낸다. 외부 Docs·Home·Meeting·Planner·Recording 소비자는 새 공개 entry를 사용하며 PMS 내부의 기존 소비자는 호환 경로를 유지한다. UI 권한 힌트가 서버 권한을 대신하지 않는다.

전체 PMS 화면·에디터·보드·서비스와 root 초기화는 이 범위에 포함하지 않는다. 전체 Planner도 Meeting 상세→Docs 협업·Recording·Whiteboard 연결이 남아 있어 이번 부분 이전만으로 완결되지 않는다. 앱 ID·경로·API·데이터·위임 권한·서비스 활성화는 바꾸지 않는다.

## 구현·검증

담당 에이전트는 소스와 공개 entry·호환 경로·소유 검사·관련 tests·소유 README를 이전한다. 부모는 canonical 관리 metadata·이 문서 트리·실제 두 UI build/브라우저를 통합한다. 상세 원본 7개와 SHA, 소비자 목록은 `.runtime/pms-public-extraction/PLAN.md`와 inventory에 기록한다.

기존 필터·순서 계산·API/errors와 같은 객체를 확인한다. 선택기의 수명 경계에 이미 수행한 검사는 아래 근거로 보존한다. 재개 후 새 보완은 구조 이전·계약 유지에 필수이거나 치명적 문제인 경우에 한정한다. 공용 picker 자체의 범위를 확대하거나 이미 수락된 서버 쓰기를 취소했다고 표시하지 않는다.

관련 기존 specs와 외부 소비자의 회귀, 타입·의존성·소유 검사를 통과한 뒤 두 composition에서 실제 Recording→PMS 선택기를 확인한다. 검색과 명시 선택·연결된 항목 제외·현재 입장 거부를 합성 API로 검사하고 실제 사용자 업무 데이터에는 쓰지 않는다. 완료 근거는 [VALIDATION.md](VALIDATION.md)에 기록한다.

2026-10-07 사용자 범위 조정에 따라 남은 두 build·대표 브라우저와 독립 리뷰는 공개 계약의 실제 연결을 확인하는 구조 검사로 유지한다. PMS 전체 업무·입력·화면 경우의 추가 검증과 비필수 개선은 [APP-ISS-001](APP_ISSUES.md)에 보류한다. 과거의 넓은 library/소비자 검사 전체를 반복하는 것은 새로운 영향이나 실패가 있을 때 판단한다.

## 중단 시점의 근거

실제 업무 6개·공용 1개 소유와 호환 경로·8개 외부 소비자를 이전했다. 선택기의 로그인/권한/열림/목록 변경 뒤 늦은 콜백 문제를 실패 우선으로 재현해 PMS 내부 수명 검사만 보완했다. library 292개, platform 50개, 기존 PMS/교차 소비자 303개와 최종 PMS UTC·America/New_York 각 67개가 통과했다. 뒤에 추가한 locale 2개와 최종 타입/린트도 통과했으며 전체 library를 294개로 재실행했다고 표시하지 않는다. API/필터/권한 힌트/순서의 본문 5개는 import·format 제외 동일하다. canonical 관리 경로·10개 appLocalTests와 생성 산출물을 갱신했고 생성/소유 검사를 통과했다.

`.runtime/pms-public-extraction/REPORT.md`는 42개 담당 입력과 부모 metadata 4개를 기록한다. `.runtime/pms-public-review/REPORT.md`의 독립 검토는 중단 당시 부분 읽기이며 현재 발견된 blocker는 없다. 부모 Recording→PMS 합성 브라우저 2개는 이전 build에서 3.1초에 통과한 기준선이다. 현재 소스의 최종 production build/브라우저 근거가 아니므로 재개 후 수행한다. 새 업무 범위·서비스·배포는 시작하지 않는다.

## 재개 후 최종 구조 연결

portal8566모듈/30.37초, official7857모듈/25.59초의 현재 소스로 두 production build를 만들었다. 실제 Chromium은 Recording→PMS·Meeting/Recording·Planner의 변경 공개 계약을 각각6개(5.9초·6.9초)로 확인했고1373개 선택 입력은 불변이었다. 전체 앱별 상세 검사는 반복하지 않았다. `.runtime/pms-public-integration-final/REPORT.md`가 최종 범위·dist hash·초기 fixture 실행 경로 오류를 기록한다. 오래 실행 중인 dev Vite의 Nx 경로 cache 때문에 발생한 새 source-library 해석 오류도 explicit Vite alias로 해결했고 실제 dev호스트/로컬 화면과24개 resolver 계약을 확인했다. 서비스배포·사용자데이터변경·기존Workbench후보재빌드는 하지 않았다.
