# 시범 개선 기록

## 현재 체크포인트: 운영자 지원 단일 소유자 흐름 인수 완료

Workbench의 같은 Task에서 자연어 요청→계획10/v2→명시 승인으로 관리번호 정규화의 왕복 결함을 수정했다. 관찰자가 앱 사업 코드를 편집하지 않았다. Source `ee3afef71110c62380c0e2121592f37c0c0fedd4`의 focused API2/UI1 검사와 자동 refresh `aad26730`을 확인했다. 앱 MR117의 pipeline308에서 개인 앱 CI job482가5.1028초, 필수 리뷰 job483이80.023491초에 통과했고 `de88e30df2785d6c7fdaf9502cf803deb14c59f6`로 병합됐다. Stable parent `f3332b7f`/feat4의 실제 배포가 성공했고 검증된 dev merge `de88e30d`의 영속 소스 인계·runtime을 보존했다. 이는 안정 개발 설치의 실행 갱신 증거이며 일반 직원 권한·전체 업무 기능·공개 운영 인수로 확대하지 않는다.

Stable feat4 포털의 실제 정상 로그인·앱 목록에서 초기 empty list와 임시 미리보기의 `WB-SYN-001` 부재를 확인했다. 별도 가상 항목 `WB-SYN-DEV-001`을 정상 UI로 생성201하고 reload 뒤 유지되는 것도 확인했다. 정리 완료 후 같은 feat4 포털 iframe이 정상이고 해당 stable 항목은 유지·임시 항목은 부재이며 anonymous `/api/equipment`401임을 실제 브라우저로 확인했다. 보호된 `fresh-stable-after-cleanup.json`이 이 결과를 소유한다. 임시 데이터가 stable에 합쳐졌다는 증거로 쓰지 않는다.

정리 operation `4c82c50f-66bf-4f9a-8e2f-4ea8debc6679`은 Core ready/`source_handoff_complete`와 busy=false에도 `workspace_busy`/unknown으로 남았었다. 정확한 기존 증거로 같은 operation을 waiting으로 복구하는 조회와 사용자가 명시한 계속하기의 정리를 구분한 수정이 직접12사례와 MR121 source `5e6da1cbd606261c006a0c165d11abc6dba29825`의 필수 pipeline309/job484를90.360737초에 통과했다. `76ece913b565efa4513ef52f13204a5285d57899`로 병합한 뒤 Workbench r21은 clean source `5e6da1cb`/digest `6d2989…`로 배포됐으며 현재 역할 active·template-r4 유지·schema9·18Task/11agent/1project/1workspace 보존을 확인했다. 이번 전환의 두 역할 stop15초 timeout는 DEF-005에 남긴다.

정상 UI의 작업 상태 확인으로 원 unknown이 waiting(v51)이 됐고, 같은 **계속 확인·반영**으로09:48:05에 workspace cleaned(v55)/원 operation succeeded가 됐다. 새 MR 병합·배포를 반복하지 않았다. Polling의 helper lock 경합은 추정이며 확정하지 않는다. 관찰자의45초 응답 대기는 잡히지 않았지만 전체 browser context의 integrate200와 server receipt cleaned를 확인했으며 제품 timeout으로 추정하지 않는다.

별도의 읽기 전용 독립 확인1회는 `fresh-cleanup-independent-receipt.json`에서38개 boolean TRUE·unavailable0으로 통과했다. 임시 PostgreSQL DB/두 role, app/ingress container·network, runtime·scratch와 SDK 세 native unit·unit file·descriptor가 모두 부재였다. Core installation archived/origin·슬롯 해제/진행 중 작업 부재, 소유 worktree·local branch·remote-tracking branch·remote branch 부재를 확인했고 cleaned journal은 보존했다. Stable DB/role/app/ingress는 유지·실행 중이며 exact `de88e30d` 인계와 runtime은 보존했다. 앞선 stable 브라우저 확인과 이 독립 자원 확인을 함께 근거로 IMP-028을 마감한다.

이번 **운영자 지원 단일 소유자 범위의 필수 인수 잔여는 없다**. 의미·벡터 검색의 실제 앱 호출, 일반 직원 계정/다른 정상 계정의 권한, 다중 사용자와 완전 자가 온보딩·배포 및 공개 운영은 미검증 또는 후속 범위다. DEF-001과 기존 보류 사항을 완료로 바꾸지 않는다. 현재 원본은 [작업 환경 배포 기록](../WORKBENCH_WORKSPACES_DEPLOYMENT.md)이며 아래 이전 실패·시점별 이력은 그대로 유지한다.

### 현재까지의 단계별 이력

필수 리뷰 pipeline303/job471 통과 후 MR116이 `dev`의 `e6ff64a8`로 병합됐고 Workbench session/management r20 배포와 public health200을 확인했다. Template service는 r4를 유지했고 개발 Core·SDK/native bundle·proxy·개인 앱 CI의 코드/산출물은 이 복구 릴리스에서 변경하지 않았다. 원 작업 환경·브랜치·Task/native thread·계획·실패 이력을 보존했다. 원 환경 중지 operation의 명시 계속하기로 SDK와 두 proxy가 inactive·PID/ControlPID0·cgroup 부재·Result success가 된 것을 확인한 뒤, 운영자가 같은 환경의 고정 backend 예산만64→256으로 갱신했다. 당시 앱24파일과 상위 worktree `.git`, source/token/port를 보존했고 갱신 자체는 새 실행을 시작하지 않았다.

기존 UI의 환경 재개로 ready가 된 뒤 원 Task와 native thread의 구현을 ask 권한으로 다시 승인했다. 새 controller generation/turn에서 정상 완료해 idle/review가 됐고, 실제 native JS4/Python4 검사와 Vite build가 통과했다. 같은 turn에서 반복한 검사를 중복 합산하거나 관찰자가 다시 수행하지 않았으며, 자동 로컬 checkpoint `17b8453f`와 clean Git을 확인했다. 관찰자의 앱 사업 코드 쓰기는0이다. 아래 IMP-021~024의 필수 복구 범위는 반영·확인됐다. 위임이 없던 auto_refresh의 `app_delivery_unconfigured` 실패를 보존하며 편집 환경/admission ready와 앱 실행 성공을 구분한다.

08:09:52 UTC에 정상 UI와 native 도구로 같은 source의 최초 등록이 성공했다. 등록 계획8을 UI에서 계획9로 저장해 변경 없는 검사 결과를 재사용했으며, 검토 중 만료된 최초5분 허용은 같은 operation에서 정상 Core 소유자 UI로 갱신하고 두 번째 허용의 만료 전에 완료했다. Owner-preview enabled/선언된 권한3개 승인과 운영자의 최소 delivery 위임·stable target 연결 및 설정 재시작을 마쳤다. 재시작 전 r20 session/management도15초 timeout였고, PID/ControlPID0·cgroup 부재와18Task/11agent/1project/1workspace 보존 확인 후 정상 reset-failed/start로 복구해 Core/WB public200을 확인했다. 이 종료 결함은 DEF-005에 그대로 남긴다.

첫 미리보기는 source/runtime `17b8453f`로 feat0에서 ready였다. Core build `4ee85fff` 성공 뒤 첫 배포는 새 앱 데이터 cluster의 기본 PUBLIC CONNECT 때문에 `data_cluster_public_connect`로 올바르게 차단됐다. 운영자가 DATA 소유 계약과 정확한 전용 container/port19412·기본 DB/role만 있는 상태를 확인하고 해당 cluster의 postgres/template1에만 PUBLIC CONNECT/TEMPORARY를 회수했다. 기존 플랫폼 DB는 변경하지 않았다. Preflight 성공 뒤 사용자의 명시적 새 refresh `73084579`에서 배포 `6298ccfe`가 성공했다. 실제 브라우저에서 가상 항목1개 생성/읽기, 별개의 수정 PUT200·172ms, reload 후 저장값 유지·검색과 anonymous API401을 확인했다. Workbench reload에서도 같은 workspace/branch/source가 유지됐다. UI의 개발에 반영을 확인한 뒤 CI와 앱 MR 리뷰를 진행했다. 이 단계에서는 dev stable runtime 갱신·작업 환경/브랜치 정리가 미완료였으며 이후 결과는 위 현재 체크포인트와 아래 후속 기록을 따른다. DEF-001의 수동 운영자 인계는 해결하지 않았다. 이전 시범의 완료 판정을 이 새 흐름에 적용하지 않는다.

개인 앱 CI 진단 보완은 source `6f4344`의 pipeline305/job474 필수 리뷰에서 MERGE_READY를 확인하고 MR118의 `13a3b`로 병합했으며 runner4에 immutable r5를 설치했다. 이는 실제 앱 CI 통과와 다르다. 재시도 job475는 `git_fetch`/`trusted_command_failed`로 실패했고, 08:39:49 Workhorse의 프로젝트 web 경로 `/lumejs/mty/info/refs`301을 확인했다. 고정 repository 설정에서 canonical clone URL의 `.git`이 빠져 redirect 금지와 충돌한 원인이다. 운영자가 idle 상태에서 프로젝트 `http_url_to_repo`의 `.git` URL로만 보정했으며 보안·소스 identity 계약은 변경하지 않았다.

같은 pipeline304/source `17b8453f`의 새 재시도 job476은 `get_sources`를 통과한 뒤 `unsupported_job_stage`로 중단됐다. 고정 Runner19.4.1/revision `3c39fceb`의 [custom executor 코드](https://gitlab.com/gitlab-org/gitlab-runner/-/raw/3c39fceb/executors/custom/custom.go)가 `step_script`를 `build_script` argv로 변환하는 것을 확인했다. 두 이름만 같은 고정 wrapper로 연결하는 수정은 source `c7dfab`의 pipeline306/job477 필수 리뷰48.374초 통과 후 MR119의 `a1de5598`로 병합하고 runner4의 r6에 반영했으며 소유 브랜치를 정리했다. 제공 script 해석·일반 `step_*` 허용·after/cache/artifact 허용은 하지 않는다. 실제 job478은 callback·source 취득을 통과한 뒤 validation/`trusted_command_failed`로5.15초에 실패했다. 이 실패와 당시 CI 미완료 기록은 보존한다.

운영자의 별도 진단에서는 UID993의 설치된 모듈 import·Docker inspect·실제 source `17b8453f`의 CI prebuild/snapshot을 확인했지만, 이것은 실제 CI 성공 증거가 아니다. `umask 077`에서 UID993 소유 export root가0700이면 고정 container UID1000이 읽을 수 없는 필수 권한 결함을 확인했다. Immutable snapshot 검증 후 공개 export root만0755로 바꾸는 공통 builder 후보의 직접6사례는 통과했으며, 승인된 immutable image에서 UID1000 소유 소스를 다른 UID1001이 읽는 검사도 포함했다. 바깥 work/context/Docker config의0700 보호는 유지한다. 같은 UID1000으로 수행한 기존 Core 미리보기 성공과 모순되지 않는다. Job478의 정확한 내부 실패 원인은 당시 확정하지 않았으며, 이후 실제 재확인 결과를 별도로 기록한다.

권한 수정 source `c6bb00f260191d467be5515c1c7be4bf7271d542`는 MR120의 필수 pipeline307/job479에서49.299516초에 통과했고 `5fa1b324a54660df5b239cc795d186cfa2b4b45d`로 병합했다. Runner4의 immutable r7을 활성화하고 수정용 local/remote branch·worktree를 정리했다. 같은 pipeline304/source `17b8453f`의 실제 재시도 job480은5.181424초에 SUCCESS로 완료해 `app-8565f140` 검증 artifact `sha256:a0e77ab6cf0bd5180a1f1d97058995078fbb5184e65695463364049254f5b560`을 확인했다. 별도 operator probe를 이 CI 결과로 갈음하지 않는다. 당시 앱 MR117의 필수 리뷰 재시도 job481은 이후 관리번호 정규화 후 길이 검사 누락으로 MERGE_BLOCKED가 됐다. 정규화 전에는64자 이하인 `ß`40개가 정규화 후80자가 되어 저장됐지만 조회·수정에서422로 거절되는 왕복 결함이었다.

이 필수 P2는 같은 Workbench Task의 native turn `01a12a41-48e9-7043-9f1b-086bbf591c6e`에서 서버/UI의 정규화 후 길이 검사를 맞추고 좁은 경계 검사로 보완했다. SDK나 사업 기능을 확장하거나 관찰자가 코드를 고치지 않았다. 최초 browser 응답 대기는 timeout였으나 messages POST200과 계획10 생성을 확인한 뒤 중복 요청하지 않았다. 후속 pipeline308의 필수 검사·리뷰와 정상 MR 병합·stable 배포는 위 현재 체크포인트의 실제 결과이며, 초기 job481 차단은 보존한다. 새 반영 intent `977`의 `integration_changed` 실패도 정상 새 intent `4c82c50f`로 진행했으며 수동 병합·metadata 강제 수정으로 우회하지 않았다. 첫 metadata 관측의 eventual consistency는 원인 후보일 뿐 확정하지 않는다.

## 현재 필수 보완과 실제 복구

| ID | 실제 관측과 영향 | 최소 보완·확인 범위 | 상태 |
| --- | --- | --- | --- |
| IMP-021 | 앱 하위 `.git`은 첫 구현 명령 시점에 생긴 UID1000/0755·entry0 디렉터리. Helper/broker의 `.git` 전면 거부로 환경 조회503과 실행 연결 오류 발생. 정상 Git 저장소를 초기화한 증거는 없음 | Exact executor 소유·쓰기 권한 제한·빈 일반 root 디렉터리만 native 임시 보호 대상으로 허용. 파일/symlink/하위 경로/실제 metadata 거부 유지. 초기 exact inode 제거·interrupt 복구와 이후 r20 적용/동일 세션 구현 완료를 구분하며 상위 Git metadata 보존 | resolved/제한된 호환 계약 반영·실제 세션 완료 |
| IMP-022 | 초기 SDK cgroup은21프로세스/57스레드, pids.max64·max event7, Codex12스레드였다. 초기 OS 관측은 다른 PID·syscall의 실패 원인까지 입증하지 않음 | Backend256/proxy64·CPU100%·메모리1GiB·격리 유지. 고유 직접23사례와 명시 stopped-only 갱신 후 실제 TasksMax256/inactive/PID0 확인. 같은 source/token/port 보존→UI resume ready→native JS4/Python4/build 성공 | resolved/실제 예산 갱신과 구현 검사 확인 |
| IMP-023 | 실제 승인 POST503과 원 pending을 보존. 준비 상태 장애가 기존 요청 거부/취소·turn 중단까지 막던 경계 | 기존 cached RPC의 정확한 Task/소스/workspace/세대/thread/turn/요청 binding을 검증한 거부·취소·중단만 readiness와 분리. 신규 승인·입력·실행은 기존 검사 유지. 고유 직접23사례 통과 후 r20에 반영; 실제 원 Task는 새로운 명시 승인·세대/turn으로 완료했고 old pending 재전송0. 준비 실패 상태의 각 negative action을 live에서 별도 재검사한 증거는 없음 | resolved/제어 계약·배포 범위, live negative 개별 검사는 한계 |
| IMP-024 | 첫 turn 없는 failed Task의 idle root가 busy에 포함되지만 stop 대상에서 건너뛰어 원 중지가 waiting에 머묾 | 실행 전 실패의 exact idle root만 구분하고 pending/lease/하위 agent/불확실 실행 차단 유지. 같은 operation의 첫 계속하기는 busy를 유지, 두 번째 명시 계속하기는 succeeded/stopped. 실제 SDK+두 proxy inactive/PID0/cgroup 부재 확인, 상태·lease 직접 수정0 | resolved/원 중지 operation의 실제 완료 |
| IMP-025 | 실제 앱 CI job475의 Git fetch는 web URL301로 실패. Canonical URL 보정 후 job476은 source 취득 성공 뒤 pinned Runner의 `build_script` stage를 지원하지 않아 중단 | Canonical HTTPS clone URL과 redirect 금지 유지. 두 exact stage만 동일 고정 wrapper·identity gate에 연결한 MR119 필수 리뷰 통과·r6 반영. Job480과 후속482 실제 앱 CI 통과를 확인하고 초기 실패 보존 | resolved/URL·stage 호환 및 실제 앱 CI 확인 |
| IMP-026 | Private umask로 만든 UID993/0700 export root를 고정 container UID1000이 읽을 수 없는 공통 builder 결함. Actual job478 validation 실패와의 원인 일치 여부는 당시 미확정 | Immutable snapshot 검증 뒤 공개 export root만0755. Work/context/Docker config0700 유지. 직접6사례·다른 UID 읽기 검사→MR120 필수 리뷰 통과·r7 반영→job480/482 실제 CI 통과. 별도 operator probe와 구분 | resolved/설치·실제 개인 앱 CI 통과 |
| IMP-027 | Job481의 필수 리뷰가 관리번호 정규화 후 길이와 저장값 조회/수정422 왕복 결함을 발견해 병합 차단 | 같은 native Task의 자연어 계획10/v2·ask 승인 뒤 서버/UI의 정규화 후 길이 검사만 보완. Focused API2/UI1 통과·새 source 자동 refresh 성공→pipeline308의482/483 통과→MR117 정상 병합·feat4 stable 실행 갱신 | resolved/필수 입력 무결성과 정상 개발 반영 범위 |
| IMP-028 | Stable 배포/영속 소스 인계 완료 뒤 원 정리 operation이 busy=false에도 `workspace_busy`/unknown에 머묾 | 정확한 기존 증거·실행 부재 확인→직접12사례/MR121 필수 리뷰/r21 배포→정상 UI의 동일 operation 조회/명시 계속하기로 cleaned/succeeded. 새 MR·배포 재실행0. Stable iframe/data 유지와 독립38개 실제 자원 확인 통과, helper lock 원인 미확정 | resolved/원 operation 복구·임시 자원 정리·stable 보존 확인, 필수 인수 마감 |

IMP-021의 실제 복구 원본은 보호된 `fresh-empty-git-recovery.json`이다. 07:22:51의 exact empty-directory 제거와 이후 interrupt200/current interrupted를 확인했으며, 중간 `ui_interrupt=pending` 필드는 당시 기록으로 남아 있다. 고정 [Codex 0.160.1 bwrap 코드](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/linux-sandbox/src/bwrap.rs#L1220-L1281)는 없는 `.git` 같은 보호 경로에 읽기 전용 빈 mount target을 만들고, [명령 종료 후 정리 코드](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/linux-sandbox/src/linux_run_main.rs#L583-L632)는 해당 target을 정리한다. 이는 코드와 생성 시각이 뒷받침하는 원인 경로이며, 해당 inode를 만든 PID/syscall과 잔존 이유는 직접 수집하지 않았다.

IMP-023의 초기 실제 승인 실패는 `fresh-approval-submission-observation.json`, 당시 후보의 직접 검사/한계는 `fresh-restrictive-controls-fix.receipt.json`이 소유한다. 이후 실제 적용·중지·자원 갱신·같은 세션 완료는 `fresh-r20-original-stop.json`, `sdk-budget-256-active.json`, `fresh-r20-implementation-resume.json`, `fresh-r20-task-completion-structure.json`, `fresh-r20-native-checks.json`에 따로 기록했다. 자원 갱신 영수증의 `resume_and_app_test=pending`은 갱신 시점의 기록이며 이후 세션 완료를 덮어쓰지 않는다. 원문 명령·업무 프롬프트·인증 정보는 기록하지 않는다. 기존 전체 검사 반복이나 필수 gate 완화는 이 문서로 승인하지 않으며, 현재 새 앱 인수에 기존 앱 이관이나 앱별 기능 확장을 추가하지 않는다.

등록 도중의 `workspace_busy`는 native 도구가 같은 checkpoint를 명시적으로 재확인해 회복했으며 실제 등록 Task는 idle/review가 됐다. 한 차례 남은 busy 경고와 최종 성공 상태를 구분한다. Helper의 전역 lock 경합은 원인 후보일 뿐, 당시 helper 실패를 직접 수집한 증거가 없으므로 확정하지 않는다. 등록 성공과 허용 갱신은 `fresh-registration-receipt.json`/`fresh-registration-renewed.json`, owner 설정은 `fresh-owner-preview-enabled.json`, r20 설정 재시작의 종료 관측은 `fresh-app-config-stop.json`이 소유한다. 이 사용성 관측은 DEF-007로 보류하며 새 수정이나 반복 검사 범위를 만들지 않는다.

미리보기의 첫 수정 UI는 일반 실패를 표시했으나, 첫 HTTP 결과는 수집하지 않았다. 같은 쓰기를 결과 미확인 상태에서 반복하지 않고 새 GET200으로 값이 반영된 것을 확인해 결과를 해소했다. 이후 별개의 명시 수정 PUT200과 reload 지속성 확인을 앞선 응답 미확인 이력과 구분한다. 소유 에이전트의 읽기 검토에서 PUT 계약 불일치는 확인되지 않았으므로 추가 플랫폼 수정 없이 앱의 실패 응답/저장 결과 안내를 DEF-008로 보류한다. 앱별 세부 기능 검사를 확장하거나 이 대표 흐름을 일반 직원·전체 권한·dev 실행 완료 증거로 쓰지 않는다.

## 2026-10-11 관리형 작업 환경 재검증

아래 표와 리뷰 경과는 이전 배포 라운드의 시점별 기록이다. 당시 대기 상태를 유지하며, 현재 상태는 위 체크포인트와 [작업 환경 배포 기록](../WORKBENCH_WORKSPACES_DEPLOYMENT.md)을 따른다.

| ID | 실제 영향 | 보완과 확인 | 상태 |
| --- | --- | --- | --- |
| IMP-016 | 정상 SDK 경로의 `@openai`를 미해결 템플릿으로 오인해 환경 준비 실패 | 실제 vendor 경로를 허용하고 미해결 placeholder·명령 삽입 검사는 유지 | 실제 native 준비 통과 |
| IMP-017 | user systemd의 proxy와 executor가 서로 다른 network namespace에 있어 연결 실패 | 고정 system manager broker와 rootless executor 사용. namespace·native initialize·중지/재개/정리 실제 확인 | 해결 |
| IMP-018 | 원격 Git에서도 운영자의 HTTPS 인증 설정을 차단해 첫 환경 생성 실패 | 고정 원격 작업만 운영자 인증 설정 사용. 일반 소스 검사 격리는 유지. 실제 원격 조회 성공 | 새 릴리스·같은 환경 재개 인수 대기 |
| IMP-019 | worktree 생성 전 실패한 환경을 재개할 수 없음 | known failed이고 브랜치·worktree·기록된 source identity가 없는 경우만 같은 UUID로 재개. 기존 브랜치 충돌은 계속 차단 | 직접 회귀 통과, 실제 재개 대기 |
| IMP-020 | 개인 앱 검증용 shell runner가 임의 MR 스크립트를 호스트에서 실행할 위험 | 신뢰된 고정 custom executor가 exact source 취득·격리 검증만 수행. job script는 실행하지 않음 | 설치·local 경계 통과, 실제 MR job 대기 |

필수 원격 리뷰 job457은 추가로 검색 권한 UI 소비자 누락, 기능 MR에 없는 release 검사 대기, 정리한 origin의 재사용 충돌, 변경 전 waiting 작업의 UI 잠금을 발견해 병합을 차단했다. 영향 검사와 이력을 보존하는 실제 PostgreSQL lifecycle 검사로 보완했으며 실제 배포는 대기 중이다. 후속 job458~461의 실행 공정성·부분 CI 기록·불확실 결과·동시 상태 갱신·인증된 CI 입력·정확한 병합 증거·archived 조회 문제와 수정/검사 근거는 [배포 기록](../WORKBENCH_WORKSPACES_DEPLOYMENT.md)이 소유한다. 필수 리뷰 성공 전에는 새 후보를 완료/배포로 표시하지 않는다.

새 구조도 최초 등록 뒤 앱별 위임과 안정 개발 target을 운영자가 연결하는 단계가 남는다. DEF-001을 완료로 바꾸지 않는다. 이번 검증의 운영자 지원과 비개발자 자연어 개발 경험을 따로 기록한다.

실제 시범을 막거나 안전 계약을 깨는 문제의 최소 수정과 후속 개선을 분리한다. 같은 HEAD의 fresh build/deploy·실제 대표 업무1회는 passed_with_unverified_secondary_account/43TRUE·정상 별도 계정2NULL이고 실제 새 PG12개 읽기 전용 확인을 마쳤다. 공통 패키징/첫 화면 장애는 해결했으며 초기 실패를 보존한다. 운영자 private grant/target 인계 공백과 unbound host 계획의 기밀 격리 한계는 해결로 표시하지 않는다.

## 상태와 최소 수정 원칙

`observed → preparing → applied → rechecking → resolved`로 기록한다. 적용/재확인 결과가 없으면 `resolved`로 바꾸지 않는다. 이번 범위를 넘는 편의·기능 확장은 `deferred`다.

기존 공개 등록·실행·템플릿 진입점과 pinned native 계약을 우선 사용한다. 한 번의 관측만을 위해 새 planner/retry engine·일반 lifecycle framework·전체 skills 주입을 만들지 않는다. 권한/설치 입장·격리·원본 일치·검증 gate는 유지한다.

## 필수 보완의 결과와 범위

| ID | 증거 | 사용자 영향 | 최소 처리 | 재확인 | 상태 |
| --- | --- | --- | --- | --- | --- |
| IMP-001 | OBS-001 roots0·OBS-006 빈 root·OBS-016 basic 소스 준비200 | 소스 준비와 실제 장비 기능 개발을 구분해야 함 | 지정 root/basic 소스 준비 완료, 호스트 전체 경로 허용 없음 | 실제 UI 준비200 확인. native 개발 환경/작업 연결은 IMP-002에서 별도 인수 | resolved |
| IMP-002 | OBS-001 executor configured0·OBS-024 SDK active·OBS-041 실제 native 사업 쓰기 | Task가 있더라도 격리된 실제 앱 개발을 수행할 환경이 필요 | Native 연결/정확 앱 소스의 읽기와 명시 승인 뒤 실제 파일 쓰기 확인. 최초 bind 장애는 IMP-009로 분리 | 개발/로컬 저장까지 실행기 연결 범위 해결. 실제 업무·권한·데이터 지속성 인수는 별도 | resolved |
| IMP-003 | OBS-001 대상 차이·OBS-051 matching receipt·OBS-062/066 fresh proof·OBS-067 actual flow | 다른 등록 원본/환경에서 앱을 만들거나 잘못된 설치로 연결할 위험 | 전용 development Core·owner 동의·동일 source/설치 manifest/digest/target·현재 검증/immutable image pair·실제 iframe 연결 | Same-source gen4 저장16flags/필수5gate·대표 업무1회/새PG 확인. 대상 연결 범위 해결이며 별도 정상 계정/일반 직원 권한은 미검증 | resolved/대상 연결 범위 |
| IMP-004 | OBS-002 순환 장애·초기fixture 실패·OBS-013 후보53PASS·OBS-048 실제 checkpoint 성공 | 정상 개발 후 기록과 등록을 이어갈 수 없음 | 현재 소유자 로컬 기록을 최초 등록 허용과 분리. DB 소스/작업·세대/구현 승인·HEAD CAS·`.git` readonly 유지, 등록/배포 grant·300초 TTL·owner 동의 변경0 | 실제 context/checkpoint/context completed/success TRUE·앱 clean HEAD로 로컬 저장 범위 해결. 이후 별도 owner 동의/등록 receipt와 새 배포를 확인했으며 로컬 저장이 그 권한을 대신한 것은 아님 | resolved |
| IMP-005 | OBS-005 required 실패·후보 UI27/API8 PASS·OBS-042/043 실제 입력 probe | 업무 설명만으로 앱 개발 시작 불가가 실제 재현됨 | 업무명/요구만 필수·안전한 ID/로컬 repo 기본값·허용 root 선택·advanced override. Server 원본/HTTPS/root/dirty HEAD/origin/등록 guard 불변 | 실제 advanced 입력0→project/Task200·자동 ID 유효·source form 기본값 valid. Probe source prepare/messages0·주 앱과 분리. 입력 UX 범위 해결, 원격/백업/전체 E2E 주장은 없음 | resolved |
| IMP-006 | OBS-011 host skill 자동 참조·OBS-013 직접 영향·OBS-034 exact source context·OBS-072 host 한계 | 이전 개발 절차가 다시 유입되거나 맥락 차단을 물리적 격리로 오인할 위험 | App-only host discovery/hooks/MCP/snapshot 차단·짧은 authority context·명시적 요청 서버 거부. 일반 Core Task/등록 권한 불변 | 시범 반영 후 실제 bounded source context/native 흐름 확인. 모든 자동 skill 부재의 독립 proof는 없으며 host 파일 읽기 격리는 DEF-002 별도, 추가 검사 요구하지 않음 | applied/맥락 범위 |
| IMP-007 | OBS-020 안내 빈틈·OBS-022 문서 검사·OBS-036 정확 반영/native key 지원 확인 | 생성된 앱에서 플랫폼 기능의 사용 방법/안전 계약을 알아내기 어려움 | Self-contained 공개 문서/로컬 pointer와 현재 소스 addendum. 필요한 data/AI·owner·버전/unknown·배포 계약만 설명, host 비밀/전체 skills 제공 없음 | 검증 문서 정확 반영/native 모델의 현재 key 계약 확인. 공개 안내 접근 범위 해결, 데이터 대표 업무는 별도 OBS-067/AI 제품 기능 전체 검사는 없음 | resolved |
| IMP-008 | OBS-023 번호 중복·초기fixture FAIL·OBS-035 후보9PASS·OBS-067 실제 중복409/version 불변 | 같은 번호를 등록할 때 목록 조회만으로 중복을 막을 수 없음 | Optional key 조건부 생성/조회, source user/설치/컬렉션의 현재 행만 고유. 기존 PK·RLS·CAS·schema/checksum 유지·전사/영구 이력 보장 없음 | 실제 등록201/중복409/version 불변·동시 대여200+409/승자1명·archive/restore 이력 유지 확인. 삭제 후 재생성/조직 전체 번호/정상 다른 사용자 검사는 별도 | resolved/현재 owner 행 범위 |
| IMP-009 | OBS-024 SDK first start bind 거부·OBS-041 같은 경계의 native 실제 쓰기 | 준비된 실행기에서도 native 앱 작업을 시작할 수 없음 | 공식 systemd 계약/독립 검토 근거로 해당 backend만 ProtectHome=tmpfs+정확 source bind. Proxy/공개 service·cap0/NNP/private network·`.git` readonly 유지 | Backend/socket active 이후 실제 bound Task 읽기/쓰기를 확인해 시작/bind 범위 해결. 최초 실패 보존, 앱 runtime/업무 기능 인수는 별도 | resolved |
| IMP-010 | OBS-027 계획 단절 baseline1FAIL→21PASS·OBS-031 확정 조건 반영·OBS-034 실제 context 성공 | 이미 답한 업무 질문/최종 계획을 새 개발 Task에서 잃고 다시 결정할 위험 | 이전 같은app/project native 최종 계획1개만16KiB 참고. 승인 복사0·다른앱/current/later/manual/raw history 제외 | 실제 native context prior plan present/reference only TRUE·execution authorized FALSE, 확정 조건 재사용 확인. 참고 전달 범위 해결이며 새 구현 승인·업무 완료와 별개 | resolved |
| IMP-011 | OBS-030 exit127/Python 적응·OBS-039 한국어 CLI 안내 정확 반영 | 제공되지 않는 host 명령을 반복하면 제한된 앱 환경을 이해하기 어려움 | Immutable SDK/package 변경 없이 현재 제공 native 명령·읽기 방법 공개 안내 | 공개 안내 반영/존재 확인, 실제 기존 starter test2PASS 관측. 안내 접근 범위만 해결, 모든 명령/업무 기능 성공 주장은 없음 | resolved |
| IMP-012 | OBS-040 UI 후보6PASS·OBS-052 disabled DOM·OBS-054 새 계획 Task200 | 등록 뒤 미리보기 배포가 준비되지 않았을 때 다음 단계를 알기 어려움 | 미연결 disabled 계획/소유자 사용 동의→관리자 요청 안내, stale/unavailable 단정0·production/configured TRUE 동작 보존 | Disabled DOM/설정 동의·운영자 연결→Task/배포/대표 업무까지 확인. 다음 행동 안내만 해결했고 private grant/target 자가 인계는 DEF-001 핵심 공백 | resolved/안내 범위 |
| IMP-013 | OBS-044 timezone/PID 초기 실패·OBS-057 실제37/10/Vite·OBS-055 고정 Core build 성공 | 제공 SDK의 시간/프로세스 경계에 맞지 않으면 후보 검사를 진행할 수 없음 | Native AI의 stdlib UTC+9/test concurrency1 직접 수정, SDK/한도/권한·Root 사업 코드 변경0 | 후보 직접 명령과 실제 Core 고정 build 성공으로 검사 호환성 범위 해결. Artifact/runtime UI 문제는 IMP-014로 분리, 업무 성공 아님 | resolved |
| IMP-014 | OBS-055 succeeded/metadataready·OBS-056 iframe500·OBS-059 후보50PASS/초기3FAIL→3PASS·OBS-062/063 actual fresh runtime | 정상 설치로 표시돼도 실제 앱 첫 화면을 사용할 수 없음 | Artifact 내부0755/private parent0700·declared exact UI path fingerprint/200HTML bounded cold gate. 과거 receipt의원identity/health-only 한계 보존 | 같은 HEAD gen4·UID1000 public artifact 읽기/rootHTTP200·actual iframe SDK/API200 이후 대표 업무1회 확인. 최초 실패/old health-only 한계 보존·전체 기능/계정권한을 보장하지 않음 | resolved/첫 화면 범위 |
| IMP-015 | 동일 앱14SHA와 유효한 native 후보 결과·OBS-060 정책2PASS/Workbench reload·OBS-062 로컬 검사 반복0 | 바뀌지 않은 앱을 반복 검사하면 필수 구조 인수에 불필요한 시간이 듦 | 같은 입력/revision의 결과만 재사용하고 필수 Core build/review/배포 gate는 유지. 짧은 앱 작업 맥락/Workbench owner 문서만 보완 | 직접 정책2PASS/19deselected·2.34초/lint·pilot reload 이후 같은 HEAD 로컬 체크 반복 없이 fresh Core build/deploy 수행. 업무 gate를 생략한 증거로 쓰지 않음 | applied |

문서 담당자는 설정·서비스를 조회/적용하지 않았다. IMP-004는 Root가 실제 발견한 필수 흐름 장애이며, 다른 준비/UX 항목과 구분한다. 실제 적용과 결과는 담당 운영자·소유 에이전트가 전달한 뒤 기록한다. 소유 에이전트의 검사 통과만으로 시범 환경 반영/브라우저 성공을 표시하지 않는다.

IMP-004 초기118PASS/28FAIL은 pinned native 도구 스키마의 필수 `type: function` 누락이었다. 해당 필드 최소 수정 후 subset53PASS를 확인했지만 당시 후보 동결은 실제 반영 근거가 아니었다. 이후 OBS-048에서 실제 checkpoint를 확인했다. 초기 baseline1FAIL/118PASS·28FAIL은 보존하고 새 후보 재실행 proof로 바꾸지 않는다. IMP-005도 최초 운영자 보조 OBS-009와 이후 별도 실제 입력 probe OBS-042/043을 구분한다.

## 관측 도구의 중단과 재개

OBS-064/065의 첫 두 업무 인수 시도는 로그인 입력의 DOM 대기/유일 선택과 generic iframe 선택에서 중단됐다. 두 번째는 정상 WB/Core 로그인200 뒤 다른 공식 widget frame을 고른 오류가 의심된다. 최종 전달에서 앞선 관측 중단은 총3회/모두 업무POST0·ledger 불변이었다. 기존 실패를 보존하고 별도 실제 업무1회만43TRUE/secondary2NULL로 기록한다. 관측 실패를 앱 critical로 분류하거나 반복 업무 검사 PASS로 더하지 않으며 일반 관측/재시도 하네스를 새로 만들지 않는다.

## 후속 개선 한 건의 기록 형식

| 항목 | 필요한 기록 |
| --- | --- |
| 개선 ID/관련 OBS | 실제 관측과 연결 |
| 증거 | 어떤 행동/도구 결과/적용 결과가 확인됐는지. 원문 로그 대신 공개 코드·boolean·범위 |
| 사용자 영향 | 사용자가 무엇을 못 했거나 잘못 이해했는지 |
| 분류 | 필수 환경 준비 / 구조·안전 critical / 앱 최소 기능 결함 / 후속 편의·기능 |
| 최소 수정 | 기존 소유 진입점으로 해결할 수 있는 가장 작은 변경과 대상 |
| 적용 | 실제 변경 여부·범위·시각. 제안과 실제 적용을 구분 |
| 재확인 | 원 실패와 직접 영향 경계의 결과. 성공한 전체 검사를 무조건 반복하지 않음 |
| 상태/한계 | observed/preparing/applied/rechecking/resolved/deferred와 미관측 한계 |

## 보류 개선

현재 시범은 **운영자가 개발 대상/실행기와 앱별 private grant를 준비하는 흐름**이다. 실제 owner UI 사용 동의 뒤 운영자 수동 허용 인계201/보호 설정을 준비했다. 이것은 완전 비개발자 전과정 자가 서비스의 핵심 공백이며 단순 편의 개선으로 취급하거나 해결로 표시하지 않는다. Root의 별도 설계 기록과 현재 시범 인수를 구분한다.

| ID | 근거·영향 | 후속 최소 방향 | 상태 |
| --- | --- | --- | --- |
| DEF-001 | OBS-040/053: 사용자 UI 동의 뒤 앱마다 운영자의 보호된 grant 인계/target 준비가 필요하며 전과정 자가 서비스 UI 미구현. 기존 등록 앱을 다른 저장소에서 가져오면 worktree manifest의 저장소/디렉터리가 바뀌어 이전 위임의 소스 정책과 달라짐 | 현재 소유자/앱/환경/session의 동의·서버 보호 허용 연결을 별도 설계. 기존 앱은 정상 소스 정의 승인/갱신 후 새 위임을 발급해야 관리형 미리보기를 사용할 수 있음. 최초 등록은 생성 전용이며 SDK 호환/import 성공을 승인으로 취급하지 않음. 토큰 복사 UI/등록 grant 자동 승격 금지 | deferred/자가 인계 설계 미완료, 기존 앱은 운영자 인계 필요 |
| DEF-002 | OBS-072: unbound host read-only 계획은 single-owner trusted client이며 host private 파일 읽기 물리 차단 없음 | 다중 사용자 전 소스 준비/계획 단계의 별도 격리를 설계. Bound SDK의 blank home/private network 증거를 host 단계로 확대하지 않음. 현재 즉시 Core gate/SDK 누출 결함 발견은 아님 | deferred/다중 사용자 전 필수 설계 |
| DEF-003 | OBS-071: 의도된5분 만료 후 Connect로 정상 복구하지만 자동 갱신/입력 상태 유지는 미구현 | 기존 TTL/서버 입장 계약을 유지하는 세션 UX 개선만 별도 검토. 안전 TTL 확대/현재SDK byte/app 사업 코드 수정으로 우회하지 않음 | deferred/편의 UX |
| DEF-004 | MR114 후속 기록은 job467까지 필수 리뷰 실패11회와 각각의 최소 수정을 집계함. Lifecycle/import/SDK 경계의 서로 다른 누락이 여러 리뷰 라운드에서 뒤늦게 발견돼 전달 시간이 길어짐 | 실제 인수 이후 실패 근거로 제한된 통합 리뷰 항목과 실제 계약을 반영한 fixture 개선안을 검토. 시간 절감과 실패 탐지 범위를 비교한 뒤 별도 승인으로 적용하며, 현재 필수 리뷰/gate를 생략하거나 변경된 경계를 이전 검사로 갈음하지 않음. 앱 사업 기능 확장과 분리 | deferred/제안만 기록, 하네스·gate 변경 미승인 |
| DEF-005 | 이전 r4/r18/r19의15초 stop timeout 실패에 이어 r20 session/management도 실제 Result timeout. PID/ControlPID0·cgroup 부재와18Task/11agent/1project/1workspace 보존 확인 후 정상 reset-failed/start, Core/WB public200. 원 작업 환경/thread 유지 | 실제 반복 종료 실패의 원인과 상태 안내를 후속 검토. 프로세스 부재·정상 재시작을 정상 종료 성공으로 바꾸지 않으며 별도 SDK3unit 중지 성공도 Workbench 종료 해결로 확대하지 않음. 종료 시간 확대·강제 종료·새 lifecycle 절차·gate 완화를 이 기록으로 승인하지 않음 | deferred/r20에서도 실제 종료 timeout 반복, 복구·기록 보존 확인 |
| DEF-006 | 첫 turn0·실행 root/runtime generation 미기록 상태의 원 Task를 r19에서 재시도했으나 `codex_request_failed`. 실패 method/원문 오류 미수집으로 원인 미확정. 새 개발 세션의 계획 완료 이후 r20에서 그 비어 있지 않은 동일 세션/thread 재연결·구현 완료. 최초 실패 Task·브랜치·이력 보존 및 계획/코드/데이터 손실0 | 최초 빈 thread의 재개 UX를 후속 검토. 원인을 cold resume로 확정하지 않으며 원문 로그 없이 정확한 공개 RPC method/오류 코드를 확인한 뒤 최소 수정 판단. 비어 있지 않은 세션 재개 성공은 최초 빈 thread 실패의 원인이나 해결 증거가 아님 | deferred/최초 빈 thread 원인 미확정, 별도 동일 세션 재개 완료 |
| DEF-007 | 등록 검토 중 최초5분 허용이 만료됐으나 같은 operation의 정상 소유자 UI 재허용으로 등록 성공. Native checkpoint의 일시 busy도 명시 재확인으로 회복했지만 idle/review 뒤 경고가 한 번 남음. 당시 helper lock 경합의 직접 실패 증거는 없음 | 현재 허용 만료·진행 상태·과거 경고를 구분하는 안내를 후속 검토. 정확한 원인 관측 없이 lock 결함으로 단정하거나 자동 재실행·TTL 확대·권한 승격·기록 삭제로 우회하지 않음. 등록 성공을 미리보기/dev 실행 성공으로 표시하지 않음 | deferred/사용성 관측, 실제 등록 성공·원인 일부 미확정 |
| DEF-008 | 실제 미리보기 첫 수정 UI가 일반 실패를 표시했지만 첫 HTTP 결과는 미수집. 결과 미확인 상태에서 쓰기를 반복하지 않고 새 GET200으로 반영을 확인했다. 별개의 후속 수정 PUT200·172ms/reload 지속성은 직접 관측. 읽기 검토에서 PUT 계약 불일치 없음 | 앱이 응답 실패와 저장 결과 미확인을 구분하고 재조회로 현재 결과를 안내하는 UX를 앱별로 후속 검토. HTTP 원인이 확정되지 않았으므로 플랫폼 결함으로 단정하거나 자동 쓰기 재시도로 우회하지 않음. 사업 코드/플랫폼 계약 수정과 세부 기능 검사 확대는 이번 단계에서 수행하지 않음 | deferred/앱 응답 안내, 저장·수정 대표 흐름은 실제 확인 |
| DEF-009 | 새 반영 intent `977`은 `integration_changed`로 거절됐고 정상 새 intent `4c82c50f`에서 필수 리뷰·MR 병합·stable 실행까지 진행. 첫 MR head metadata의 eventual consistency는 추정이며 확정하지 않음 | 변경된 관측과 기존 intent의 거절을 구분하는 안내만 후속 검토. 정확한 metadata 불일치 원인 없이 자동 병합/재실행·manual merge·현재 head 강제 채택으로 우회하지 않음. Source 고정과 최신 필수 gate를 유지하며 원 실패 보존 | deferred/관측·intent 안내, 실제 정상 반영 확인 |
| DEF-010 | 정리 완료 후 operation은 succeeded지만 역사적 failure_code `workspace_busy`가 남았고 현재 상단 경고는 사라짐. Workbench에는 임시 preview 링크가 숨겨지고 MR 링크만 남아 stable 앱으로 바로 이동하는 링크가 없음. App catalog의 정상 portal URL은 유효 | 과거 실패와 현재 완료를 구분하는 표시 및 정리 후 stable 앱 이동 안내를 후속 검토. 기존 이력을 지우거나 정상 복구를 다시 실행하지 않으며 필수 code 수정으로 확대하지 않음 | deferred/완료 표시·앱 이동 편의, 원 복구 완료 |

DEF-004와 DEF-001의 기존 앱 이관 추가 근거는 각각 보호된 후속 요약 `review-feedback-followup.json`과 `existing-source-handoff-followup.json`이다. 원문 trace·인증 정보·앱 데이터는 이 문서에 옮기지 않는다. 기존 앱에 대한 실제 승인 갱신/위임 발급은 수행하지 않았고, 현재 새 앱 인수의 범위를 늘리지 않는다. DEF-005 역시 이전 버전의 실제 운영 관측과 새 버전의 미검증 동작을 구분한 기록이다.

DEF-005의 r18 직접 관측 원본은 보호된 `workbench-r19-stop-observation.json`이다. 두 서비스의 `Result=timeout`, `ActiveState=failed`를 실패 이력으로 유지한다. 이후 r19의 배포 기록과 r20의 `fresh-app-config-stop.json`에서도 실제 종료 timeout를 확인했다. 프로세스·cgroup 부재와 기록 보존을 확인한 후의 정상 배포/설정 재시작 복구는 이 종료 결함의 해결 근거가 아니다.

대리급 사용자는 업무/자연어/조작 역할 시뮬레이션이고 실제 정상 Core 계정은 기존 administrator였다. 가상 직원은 앱 업무 데이터로 employee 인증 증거가 아니다. 일반 직원의 자가 등록과 다른 정상 계정의 same-install403은 미검증이며 정상 테스트 신원으로 일반 rollout 전에 별도 확인한다. 새 계정/권한/메일 변경0이며 이 한계를 기능 고도화나 이번 시범의 추가 반복 검사로 바꾸지 않는다.

최종 원 브라우저 읽기 확인은 대여2+반납2=4개의 committed 이력을 확인했고 물리적 prepared5 중 동시 패배1은 UI에 노출되지 않았다. 기존 안전 gate를 유지한 운영자 지원 단일 소유자 시범의 필수 인수 잔여는 없다. 공용 소스/typed tool·manifest/등록 원본·소유 generator·일반 데이터/첫 UI 계약의 최소 보완과 앱별 기능 고도화를 구분하며, 전체 기존 절차/skills를 종합 로드하지 않는다. 시범 자원/준비 기록 cleanup이나 일반 공개 배포를 수행한 것으로 쓰지 않는다.

그 외 실제 관측한 편의 문제만 추가한다. 기본적으로 다음 확장도 별도 요청 대상이며 진행 중/완료로 표시하지 않는다.

- 소모품 수량·구매/폐기·감가상각·바코드·알림·결재·대량 가져오기.
- 상세 대시보드·탐색 UX·추가 명령 템플릿·반복 표현/모델 평가.
- 실제 직원 계정·부서별 정책·전사 공개와 다중 사용자 Workbench.

앱별 개선은 이 시범의 관측에 연결하고, 플랫폼 후속 고도화는 [기존 분리 문서](../FOLLOW_UP_ENHANCEMENTS.md)의 소유 범위를 유지한다. 준비된 최소 앱의 대표 흐름을 방해하지 않는 고도화는 이번 인수의 선행조건으로 추가하지 않는다.
