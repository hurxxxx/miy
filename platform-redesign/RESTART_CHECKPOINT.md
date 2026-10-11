# 작업 중단과 재개 체크포인트

**재개 기록:** 2026-10-10 필수 범위 확정 후 사용자가 “계획대로 진행”을 지시해 구현을 재개했다. 아래 중단 상태·패킷·검증 자료는 보존 시점 기록이다. 현재 실행은 [STATUS.md](STATUS.md)의 필수 범위를 따르며 미채택 고도화는 보류한다.

**2026-10-10 최신 범위:** [필수 구조 변경](PLAN.md#이번-범위)만 이번에 수행하고 [후속 고도화](FOLLOW_UP_ENHANCEMENTS.md)는 별도 지시까지 보류한다. 아래 미게시 후보는 보존 자료이며 모두 통합할 의무가 아니다. C2/Files 저장 확장은 실제 분리 장애·치명적 결함의 최소 해결에 필요한 부분만 선택한다. 필수 구조 완료에 고급 UX·모니터링·부하/반복 평가를 다시 추가하지 않는다.

2026-10-10 UTC. 사용자가 중간 진행 점검을 위해 현재 작업만 마무리한 뒤 중단하도록 지시했다. 현재 실행하던 C2 검증과 소유 임시 자원 정리를 완료하고 수정본·문서를 보존한다. **사용자의 재개 지시 전 추가 구현·검증·게시·배포를 시작하지 않는다.**

이후 사용자 요청으로 검증 계획만 [최종 통합 검증 방식](VALIDATION.md#2026-10-10-검증-일괄-수행-원칙)으로 조정했다. 재개 후 아래 후보와 남은 구조 구현을 최대한 통합한 뒤 필요한 검토·준비·실행·정리를 한 번에 진행한다. 후보별 기능 검증·게시·배포를 반복하지 않고 필수 리뷰·CI와 승인된 반영 확인까지 연속 진행한다. 기존 통과 자료와 CI 검사를 로컬에서 중복 실행하지 않는다. 후보별 최종 검토 대기는 유지하되 준비 결과나 검증 도구마다 별도의 독립 리뷰를 자동 추가하지 않는다. 이번 요청은 구현 재개가 아니다.

## 현재 반영과 보존 범위

- Dev `c40e70910ccc3b148b8c00e504be2122a346d0c8`, main/prod `9cbf9c5c9e623433e23daab767fffb29748adc76`, tree `64e456b4cacf2af723d47f88a1fa35f7030607e3`다. PR96/MR103·필수264/432·full265/433·MR81·guarded 운영 전달을 마쳤다. 운영 API/worker/Beat는 immutable image `389d1e67…`와 C1 head `wb_checked_cas_20261009`로 정상이며 이전 image/env/백업을 보존한다. [전달 기록](PUBLICATION_CHECKPOINT.md)이 정확 범위를 소유한다.
- Docker 실제 저장소 `/var/lib/miy-docker-data`와 canonical `/var/lib/docker` bind로 이전·복구했다. 마지막 확인 root117GiB/약40GiB 여유, 기존 컨테이너/볼륨 보존이다. OS reboot는 미검증이며 미확인 orphan220개는 보존한다.
- 중단 시 Main의 중간 점검 문서9개를 미커밋으로 보존했고, 이후 검증 계획 조정도 문서 변경으로만 남긴다. SDK·C2 제품 후보는 아래 별도 worktree에 보존하며 main/prod에 새로 통합하지 않았다. 모든 작업은 구조 필수 변경/치명적 경계에 한정한다. 앱별 상세 기능·다중 사용자는 보류한다.

## 미게시 후보와 정확한 재개 지점

| 후보                         | 보존 위치·근거                                                                                                                                                                                                                      | 재개 후 필요한 단계                                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Workbench SDK/UI/cache       | `/tmp/miy-sdk-integration-ux-20261009`; source manifest SHA `0b57fcb3303583501a6e4f79cd0a749a12aff08256d3e2100ade7a6ee52490b0`; UI peer `d0abe93c…`, cache peer `1502c583…`                                                         | 정상 controller 결과 증거 인수, feature 리뷰/게시/병합, 별도 Workbench 릴리스·SQLite 백업·서비스 전환·실제 로그인/화면 |
| C2 단일 journal35/checkpoint | `/tmp/miy-c2-closed-journal-20261009`; constraint-catalog correction source `25f14b24cafdb9091485bd574d588aead9e5f297e847a2b2764b7c3a4b1174ba`; actual96 receipt `4c29ad144f47b2e96140448ffe47a03b490e17c18b2604f5e6f5dfc981b58d2a` | 최종 adapter와 정확 source 조립·실제 SQL/native/C1 통합·리뷰/릴리스                                                    |
| C2 trusted adapter           | `/tmp/miy-c2-trusted-adapter-20261009`; 합성56 PASS, 기본 owned isolation verifier 미설정은 fail-closed                                                                                                                             | 최종 동결 source 독립 리뷰·실제 통합·native fullRSS/ABI boundary·room final retirement/C3; 현재 활성화하지 않음        |

SDK 원 Task/thread의 계획·구현2턴과 read-only3번째 인수를 보존한다. 원 Task에4번째 턴을 붙이지 않는다. 두 starter의 수동 carrier native protocol 증거를 정상 carrier 성공으로 바꾸지 않는다.

최신 정상 controller 단일 claim은 결과 파일 O_EXCL 충돌로 최종 결과가 저장되지 않아 **HOLD**다. Ephemeral 실행 결과·정확 모델 제출 횟수(최대1)를 추정하지 않는다. 기존 before-claim negative `e153bb04…`, manager start `4fdf299f…`/stop `d36e92d7…`, Root post-safety `49985ec5aad7626c148e1cf1b15505b7f07b05fa93c248239b4f4fd761a0670f`를 보존한다. 소유3unit 파일/프로세스/cgroup/port 정리와 Source/Git/current3607/전체 cache/native 불변은 별도 실제 확인했다. 해당 claim을 재실행하거나 결과를 재구성하지 않는다. 결과 파일 선예약의 최소 보완 패킷은 동결까지만 마무리하며 새 준비·모델·서비스 실행은 재개 이후다.

## 이번 중단에서 동결을 마친 패킷

- 정상 Workbench 결과 선예약 helper: `.runtime/structural-next-delivery/SDK-normal-controller-receipt-reservation-author/frozen-author-packet.json`, SHA `b941d2425a94c2df0cb2066fb08949bedfd0426ca72d364bb1d95693112ae4e8`, inputs `8084da8be937aef27000692908ff5382e1298382985eb8242c5b962e43102bcb`, 합성12 PASS. Source0b57과 기존 route/execute/정책/예산은 보존했고 새 path/ports28461·28462 및 결과 FD 선확보만 수정했다. **최종 독립 리뷰 대기**, 새로운 준비/실제 모델/서비스 실행0이다.
- C2 adapter: `/tmp/miy-c2-trusted-adapter-20261009/.runtime/C2-trusted-adapter-author/frozen-author-packet.json`, SHA `83b0276a7b41936c64dac3aa7bcf8091d6f46b393f299c70d350eb2930c25b3c`, source20 manifest `02dd1f400efc76881988ba3a35caa42d6b319e430fbaea47e9a9c37536f4877a`, 합성56 PASS1.33초·Ruff/format/diff/source guards다. Handoff는 같은 owner의 `handoff.md`(`b8ce9d9beabb20bb7538533356568990c45aa55e408c7d25200950091d79a0ec`)가 소유한다. Unknown checkpoint COMMIT/stale capture는 원본/F/S·GC lease를 보존한다. 이미 checkpoint handoff로 lease가 풀린 후 발생한 native 변경의 final room retirement는 활성화 전 필수 잔여다. 최종 독립 리뷰·실제 통합·전체 RSS/ABI·C1/C3는 미완료다.

모든 담당 에이전트가 동결과 인계를 마치고 중단했다. 진행 중인 이번 작업의 검증·모델·임시 서비스는 없다. 기존 개발/운영 서비스는 유지한다. 현재 중단 기록과 후보는 미커밋이며 새 게시/배포를 수행하지 않았다.

## 검증 종료와 재개 순서

C2 source25f14의 actual96은509.356302초에 setup/call/teardown 각각96 PASS, 오류/skip0, source guards·owned cluster/container/sidecar 정리 PASS다. 이전 source3908/629fc 실패와 catalog 진단을 그대로 보존한다. 이 결과는 adapter56이나 전체 runtime의 인수 증거가 아니다.

재개 시 현재 Git와 필요한 보존 후보부터 확인한다. 종료한 agent/session/process가 살아 있다고 가정하지 않는다. 필수 구조를 먼저 구현·통합한 뒤 Workbench 정상 실행과 UI·DB 대표 앱 흐름, 공식 묶음 전환의 필요한 검사를 한 최종 흐름에 모은다. C2 adapter 전체 연결/인수는 기본 재개 단계에서 제외하고 조건부 필수 부분만 채택한다. 미채택 후보의 독립 리뷰·실제 통합은 후속으로 남긴다. 실제 서비스 전환의 권한·구형 writer 정리·데이터 보존·복구와 필수 릴리스 리뷰/CI는 유지한다. Platform deployment가 Workbench deployment를 대신하지 않으며 현재 새 factory/roles·공식 cutover는 계속 비활성이다.

## 이전 중단 기록 — 2026-10-07 서버 재시작

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
