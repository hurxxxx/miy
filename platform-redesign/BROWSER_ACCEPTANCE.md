# 실제 공개 사이트 브라우저 확인

2026-10-10 사용자의 요청에 따라 실제 Chromium/Playwright로 공개 HTTPS 사이트를 확인했다. API 응답 대체·합성 backend·인증 정보 내보내기·고객 화면 캡처는 사용하지 않았다. 아래 결과는 대표 구조 흐름의 확인이며 앱별 전체 인수나 새 개인 앱의 자연어 개발·배포 완료가 아니다.

## 확인 결과

| 환경·대상            | 실제 관측                                                                   | 결과·범위                                                  |
| -------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------- |
| 개발 로그인          | 화면의 개발 관리자 계정 버튼으로 로그인, HTTP200                            | 통과                                                       |
| 개발 Docs            | `/apps/docs`의 `전체 문서` 화면과 실제 `/api/v1/docs/hub` HTTP200           | 후속 부분 관측에서 조건 확인; 작성·Yjs 협업은 미검증       |
| 개발 PMS             | `/apps/pms/assigned`의 `내게 배정됨` 화면과 실제 업무 조회 HTTP200          | 후속 부분 관측에서 조건 확인; 업무 편집은 미검증           |
| 개발 Files           | `/apps/files`의 본문 h1 `파일`과 실제 `/api/v1/files` HTTP200               | 설정 재읽기·검사 선택자 보정 뒤 통과; 업로드·삭제는 미검증 |
| 개인 앱 등록 화면    | Workbench 초안 파일 입력 표시, 초안이 없으면 등록 버튼 비활성               | 화면·기본 입력 경계 통과; 등록 제출 없음                   |
| Workbench 연결       | 포털 링크로 새 창 열기, native 세션 교환, shell 표시, handoff fragment 제거 | 통과                                                       |
| Workbench Codex 계정 | account HTTP200, `connected=true`, 구독 인증, 오류 코드 없음                | 통과; 새 모델 턴 없음                                      |
| Workbench 목록·선택  | 목록18개, 선택 버튼과 상세 화면 연결                                        | 통과; 개인 앱 수정 완료의 증거는 아님                      |
| 기존 세션·에이전트   | idle 세션 선택, 서버 실행 권한 목록과 UI 일치, 에이전트 카드 표시           | 후속 부분 관측에서 조건 확인; 재실행·권한 변경 없음        |
| 새 앱 준비           | 프로젝트 폼과 소스 옵션 HTTP200, 템플릿2개, 허용 생성 폴더0개               | 조회 통과; 신규 앱 전체 흐름은 설정 부족으로 중단          |
| 모바일 표시          | 390×844에서 개발 Docs 제목·Workbench 앱 선택 표시, 가로 넘침 없음           | 대표 배치 확인; 모바일 전체 기능 인수는 아님               |
| 운영 포털            | 실제 로그인 입력 화면 표시, 데스크톱 가로 넘침 없음                         | 공개 로그인 화면 통과; 운영 인증·앱 쓰기는 미검증          |

고객 업무 데이터·등록·소스·배포·Task를 수정하지 않았다. 실제 UI의 기본 `app.open` 통계와 개발 로그인·Workbench 세션 교환만 쓰기로 허용했다. 허용 밖 요청 차단 관측은0건이며 Task/LLM 실행은0이다.

## 발견한 서비스 문제와 조치

최초 검사에서 개발 Docs·PMS·Files가500을 반환했다. Vite 로그에는 공식 API의 loopback18781로 연결하려다 실패한 `ECONNREFUSED`가244개 있었다. 실제 공식 API는 Docker bridge 주소의18781에 수신 중이었다.

현재 `firstPartyApiDevelopmentProxies` 코드는 이미 `MIY_DEV_API_HOST`를 사용한다. Vite는05:25:37 UTC에 시작했고 해당 routing source의 수정 시각은05:49:14 UTC였다. 수정 전 bundled config를 계속 사용한 개발 프로세스 문제로 확인했다. 추가 제품 코드 변경은 없었다.

14:21:01 UTC에 소유 Vite config 두 파일의 **내용을 유지하고 수정 시각만 갱신**해 native config watcher가 설정을 다시 읽도록 했다. 두 restart 완료·감독 PID 유지·Core/Official API의 기존 프로세스 유지·이후 proxy/restart 오류0을 확인했다. API·worker·Beat 종료 명령, 환경 설정·DB 변경, 운영 서비스 변경은 없었다. 재읽기 뒤 공개 Docs 익명 조회는 JSON401, 실제 인증 브라우저의 Docs·PMS·Files 조회는200이었다.

## 원 실패와 검사 보정

- 최초12단계 중5단계는 실패했다. 공식 앱3개는 실제 proxy 오류였으며, 소스 옵션의 `Response.status()` 호출과 넓은 agent summary 선택자에는 검사 코드 오류가 있었다. 최초 실패 receipt를 성공으로 바꾸지 않는다.
- 실패한 항목만 좁힌 후속 묶음에서 Docs·PMS·기존 세션/권한/에이전트·소스 옵션의 성공을 관측했다. Files의 넓은 제목 선택자가 실패했고, 기다리던 응답이 browser close 때 처리되지 않아 프로세스는 exit1로 종료했다. 전체 성공 receipt는 없으며 안전한 stdout 관측을 별도로 기록했다.
- Files에는 본문 h1과 sidebar h2가 모두 `파일`인 정상 화면이 있다. 선택자를 본문 h1으로 좁힌 Files 전용 확인은 API200·본문 표시·browser close·실패0으로 종료했다. 제품 제목이나 기능은 바꾸지 않았다.
- 이미 통과한 모바일·운영 로그인·앱 선택 전체를 반복하지 않았다. 단위 테스트·full CI·이미지 빌드·배포도 추가하지 않았다.

## 새 개인 앱 전체 흐름의 제한

실제 생성 옵션은 허용 폴더0개이고 목록에서 전용 실행 환경이 설정된 항목도0개다. 소유 설정 확인 결과 Workbench의 MIY API 대상은 **운영 플랫폼**이며 이번 포털 검사는 **개발 플랫폼**을 사용했다. 두 목록을 같은 플랫폼의 동적 등록 성공 근거로 비교하지 않는다. 개발의 개인 앱 목록도0개여서 개인 앱 선택·수정의 양성 사례는 확보하지 못했다.

최초 helper의 `same_control_plane:true`는 구성 확인 없이 넣은 잘못된 표현이다. 원 receipt는 보존하고 `CONTROL_PLANE_OBSERVATION.receipt.json`에 이 표현과 앱 누락 비교가 유효하지 않음을 따로 기록했다.

새 프로젝트·빈 Task를 남기거나 플랫폼 저장소에 앱을 생성하지 않았다. 다음 실제 개인 앱 검사는 아래 조건을 확정한 뒤 하나의 전용 테스트 앱으로 묶어서 수행한다.

1. Workbench와 등록 대상 플랫폼의 개발/운영 대상을 일치시킨다.
2. 허용된 전용 앱 생성 폴더와 격리 실행 환경을 설정한다.
3. 별도 HTTPS 개발 origin 및 배포 대상·권한을 준비한다.
4. 자연어 생성 → 실제 등록 → Workbench 선택·수정 → iframe 미리보기 → 배포·복구를 확인한다.

이번 브라우저 검사에서 이 설정을 임의로 만들지 않았다. 외부 `open-work-hub` 앱·다중 사용자·앱별 상세 업무 인수도 포함하지 않는다.

## 근거 위치

소유자 전용 로컬 `.runtime/live-browser-20261010/`에 `PUBLIC_BROWSER.receipt.json`, `FAILED_FOLLOWUP_OBSERVATIONS.receipt.json`, `PUBLIC_BROWSER_FILES_FOLLOWUP.receipt.json`, `VITE_CONFIG_RELOAD.receipt.json`, `VITE_CONFIG_RELOAD_QUALIFIED.receipt.json`, `CONTROL_PLANE_OBSERVATION.receipt.json`을 보존했다. 원 응답·이름·업무 제목·토큰·쿠키·trace는 저장하지 않았다. 임시 검사 코드는 로컬 근거용이며 상시 하네스나 새 필수 CI 절차로 추가하지 않는다.
