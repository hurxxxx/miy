# MIY 플랫폼 재설계

공통 플랫폼, 공식 앱, 현업 제작 앱, MIY Workbench의 개발·실행·배포 경계를 분리하기 위한 계획과 진행 기록이다. Workbench는 기존 Codex 개발 체계를 활용하는 **단일 사용자 관리 도구**로 개선한다. 다중 사용자 Workbench는 후속 범위다.

**현재 작업은 사용자 지시로 구조 우선 구현을 재개했다.** 완료한 범위와 재개 후 검증은 [현재 상태](STATUS.md)에 기록했다.

공식 UI 12개와 공통 Chatbot의 소유 이전·두 production build·브라우저 통합 검증을 마쳤다. 다음은 원본 앱의 플랫폼 파티션·검색 작업 쓰기와 Files 추출 결과 쓰기를 분리하는 서버 경계다. 소스 분리 완료와 별도 서비스·배포 완료는 구분한다.

재개 후에는 [구조 완성에 필수인 변경·치명적 문제](PLAN.md#구조-완성-우선과-앱별-후속-작업)에 집중한다. 앱별 비필수 개선·상세 검증은 [이슈 대장](APP_ISSUES.md)에만 기록하고 별도 사용자 지시 전까지 착수하지 않는다. 범위 조정 이후의 명시적 구현 재개 요청에 따라 구조 작업을 진행한다.

현재 승인된 실행 범위는 **계획에 따른 구현·검증과 현재 변경의 GitHub 커밋·push·PR·병합**이다. 병합 후 이번 PR 작업 브랜치만 원격·로컬에서 정리하고 다음 구조 구현을 이어간다. 영구 `dev`·`main`과 다른 작업 브랜치는 유지하며 서비스·운영 배포는 포함하지 않는다. [게시 체크포인트](PUBLICATION_CHECKPOINT.md)가 이 일회성 게시 범위와 검증을 소유한다. 기존 하네스와 스킬은 적용할 절차가 아닌 최소화할 검토 대상으로 취급한다. 여러 에이전트가 경로별로 구현하며 주 에이전트가 통합한다. 작업을 재개할 때는 대화의 최신 요청과 [현재 상태](STATUS.md)를 먼저 대조한다.

## 문서별 책임

| 문서                                                           | 소유하는 내용                                                           |
| -------------------------------------------------------------- | ----------------------------------------------------------------------- |
| [PLAN.md](PLAN.md)                                             | 목표 구조, 이번 범위와 후속 범위, 인터페이스, 이행 순서와 완료 기준     |
| [REVIEW.md](REVIEW.md)                                         | 웹 재검토 근거·반영 전 발견 사항·소유 문서의 반영 위치                  |
| [POLICY.md](POLICY.md)                                         | 이번 재설계에 적용할 기존 규칙의 유지·대체·제외 기준과 전환 계획        |
| [WORK_ITEMS.md](WORK_ITEMS.md)                                 | 작업 ID, 의존성, 변경 범위, 상태와 완료 조건                            |
| [APP_ISSUES.md](APP_ISSUES.md)                                 | 별도 지시까지 보류할 앱별 개선·상세 검증과 근거·착수 상태               |
| [STATUS.md](STATUS.md)                                         | 현재 단계, 최근 완료 항목, 장애 요인과 다음 행동                        |
| [PROGRESS.md](PROGRESS.md)                                     | 주요 결정·구현·검증·방향 변경의 날짜별 이력                             |
| [VALIDATION.md](VALIDATION.md)                                 | 검증 계획, 실제 명령·환경·결과와 미검증 항목                            |
| [PUBLICATION_CHECKPOINT.md](PUBLICATION_CHECKPOINT.md)         | 현재 GitHub 게시 범위, 검증 요약과 병합·브랜치 정리 기록                |
| [OFFICIAL_APPS.md](OFFICIAL_APPS.md)                           | 공식 앱 분리 전 코드·데이터·소비자 경계 조사                            |
| [OFFICIAL_PMS_PUBLIC.md](OFFICIAL_PMS_PUBLIC.md)               | PMS 공개 API·선택기·순서 계산의 실제 소유 이전과 호환 경계              |
| [OFFICIAL_FILES_WORKSPACE.md](OFFICIAL_FILES_WORKSPACE.md)     | 공식 파일 목록·검색·업로드 소유 이전과 공용 다운로드/표시 경계          |
| [OFFICIAL_API_CUTOVER.md](OFFICIAL_API_CUTOVER.md)             | 공식 API의 인증·transaction writer·queue·서비스 전환 순서와 미완료 경계 |
| [FILES_SOURCE_RESULTS.md](FILES_SOURCE_RESULTS.md)             | Files Source 추출 요청·결과와 Core 읽기 전용 경계의 단계별 구현 계획    |
| [FILES_EFFECT_BOUNDARY.md](FILES_EFFECT_BOUNDARY.md)           | Core 색인 효과의 durable identity·lifecycle·완료·유한 vector 한도       |
| [FILES_PUBLICATION_STORAGE.md](FILES_PUBLICATION_STORAGE.md)   | Source 불변 publication의 bounded PUT·VersionId ACK 구현 계획           |
| [REGISTRATION_AUTHORIZATION.md](REGISTRATION_AUTHORIZATION.md) | Workbench 자연어 최초 등록의 제한 위임·저장·실패 복구 구현 계획         |
| [SDK_NAVIGATION.md](SDK_NAVIGATION.md)                         | 독립 앱의 이동 제안과 포털의 현재 권한·사용자 선택에 따른 탐색 계획     |
| [SDK_FILES.md](SDK_FILES.md)                                   | 사용자가 선택한 파일의 제한 읽기·Files 소유 권한·SDK/템플릿 구현 계획   |
| [OWNER_PREVIEW.md](OWNER_PREVIEW.md)                           | 등록 이후 본인 개발 설치의 최초 미리보기·권한 설정과 동시 수정 경계     |

## 작업 재개 순서

1. 최신 사용자 요청으로 이번 작업의 실행 범위를 확인한다. 계획에 존재하는 작업이라는 이유만으로 구현이나 배포가 승인된 것으로 취급하지 않는다.
2. [STATUS.md](STATUS.md)와 [POLICY.md](POLICY.md)를 읽는다. 검토 근거가 필요하면 [REVIEW.md](REVIEW.md)의 발견 사항과 반영 추적을 확인한다. 현재 설계·완료 기준은 각 소유 문서를 따르며 반영 전 검토 문구를 새 지침으로 사용하지 않는다.
3. [WORK_ITEMS.md](WORK_ITEMS.md)에서 구조 대상 작업과 의존성을 확인하고, [PLAN.md](PLAN.md)의 관련 절만 읽는다. `APP_ISSUES.md`의 보류 항목은 별도 지시 없이 현재 작업에 추가하지 않는다.
4. 실제 작업 디렉터리의 Git 상태, 변경분, 코드·테스트를 확인한다. 문서에 기록된 마지막 기준 버전과 달라졌으면 차이를 먼저 정리한다.
5. 필요한 계약·코드·소유 문서를 확인한다. 이번 구현에 기존 하네스·스킬을 작업 절차로 적용하지 않는다. 해당 파일은 핵심 계약 보존과 최소화 검토를 위해 읽는다.
6. 작업 범위·완료 조건을 확인한 뒤 실행하고, 검증 근거와 상태를 함께 갱신한다.

## 기록과 갱신

- 작업 상태의 원본은 `WORK_ITEMS.md`다. `STATUS.md`는 현재 위치와 다음 행동만 요약하고 전체 작업표를 복제하지 않는다.
- 구현 전에는 변경 범위와 완료 조건을, 의미 있는 변경 후에는 결정과 결과를 기록한다. 도구 호출마다 진행 기록을 추가하지 않는다.
- 검증은 소스 버전·변경 식별값·환경·명령·결과를 연결한다. 수행하지 않은 검사는 수행하지 않았다고 표시한다.
- 세션 종료·중단 시 다음 세션이 이어갈 수 있도록 `STATUS.md`와 관련 작업 항목을 갱신한다.
- 원시 로그, 프롬프트 원문, 비밀정보, 운영·사용자 데이터는 저장하지 않는다.

## 기존 문서와의 관계

사용자가 루트의 별도 경로와 지속적인 진행 기록을 요청했으므로 이 프로젝트는 기존의 진행 문서 금지 규칙에 대한 명시적 예외다. 이 디렉터리는 **목표 설계와 이행 상태**를 소유하며, 이미 구현된 플랫폼 계약을 대체한 것으로 취급하지 않는다.

구현된 계약은 해당 소유 문서에 반영하고 여기서는 연결한다. 장기적인 아키텍처 결정은 루트 [adr/](../adr/)에 기록한다. 계획만으로 기존 ADR을 폐기하거나 현재 런타임 동작이 바뀌었다고 표시하지 않는다.

| 현재 구현을 확인할 대상               | 소유 문서                                                        |
| ------------------------------------- | ---------------------------------------------------------------- |
| 앱 등록·권한·런처                     | [App Platform](../docs/domains/app-platform/README.md)           |
| 기존 Workbench·Codex 실행·복구 저장소 | [Codex Console](../docs/apps/codex-console/README.md)            |
| 하네스와 검사                         | [Vibe Coding Harness](../docs/agents/vibe-coding-harness.md)     |
| 회사·사용자·그룹·앱 접근              | [ADR 0012](../adr/0012-company-app-access-without-workspaces.md) |
| 설치와 실행 절차                      | [INSTALL.md](../INSTALL.md)                                      |

루트 `AGENTS.md`에 이 디렉터리를 연결했고 Web/API scoped 계약을 해당 기존 서비스에 한정했다. 실제 native 지침 선택과 결과의 평가는 [VALIDATION.md](VALIDATION.md)에서 별도로 추적한다. 링크 추가만으로 모든 세션이 새 정책으로 실행되었다고 주장하지 않는다.

2026-10-07 사용자 지시로 로컬 구현을 재개했다. 중단 시점은 [RESTART_CHECKPOINT.md](RESTART_CHECKPOINT.md), 일회성 비공개 원격 백업은 [EMERGENCY_BACKUP.md](EMERGENCY_BACKUP.md), 현재 위치는 [STATUS.md](STATUS.md)가 소유한다.
