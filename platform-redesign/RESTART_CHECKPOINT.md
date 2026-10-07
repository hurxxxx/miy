# 서버 재시작 전 중단 지점

2026-10-07 UTC. 사용자가 서버 재시작을 위해 현재 하던 작업만 마무리하고 일시중단하도록 지시했다. 새 구현·검사를 시작하지 않았고 실행 중이던 검사와 정확히 소유한 임시 자원만 정리했다. **사용자의 재개 지시 전까지 작업을 시작하지 않는다.** 서버 재시작은 사용자가 수행하며 이 작업에서 서비스를 재시작하지 않았다.

## 보존한 작업

- 체크아웃: /home/user/projects/miy/dev, dev, HEAD 449d1417afbf6a2eb978c1465c765e26ef43c5dc. 관련 변경은 커밋하지 않은 상태로 보존했다. 원격 Git·공유 DB migration/GRANT·운영 queue·서비스·배포는 변경하지 않았다.
- 범위: 구조 완성에 필요한 변경과 치명적 문제만 구현한다. 앱별 비필수 개선은 [APP_ISSUES.md](APP_ISSUES.md)에 보류한다. Workbench는 단일 사용자·native Codex·SQLite를 유지하며 다중 사용자는 후속이다.
- 기존 하네스·skills는 작업 절차로 적용하지 않는다. 핵심 서버 권한·등록·실행·AI 승인·생성 계약·비밀정보 보호는 유지한다. 사용자 요청에 따라 독립 경로를 멀티에이전트로 분담한다.

## 검증을 마친 checkpoint

| 범위                          | 확인한 결과                                                     | 한계                                                                  |
| ----------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------------- |
| Vite import 복구·Planner 조립 | 포털/공식 build 통과, 최종 browser 26/26·실제 dev 22, owner 106 | 이후 PMS source가 바뀌었으므로 이 산출물이 현재 PMS를 검증하지는 않음 |
| Core Docs 구형 작업 변환      | actual PG 238, 입력 107/최종 읽기 116, 독립 리뷰                | 실제 backlog·구버전 drain·운영 적용 없음                              |
| Recording legacy 발행·retry   | actual PG 68, 입력 164/owner 6, 독립 리뷰                       | 기본 Canvas 유지; remote/broker 전체 보장 아님                        |

세부 근거와 초기 실패는 [VALIDATION.md](VALIDATION.md)가 소유한다. 공식 UI 아홉 개는 두 build와 대표 browser까지 검증했다.

## PMS: 구현·예약 검사 완료, 부모 통합은 미실행

실제 업무 구현 93개와 순수 shell navigation 한 개, 기존 업무 spec 52개와 fixture를 새 소유자로 옮겼다. PMS 도움말 HTML은 suite public의 원본 한 개가 소유한다. pinned Vite adapter 하나가 도움말과 기존 Recording SW 두 고정 파일만 제공한다. 기존 narrow PMS API, cold shim 19개, 교차 앱 연결과 전체 번역은 유지한다.

- 원본 body/export·HTML·전체 catalog **96개 동등성**, 소비자 본문 다섯 개 동일.
- whole suite 917/platform 124/root cross 44/New York 318개 통과. 이 실행은 최종 test-only helper 경로 정정 전이며 제품 bytes는 같다.
- 이미 실행 중이던 마지막 runner에서 최종 PMS 318/root shell 27·타입 5종·구조 검사를 완료했다. alias/두 자산 81개, 실제 graph 1,524 modules/2,878 dependencies 통과. lint 오류 없음·기존 warning 여섯 개.
- 최종 test helper는 packages/official-suite-web/tests/pms-fixtures.ts와 pms-i18n.ts다. 번역 scanner 예외를 만들지 않았다.
- 입력 **275개**와 부모 metadata 다섯 개가 현재와 같고, 이동된 이전 경로 **54개**는 없다. 최종 runner 종료·소유 Vite 임시 자원 정리 완료.
- 근거: .runtime/pms-module-extraction/{REPORT.md,inputs.json,final-input-check.json,cleanup.json}. canonical PMS manifest 실제 검사 68개와 source 경로 다섯 개는 갱신했고 generator --check도 통과했다.

**PMS 독립 비교·새 production build 두 개·새 대표 browser·dist HTML/SW 검증은 재개 후 필수다.** 전체 source 소유는 PMS까지 열 개지만 최종 통합 완료로 집계하지 않는다. Files·Video Chat은 미착수 잔여다.

## Recording managed: 중간 초안으로 동결

source command와 Core publication 두 표, 실제 principal provenance와 고정 네 단계 worker 분기를 구현 중이다. 기본 HTTP/legacy Canvas와 기존 안전성 slice 여섯 파일은 그대로다. managed 원격 TransientError는 원 실행 token을 보존하며 자동 retry command나 provider 재호출을 만들지 않는다. 실제 공식 profile·publisher는 활성화하지 않았다.

- 실제 PG pipeline **25 PASS**, captured 175개 전후 동일. 이후 설치된 Celery public signature를 검사하는 test 한 개만 추가하여 pure wire **11 PASS**; 제품 bytes는 같다.
- Data의 첫 schema/역할 준비 두 개는 통과했다. 이어 authority **23 PASS/1 fixture FAIL**이었다. Data는 drain-thread에서 transition의 필수 artifact 인자가 빠져 SQL에 도달하지 못한 원인으로 분류했다. 수정·재실행은 시작하지 않았으며 **해결 완료로 표시하지 않는다**.
- 근거: .runtime/official-recording-managed/{INTERFACE.md,REPORT.md,inputs.json,input-check.json}, .runtime/official-recording-managed-db/와 두 owned PG evidence 디렉터리.
- native 독립 리뷰·새 schema에서 기존 legacy 통합·추가 role/concurrent preparation 검증은 미완료다.
- 새 worker artifact의 managed 존재조회는 새 schema와 명시적 source principal 준비가 필요하다. old schema/old restricted principal 완전 호환을 주장하지 않는다. 공유 DB에는 새 migration을 적용하지 않았으며 실행·권한 전환은 별도 운영 경계다.

소유 임시 PostgreSQL 컨테이너와 검사 프로세스는 정리했다. 운영 서비스나 다른 사용자의 프로세스를 중단하지 않았다.

## 재개 순서

1. 사용자 재개 지시와 Git 변경분을 확인한다. root/경로별 계약, 이 문서와 현재 owner 보고서를 읽고 파일 hash 차이부터 정리한다. 이전 agent/session/process ID가 살아 있다고 가정하지 않는다.
2. PMS 부모 독립 검토→선택 입력 capture→두 production build→대표 browser와 고정 자산 bytes를 마무리한다. 현재 Planner dist를 새 PMS 결과로 재사용하지 않는다.
3. Recording authority fixture를 최소 정정하고 해당 실패를 재검증한다. 새 protocol의 legacy 영향 통합·역할 경계·독립 리뷰를 닫은 뒤 새 고정 checkpoint를 기록한다.
4. 이후 Files·Video Chat, source-only wiring/consumer·partition·Files 추출 역방향 쓰기·broker/Beat·auth/ACL/audit/runtime 분리를 이어간다. Core Files 추출의 결과 소유 방식은 읽기 조사만 했고 새 구현이나 설계 결정은 하지 않았다.
5. Workbench native 실행의 상위 syscall filter 제약과 전체 자연어 흐름은 기존 잔여다. 보안 정책·shared DB·서비스를 임의 변경하지 않는다. 앱 세부 이슈를 자동 착수하거나 구조 잔여를 앱 이슈로 옮겨 완료 처리하지 않는다.
