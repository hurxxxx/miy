# Files publication 업로드 경계 구현 계획

2026-10-07 UTC. [FILES_SOURCE_RESULTS.md](FILES_SOURCE_RESULTS.md)의 F4 필수
불변 입력 준비다. Source publication schema·트리 조립과 실제 서비스 전환은
이 transport를 인수한 뒤 별도로 구현한다. 현재 250MiB 일반 업로드 계약을
유지하며 기존 upload endpoint·MinIO client·F2 고정 SQL은 변경하지 않는다.

## 이번 구현 범위

- Source가 보관할 publication/operation UUID와 unique key를 명시적으로 받는
  작은 비활성 adapter를 추가한다. 새 UUID/key 생성·자동 retry·삭제·관측에
  따른 재전송은 없다. actor/app/ACL과 durable attempted permission은 이후
  Source 명령이 소유하며 transport에 입력했다고 권한을 얻지 않는다.
- 고정 public MinIO presigner는 명시적 endpoint/bucket/region/static credentials로
  로컬에서만 URL을 만든다. HTTPX async transport는 proxy/redirect/retry를
  사용하지 않고 기존 MinIO/selected reader의 CA 정책과 TLS 검증을 유지한다.
  signed URL·key·headers·provider 오류
  본문은 adapter 밖 오류나 로그에 노출하지 않는다.
- Source가 소유하는 열린 regular spool FD의 실제 bytes를 최대 64KiB씩 읽어
  전송한다. caller FD는 닫지 않고 전체 파일을 메모리로 복제하지 않는다.
  크기는 0..250MiB, 실제 전송 bytes의 길이와 SHA256을 검증한다. FD/type/크기,
  digest·UUID·configuration 오류는 전송 전에 거부한다. 전송 도중 변경·읽기
  실패는 불명확한 외부 효과로 분류한다.
- 고정 PUT+ACK socket-I/O timeout 120초·단계 timeout 5초·process별 동시 전송
  최대2로 제한한다. response/transport 정리는 각각 별도5초 cooperative
  timeout으로 제한한다. 이미 발생한 총 timeout을 정리에서 격리한 뒤 다음
  close가 무한히 기다리지 않아야 한다. 정상 socket 경계는 PUT+ACK120초와
  최대 정리10초를 구분하며 서비스 전체 동시성은 F5 조립이 소유한다.
  overload는 대기열 없이 거부한다. 이 async 경계는 socket 취소를 검증하며
  bounded local regular-file read·SDK presigning CPU를 강제로 중단하는
  wall-clock 보장은 주장하지 않는다. 무한 background thread를 만들지 않는다.
- HTTP 200과 하나의 유효한 opaque VersionId, 실제 body 전송 완료 및 bounded
  응답 완료를 모두 확인해야 receipt를 반환한다. null/missing version·redirect,
  status/timeout/cancel·length/digest mismatch는 완료가 아니다. 마지막 정리
  실패는 이미 확인한 ACK나 원래 unknown/cancellation을 가리지 않는다.

## 구현·검증 순서와 소유

1. Delivery: 새 `publication_storage.py`·집중 테스트·인접 runtime owner 문서.
   공개 SDK를 재사용하고 ordinary storage/reader는 변경하지 않는다. 실제
   로컬 TCP에 대한 성공·size/hash·early response·timeout/cancellation·cleanup,
   bounded concurrency·private logging·버전 ACK 경계를 검증한다.
2. Data: 읽기 전용 SDK 계약 검토와 disposable owned MinIO probe를 별도 경로에
   작성한다. cached image만 사용하며 loopback 임시 endpoint에서 versioning,
   0/small/250MiB PUT·정확한 version 고정 GET/SHA와 overwrite 후 old version을
   검증한다. Source schema/role·공유 bucket/configuration은 변경하지 않는다.
3. Structure: 작성자와 분리해 전송 전 거부/전송 후 unknown·완료 ACK·정리,
   bounded resources·응답/로그·기존 공개 계약 보존을 검토한다. 실패는 먼저
   재현하고 수정 뒤 현재 입력 hash와 근거를 확인한다.
4. Root: 현재 계획·진행·검증 대장을 갱신하고 affected lint·architecture를
   확인한다. 이후 Source publication record의 최소 active File hold·불변
   version binding·원자 canonical/event apply 설계를 구현 계획으로 확정한다.

각 실행은 선택 입력 before/after, `.env` 읽기 없음·허용한 owned loopback 외
접속 없음·소유 자원 정리를 기록한다. 서로 겹치는 검사 수와 후기 변경을
이전 동결 결과에 소급하지 않는다. 실제 MinIO 검증 없이 SQL row의 version
문자열을 remote ACK 증거로 인정하지 않는다.

## 완료 기준과 후속 구조 gate

집중 테스트·실제 owned MinIO·독립 리뷰가 통과해야 이 비활성 transport만
인수한다. 그것이 Source publication·권한·company audit·pinned prepared read,
version-specific cleanup·tree/bootstrap·durable Core caller checkpoint 또는
F5 전체 서비스 조립의 완료를 뜻하지 않는다. 중요한 미해결 구조는 앱별
후속 이슈로 넘겨 완료 처리하지 않는다. 게시·배포·공유 서비스 변경은 없다.

## 현재 인수 상태

2026-10-07 16:23 UTC — 이 transport 범위는 로컬 비활성 인수 완료다. 최신
focused68·현재selected21, 실제0/small/250MiB PUT과 exact version SHA/size·
overwrite 뒤 old version을 확인했다. actual missing-Version2 case는 remote
bytes가 있어도 같은 IDs의 Unknown으로 남고 retry/delete가 없다. 작성자 외
리뷰 blocker0과 lint·API architecture/i18n을 확인했다. 초기 실패·후기 probe
fixture 변경과 실제/합성 검증은 [VALIDATION.md](VALIDATION.md)가 소유한다.
현재 런타임 계약은
[PUBLICATION_STORAGE.md](../apps/api/src/miy_api/domains/files/PUBLICATION_STORAGE.md)다.
다음 Source aggregate·publication/apply·기존 파일/managed 전환과 F5 조립은
[FILES_SOURCE_RESULTS.md](FILES_SOURCE_RESULTS.md)의 필수 후속 순서로 유지한다.
