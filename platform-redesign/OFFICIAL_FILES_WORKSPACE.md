# 공식 Files 화면의 소스 소유 이전

2026-10-07. 승인된 `OFF-002A`의 Files 전체 UI 소스·owner와 부모 통합 두 build·대표 브라우저 게이트를 완료했다. 아래 앞선 workspace artifact와 현재 전체 module/common Chatbot artifact를 구분한다. 공식 UI 소스와 두 composition 통합은 **12/12개 완료**이며 서비스·DB·독립 릴리스 완료를 뜻하지 않는다.

## 이전 범위

파일 목록·검색·폴더 트리·이미지 미리보기·검색 출처 표시, Files API와 업로드 Provider/세션의 15개 업무 소스를 `packages/official-suite-web/src/files/`로 이전했다. 기존 경로는 같은 객체를 다시 내보내는 호환 경로로 남긴다. 두 root가 사용하는 업로드 Context를 복제하지 않는다.

공용 인증 콘텐츠 다운로드·파일 크기 표시·전체 화면 이미지 대화상자는 `packages/platform-web`가 소유한다. 이미지 대화상자의 기존 기본 닫기 번역은 host i18next를 사용하므로, 번역 의존성이 없는 `packages/ui`에 새 의존성을 넣지 않는다. 현재 API·인증·i18next 객체와 다운로드 grant 해석, object URL 정리, Escape/body-lock 동작을 유지한다. 임의 다운로드 주소나 이미지 정책을 새로 허용하지 않는다.

`FilesChatView`와 route/sidebar/module 구현도 같은 공식 owner의 `/files/module`에 이전했다. 기존 좁은 `/files` 공개 API·업로드·artifact entry는 byte 동일하다. 공용 Chatbot 실제 구현은 `platform-web`가 소유하며 Files는 기존 공개 경험 계약에 자신의 scope·artifact renderer를 전달한다. root Auth/admission/i18next 초기화는 기존 조립 위치에 남는다. 공식 library의 web 역참조나 플랫폼의 업무 구현 의존은 없다. Core/Files의 [선택 파일 읽기](SDK_FILES.md)는 별도 구현이며 이 작업에서 backend 권한·원본·저장소 계약을 바꾸지 않는다.

앞선 15+3개 목록과 기존 바이트·소비자 기록은 `.runtime/files-workspace-extraction/PLAN.md`와 같은 경로의 inventory가 보존한다. 마지막 module/common Chatbot 구현의 정확한 74개 위치와 기존 본문·공개 객체·초기화는 [현재 owner 보고서](../.runtime/files-module-extraction/REPORT.md)가 기록한다. 실제 소스 소유와 backend/service 분리를 구분한다.

## 진행과 검증

- 이전 담당 에이전트가 소스·공개 entry·호환 경로·소유 검사·관련 단위 검사를 담당한다. 부모는 canonical 관리 metadata, 이 문서 트리와 실제 두 UI build/브라우저를 통합한다.
- 기존 세션·폴더·화면 변경 중 늦은 결과, 이미 닫힌 미리보기, 업로드 follow-up을 확인한다. 실제 재현된 수명 결함만 좁게 보완하고 이미 접수된 서버 쓰기를 취소했다고 표현하지 않는다.
- API/error/Provider identity, 다운로드 URL/header·실패·정리, 기존 Files Chat/sidebar/routes와 공용 소비자의 회귀를 확인한다. 공식/platform/web 타입과 단방향 의존성을 검사한다.
- 현재 production build에서 먼저 합성 브라우저 fixture를 검증한 뒤 새 소스로 두 build를 만들고 같은 시나리오를 실행한다. 명시 폴더 생성·업로드 중 폴더 이동과 진행 표시·검색 snippet 텍스트·인증 다운로드·Files 입장 거부를 확인한다. 실제 사용자 파일·저장소·계정에는 쓰지 않는다.
- 완료 근거는 [VALIDATION.md](VALIDATION.md)에 기록한다. Files/공용 Chatbot 소스와 두 UI artifact 조합은 현재 범위에 포함하며, 서비스 설치·활성화·배포와 API/worker 분리는 미완료다.

## 앞선 workspace 이전의 통합 근거

공식 UI library227개·플랫폼44개·교차 소비자56개와 overlapping 집중 검사, 타입/소유/구조 검사가 통과했다. 원래 API/download/format/search body와 Context identity를 독립 대조했다. 로그인/폴더/unmount 뒤 오래된 후속 동작을 실패 우선으로 수정했으며 별도 독립 리뷰가 찾은 삭제 후 reload 중 로그인 교체 이벤트도 재현 후 보완했다. 71개 최종 소스 입력이 리뷰 시 동일했다.

이전 build의 새 fixture3개 선행 통과 뒤 최종 portal8559/26.91초·official7850/24.86초 build를 만들었다. 합성 Chromium portal27개/36.3초·official11개/12.9초가 통과했고 Files3개는 두 composition 모두 포함한다. 최종 SDK Unicode 보완도 같은 portal 검사에 포함했다. 1324개 선택 입력 불변·dist786/441개를 기록했다. 상세 근거는 `.runtime/files-workspace-integration/REPORT.md`와 [검증 기록](VALIDATION.md)에 있다.

## 전체 Files와 공용 Chatbot 소스·owner 완료

2026-10-07 재개 조사 뒤 남은 Files module·routes·sidebar·FilesChatView 네 개와 현재 플랫폼 앱인 Chatbot의 공용 대화 구현을 실제 owner로 이전했다. Files는 `@miy/platform-web/chatbot`의 기존 공개 component·경험 계약을 사용한다. `/chatbot/module`은 전체 플랫폼 앱 조합으로 구분한다. 의존을 감추는 새 render callback이나 중복 대화 엔진을 추가하지 않았다.

공통 Chatbot 구현 64개·public barrel 하나, 공통 artifact/terminal/SSE 네 개와 Files 네 개가 73개며, 사용되지 않는 Meeting 제목 hook 하나를 삭제하거나 새로 호출하지 않고 공식 owner에 보존해 **총 74개** 기존 위치를 이전했다. hook은 명시적인 type-only `/chatbot/state-types`를 사용한다. `apps.ai`·`apps.hermesWorkspace`·`apps.files` ko/en namespace만 각각 실제 owner가 소유한다. 전체 catalog 값·기존 공용 CSS·narrow Files entry와 74개 본문/export 소유가 같고, 원래 cold initializer 경로 20개·단일 root Context·Portal Map/Set·HTML bundle cache·callback identity를 보존한다. 기존 Vite `esbuild-wasm/esbuild.wasm?url` asset과 HTML sandbox/CSP·SVG·SSE 정책도 그대로다.

읽기 전용 [제안](../.runtime/files-module-review/REPORT.md)의 입력 156개·projected closure 109개와 현재 구현을 혼동하지 않는다. 현재 actual runtime closure는 **111개**, root 역참조·공통→업무·미해결·cycle은 모두 **0**이다. 기존 spec 33개를 실제 owner로 이동하고 root cold-init 통합 검사는 유지했다. 공통 전체 **269 PASS**, 공식 전체 **933 PASS**, 실제 provider/public-object/Portal/locale/root 조합 **15 PASS**, TypeScript 5개·정상 React owner lint 오류 0·전체 web architecture가 통과했다. 최종 선택 소스 **254개**가 동결 후 같으며 13개 상속 lint 경고만 [APP-ISS-008](APP_ISSUES.md)에 기록했다.

현재 동결 소스의 부모 통합도 완료했다. portal **8,567 modules/26.23초**, official **7,833/22.81초** build 뒤 같은 artifact에서 portal **36 PASS/21.7초**와 별도 Whiteboard **1 PASS/2.2초**(고유 37개), official **35 PASS/24.8초·포털 Chatbot 의도된 skip 1개**와 별도 Whiteboard **1 PASS/2.0초**(통과 36개·skip 1개)를 확인했다. actual-dev는 선택 Files 네 개·Video 두 개 **6 PASS/11.9초**이며 전체 dev suite 통과 주장은 아니다. 선택 입력 **1,823개**와 Files owner **254개**·Video **35개**가 두 build와 browser 후 같고, 독립 비교에서 74개 본문·전체 catalog·CSS·narrow API가 같다.

최종 dist는 portal **787개/SHA e4645ece…**, official **441개/SHA 4cca8a52…**다. 고정 PMS HTML **39,591 bytes/SHA 2faaeee0…**와 Recording SW **624 bytes/SHA ddb07aae…**는 양쪽에서 canonical source와 같다. [현재 부모 통합](../.runtime/official-ui-final-integration/REPORT.md)과 `final-input-check.json`·`source-review.json`이 정확 범위·시점을 소유한다. 이전 workspace artifact를 이 결과에 소급하지 않으며, 상세 앱 인수·실제 AI/provider/media·서비스·배포·Workbench 완료를 주장하지 않는다.
