# Workbench 작업 환경 배포·실제 인수

기준 2026-10-11. 사용자 배포·테스트·이전 코드 정리 승인으로 진행한다. 현재 상태는 `passed_with_scoped_limits`다. 운영자 지원 단일 소유자의 새 작업→자연어 구현→미리보기→필수 리뷰→dev 병합·실행→임시 환경 정리 대표 흐름을 실제로 확인했다. 로컬 검사와 실제 설치/브라우저/모델/검색/MR 근거를 구분한다.

## 최신 인수 상태 — 2026-10-11 최종 확인

| 항목 | 실제 상태 |
| --- | --- |
| HTTPS 슬롯 | feat0~feat4 →19520~19524 정확한 연결 확인 완료 |
| Workbench | r21 실제 적용, 원래 세션·agent·project 보존 및 같은 정리 intent 복구 완료 |
| Core development | archive migration 적용, 앱 데이터/배포 설정 적용 및 health200 |
| 장비·비품 앱 | Workbench 자연어 계획·ASK 실행·등록 및 리뷰 지적 수정 완료, source ee3afef |
| 임시 preview | feat0 실제 배포·소스 일치, 가짜 장비 생성/수정/reload 보존/검색·비인증401 확인 |
| dev 통합 | 실제 MR117/pipeline308의 개인 앱 검사482·필수 리뷰483 통과, dev de88e30에 병합 |
| 영속 dev 실행·정리 | feat4 실행·데이터 보존, 임시 DB/계정·SDK·컨테이너·네트워크·worktree·local/remote branch의 정확한 제거 확인 완료 |
| 보류 | 의미 검색(임베딩 서버 없음), 일반 직원 계정 검증, 운영자 연결 UX·종료 지연·응답 불확실 UX |

이하 기록은 발견·수정·검증의 시점별 이력이며, 이전 릴리스·실패 상태는 최신 완료 여부와 구분한다.

## 초기 완료 기록

- 기존 개발 DB의 private custom-format 백업과 archive 목록 검증 완료. dev supervisor 정상 재시작 후 Core Alembic `independent_workspaces_20261011`과 공개 health200 확인.
- 새 설정 키 2개 반영 및 순서 보정 후 환경 계약 PASS. 전용 앱 데이터 PG18을 `miy-dev-app-data`/loopback19412에 설치하고 private DSN·키 설정. 검색 flag는 false.
- 기존 시범 WB/Core/Delivery/Portal·SDK와 앱 ingress/runtime을 중지했다. exact PID/cgroup 소멸 후 이전 앱 코드를 Git bundle 검증과 private archive로 보관했다. PG/SQLite/등록 이력은 유지한다. 기존 설치는 정상 관리자 API로 disabled 처리했고 접근 정책·데이터를 보존했다. [이전 시범 상태](workbench-equipment-pilot/STATUS.md)가 보관 근거를 소유한다.
- SDK v3 immutable `/opt/miy` 설치 검증 완료. 실제 OS/Qdrant의 owned synthetic 자원 준비·검색 프로토콜·소유 경계·정리 6항목 PASS; 임베딩/실제 사용자 앱 검색 성공과 다르다.

## 실제 실행에서 발견한 보완

1. helper의 placeholder 검사가 정상 native vendor 경로 `@openai`를 거부했다. 실제 입력 회귀를 추가하고 미해결 placeholder/명령 삽입 차단을 유지하며 수정했다.
2. user systemd의 `JoinsNamespaceOf`가 실제로 SDK executor와 proxy를 같은 네트워크 공간에 넣지 못했다. 실제 namespace identity·native initialize 실패를 확인했다. 고정 system manager broker로 보완했고 실제 prepare/native initialize/동일 network namespace/stop/resume/cleanup을 통과했다. 기존 private network·UID·capability 경계를 유지한다.

## 주소와 검색 준비

사용자가 HTTPS 앞단을 직접 관리한다. **19520~19524**를 개발 앱 확인용 포트로 예약했다(예약 시 모두 비어 있음). `feat0.1punicorn.com`~`feat4.1punicorn.com`을 순서대로 연결했고, 앞단은 `10.173.130.111`로 접근한다. loopback 앱 listener를 유지하는 고정 systemd socket proxy를 설치했다. 사용자 feat2 수정 후 5개 모두 TLS 검증을 켠 실제 HTTPS/정확 포트 응답 확인을 통과했다. 검사 listener는 종료했으며 아직 앱 없는 슬롯의 502는 준비 상태다. 작업 미리보기와 dev 반영 후 앱 실행은 서로 다른 slot을 사용한다. URL을 임의로 발급하거나 TLS 검사를 끄지 않는다.

사용자는 임베딩 서버가 아직 없다고 확인했다. 의미 검색은 비활성/미검증으로 유지하고 앱 생성·SDK 실행·미리보기·PG 데이터·dev 통합/정리를 우선 인수한다. 현재 검색 선언은 승인 embedding 프로파일과 묶여 있어 keyword-only 임시 우회도 하지 않는다.

## 실제 배포·첫 브라우저 인수

- Workbench SQLite online backup 후 세 역할을 멈추고 migration을 적용했다. `current`와 `template-current`를 `20261011-managed-workspaces-r4`로 전환했다. session/management/templates 모두 active, 공개 health200. 이전 task15/agent8/project0 행 수가 보존됐다. 릴리스는 아직 커밋 전 소스 스냅샷으로 빌드됐으며 원격 통합 완료와 구분한다.
- dev 조회 전용 키·API origin과 등록 audience를 연결했다. 실제 dev 관리자 로그인 → 포털 Workbench 링크 → SSO 진입 → 새 프로젝트 생성 성공. 앱 ID `app-8565f140`, project `53e09a59-e41c-4112-b355-93093e2015d5`.
- 자동 workspace `584a1107-b8c1-5aa9-a545-720341f48b6d`가 Git 단계 `git_unavailable`로 실패했다. 고정 원격 작업에도 global 인증 설정을 막던 원인을 수정했고, 운영자 credential 설정을 사용하는 실제 원격 조회가 통과했다. base/source revision은 null이며, 생성 전 known-failure만 같은 UUID로 재개하는 보완과 직접 회귀4 PASS를 완료했다. 새 릴리스 반영과 실제 재개는 남아 있다.
- 개인 앱 CI trusted builder의 실제 격리 빌드와 정리를 통과했다. 임의 MR job script의 host 실행을 막는 custom executor를 별도 UID993으로 설치했다. GitLab runner4 online; 기존 runner2/3은 유지했다. 실제 MR job/pipeline은 아직 미검증이다. 기존 dev에는 신규 CI job이 없어 플랫폼 기능 MR을 먼저 dev에 반영해야 한다. `miy-dev-app-delivery.service`의 고정 consumer도 설치·시작했다.
- Core search flag=false. 사용자 확인대로 embedding 서버가 없으므로 실제 의미 검색은 별도 준비 사항으로 남는다.

## 착수 시 필수 잔여 — 과거 시점 기록

- Git 실패와 같은 UUID 재개 보완, 실제 native 개발 턴 및 최초 등록/명시 위임 연결.
- 전용 개인 앱 CI runner의 실제 MR job/리뷰/병합 인수.
- fresh 장비 앱의 Workbench 자연어 생성·실행·재접속·dev 반영/정리 실제 인수.
- 의미 검색은 승인 endpoint 준비 후 별도 실제 인수. 다른 흐름 성공을 의미 검색 성공으로 표시하지 않는다.

## 원격 리뷰 1차 결과와 필수 보완

플랫폼 기능 MR [!114](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/114), 최초 source `dbf6b86edbb82f27888b922596c8dac4d82d5958`의 pipeline289/job457은 `MERGE_BLOCKED`였다. 성공·병합으로 표시하지 않으며 운영자 수동 gate 우회도 하지 않는다.

1. 검색 권한 소비자 누락: 플랫폼 등록·미리보기·Workbench 검증기와 동의 문구를 5개 권한에 맞췄다. 영향94 PASS, 두 frontend 타입 검사·i18n·lint 통과. 자동 권한 부여는 추가하지 않았다.
2. 기능 MR에서 생성되지 않는 release_validation을 기다리던 문제: 실제 feature CI의 codex_review·personal_app_validation과 모든 비선택 작업 성공을 요구한다. 직접15 PASS. dev→main release gate는 변경하지 않았다.
3. 정리한 슬롯 origin의 고유성 충돌: disabled 개발 설치를 archived로 남기고 활성 origin claim만 원자적으로 반납한다. 기존 UNIQUE와 FK 이력을 유지하며, 실제 PG18에서 다른 앱/새 작업의 같은 슬롯·origin 재사용을 확인했다. 첫 묶음8 PASS/1 FAIL에서 fixture의 세션 만료 ID와 공개404 기대를 수정했고 해당1건만 재확인 PASS했다. 중간 진단 FAIL도 보존한다. archived 이력이 있으면 schema downgrade를 거부한다. 최종 API 생성 및 단일 Alembic head `independent_archive_20261011`도 확인했다.
4. 소스 변경 후 이전 waiting 작업이 UI를 막던 문제: 현재 revision의 대기 작업만 이어가며 새 명시적 행동이 이전 대기 작업을 blocked로 전환한다. 원격 receipt는 보존하고 pending/unknown은 여전히 차단한다. backend2 PASS/UI11 PASS. 첫 UI 실행의 production NODE_ENV 오류는 기존 test 진입점으로 바로잡았으며 제품 결함으로 세지 않는다.

커밋 원본과 일치하는 Workbench r6 후보를 만들었지만 이 네 건의 수정 전 후보이므로 배포하지 않았다. 현재 실제 서비스는 r4이며, 후속 수정·필수 리뷰 성공 후 새 후보로 전환한다.

## 원격 리뷰 2차 결과

수정 source `ca68d5f5e6dfa4d881652397444f98737a99a285`의 pipeline290/job458도 `MERGE_BLOCKED`다. 이 소스로 만든 r7은 clean commit 빌드이지만 배포하지 않았다. 현재 서비스는 계속 r4이며 기존 프로젝트·실패한 작업 환경을 유지한다.

후속 필수 수정은 네 실패 경로다: 불확실 배포의 반복 재조정이 유지보수·검색을 막는 문제, 첫 workspace의 대기/예외가 다음 workspace 정리를 막는 문제, 병합 전 정리 거절이 개발 상태를 바꾸는 문제, 여러 앱 CI에서 부분 성공 후 실패하면 이미지 소유 기록을 잃는 문제. Core 스케줄러·Workbench 상태 전이·CI 소유 기록을 분리해 병렬 보완하고 영향 검사만 재실행한다. 기존 검증 전체를 반복하거나 실패한 리뷰를 우회하지 않는다.

- Workbench 정리 자격을 예약 전에 확인하며, 거절은 상태·버전·작업 기록을 바꾸지 않는다. 같은 화면에서도 정리를 비활성화한다. backend3/UI5 PASS; 부분 정리와 unknown 기록 보존도 확인했다. 최초 UI 실행의 production 환경 오류는 정상 테스트 환경으로 보정한 직접 영향 검사만 다시 실행했다.
- CI는 앱별 성공을 기존 소유 기록에 즉시 fsync/원자적 교체로 저장한다. 전체 실패·시간 초과 후에도 기존 기록을 읽어 정확한 이미지를 정리하며 불확실한 기록은 보존한다. 직접13 PASS와 하위14 검사 PASS. 보호 실행기의 두 스크립트를 함께 담은 `/opt/miy/personal-app-ci-20261011-r2`를 준비했으며 아직 활성화하지 않았다.
- Core 영향 묶음의 첫 실행은27 PASS/1 FAIL/25 setup ERROR였다. 현재 개발 프로필이 유입되어 빈 설정을 전제한 기존 startup 검사가 반복 대기한 원인을 확인했다. 자기 검사만 정상 중단하고 원 결과를 보존했으며, 테스트의 빈 프로필 전제와 private 실행 환경을 명시한 뒤 실패·미완료26건만 재확인해 모두 PASS했다. 기존27건과 합쳐53건의 영향 근거이며 새 한 번의53 PASS 실행으로 바꾸어 쓰지 않는다. 공용 DB·제품 인증·서비스 설정은 변경하지 않았다. 검색 검사는 소비 기회와 DB 회전만 확인했으며 실제 embedding 성공과 다르다.

## 원격 리뷰 3차 결과

source `e7bec8c6c141936485825dc178234af03b2daf54`의 pipeline291/job459는 두 가지 추가 실패 경로로 `MERGE_BLOCKED`다. 같은 clean commit으로 만든 r8과 CI r2 후보는 활성화하지 않았다.

- MR 병합 후 Core 호출 중에는 running을 유지하고, 개발 설치 빌드·배포의 불확실한 결과는 unknown으로 보존했다. 원 요청과 병합 증거를 유지하며 새 요청 생성 대신 기존 요청만 관측한다. 실제 adapter와 격리 Git/SQLite, Core 통신 대역으로 build/deploy 두 경계의 요청 중복 차단·같은 ID 관측·명시 재개2 PASS를 확인했다. 실제 HTTP 인수는 후속 브라우저 흐름에서 확인한다.
- 기존 `source.directory=app`이며 루트에 manifest가 있는 앱의 빌드 호환성을 복원했다. 새 subtree 내부 manifest 형식과 구분하고, 선언된 앱 파일과 검증된 manifest만 추출한다. 양쪽 manifest가 함께 있으면 거절한다. 관련 build 검사51 PASS/5.46초, 실제 임시 Git 객체와 Docker 명령 대역을 사용했으며 실제 Docker 인수로 표시하지 않는다. 보호 CI 실행기에 복제된 builder도 같은 소스로 함께 갱신한다.

전체 검사를 반복하지 않고 각 실패 경로의 직접 영향 검사만 수행한다. 현재 실제 서비스는 계속 r4이며 새 앱 환경 재개·모델 턴·미리보기·MR 인수는 아직 재개하지 않았다.

## 원격 리뷰 4차 결과

source `14c90f3ca9184e28f30ca6ea755f20e58f0ed361`의 pipeline292/job460은 중지 요청과 runner 작업 시작의 경합으로 `MERGE_BLOCKED`다. 같은 clean commit의 r9는 준비만 했으며, 실제 서비스는 계속 r4다. 보호 CI r3도 builder·부분 성공 기록 소스를 같은 commit과 대조하고 실제 runner UID의 격리 import까지 확인했지만 활성화하지 않았다.

이번 필수 수정은 늦은 결과가 새로운 상태를 덮는 세 경계로 한정한다. Core는 대기 작업 취소의 상태·active slot 조건을 실제 UPDATE 시점에 확인한다. 같은 원인에 대한 범위 제한 검토에서 발견한 maintenance의 중지 완료와 후속 정리 요청 경합, Workbench의 불확실 결과 GET과 명시적 재개 경합도 함께 보완했다. 새 기능·스키마·일반화된 실행 프로토콜은 추가하지 않았다.

- Core 대기 취소: 실제 PG row lock 대기를 확인한 build/deploy의 시작·완료 경합4건과 정상 취소·예약 유지·기존 stop/cleanup 경계를 포함해10 PASS/27.92초. 공용 DB를 사용하지 않았고 전용 검사 컨테이너를 정상 정리했다.
- Workbench 관측: 캡처한 unknown 상태와 갱신 시각이 일치할 때만 같은 트랜잭션에서 결과를 저장한다. 늦은 GET이 같은 operation의 running·succeeded·더 새로운 unknown 상태를 덮지 않는3건과 기존 불확실 Core 결과2건을 묶어5 PASS/2.47초. 실제 임시 Git/SQLite와 외부 관측 대역을 사용했으며 서비스·실제 HTTP 인수로 표시하지 않는다.
- Core 중지 완료: stopping·최초 version·installation identity가 일치할 때만 stopped를 저장한다. 이미 승인된 cleanup이 있으면 새 intent·증거·runtime slot을 보존한다. 뒤늦게 확인된 이 경합1건과 정상 stop1건만 추가하여 실제 PG2 PASS/11.06초. 앞선10건을 모두 반복하지 않았으며 Core 전체 고유 사례는11건이다. 두 전용 PG 컨테이너의 정확한 정리도 확인했다.

## 새 앱 인수의 운영자 연결

최초 등록 주소는 안정 dev 앱의 `https://feat4.1punicorn.com`이며, 그 parent installation UUID에 소유자 승인과 WB delegation(`read,sync,build,deploy,workspace`)·Core 안정 delivery target을 연결한다. 토큰은 비공개 운영 설정에만 저장한다. 임시 preview installation에는 이 연결을 만들지 않는다.

안정 target의 정적 `source_root`는 플랫폼 checkout과 관리형 worktree/build/runtime 경로 밖의 별도 예약 경로여야 한다. 설정·최초 등록은 이 경로에 Git 저장소가 있음을 요구하지 않으므로 dummy 저장소를 만들지 않는다. 임시 preview는 trusted profile의 Git 객체를 사용한다. dev 병합 후 Core `/integrate`가 저장한 source handoff만 실제 trusted repository로 안정 source를 전환하며, 그 다음 안정 build/deploy를 요청한다. 예약 경로 자체를 실행 가능한 source 증거로 취급하지 않는다. 이 운영자 연결은 현재 비개발자 완전 셀프서비스의 남은 제약이다.

## 원격 리뷰 5차 결과

source `1bd1df74f53f8146edf590b71a2d7ba1b02f95ab`의 pipeline293/job461은 CI 입력 신뢰 경계·병합 대상 경합·archived 설치 조회 누락으로 `MERGE_BLOCKED`다. r10과 CI r3 후보는 활성화하지 않았으며 실제 서비스는 r4를 유지한다.

필수 보완은 재정의 가능한 CI 커밋 변수를 인증된 GitLab job/MR 정보와 대조하는 것, 리뷰한 dev revision과 실제 병합 결과의 일치를 확인하고 경합 시 배포를 보류하는 것, archived 설치의 owner-preview GET/PATCH를 기존 이용 불가 경계에서 처리하는 것이다. 각 담당자가 분리된 경로에서 수정하고 직접 영향 검사만 수행한다. 이전 검사 전체 재실행과 실패 gate 우회는 하지 않는다.

- archived owner-preview는 기존 경계에서 GET/PATCH 모두404로 거절한다. 실제 PG archived 사례와 정상 설정2 PASS/12.86초, 보관 origin·권한·generation·감사 불변과 검사 컨테이너 정리를 확인했다. 응답 schema나 generated 계약은 바꾸지 않았다.
- Workbench 병합은 직전 target 재확인과 실제 Git 부모·native 합성 tree를 검증한다. 사전 확인 뒤의 경합은 이미 발생한 merge SHA를 unknown으로 보존하고 Core 배포·정리를 보류하며 재병합하지 않는다. lost acknowledgement의 GET은 읽기 관측만 하며 동일 intent의 명시 재개에서 tree 검증을 수행한다. 임시 실제 Git과 원격 통신 대역의 새5건+기존15건을 한 묶음20 PASS/0.28초로 확인했다. 실제 서버 설정 `merge_method=merge`, `squash_option=default_off`와 맞으며 실제 MR 인수는 아직 남아 있다.
- 개인 앱 CI는 source 취득과 실행 직전, 기존 job token으로 고정 GitLab `/job` 및 같은 project의 MR을 읽어 job·pipeline·head/base·브랜치를 대조한다. 검증 기록은 private journal에 결속하며 앱 wrapper에 토큰을 전달하지 않는다. 직접18 PASS/하위34 검사 후, 실제 서버에 없는 optional job.source 요구를 제거하고 해당4건/하위15 검사만 재확인 PASS했다. MR head_pipeline의 native source와 authenticated job pipeline ID로 같은 경계를 증명한다. 새 설정 키·관리자 credential·외부 의존성은 없고 보호 실행기의 runner/CI 두 파일을 함께 갱신해야 한다. 실제 job-token 호출은 새 앱 MR 인수에서 확인한다.
- 통합 검토에서 merge 증거를 확인하는 활성 coroutine은 operation을 running으로 유지하도록 보정했다. 불가역 merge SHA와 불확실한 receipt는 즉시 보존하되, 실패·프로세스 복구 때만 operation이 unknown이 된다. 이 변경으로 영향받은 병합20건과 실제 adapter·SQLite 실행 fence2건을 최종 한 묶음22 PASS/1.12초로 확인했다. 이전20건 실행 기록도 보존하며 검증 건수를 별개 고유 사례로 중복 합산하지 않는다.

## 원격 리뷰 6차 결과

source `d99039f723d9a6844ab34cc74027486d90bd4e73`의 pipeline294/job462는 검색 준비 세대와 재개 관측의 두 상태 관리 경계로 `MERGE_BLOCKED`다. r11과 보호 CI r4 후보는 clean commit에서 준비했고 CI 실행기 UID의 두 모듈 import·시스템 CA 로딩도 확인했으나 활성화하지 않았다. 실제 서비스는 계속 r4다.

검색 리소스 준비 뒤 앱 health/UI가 실패해도 기존 리소스를 보존하면서 다음 변경 배포가 새 검색 세대를 확보할 수 있어야 한다. 또한 SDK/설치 admission만 재개한 관측은 앱 미리보기·runtime revision의 배포 성공 증거가 될 수 없다. 이 두 실패 경로를 최소 수정하고 직접 영향만 확인한다. 검색의 실제 embedding endpoint 부재는 유지하며 기능 성공으로 표시하지 않는다.

- Workbench 재개 관측은 top-level 환경 ready와 미리보기 상태를 분리했다. Core 설치가 있으면 configured, SDK만 있으면 unconfigured이며 이전 runtime revision을 유지한다. 정상 재개와 응답 유실 비교2건 및 실제 성공 배포 관측 대역1건을 기존 직접11건과 묶어14 PASS/0.04초. 실제 HTTP/SDK 실행 성공으로 표시하지 않으며 이전 병합 검사22건은 반복하지 않았다.
- 검색 준비는 installation 행 잠금 아래 검색 binding 이력의 최대 세대+1을 할당하며 배포 성공 generation과 분리했다. 동일 선언·profile의 ready 재사용과 preparing/unknown HOLD를 유지한다. 수정 전 실제 PG·배포 CLI callback 경로의 health 실패 후 변경 재배포1 FAIL을 재현·보존했다. 수정 후 선언/profile 변경·동시 할당·unknown 보존과 직접 기존 경계6 PASS/20.75초, 전용 컨테이너 정리 완료. Docker·검색/임베딩은 대역이며 실제 서비스 인수로 표시하지 않는다. 모델·스키마·공개 API·SDK 변경은 없다.

## 원격 리뷰 7차 결과

source `fdca72253e733a7d38d43f7d43a184ef47643bf2`의 pipeline295/job463은 정리 중 재활성화와 세 가지 복구/원본 보존 경계로 `MERGE_BLOCKED`다. r12는 준비만 했으며 실제 서비스는 r4를 유지한다. 보호 CI r4의9개 소스가 이 commit과도 같음을 확인해 후보를 재사용했다.

필수 보완은 cleanup_pending 설치의 재활성화·새 데이터 입장 차단, SDK 중지 후 유휴 Task 이력 때문에 막히는 정리 재시도, 최초 SDK 시작 응답 유실 뒤 같은 create 관측 복구, 기존 앱 import의 Git 실행 비트 보존이다. Core 권한·Workbench 복구·Git import를 분리하여 최소 수정하며 직접 영향 경계만 확인한다.

- 기존 앱 import는 검증한 Git 일반 파일/실행 파일 모드를 유지하며 소유자 전용0600/0700으로 만든다. 실제 임시 Git에서 루트·하위 앱 import→checkpoint의100755 보존·스크립트 실행과 원본 불변, symlink/gitlink 거절 및 기존 starter를 고유5사례로 확인했다. 수정 전2 FAIL과 첫 수정 배치의 새 fixture 기대 타입 오류2 FAIL/3 PASS를 보존했고, 기대만 보정해 실패2건만 재확인 PASS했다. 실제 서비스·원격 Git·기존 앱 코드는 변경하지 않았다.
- Workbench 정리는 유휴 Task 이력에 SDK describe를 요구하지 않으며 실제 Runtime 경로의 stopped/cleaned 거절과 정리 재시도를 확인했다. 불확실 Task·활성 하위 작업·lease fence는 유지한다. 최초 SDK 준비 응답 유실은 같은 source·descriptor의 소유권과 ready 관측이 일치할 때만 편집 환경을 복구하고, Core 준비 요청 증거가 있으면 unknown을 유지한다. 편집 ready를 앱 미리보기 배포 성공으로 표시하지 않는다. 직접 고유24건은 최초22 PASS/새 fixture 기대 오류2 FAIL 뒤 해당2건만 보정·재확인 PASS했다. 실제 SDK/HTTP/원격 정리는 대역이며 브라우저 인수를 대신하지 않는다.
- Core는 현재 workspace 상태를 공통 admission과 기존 설치 설정·owner-preview에서 확인하고, cleanup_pending 이후 stop/resume 역전을 거절한다. 설정과 상태 전이는 기존 installation 행 잠금을 따르며 갱신된 값을 다시 읽는다. 실제 PG의 설정 경합·정리 receipt commit 경계·기존 세션 차단·정상 stop/resume 네 사례를 확인했다. 최초3 PASS/fixture 생성자 오류1 FAIL(14.61초)을 보존하고 그1건만 보정·재확인 PASS(10.14초)했다. 앱 runtime 중지/앱 DB 삭제는 대역이며 공용 DB·설정은 변경하지 않았다. 스키마·공개 API 변경과 이전11/6건의 반복은 없다.

## 원격 리뷰 8차 결과

source `1e5cc89f0741164adb413c2b8cac859dc6e4d7b9`의 pipeline296/job464는 보관된 설치 현황 조회와 SDK 실제 관측 경로의 두 누락으로 `MERGE_BLOCKED`다. 같은 clean commit의 r13을 준비했으나 배포하지 않았으며 실제 Workbench는 r4다. 보호 CI r4의 소스는 동일하여 재사용한다.

정리 후 활성 origin이 null인 설치도 기존 조회 응답 계약을 유지해야 한다. SDK 최초 준비의 readiness 실패 뒤 helper journal이 unknown일 때는 status만 반복해도 복구되지 않으므로, 같은 실행을 검증하는 실제 describe 경로와 Workbench 관측을 연결해야 한다. 각각 공개 응답 모델과 실제 helper 상태 전이를 포함한 직접 회귀로 보완한다. 기존 전체 검사와 SDK 시작 요청을 반복하지 않는다.

- 설치 현황 조회는 기존 표시 helper를 공통으로 재사용하여 archived origin을 반환한다. 실행·입장 주소에는 fallback을 추가하지 않았다. 실제 PG의 Core 정리→API 응답 검증 실패1건(11.69초)을 먼저 보존했고, 수정 후 해당 경계와 기존 scoped/read-only 조회를 묶어2 PASS(10.70초)했다. 같은 nullable origin 표시 소비자를 제한 검토했으며 추가 누락은 발견하지 못했다. 공개 응답·스키마 변경은 없고 앱 runtime은 대역, 앱 데이터 DB 삭제는 이 검사의 범위 밖이다.
- SDK 관측은 ready가 필요한 작업에서 status가 unknown이어도 기존 describe의 정확한 소유권·source·unit·native 준비 확인을 사용한다. 실제 helper와 private journal을 연결해 수정 전 unknown 고착1 FAIL을 재현했으며, create와 두 resume의 같은 실행 복구·불일치/미준비/Core 준비 전송 증거의 HOLD 등 영향10 PASS(0.64초)를 확인했다. 성공 후 응답도 ready로 갱신하며 시작 명령은1회, 토큰 bytes는 그대로 보존됐다. systemd 준비 확인은 대역이고 실제 서비스 동작 인수와 구분한다. helper·broker·SDK pin·생성 계약은 변경하지 않았으며 기존24/14/22건은 반복하지 않았다.

## 원격 리뷰 9차 결과

source `3e2a2a41dc0a2fa1fe8808d3ec0b7761d5995ff4`의 pipeline297/job465는 기존 루트 manifest·하위 앱 디렉터리의 가져오기 호환성과 정상 MR 검토 대기 중 UI 중단 차단으로 `MERGE_BLOCKED`다. r14는 준비만 했으며 실제 Workbench는 계속 r4다.

기존 앱 import는 같은 커밋의 루트 manifest와 선언한 하위 소스만 검증해 가져오며, builder와 같은 모호성 거절·소유권·실행 파일 모드 경계를 유지한다. UI는 현재 source의 정상 integrate/reviewing 대기에만 명시적인 stop을 허용하고, 미확정 실행 및 기타 동작의 차단은 유지한다. 별도 담당자의 제한된 통합 읽기 검토를 병행해 확인된 필수 누락을 다음 한 묶음에 모으며, 앱 업무 기능과 전체 검사 반복은 포함하지 않는다.

- UI는 같은 공개 상태 조건을 버튼과 stop 요청에 적용하고 새 요청 ID·현재 version으로 기존 서버 입구를 사용한다. pending/running/unknown·로컬 응답 유실 차단, 같은 ID의 계속 확인, stale waiting·정리 자격을 포함한 영향16 PASS/범위 밖7 미실행(2.26초)을 확인했다. backend·응답 스키마·서비스는 변경하지 않았으며 실제 브라우저 인수는 남아 있다.
- 독립 담당자의 제한된 통합 읽기 검토에서 기존 앱 계약·SDK 관측·등록/checkpoint·Core 입장/조회·CI/dev 반영·source handoff/정리를 owner 문서와 교차 확인했다. 위 두 건 외 확실한 추가 P1/P2는 발견하지 못했다. 진행 중인 import 수정의 최종 검증은 담당자에게 남겼으며, 이 읽기 결과를 실제 통합 인수나 전체 결함 없음의 증거로 확대하지 않는다.
- 기존 앱 import는 같은 clean HEAD의 정확한 subtree와 루트 manifest를 읽어 기존 앱 ID·선택 경로·선언 디렉터리·원격 저장소 계약을 검증한다. 루트와 내부의 이중 manifest, 비정규 Git 파일·초과 크기를 거절하고 실행 비트와 원본을 보존한다. 정상 기존 레이아웃의 수정 전 실제 Git1 FAIL(0.26초)을 보존했고, 수정 후 직접 영향18 PASS(5.49초)와 Ruff를 확인했다. 공통 helper·설정·스키마·생성 계약은 변경하지 않았다. 실제 UI 인수는 후속 배포 뒤 수행한다.

## 원격 리뷰 10차 결과

source `31479c6635e80f36c36e57085652bbd3654871e9`의 pipeline298/job466은 검토 대기 작업의 중지 후 재개 차단과 변경 없는 자동 재배포로 `MERGE_BLOCKED`다. r15는 준비만 했으며 실제 Workbench는 계속 r4다. 앞선 중지 수정에서 재개까지 이어지는 검증이 빠졌으므로 이번에는 전체 상태 전이를 한 흐름으로 확인한다.

- UI는 현재 source의 정상 검토 대기에 같은 stop/resume 예외를 적용한다. 중지 중 integrate/refresh 계속하기는 기존 서버 자격에 맞춰 막으며, 환경 재개 뒤 원래 MR operation ID·source·receipt를 보존해 계속한다. UI 영향16 PASS/범위 밖15 미실행(7.96초), 실제 action/reserve/persist와 격리 Git/SQLite를 연결한 서버4 PASS(2.46초), ESLint·Prettier·Ruff를 확인했다. pending/running/unknown 및 응답 유실의 차단을 유지한다. SDK와 GitLab은 대역이며 실제 브라우저 인수는 남아 있다. 이전 전체 검사와 이미 통과한 영향 묶음은 반복하지 않았다.

- 자동 checkpoint 대기 중에는 마지막 검증된 preview를 보존하면서 admission을 닫는다. 저장된 source와 현재 ready 미리보기의 runtime revision이 일치할 때만 같은 트랜잭션에서 자동 작업을 성공 처리하고 admission을 복구하며 Core 배포를 생략한다. 수동 갱신·변경 소스·configured/stopped/unknown 등은 기존 갱신 경로를 유지한다. 수정 전 직접1 FAIL(0.59초), 첫 영향15 PASS/1 FAIL(5.96초)을 보존했고, source guard의 기존 공통 오류 처리로 admission이 열리던1건만 보정·재확인 PASS(0.44초)했다. 마지막 guard 마감 변경의6건만 재확인 PASS(2.42초)했으며 고유 영향은 기존 known-failure 복구1건을 포함한16사례다. 정상 공개 API의 in-flight/busy fence로 막힌 경합은 강제 DB 변경으로 방어 경계만 확인했다. 정확한 원 running 작업만 blocked로 마감하고 새 source·행·receipt·unknown 작업은 덮지 않는다. 실제 Git/SQLite와 SDK/Core 대역 근거이며 실제 배포 generation 관측과 다르다. Ruff·format·소유 파일 whitespace 검사도 통과했다.

- 동결된 두 변경의 실제 diff와 직접 회귀를 독립 담당자가 한 번 읽어 추가 확실한 P1/P2가 없음을 확인했다. 이는 source 검토이며 원격 필수 리뷰나 실제 runtime 인수를 대신하지 않는다.

## 원격 리뷰 11차 결과

source `20c4e0e195ddb2113ee6497951ed6d42854c7a27`의 pipeline299/job467은 이전 v2 SDK를 포함한 기존 앱 가져오기와 managed v3 실행 환경의 호환성 누락으로 `MERGE_BLOCKED`다. r16은 같은 clean commit으로 준비했지만 활성화하지 않았으며 실제 서비스는 r4다. root manifest·subtree 호환만으로 실제 source mount의 SDK 검증까지 통과한다고 가정했던 경계를 보완한다. 새 기능을 추가하지 않고 검증된 SDK bytes·앱 원본 보존·실제 source-mount 확인에 한정한다.

- 기존 앱 가져오기는 원 v2 pin의 전체 SHA/profile/archive 결속과 공개 SDK 파일 집합을 확인한 뒤, 새 worktree의 SDK만 current v3 pin과 일치하는 공개 bytes로 전환한다. 전환 내역은 `SDK_IMPORT.md`로 첫 checkpoint에 포함한다. 원본·업무 코드·권한·의존성·Git 실행 모드는 유지하며 기존 기록 충돌, 변형·혼합·누락·추가 SDK 파일은 거절한다. helper·broker·cache·pin·운영 설정은 변경하지 않았다. 이 방식으로 실제 readonly SDK mount와 trusted build의 SDK를 일치시킨다.
- 실제 Git import/checkpoint와 기존 `verify_source_mounts(managed=True)`를 연결해 고유12사례를 확인했다. 양성 사례는 v2 원본이 원 v2 pin에는 통과하고 v3에는 거절됨을 먼저 증명한 뒤, 가져온 결과의 v3 통과·첫 migration 기록·원본 불변을 확인한다. 최초3 PASS/fixture setup8 FAIL(3.75초), 실패군과 partial-source 경계의7 PASS/fixture2 FAIL(3.43초)을 보존했고 그2건만 보정·재확인 PASS(0.78초)했다. 실패는 unsupported Git helper 인자, 기존 bounded-reader 오류 코드 기대, ignored dependency fixture에 한정됐으며 첫 실행 뒤 제품 bytes 변경은 없다. 파일 수·전체/개별 크기·실패 시 소유 partial source/worktree/branch 보존도 확인했다. Ruff·format·Prettier·소유 파일 whitespace PASS. 원 v2 공개5파일만 기록한 fixture는 pin과 대조했으며 검사 시 Git 과거 이력이나 호스트 SDK 설치에 의존하지 않는다. 실제 서비스/모델 턴 인수는 여전히 남아 있다.

- 동결4파일의 hash·명시 SDK 전환 순서·source-mount/checkpoint 직접 회귀·기존 release 포함 파일을 독립 담당자가 제한 검토했고 추가 확실한 P1/P2는 없었다. 검사 재실행과 host 변경은 없으며 실제 bwrap·서비스 인수로 확대하지 않는다.

## 원격 리뷰 12차 결과

source `a4585550f9ab0e75d462bf5a709a19565eb265ea`의 pipeline300/job468은 실제 SDK 중지·정리 후 응답 유실의 영속 기록 복구 두 경계로 `MERGE_BLOCKED`다. r17은 준비만 했고 실제 서비스는 r4다. 중지 관측 후 journal이 stopping에 남아 재개를 막는 문제와, unit 제거 후 최종 기록 전 중단으로 cleaning이 해소되지 않는 문제를 보완한다. 실제 설치가 사용하는 system broker에도 삭제 전 정리 intent와 삭제 완료 관측이 필요함을 확인했으므로 helper·broker·API 연결 회귀를 분리해 같은 필수 원인을 수정한다. 불확실한 부수효과를 다시 실행하거나 다른 소유 자원을 채택하지 않는다.

- helper는 정확한 소유 unit의 inactive 관측을 stopped로 영속화한다. 정리 intent가 있는 경우에만 세 unit 경로의 lstat 부재와 native not-found/inactive/PID 증거를 함께 확인해 cleaned를 확정한다. 남은 private descriptor는 원 token·binding·렌더링된 unit hash로 검증하며 GET 관측에서는 보존하고 명시적인 cleanup에서만 삭제한다. 수정 전 직접2건의1 FAIL/1 ERROR를 보존했고 영향12 PASS(0.662초), descriptor 삭제 후 부모 fsync 보완의 해당1건 재확인 PASS(0.060초), Ruff·format·AST PASS다. 부분 삭제·외부 파일·깨진 링크·활성 실행·다른 binding은 HOLD한다.
- root system broker는 unit 삭제 전에 cleaning intent를 fsync하고 영속 receipt 교체 후 부모 디렉터리도 fsync한다. query는 같은 세 unit의 정확한 부재와 비활성 증거로만 cleaned를 확정하며 stop/start/reload/delete를 재전송하지 않는다. 정리 intent가 없는 기존 owned receipt의 누락 파일은 채택하지 않는다. 수정 전 직접1 FAIL 후 영향11 PASS(0.125초), 실제 호스트의 socket 응답에는 MainPID가 없고 ControlPID는0인 형태를 확인해 서비스와 socket PID 증거를 구분한 추가1 PASS(0.015초), Ruff·format PASS다. 고유12사례이며 실제 설치된 root entrypoint는 아직 이전 bytes다. Workbench 서비스 중단 구간에 root 소유 entrypoint를 별도로 교체·기록해야 한다.
- API 연결은 실제 helper journal/file IO와 임시 migrated SQLite를 사용해 중지 응답 유실→원 operation 성공→같은 descriptor 재개, 정리 응답 유실→원 operation waiting/admission 닫힘, active/foreign/부분 삭제의 unknown 보존을 고유6 PASS(2.451초)로 확인했다. 원 operation ID·receipt·source·worktree·descriptor를 보존하며 API 제품 코드는 변경하지 않았다. Ruff·format·whitespace PASS다. native manager와 Core GET은 대역이므로 실제 systemd·HTTP·모델 턴·원격 Git 인수와 구분한다.
- 동결된 helper·broker·API 연결의 소유권/상태 전이를 독립 담당자가 제한 검토해 추가 확실한 P1/P2는 없었다. 이전 전체 검사를 반복하지 않았으며 필수 원격 리뷰와 실제 배포·브라우저 인수는 남아 있다. 설치 owner 문서에는 최신 archive migration과 root broker의 별도 반영 절차를 함께 갱신했다.

## 필수 리뷰 통과·개발 배포

최종 source `6f5305c68907152b9fb32acae2a46b8a4de55de9`의 pipeline301/job469는 `MERGE_READY`로 성공했다(340.17초). 인증된 리뷰 context·대상 dev SHA·필수 job·discussion 조건을 확인한 뒤 [MR !114](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/114)를 merge commit `614bab516bae220912d6054eb63fd4f1481fab5b`로 병합했다. 원 dev checkout의191개 파일을 snapshot hash와 대조해 물리 파일을 덮지 않고 병합 커밋에 정렬했다. 병합된 임시 플랫폼 branch와 worktree는 로컬·원격 모두 정상 정리했고 persistent dev를 유지한다.

- 개발 Core는 정상 시작 절차로 `independent_archive_20261011`에 migration했고 공개 health200·개발 환경·delivery consumer active를 확인했다. 기존 build/deployment 성공 이력은 유지됐다. GitHub upstream 및 Core production 배포는 수행하지 않았다.
- 보호 앱 CI 실행기는 검증한 immutable r4로 전환했다. 전환 직전 실행 job0, 원 설정 백업·고정9개 소스 및 설치 manifest 대조·서비스 active를 확인했다. 실제 새 앱 MR의 job-token 실행 검증은 후속 인수에 남아 있다.
- Workbench session/management는 clean source의 `20261011-managed-workspaces-r18`로 반영했다. artifact digest는 `sha256:fc97c483f9a27d828a07ce62815e1aeaac410b9df148881bc8d0f29d28823d6c`다. template service는 기존 r4를 유지하며 schema `console_sqlite_0009`, task15/agent8/project1/workspace1의 기존 기록을 보존했다. 두 실행 프로세스의 실제 cwd와 direct/public health200을 확인했다.
- 이전 management service가 정상 종료15초 제한을 넘겨 systemd가 종료하고 failed 상태가 되어 첫 전환 guard가 멈췄다. 새 버전 전환 전 MainPID/ControlPID0·cgroup 없음·작업 idle/agent completed를 확인하고 실패 근거와 SQLite 백업 무결성을 보존한 뒤 정상 reset-failed로 재개했다. 승인·실행 gate를 완화하지 않았다. 새 버전의 종료 동작은 이번 시작 성공으로 검증했다고 간주하지 않는다.
- Workbench 중단 구간에 root broker를 별도로 교체했다. 설치된 SHA256은 `9e60a917dc2f58dea6cc08dc01cd0326515a11b364b53a1b6efac2e8d5206985`이며 이전 root0555 bytes를 백업했다. 설정·SDK cache/pin은 유지했다. 실제 SDK lifecycle과 새 앱 자연어 개발·미리보기·dev 반영/정리는 배포 이후 브라우저에서 계속 확인한다.

## 새 작업 재개·첫 계획 요청 관측

포털의 정상 개발 로그인·Workbench SSO 후 기존 workspace `584a1107-b8c1-5aa9-a545-720341f48b6d`에서 환경 재개를 눌러 성공했다. base는 dev merge `614bab516bae220912d6054eb63fd4f1481fab5b`, 작업 branch는 `feature/wb-app-8565f140-584a1107`, 초기 source는 `aa6170c64baea7a4ad8e89d8976d439ddfa8d191`다. 편집 환경 ready/admission open과 앱 미리보기 unconfigured를 구분하며, 준비되지 않은 환경의 정리 버튼이 비활성화된 것도 확인했다.

개발 세션 `fa961e89-532c-4e04-970b-ee3797933aaf`는 managed worktree의 `personal-apps/app-8565f140`에 연결됐다. 총무 담당자가 엑셀 장비 대장을 간단한 등록·수정·검색 앱으로 바꾸려는 수준의 자연어 요청을 계획 모드·별도 스킬 없음으로 보냈다. native thread는 생성됐으나 첫 turn 제출 전에 `workspace_environment_unavailable`로 실패했고 계획/업무 코드 생성은 아직 없다. 관찰자가 앱 코드를 대신 작성하지 않았다.

단독 helper describe는1.559초에 성공했다. 동일 환경에 동시 describe 두 건을 보내자 하나는1.562초에 성공하고 다른 하나는0.056초에 `workspace_busy`로 거절됐다. UI 상세 조회의 threadpool 호출과 모델 제출 직전 호출이 전역 비차단 exclusive lock에서 충돌할 수 있음을 코드 경로로 확인했다. 최초 실패 당시 helper 오류 원문을 수집한 것은 아니며, 별도 재현 결과와 구분한다. describe의 짧은 bounded 대기와 API 오류 보존을 필수 보완한다. lifecycle 명령 재전송·소유권 검사 생략·기존 전체 검사 반복은 포함하지 않는다.

독립 담당자의 실제 OS metadata 관측에서는 정확한 SDK unit이 active이며 관측3개 프로세스 모두 UID1000·NNP1·유효 capability0·호스트와 다른 network namespace였다. source RW, SDK v3/cache/app SDK/node_modules RO와 빈 root/scratch tmpfs를 확인했다. credential/descriptor/환경값/대화 원문/전체 명령행은 읽지 않았다. 이 결과는 실제 모델 실행이나 브라우저 업무 기능 완료를 뜻하지 않는다.

필수 보완은 describe의 exclusive lock 취득만 최대3초 대기하고 검증·manage를 한 번 수행하는 것이다. lifecycle/status의 즉시 HOLD, 기존 소유권 검사·전체 describe10초 제한을 유지한다. API는 workspace_busy만409로 보존하고 unknown 우선순위·기타503·timeout unknown409·자동 재시도 없음은 유지한다. 실제 fd flock release/timeout/나머지5action 즉시 거절/unsafe lock 거절의4 PASS(3.219초), descriptor 소비자까지 API 반환 경계8 PASS(1.863초), Ruff·format·AST/whitespace PASS다. 이전 전체 검사를 반복하지 않았다.

같은 실제 SDK 환경에 새 helper 후보로 동시 describe 두 건을 한 번 재확인해 두 호출 모두 성공(3.400초/1.961초)했다. 명령은 describe이며 새 프로세스 준비·중지·서비스 전환은 하지 않았다. 이 후보 관측은 실제 first model turn 성공이나 배포 완료가 아니다. 필수 리뷰 뒤 새 Workbench 릴리스에 반영하고 원 세션에서 첫 계획 요청을 재개한다.

source `d9cc81afb6f83d9813b02672bff09f691cac063c`의 [MR !115](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/115)는 pipeline302/job470의 필수 리뷰를 통과했다(67.046초). dev merge `65356b926550dcf412c4d3bbc3f62205d7fb145a`로 병합·정렬한 뒤 Workbench만 r19로 반영했다. artifact digest는 `sha256:1674c6fd359531193155fa7d3d3bc26de39abb01005ee700a45f257d24681cc7`이며 root broker·Core·CI·template service는 바꾸지 않았다. public/direct health200·실행 cwd·SQLite schema와 task16/agent9/project1/workspace1 보존을 확인했다. 임시 수정 branch와 worktree는 로컬·원격 모두 정상 정리했다.

r18 session/management 종료는 둘 다15초 timeout 뒤 PID/ControlPID0·cgroup 부재였다. 작업 미실행과 기록 보존을 확인하고 정상 reset-failed 후 r19를 시작했다. r18 종료 실패는 개선 대장의 deferred 항목으로 유지하고 새 r19의 종료 성공으로 주장하지 않는다.

원래의 첫 turn 미생성 Task를 r19에서 재시도하면 `codex_request_failed`가 native 제출 경계 전에 발생했다. previous execution root/runtime generation은 null이며 계획·업무 코드·turn 손실은 없다. 오류 원문이나 실패 method는 수집하지 않았으므로 빈 thread의 cold resume 문제가 원인이라고 확정하지 않는다. 실패 이력을 유지하고 정상 UI의 **개발 세션 시작**으로 같은 workspace에 Task `e38072df-7dbe-44b5-8cf9-9a8e021bfb30`을 생성해 같은 업무 요청을 보냈다. 새 Task는 실제 thread/turn 생성·plan running·agent active·명령 실행까지 진행했으며 별도 앱 코드 작성이나 DB 상태 우회는 없었다. 아직 첫 계획 완료·구현·유의미한 세션 재연결은 관측 중이다.


## 장비 앱 계획·구현과 실제 실행 환경 장애

같은 workspace의 새 Task에서 native AI가 개인 계정별 보관과 전사 공유를 구분해 질문했고, 사용자 역할로 **본인 계정의 가상 장비 데이터 저장**을 선택했다. 계획 revision7/version1이 완료된 뒤 정상 UI의 **이 계획으로 실행**, 실행 권한 **ask**를 명시 승인했다. AI가 자기 앱 subtree의 React·FastAPI·업무 검사 파일을 수정했으며 관찰자가 업무 코드를 대신 작성하지 않았다. 계획·구현 시작은 확인했지만 앱 등록·미리보기·dev 반영·정리는 아직 완료되지 않았다.

실제 `pnpm test` 실행에서 스레드 생성 실패가 발생했다. SDK cgroup은21개 프로세스·57개 스레드/상한64이며 `pids.events.max=7`을 관측했다. Codex 본체12개 스레드와 Node·wrapper 자식들이 한도를 공유한다. 무제한 해제 대신 고정된 적정 예산과 기존 환경의 소유권·정리 호환을 검토한다.

해당 테스트의 일회성 승인 버튼을 눌렀으나 API가503으로 거절했고 원 pending request는 그대로다. 승인 성공으로 기록하지 않는다. 별도 소스 metadata 검사에서 앱 subtree 안에 새 `.git` 디렉터리가 발견됐고 이는 helper의 명시적 거절 조건이다. 생성 원인과 정확한 실패 경계를 조사 중이며 스레드 실패와 같은 원인으로 단정하지 않는다. 현재 readiness 검사 실패 시 원 pending의 거절·turn 중지도 함께 막히므로, 기존 살아있는 controller의 정확한 identity/generation을 확인한 권한 축소 동작만 허용하는 최소 보완을 진행한다. 새 실행·권한 승인·자동 재전송·lease 강제 해제는 허용하지 않는다.


읽기 전용 확인에서 문제의 하위 `.git`은 UID1000·0755·entry0이며 상위 worktree의 정상 `.git` 파일과 별개였다. [고정 Codex0.160.1 sandbox 구현](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/linux-sandbox/src/bwrap.rs#L1220-L1281)은 writable root의 없는 `.git`을 읽기 전용 synthetic mount target으로 만들며 [종료 경로](https://github.com/openai/codex/blob/rust-v0.160.1/codex-rs/linux-sandbox/src/linux_run_main.rs#L583-L632)에서 정리한다. 생성 시각·코드 경로가 일치하나 실제 생성 PID와 잔존 원인은 독립 수집하지 않았다.

정확한 빈 디렉터리의 inode·소유권·mode·내용 없음을 재확인해 `rmdir`로만 제거하고 기존 브라우저의 **중단**을 눌렀다. interrupt200과 native Task/agent interrupted·stage review·pending0을 관측했다. 앱24개 파일과 상위 worktree `.git` 해시는 보존됐고 승인 재전송·새 모델 실행·DB 상태 변경은 하지 않았다. 이 조치는 재발 방지 배포가 아니라 현재 실행의 정상 종료 복구다.

이후 정상 UI의 **환경 중지** operation `9b2c1534-039d-4e64-877b-fbc990ecb943`는 waiting/workspace_busy다. 첫 turn 전에 실패한 이전 Task는 root Agent idle, Task/Agent turn null·runtime generation null·operation2건 failed·resource lease0·pending0이지만, workspace busy는 이를 실행 중으로 세고 stop_tasks는 건너뛰는 불일치를 확인했다. 이 일반적인 첫 제출 실패 경계의 정합화도 필수 보완에 포함한다. SDK는 아직 active이며 환경 중지를 성공으로 보고하지 않는다.


## 실행 환경 복구 후보 검증

필수 변경을 하나의 후속 릴리스로 묶는다. 기존 live controller에 결속된 거절·취소·중단은 readiness 실패와 분리하며, 새 승인·입력·실행에는 기존 gate를 유지한다. 고유 영향23건과 독립 읽기 검토를 통과했다. 단절된 controller를 재연결하거나 이전 pending을 새 generation에 채택하지 않고 native 완료 전 lease를 해제하지 않는다.

managed app-root의 `.git`은 정확한 소유자의 빈 일반 디렉터리만 native 임시 보호 대상으로 인정한다. 파일·symlink·하위 `.git`·실제 metadata·외부 사용자 쓰기 권한은 계속 거절한다. 첫 turn 전 실패의 exact idle root만 workspace busy에서 구분하며 모든 실패 operation 기록·pending·lease·하위 agent·불확실 실행의 차단을 유지한다. 기존 대기 stop의 실패를 먼저 재현했고 같은 intent 계속하기와 실패 경계36건이 통과했다. native 서비스는 대역이며 실제 SDK·브라우저 검증과 구분한다.

SDK backend의 새 고정 예산은256이고 proxy64·CPU100%·메모리1GiB·네트워크/소스 격리는 유지한다. 과거64 환경의 관측·중지·정리는 원 bytes로 계속 검증한다. 기존 workspace의 재개에는 inactive/PID0을 증명한 명시 `upgrade-budget`가 필요하며, 동일 source/token/port·stopped 상태를 보존하고 시작은 기존 UI에 맡긴다. helper와 root broker의 실제 파일·journal 연결 및 유실/소유권 경계23건이 통과했다. 최초 결과 수집기의 기존 fixture id 이름 충돌은 수집 실패로 기록한 뒤 수집기만 보정했다. 실제256 실행과 앱 테스트 성공은 아직 검증하지 않았다. 이전 전체 검사 묶음은 반복하지 않았다.


## 복구 릴리스 실제 반영

[MR !116](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/116)의 source `720866d05f380af38704d32af52aa0b87ee4a861`은 pipeline303/job471의 필수 리뷰를 통과했다(197.815초). 소스·대상·필수 job·신뢰된 review context·해결된 discussion을 확인해 dev merge `e6ff64a82fd501fefb1447276a463e124cd44933`에 병합했다. 원 checkout의17개 파일을 hash로 보존해 정렬했고 임시 복구 branch와 worktree는 로컬·원격 모두 정리했다. 앱의 기능 branch/worktree는 유지한다.

Workbench session/management는 clean r20으로 실제 반영했다. digest는 `sha256:02cedaee3d869753d588d9c76c429a262dcf3643d4f35d65086afe98e9c24dad`이며 두 실제 PID의 cwd·direct/public health200·schema0009와 task17/agent10/project1/workspace1 보존을 확인했다. template service는 r4다. root broker SHA `2e51830561a3fa50afb9b0a9fb982ae556baa94c4f99781a37a65db8a552e044`, backend template SHA `3054b4710e6391a55af7dc50f07e0bfd0896471cea5aa785eda7fd2f20987a3f`와 해당 root pin만 별도 갱신했고 백업을 보존했다. Core·SDK/native bundle·proxy·CI9개 소스는 변경하지 않았다.

r19의 두 Workbench 서비스 종료도15초 timeout 뒤 PID/ControlPID0·cgroup 부재였다. 정상 reset-failed 후 전환했으며 r20 종료 검증으로 확대하지 않는다. 같은 브라우저·로그인·원 Task와 계획 이력을 다시 읽었다.

환경 중지는 원 operation `9b2c1534-039d-4e64-877b-fbc990ecb943`의 명시 **계속 확인·반영**으로 완료했다. 첫 계속하기는 workspace_busy 대기를 유지했고 두 번째 명시 계속하기에서 succeeded/stopped가 됐다. backend와 두 proxy unit은 실제 inactive·PID/ControlPID0·cgroup 부재·Result success였다. 상태나 lease를 직접 수정하지 않았다.

중지된 같은 환경에 검토된 `upgrade-budget`를 한 번 실행했다. 동일 UUID/source/token/port와 앱24파일·상위 worktree `.git`을 보존했고 실제 backend TasksMax256·inactive/PID0을 확인했다. 그 후 기존 UI의 **환경 재개**로 ready/version15를 확인했다. 기존 Task/계획 revision7/version1을 ask 권한으로 다시 승인해 동일 native thread의 구현을 이어가는 중이며, 아직 앱 테스트·등록·미리보기 인수 성공은 주장하지 않는다.


같은 Task와 native thread가 새 controller generation/새 turn으로 정상 재개되어 완료됐다. 실제 native `pnpm test`는4 PASS·0 FAIL, Python unittest는4 PASS, Vite build는 성공했다. AI는 이번 turn에서 test/build를 각각 두 번 수행했으므로 4건을 중복 합산하지 않으며, 관찰자가 동일 검사를 다시 실행하지 않았다. source checkpoint `17b8453fb377e70f1db71bcd6da273210c2a3a38`이 자동 저장됐고 작업 tree는 clean이다. 아직 위임이 없어 auto_refresh operation은 명시 `app_delivery_unconfigured`로 실패했으며 이를 앱 실행 성공으로 표시하지 않는다. 편집 환경과 admission은 ready를 유지했다.

정상 UI의 새 등록 작업으로 Task `2233e751-81f8-46c0-a7f5-ea4f426acb14`를 만들고 안정된 개발 주소 `https://feat4.1punicorn.com`을 지정했다. MIY 소유자 화면에서 해당 앱/주소의 최초 등록 한 번을 허용하고 같은 Workbench 등록 operation `01ab86db-5d37-4a10-9b4e-62d3b7a26a59`의 권한 연결 ready를 확인했다. 일반 업무 문장으로 개인 계정에서 가상 자료를 확인할 앱의 등록 계획을 요청했다. 등록·실행·개발 설치 권한은 별도 단계로 유지한다.

### r20 등록 계획 실행 관측 (2026-10-11 UTC)

- 같은 등록 Task의 계획 8을 검토한 뒤, 동일 checkpoint `17b8453`의 JS 4개·Python 4개·빌드 성공을 재사용하도록 UI 문서 편집·저장(계획 9) 후 ASK로 실행했다. 변경 없는 전체 검증을 재실행하지 않도록 했으며 필수 CI는 유지한다.
- 최초 등록 일회성 승인은 계획 검토 중 만료되어 동일 operation에서 정상 소유자 승인 UI로 갱신했다. 반복 등록이나 인증 우회는 하지 않았다.
- 등록 체크포인트에서 일시적인 `workspace_busy`를 관측했다. native AI가 같은 작업을 명시적으로 재확인한 뒤 변경 없는 체크포인트 확정을 보고했다. helper 상태 조회 경합이 후보이며 원인 확정 전에는 별도 구조 수정으로 확대하지 않는다. 실제 등록/활성화/미리보기 완료를 의미하지 않는다.

- 최초 등록은 08:09:52 UTC에 실제 성공했다. 영수증의 앱/정의 digest/source17b8453이 계획과 일치한다. 소유자 UI에서 본인 전용 개발 미리보기 및 identity:read/data:read/data:write를 저장했다.
- 소유자 실제 로그인에서 read/sync/build/deploy/workspace의 제한 위임을 발급하여 보호된 Workbench 설정에만 연결했다. 안정 개발 target은 feat4:19524이며 임시 네 슬롯과 별개이다. 최초 등록의 짧은 승인 토큰을 배포 권한으로 재사용하지 않았다.
- Core development 및 Workbench r20 설정 반영 후 공개 health 모두200, Task18/agent11/project1/workspace1 보존. r20 세션/관리 종료에서도 timeout이 재현됐으나 PID0/ControlPID0/cgroup 부재 확인 후 정상 재시작했다(DEF005 유지). 운영 Core 변경은 없다. 아직 앱 build/preview/dev 통합/cleanup 완료 증거는 아니다.

### 최초 실제 앱 preview 배포의 DB preflight (2026-10-11 UTC)

- 첫 수동 갱신에서 실제 Core build `4ee85fff-808b-5ac6-89a5-693ac9e5f8f4`는 성공했으나 임시 설치의 배포가 `data_cluster_public_connect`로 차단됐다. 신규 전용 app-data cluster의 PostgreSQL 기본 PUBLIC CONNECT가 원인이며 앱 소스 결함이 아니다.
- `DATA.md` 계약에 따라 Docker 소유 label/127.0.0.1:19412 바인딩·postgres/template0/template1만 존재·postgres 외 사용자 역할 부재를 확인한 뒤 이번 전용 클러스터의 연결 가능한 두 기본 DB에서 PUBLIC CONNECT/TEMPORARY만 제한했다. 기존 Core/개발 DB는 변경하지 않았다. 실제 provisioner preflight 성공 후 정상 UI에서 새 앱 갱신을 명시 요청했다. 근거: `fresh-app-data-preflight-fixed.json`.

### 실제 임시 preview와 브라우저 흐름

- 명시적 두 번째 갱신 `73084579-04db-4d8a-b3d9-7e8f0ee6362e` 성공. 임시 설치 c14580b5의 실제 deploy `6298ccfe-0c72-55a1-8804-aa398884c70f` 성공 후 preview ready, source/runtime 모두 `17b8453`이다. Workbench 정상 링크 → 개발 포털 → feat0 iframe으로 연결됐다.
- 가짜 장비 1개 신규 등록·목록 조회, 별도의 위치 수정(실제 PUT200/172ms), 포털 reload 후 수정 보존, 관리번호 검색을 브라우저에서 확인했다. 인증 없는 앱 API 요청은401이다. 관찰자는 업무 소스 코드를 직접 작성하지 않았다. 영수증 `fresh-preview-crud.json`, 가짜 자료만 담긴 화면 `fresh-preview-equipment.png`.
- 첫 수정은 화면에 일반 실패를 표시했지만 이후 완료된 GET200에서 변경 반영이 확인됐다. 최초 응답 status/전달 실패 원인은 미수집이며 timeout 등은 가설이다. 오래된 화면을 본 즉시 재전송하지 않았고, 최신 조회 후 값이 바뀐 것을 확인하여 중복 저장을 하지 않았다. PUT 실패 응답을 조회로 확인하는 UX는 앱별 후속 이슈로 분리한다. 정상 계약 불일치/지속 플랫폼 오류는 확인되지 않았다.
- Workbench reload 후 동일 workspace/feature branch/source/ready preview가 유지됐다. 정상 `개발에 반영` 확인 화면에서 리뷰·dev 통합 및 소유 임시 자원 정리 흐름을 승인했다. CI와 실제 dev runtime/cleanup 결과는 아직 대기한다.

- Workbench가 실제 앱 MR117을 만들었다. source17b8453 / native diff base614bab5 / review target e6ff64a는 구분해 기록한다. pipeline304에서 `personal_app_validation` job472가 get_sources 단계 `personal_app_runner_required`로 실패했고, 필수 선행 job 성공을 요구하는 `codex_review` job473도 pre-review에서 거부됐다. 코드 리뷰 결과 MERGE_BLOCKED가 나온 것은 아니며 아직 모델 리뷰 전이다. 실패를 우회하거나 원 source를 재게시하지 않고 고정 runner의 실제 실행 연결을 진단한다.

### 고정 개인 앱 CI의 안전 진단 보완

- GitLab 서버의 시각/경로/status만 추출한 확인에서 job472의 `/job`와 MR117 조회는 각각200이었다. MR 조회는 native job 검증 뒤 호출되므로 인증/native job 단계를 통과한 증거다. 이후 MR 본문 predicate·소유 journal 쓰기·local Git 준비 중 정확한 실패 위치는 당시 공통 오류 및 종료 후 정상 cleanup 때문에 남지 않았다. 현재 MR 메타데이터 일치만으로 과거 실패 원인을 단정하지 않는다.
- 고정 driver의 기존 `personal_app_runner_required` 실패 코드는 유지하고 허용된 단계/거절 원인/예외 종류/HTTP 상태만 추가했다. 토큰·응답본문·명령 인자/출력·예외 메시지·환경값을 출력하지 않는다. 현재 pipeline/소스 증거를 완화하거나 자동 재시도를 추가하지 않았다. 직접 영향9개 메서드(신규21 subcase 포함)·Ruff/format/diffcheck PASS. 실제 job 재시도 결과는 아직 없으며 코드 필수 리뷰·immutable runner 설치 후 해당 작업만 재실행한다.


### 실제 개인 앱 CI 연결 진단 (2026-10-11 08:48 UTC)

- 안전 진단 [MR !118](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/118), source `6f4344cd35196e83b0bcd30ab704e620cab6248e`는 pipeline305/job474 필수 리뷰를 통과했고 dev `13a3b42317653604b480ba6ed046f8e381ea44f2`에 병합했다. 고정 runner4만 immutable r5로 반영했다. Workbench r20/Core를 다시 배포한 것은 아니다. 플랫폼 수정의 임시 local/remote branch/worktree는 정리했고 앱 기능 branch는 유지했다.
- 명시 재시도 job475는 `git_fetch/trusted_command_failed`로 실패했다. 동일 시각 실제 Workhorse의 `/lumejs/mty/info/refs` HTTP301과 비인증 고정 Git probe로 원인을 확인했다. 보호 config가 웹 저장소 URL을 사용하고 있어 Git clone 경로로 redirect되던 문제였다. GitLab 프로젝트의 `http_url_to_repo`와 일치하는 canonical `.git` URL로만 운영자 config를 보정했다. TLS/redirect 거절·job token·현재 MR/pipeline/소스 증명·manifest 정체성은 유지한다. idle runner/보호 config 백업을 확인했고 이전 journal을 재서명하지 않았다.
- 새 retry job476은 get_sources를 통과했지만 step_script 구간에서 `ownership_read/unsupported_job_stage`로 실패했다. 설치된 Runner의 실제 custom callback 이름과 adapter 허용 이름을 확인하여 최소 호환 보완한다. 개인 앱 검사·모델 리뷰·dev 병합·feat4 실제 실행·임시 정리는 아직 완료되지 않았다. 정상 Workbench 조회에서 원 integration operation은 waiting/continuable, source17b8453의 임시 preview는 ready다.

고정 Runner19.4.1/revision3c39fceb의 upstream custom executor는 외부 `step_script`를 callback argv `build_script`로 바꾼다. 두 exact 이름을 기존의 동일 current-MR 증명/journal/fixed wrapper로만 연결했다. 제공 script 파일·before/after/cache/artifact·임의 step 이름은 계속 실행하지 않는다. 직접 영향5메서드(실제 main 인수 경로의 fixed wrapper 호출, 두 alias의 재실행·오래된 MR·미검증 journal 거절 및 기존 경계)와 Ruff/format/AST/diffcheck PASS. 실제 runner 반영과 required app job 통과는 필수 리뷰 후 확인한다.


### Runner callback 호환 실제 반영

- [MR !119](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/119) source `c7dfab004e531c7a8823a3628152d622bd579b2f`는 pipeline306/job477의 필수 리뷰를 통과했다(48.374초). exact source/target/review evidence/보호 dev/discussion을 확인해 dev `a1de55986ca6321052bf6ec62da4b3a43fbc1204`에 병합했고 고정 runner4만 immutable r6로 반영했다. 독립 읽기 검토에서 추가 P1/P2 없음. 해당 플랫폼 작업의 local/remote branch·clean worktree를 정리했다.
- 명시 재시도 job478(기존 pipeline304/source17b8453)은 Git 취득·callback 분기를 통과한 뒤 `validation/trusted_command_failed`로 실패했다(5.150초). 검증기가 실행되는 전용 계정의 설치/권한 경계를 확인 중이다. 앱 MR117을 병합하거나 검증 실패를 우회하지 않았으며 같은 Workbench integration/preview를 유지한다.


### 전용 CI 계정의 소스 읽기 경계

- 전용 UID993에서 r6 고정 Python/module import 및 승인 toolchain image 조회를 확인했다. 별도 private 진단 copy에 동일 source17b/base614 Git object를 준비하여 CI의 HEAD/diff/manifest 확인이 build 호출 직전까지 통과하고 immutable `_snapshot`이 성공함을 확인했다. 실제 CI journal·인증을 우회하거나 앱 명령을 실행한 결과가 아니며 가짜 CI 성공 영수증은 만들지 않았다.
- 별도 필수 결함으로 umask0077일 때 검증된 snapshot bind root가 호스트 UID993/0700이어서 고정 container UID1000이 읽을 수 없는 것을 확인했다. 기존 Core의 호스트 UID1000 미리보기 성공과 모순되지 않는다. immutable source 검증 뒤 해당 root만0755로 명시하고 바깥 work/temporary/context/Dockerconfig의0700·read-only mount·container UID와 격리 예산은 유지했다.
- 새 회귀의 기존 코드 실패를 확인한 뒤 직접 영향6 PASS(1.15초), 실제 승인 immutable image의 다른 비root UID 읽기·Ruff/format/AST/diffcheck PASS. 실제 읽기 증명은 host1000/container1001로 nonowner 경계를 검증했으며 앱 기능 실행은0이다. 실제 job478의 첫 실패 원인과 동일하다는 단정이나 실제 CI 완료 주장은 하지 않는다. 필수 리뷰·고정 runner 반영 후 같은 앱 CI를 확인한다.


### 실제 개인 앱 검사 통과와 리뷰 피드백

- [MR !120](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/120) source `c6bb00f260191d467be5515c1c7be4bf7271d542`는 pipeline307/job479 필수 리뷰를 통과했고(49.300초), dev `5fa1b324a54660df5b239cc795d186cfa2b4b45d`에 병합했다. exact gate 확인 뒤 고정 runner4를 immutable r7로 반영하고 수정용 local/remote branch·clean worktree를 정리했다.
- 같은 앱 source17b8453/pipeline304의 실제 retry job480은5.181초에 성공했다. 앱 artifact `sha256:a0e77ab6cf0bd5180a1f1d97058995078fbb5184e65695463364049254f5b560`의 검증 결과가 passed다. 별도 private 진단 copy만 exact source/owner/clean 상태 확인 후 정리했고 실제 앱 workspace는 보존했다. 이전 실패 job은 이력으로 유지한다.
- 필수 앱 리뷰를 job481로 재개했으나 관리번호 정규화 순서의 P2 한 건으로 MERGE_BLOCKED였다. 정규화로 길이가 늘어나는 입력은 생성되지만 같은 저장값의 조회/수정이 길이 제한으로 거절될 수 있다. 필수 gate를 우회하지 않고 동일 Workbench 구현 Task에서 이 저장 일관성 결함만 수정하도록 짧은 계획을 요청했다. 관찰자가 업무 코드를 직접 쓰거나 일반 기능 고도화를 추가하지 않는다.


### 자연어 리뷰 수정·dev 병합과 안정 실행

- 같은 Workbench 구현 Task의 계획10/version2를 정상 ASK로 승인했다. native turn `01a12a41-48e9-7043-9f1b-086bbf591c6e`가 서버·UI의 정규화 후 관리번호 제한과 직접 회귀를 수정했다. API2·UI1 검사는 통과했으며 전체 검사/빌드를 반복하지 않았다. 관찰자의 앱 업무 코드 편집은0이다. clean checkpoint `ee3afef71110c62380c0e2121592f37c0c0fedd4`와 자동 미리보기 갱신 `aad26730-05d9-5a10-a07d-efdede597380` 성공을 확인했다.
- 실제 [앱 MR !117](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/117)의 pipeline308은 personal_app_validation job482(5.103초), codex_review job483(80.023초) 모두 성공했다. 첫 새 통합 intent는 source 갱신 직후 `workspace_integration_changed`로 보류됐고, 정확한 현재 MR head를 확인한 정상 UI 재승인으로 진행했다. MR metadata 반영 지연은 추정이며 원인 확정으로 기록하지 않는다.
- 정상 Workbench 통합 `4c82c50f-66bf-4f9a-8e2f-4ea8debc6679`가 dev `de88e30df2785d6c7fdaf9502cf803deb14c59f6`에 병합하고 같은 revision을 parent installation/feat4에 배포했다. Core handoff 완료 및 deployment `5359e1d9-6661-5dbe-a82f-cdc9209cd9c1`을 확인했다. 브라우저 포털에서 feat4 iframe이 인증·정상 표시됐고, 임시 preview의 시험 관리번호가 없는 빈 목록으로 데이터 분리를 확인했다.
- 이어진 cleanup은 `workspace_busy`로 unknown이 됐다. 관측 시점의 Task/agent/lease/operation은 quiescent지만 SDK는 active, Core는 ready여서 정리 완료가 아니다. 같은 receipt에는 acknowledged `/complete`와 병합·배포 증거가 있으며 `/stop`·`/cleanup`·remote cleanup 시도 증거는 없다. helper 조회 경합은 가능성일 뿐 확인된 원인으로 표시하지 않는다. 브라우저 HTTP 관찰의 timeout도 서버 실행 실패와 구분한다.
- 필수 보완은 서버가 quiescent를 확인하고, 같은 source/operation/merged revision·Core workspace/app/profile/temporary installation·handoff 및 deterministic dev-deploy ID·acknowledged `/complete`를 대조한 GET 관측에서만 기존 operation을 waiting으로 돌리는 것이다. SDK ready의 describe 또는 stopped 증거가 필요하고, Core write나 재병합·재배포를 자동 실행하지 않는다. 같은 intent의 명시 계속하기가 기존 정리 경로를 실행한다. 새 schema/helper/일반 실행 프로토콜은 추가하지 않는다.
- 회귀는 기존 코드 실패를 먼저 확인했다. 첫 영향 묶음10 PASS/fixture의 Core version 누락2 FAIL 후 해당2건만 보완·재확인 PASS로 최종 고유12건을 확인했다. Ruff/format/AST/diffcheck 통과. 실제 SDK/Core는 대역이며 필수 원격 리뷰·Workbench 릴리스 반영·실제 정리 인수는 남아 있다.

- 안정 dev 앱에서 별도 가짜 관리번호 `WB-SYN-DEV-001`을 정상 UI로 생성해 HTTP201·reload 보존을 확인했다. 임시 데이터는 계속 보이지 않으며, 이 안정 데이터가 정리 이후에도 보존되는지 최종 확인한다. 독립 읽기 리뷰에서 cleanup 보완의 추가 P1/P2는 없었다.


### r21 적용과 같은 intent의 실제 정리 완료

- [MR !121](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/121), clean source `5e6da1cbd606261c006a0c165d11abc6dba29825`의 pipeline309/job484 필수 리뷰가90.361초에 성공했다. 보호 dev·exact source/target·필수 job 및 review context를 확인한 뒤 `76ece913b565efa4513ef52f13204a5285d57899`에 병합했다. 정상 로컬·원격 수정용 branch와 해당 clean 빌드 worktree만 정리했다.
- Workbench `20261011-managed-workspaces-r21`은 같은 clean source로 빌드됐다. digest `sha256:6d2989794ba58ab2cb484ee96cf710332384df8a90bc43935099b233f31fbc1f`. 공식 SQLite online backup 후 current의 session/management 두 역할만 교체했고 template-current는r4 그대로다. 두 역할의 종료가15초 timeout으로 표시됐지만 PID0·ControlPID0·빈 cgroup과 데이터 보존을 확인한 후 전환했다. 종료 지연 DEF-005는 해결로 바꾸지 않는다.
- 공개/내부 health200, 실제 두 PID의 새 release cwd, schema0009 및 Task18/Agent11/Project1/Workspace1 보존을 확인했다. helper·Core 운영·CI runner는 이번 Workbench 패치로 교체하지 않았다.
- 정상 브라우저의 작업 상태 확인으로 같은 operation `4c82c50f-66bf-4f9a-8e2f-4ea8debc6679`가 unknown에서 waiting(version51)으로 회복됐다. 같은 `계속 확인·반영` 버튼을 한 번 실행해 09:48:05 UTC에 succeeded, workspace/cleanup cleaned(version55)를 확인했다. 새 병합·안정 배포 요청을 만들거나 DB 상태를 수동 보정하지 않았다.
- 관찰 스크립트의 response 대기는 응답을 포착하지 못했다. 이를 제품 timeout으로 해석하지 않으며 브라우저의 완료 화면·정상 GET 결과·서버 원 operation receipt를 근거로 결과를 확인했다. 화면 최상위 오류는 없어졌고 원 operation의 과거 failure_code는 이력에 남아 있다.
- Workbench가 관리하던 정확한 작업 경로와 로컬 feature branch, `origin`의 같은 feature branch가 모두 없는 것을 별도 읽기로 확인했다. 정리 후 안정 portal/feat4 앱을 다시 열어 기존 가짜 `WB-SYN-DEV-001` 데이터 보존·임시 `WB-SYN-001` 미노출·비인증 API401을 확인했다. 임시 데이터가 안정 DB로 복사됐다고 해석하지 않는다.
- 정리한 미리보기 링크는 숨겨지고 MR 링크가 유지된다. 안정 개발 앱으로 바로 이동하는 링크와 복구 후 과거 failure 표시는 후속 UX 개선으로 기록하며 새 기능 수정을 추가하지 않는다. 일반 직원 인증·의미 검색·다중 사용자·전사 공유 장비 업무와 앱별 상세 검증은 이번 인수 범위 밖이다.


### 최종 자원 대조와 인수 범위

읽기 전용 관측을 한 번 묶어 수행해38개 지표가 모두 true였다. Workbench 원 요청·history·closed admission/lease0, Core cleaned workspace·temp installation archived·origin/slot 반납·대기 delivery0, 임시 전용 PostgreSQL DB와 두 role 부재, 임시 build/runtime 디렉터리 부재, SDK의 세 native unit·unit file·descriptor 부재와 cleaned journal 보존, 임시 container/ingress/network 부재를 확인했다. exact worktree 등록·local branch·tracking ref·remote branch도 없다. 안정 설치는 ready이며 dev 병합 revision의 release/deployment/source handoff, 실제 app/ingress 실행, 안정 DB·role을 보존한다. 앱 고객 record·비밀값·raw log는 조회/출력하지 않았다. 이38개는 자원 상태 지표이며 앱 기능 테스트38건이라는 뜻이 아니다.

이번 **운영자 지원 단일 소유자 대표 흐름**의 필수 인수 잔여는0이다. 앱 업무 코드는 Workbench native AI가 작성·수정했고 관찰자는 플랫폼 실행·회복 경계를 보완했다. 이전 별도 소스 시범은 private archive·복구 bundle 및 기존 데이터를 보존하며 비활성화했고, 새 앱은 같은 MIY 저장소의 dev로부터 기능 branch/worktree에서 작성되어 `personal-apps/app-8565f140`에 병합됐다. 임시 환경 데이터는 안정 개발 데이터와 분리됐고 정리 후 안정 데이터가 유지됐다.

일반 직원 신원·완전 자가 온보딩, embedding이 필요한 의미 검색, 다중 사용자, 전사 공유 업무/세부 앱 기능은 완료로 표시하지 않는다. [후속 개선 기록](workbench-equipment-pilot/IMPROVEMENTS.md)의 DEF 항목은 별도 요청 때 수행한다. 이 인수 시점의 Git 게시·병합 대상은 GitLab origin/dev이며 Core production/GitHub upstream 반영은 아래 후속 릴리스에서 별도로 확인한다.

### 개발 인수 이후 운영·GitHub 전달 (2026-10-11 UTC, 진행 중)

사용자의 후속 승인으로 GitLab dev → main 릴리스, Core/공식 앱 운영 배포,
GitHub main/dev의 정상 PR 동기화와 소유 작업 브랜치 정리를 진행한다.
Workbench r21과 장비 앱의 안정 개발 배포는 앞선 실제 인수 근거를 유지한다.
플랫폼 소스의 운영 배포를 장비 앱의 운영 설치나 Workbench 재배포로 표시하지 않는다.

- [릴리스 MR123](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/123)의
  최초 source는 `2e865ef28e450f06edea69c75ace2d357814f275`다.
  변경에 schema/runtime/공유 계약이 포함되어 전체 릴리스 CI를 선택했다.
  [Pipeline311](https://gitlab.1punicorn.com/lumejs/mty/-/pipelines/311)의
  개인 앱 검사 job487은 통과했지만 플랫폼 job486은 실패했다(3,467초).
  API 준비 단계 오류가 반복되어 4MiB 로그 제한 전에 최종 요약이 남지
  않았고, 기존 artifact에는 전체 검사 실패 상태만 있었다. 실패를 통과로
  취급하지 않고 원인을 보완한 동일 소스의 전체 gate를 다시 요구한다.
- 실제 운영의 기존 six-role 상태·smoke와 새 소스의 운영 설정 해석은 통과했다.
  운영에는 개발 workspace profile을 전달하지 않는다. 최신 릴리스 gate,
  fresh DB/env 백업, 세 immutable artifact 준비·교체와 공개 인수는 남아 있다.
- 검증 중 새 두 Alembic revision이 기존 chain 기대 목록에 빠진 것을 확인했다.
  검색 세대 테스트 두 건도 `apps/api`에서 Core CLI를 호출하면 실행 위치
  검증에 거절되는 것을 좁힌 재현으로 확인했다. 기대 목록과 테스트의 명시적
  checkout cwd를 보완하며 제품의 실행 위치 제한은 유지한다.
  이 두 검색 사례를 포함한 검색 세대4건과 revision 목록1건은 보완 후
  통과했다. 실제 PostgreSQL18의 별도 임시 클러스터에서 전사 앱 권한
  초기화의 `InsufficientPrivilege`도 재현했다. 추가된 보관용 origin 열을
  전체 ORM 조회하면서 제한된 인증 role의 열 권한을 벗어난 문제다.
  설치 인증은 공통13열 조회로 고정하고 제한 reader에는 workspace의
  installation ID·state 두 열만 추가했다(현재15테이블/89열). 보관용 origin,
  workspace 자원과 쓰기 권한은 허용하지 않는다. 실제 현재 schema에서 인증을
  캡처한 뒤 과거 actor/ACL/checked schema로 내려가는 테스트 준비만 보완했으며,
  과거 migration body·SQL guard·현재 작업공간 차단은 유지한다.
  제한 reader 전체, 세 역사 migration 묶음, actor/ACL/checked 실제 양성 흐름,
  workspace 격리의 집중78건이 PostgreSQL18 별도 클러스터에서129초에 통과했다
  (실패/오류/skip0). 독립 읽기 검토 추가 P1/P2 없음. 현재 first-party 운영은
  prepared reader를 활성화하지 않으므로 운영 DB role grant를 변경하지 않는다.
- 로컬 재현에서는 실제 개발 delivery target이 테스트용 플랫폼 origin과
  충돌해 준비 단계가 거절됐다. 공통 테스트 설정에 delivery targets와
  workspace profiles의 빈 목록, 검색 비활성 기본값을 추가해 collection과
  개별 테스트에서 운영자 설정 유입을 막는다. 긍정 사례의 명시적 설정은
  유지하며 실제 `.env`와 제품의 origin 검증은 변경하지 않는다.
- API 전체 runner는 네 구간의 native JUnit을 기존 maintainer 전용 artifact에
  보존하고 짧은 traceback을 사용한다. 검사 선택·네 구간 실행·실패 gate는
  유지하며 raw captured output을 추가 보관하지 않는다. 직접 CI 회귀3건과
  shell/형식/변경 Python13파일 Ruff 검사를 통과했다. 이 집중 검증은 다음
  실제 전체 릴리스 CI를 대체하지 않는다.
- GitHub dev의 독립 여섯 커밋을 조사했다. 기존 기능은 GitLab에서 보존되며
  옛 MTY 명명은 후속 MIY 전환으로 대체된 근거를 확인했다. 각 GitHub
  대상 브랜치의 현재 이력을 부모로 보존하는 snapshot PR을 사용하고,
  최종 GitLab branch별 tree와 일치하는지 정상 병합 전후에 확인한다.
  직접 upstream push 차단과 영속 dev/main은 유지한다.
  [GitHub PR106](https://github.com/hurxxxx/miy/pull/106)(main)과
  [PR107](https://github.com/hurxxxx/miy/pull/107)(dev)은 최초 source의 동일
  tree를 전달한 draft이며, 테스트 보완 후 최종 소스로 갱신할 예정이다.

배포·동기화 완료는 실제 성공한 pipeline/MR/PR와 runtime revision을 확인한
후 이 문서와 게시 체크포인트에 갱신한다. 진행 중 기록은 완료 근거가 아니다.

### 전체 릴리스 재검증의 추가 보완 (2026-10-11 UTC)

[MR124](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/124)의
필수 리뷰 job488이 통과했고 source `8cac328f484e5007a8a6f77c052b49fd668c91eb`를
정상 병합한 dev는 `711d50875b0e11fd02070fc304b9b3bcc93b8baa`다.
[Pipeline313](https://gitlab.1punicorn.com/lumejs/mty/-/pipelines/313)은
개인 앱 job490 성공, 플랫폼 job489 실패다. API fast는 6,685통과·5실패·7skip,
slow는16통과, migration은35통과·2실패, external은15통과했다.
네 구간의 JUnit이 보존되어 실패7건 모두를 확인했다. 뒤의 web/Workbench
전체 검사는 이 pipeline에서 실행되지 않았으며 완료로 계산하지 않는다.

- 작업공간 중지는 설치를 잠근 뒤 요청을 취소하고, 소비자는 요청을 잠근 뒤
  설치를 확인해 잠금 순서가 역전될 수 있었다. 네 동시 소비자 사례의
  PostgreSQL deadlock을 로컬에서도 재현했다. 중지는 잠기지 않은 queued·미예약
  요청만 native `FOR UPDATE SKIP LOCKED`로 취소하도록 보완한다.
  잠긴 요청의 소유권·완료 증거를 유지하며, 미해결 요청이 남으면 유지보수의
  런타임 중지·데이터 정리는 계속 보류한다. 자동 재배포나 DB 재시도를 추가하지 않는다.
- Hermes 한 사례는 권한을 취소하기 전 operation queue 진입 대기의2초 제한에서
  실패했다. 테스트가 native limiter 토큰을 직접 보유해 실제 queue를 확인한 뒤
  권한을 취소·해제하도록 바꾸고, 조기 응답을 즉시 실패시킨다. 제품 권한 검증과
  거절·무부작용 검증은 유지한다.
- 역사 migration 두 사례는 당시 없던 `archived_origin`을 최신 ORM으로 삽입해
  실패했다. 해당 revision의 실제 table을 반영한 fixture INSERT와 명시 열 조회로
  수정하며 기존 데이터 보존·FK·nullable·index·upgrade/downgrade 검증을 유지한다.
  제품 모델과 과거 migration 본문은 변경하지 않는다.

Hermes 지연 I/O·workspace 취소·workspace 기본 흐름 세 파일과 역사 migration
두 사례를 한 번에 검사해52건 모두 통과했다(56.37초, 실패/오류/skip0).
독립 읽기 리뷰에서 추가 P1/P2는 없었고 변경 Python5파일 Ruff·형식·AST·diff
검사를 통과했다. 필수 리뷰·새 전체 릴리스 gate는 아직 진행 중이다.
운영은 기존 source를 유지하며, GitHub PR106/107은 `711d5087`의 동일 tree로
갱신된 draft다. 최종 검증 소스로 다시 갱신하고 정상 병합해야 한다.

### Workbench 역사 스키마와 검사 결과 보존 보완 (2026-10-11 UTC)

[MR125](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/125)는 필수 리뷰
job491을 통과해 dev `7fcc3fbeb00d299838837826d95abe1d6c14d554`로 정상 병합했다.
[Pipeline315](https://gitlab.1punicorn.com/lumejs/mty/-/pipelines/315)의 개인 앱
job493은 통과했다. 플랫폼 job492에서 API 네 구간은 6,760통과·7skip·실패0
(약58.1분), web 검사는 통과했다. Workbench backend는1,404통과·9실패였으며,
뒤의 Workbench build/e2e는 실행되지 않았다. 전체 릴리스 성공 근거는 아니다.

9건 모두 frozen PostgreSQL `console_0011`에 없는 SQLite 전용 `workspace_id`를
현재 Task ORM으로 읽은 역사 fixture 문제였다. 해당 조회에만 native
`defer(..., raiseload=True)`를 적용해 없는 열은 읽지 않으며, 향후 뜻밖의 접근은
실패시킨다. 실제 migration과 복구·출처·기존 문서 보존 assertions는 유지한다.
관련 역사 복구·migration14건을 실제 비운영 PostgreSQL에서 한 번에 확인해
모두 통과했다(13.11초, 실패/오류/skip0). 제품 및 migration 본문 변경은 없다.

또한 후속 Playwright 실행이 `test-results/`를 정리하면서 앞선 API JUnit까지
삭제한 사실을 job492 artifact에서 확인했다. API 보고서를 별도
`api-test-results/`로 옮기고 GitLab artifact·report 등록과 엄격한 CI 계약을
함께 수정한다. maintainer 전용·14일 보존과 네 구간 선택·실패 처리는 유지한다.
브라우저 출력 정리 후에도 네 보고서가 남는 직접 회귀를 포함해 CI 검사3건과
Python/JS/YAML/shell 형식·정적 검사를 통과했다. 필수 리뷰와 다음 전체 CI는
별도로 통과해야 하며 운영 배포·GitHub PR106/107 병합은 아직 완료되지 않았다.

현재 배포·동기화 완료 후에는 사용자가 요청한 API 검사 약1/10 축소를 별도
작업으로 진행한다. 기본 실행 목록만 줄이는 방식에 그치지 않고 중복 테스트를
통합·삭제하며, 실제 소요 시간과 필수 권한·데이터 보존·migration 검증을 확인한다.

최종 공개 문서는 이 파일과 [개선 기록](workbench-equipment-pilot/IMPROVEMENTS.md)이며, 세부 실행 영수증·스크린샷·서비스/SQLite 백업은 비공개 `.runtime/workbench-workspaces-20261011/deployment/`와 전용 backup 경로에 보존한다. private evidence나 설정 파일을 Git에 추가하지 않는다.
