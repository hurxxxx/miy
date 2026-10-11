# API 검사 통합·축소

기준: 2026-10-11 UTC. 사용자는 API 검사 수를 약 1/10로 줄이고 **중복 테스트 자체도 대폭 통합·삭제**하도록 요청했다. 기존 개발·운영·Workbench 배포와 GitLab/GitHub 동기화를 완료한 뒤 구현·로컬 검증을 마쳤다. **6,768건 → 866건, 87.2% 감소**이며, 전체 배치와 수정 범위 재검증을 합친 최종 근거는 **861 통과·기존 skip 5건**이다. 사용자 요청에 따라 이 테스트·문서 묶음을 GitLab과 GitHub의 `dev`에 정상 리뷰·병합으로 동기화한다. 최종 게시 결과는 해당 MR/PR 상태가 소유하며, 실행 코드 변경이 없어 서비스 재배포는 필요하지 않다.

초기 약 700건 목표에는 도달하지 못했다. 현재는 원래의 **12.8%, 약 1/8**이다. 독립 대조 후에도 구별되는 SQL 역할·잠금·권한 취소·커밋 결과 불확실·영속 데이터 보존 경계를 남겼다. 정확히 1/10을 달성했다고 표시하지 않는다.

## 비교 기준

성공한 [전체 pipeline323](https://gitlab.1punicorn.com/lumejs/mty/-/pipelines/323)의 제품 source는 `3a411c3a84f61de443bae62c7b9ef8f7df88b7e8`이다. API는 **6,761 통과·기존 7 skip, 총 6,768건**이고, 정적 검사를 포함한 API 단계의 실제 경과 시간은 **3,029.876초(50분 30초)**다. 개별 testcase 시간 합산으로 성과를 계산하지 않는다. 변경 전 전체 검사를 다시 실행하지 않는다.

후속 배포 문서의 [MR130](https://gitlab.1punicorn.com/lumejs/mty/-/merge_requests/130)은 필수 review324/job506을 통과했다. 축소 작업의 시작점은 dev `249163cbb92340d9e43e7397d9f31573c564e36c`이며, 이 시점에는 GitHub [main PR106](https://github.com/hurxxxx/miy/pull/106)·[dev PR107](https://github.com/hurxxxx/miy/pull/107) 병합, 각 GitLab 대응 branch의 tree 일치와 소유 임시 branch/worktree 정리가 완료됐다. 제품 전체 검사는 문서만 다른 이 시작점에도 재사용한다.

## 변경 원칙

- 반복 CRUD·표시·단순 getter/DTO·같은 정책의 과도한 parameter 조합을 실제로 삭제한다. 선택 목록을 숨기거나 skip을 추가해서 수를 맞추지 않는다.
- 같은 자원의 생성→사용→권한 취소→정리를 자연스러운 수명 흐름으로 통합한다. 기존 검사를 그대로 호출하거나 대형 반복문에 넣어 개수만 줄이지 않는다.
- 서버 인증·현재 앱 admission/원본 ACL, 실제 PostgreSQL 역할·잠금·동시 실행·migration, 결과 불확실 시 재실행 방지, 영속 데이터 보존과 정확한 임시 자원 정리를 남긴다.
- 테스트 간에 사용하는 fixture/helper를 보존한다. 제품 코드·권한·DB 계약·CI gate를 완화하지 않는다.

## 구현 결과

독립 에이전트 3개와 통합 담당이 378개 테스트 파일의 소유 범위를 나눴다. 아래 수는 함수 개수나 AST 추정이 아닌 실제 JUnit 사례 수다.

| 영역 | 이전 | 현재 |
| --- | ---: | ---: |
| Files·검색·원본 접근 | 2,432 | 210 |
| AI·Hermes | 890 | 155 |
| Whiteboard·작업 환경 | 1,124 | 125 |
| 인증·기반 인프라 | 1,131 | 168 |
| 전사 앱 | 444 | 63 |
| 공통 경계 | 270 | 72 |
| 나머지 어댑터 | 477 | 73 |
| **합계** | **6,768** | **866** |

반복 CRUD·DTO·표시·getter·같은 정책의 parameter 조합을 삭제했다. 공유→게시→권한 취소, 작업 종료→기존 실행 권한 차단→정리, Mail 동기화→원격 삭제, 앱 원본 export→build처럼 같은 자원의 흐름으로 합쳤다. 기존 테스트를 다른 테스트에서 호출하거나 큰 반복문으로 옮겨 숫자를 줄이지 않았다. 테스트 간 helper/re-export와 CI가 직접 지정하는 계약 검사 파일을 보존했다. 제품·마이그레이션·전역 fixture·CI 명령과 gate는 바꾸지 않았다.

실제 PostgreSQL의 역할·잠금·동시 실행, Workspace claim/rollback 경합 6개와 PMS 경합 3개, checked save의 CAS/ABA/unknown, 기존 세션의 현재 권한 재검사, 마지막 관리자 보호, 영속 데이터와 임시 자원 구분을 유지했다. MR129의 DB 준비 timeout 시 재시도·역할 삭제 금지 및 실제 읽기 전용 Whiteboard 연결, configured readiness와 live AI probe 구분도 실행 근거에 포함한다. 기존 Docker opt-in skip 7개 중 2개는 중복 정리 과정에서 삭제했고, 남은 5개는 기존 사례·사유와 일치한다. 새 skip/xfail은 없다.

## 실제 검증과 시간

영역별 pytest나 별도 collection을 반복하지 않고, 통합 후 기존 `pnpm ci:api:full`로 architecture/lint/typecheck와 fast·slow·migration·external 네 구간을 실행했다. 기준과 동일한 검증 이미지 `sha256:1999eaca49049d0d3eca5cb937452ef1dc7a7c8a9467f907f7dbc89403c6c5b3`와 fast 2 workers를 사용했다.

| 실행 | 결과 | 실제 경과 시간 |
| --- | --- | ---: |
| 최초 전체 API 배치·정적 검사 | 853 통과·5 skip·8 실패 | 587.874초 |
| 수정한 7개 함수의 8개 사례·범위 lint/format | 7 통과·1 실패 | 19.761초 |
| 남은 공급자 수명 사례·범위 lint/format | 1 통과 | 12.860초 |
| **실행 시간 합계** | **기존 통과 + 수정 범위 통과: 861 통과·5 skip** | **620.495초, 10분 20초** |

최초 네 구간은 fast 823 통과·5 skip·8 실패, slow 3 통과, migration 21 통과, external 6 통과였다. 실패를 지우거나 최초 전체 명령의 exit 1을 성공으로 바꾸지 않았다. 수정 후 전체를 다시 실행하지 않고 기존 통과와 영향 범위 재검증을 결합했다. 이는 새 전체 CI가 녹색이라는 주장이나 향후 필수 gate 면제가 아니다.

실패는 통합된 테스트의 준비·관측 오류였다. 공유 해제의 정확한 HTTP 204와 비활성 공급자의 공개 오류 코드를 반영하고, Mail의 bulk 삭제 뒤 실제 DB를 조회했다. 첫 원본 revision의 Core acceptance 경쟁을 다음 revision 생성보다 먼저 확인하도록 순서를 고쳤다. build 디렉토리 준비, queued/succeeded 실행 기록 두 개의 정확한 식별자, native registry 의존성을 보완했다. 마지막 공급자 삭제는 이 테스트가 만든 정확한 선택 정책을 먼저 해제해 기존 RESTRICT FK를 준수했다. 권한 검사·외래 키·timeout·제품 동작은 완화하지 않았다.

검증 전에는 외부 통신이 차단된 컨테이너가 선언된 Python 빌드 의존성을 내려받지 못해 28.814초 후 멈췄다. 이때 pytest는 시작되지 않았다. 검증 컨테이너에만 외부 연결을 추가하고 동일 source hash로 재개했다. 위 620.495초에는 이 준비 실패와 수정 작업 시간은 포함하지 않는다. 준비 실패까지 합친 명령 실행 시간은 649.309초다.

이전 성공 배치 3,029.876초 대비 보정 재검증을 포함한 실행 시간은 관측상 **79.5% 감소**했다. 같은 이미지·worker 수의 단회 비교이며 호스트 부하 등 차이가 있어 일정한 배속을 보장하지 않는다. testcase duration의 합을 wall time으로 사용하지 않았다.

## 게시 리뷰에서 보완한 필수 경계

[필수 review325/job507](https://gitlab.1punicorn.com/lumejs/mty/-/pipelines/325)은 등록 workload 우회 탐지가 대체 없이 삭제된 점을 지적해 병합을 차단했다. 삭제한 legacy gateway matcher를 기존 호출 경로 검사에 통합하고, API·worker 범위와 matcher별 원래 예외 목록을 그대로 보존했다. API의 저수준 호출 허용 파일이 workload 검사까지 건너뛰지 않으며 worker의 legacy 호출에는 예외가 없다. 이 실패 리뷰를 성공으로 바꾸지 않고 수정 source를 새 필수 리뷰에 제출한다.

실제 소스 검사 함수 3개를 직접 실행하고 합성 소스의 우회 거부 5개·정상 허용 3개를 확인해 모두 통과했다(0.420116초). `complete_gateway_chat_text(request, db)`가 API·worker에서 거부되고 두 허용 목록이 서로 확대되지 않음을 확인했다. 범위 Ruff check·format도 통과했다. 이 결과는 DB나 pytest/JUnit 실행이 아닌 순수 소스 검사이며 기존 전체·영향 범위 근거에 추가한다. 테스트 함수는 3개로 유지해 전체 사례 수 866건은 변하지 않았다. 비공개 `gateway-guard-review-fix.json`이 최종 source hash와 실행 근거를 소유한다.

## 범위·근거·남은 한계

실제 `.env`·제품 데이터·인증 정보를 연결하지 않은 전용 PostgreSQL 18·Redis·MinIO·OpenSearch와 검증 컨테이너를 사용했다. 원 실패와 네 JUnit, 재검증 JUnit, 정확한 source hash, 집계 결과는 로컬 비공개 `.runtime/api-test-reduction-20261011/`에 남겼다. 최종 판정은 `corrected-validation-acceptance.json`, 정리 결과는 `isolated-infra-cleanup.json`이 소유한다. 정확한 ID·label을 확인해 이번 컨테이너 5개·네트워크 2개·합성 환경 파일 4개를 정리했다. 개발·운영 서비스와 데이터는 변경하지 않았다.

상세 기능별 회귀 검출 범위는 줄어들었다. 제거한 표시·DTO·개별 CRUD의 모든 동작을 계속 보장한다는 의미가 아니다. 앱별 기능 변경 시 관련 위험에 맞는 대표 검사를 추가하고, 의미 검색·일반 직원 계정·다중 사용자 등 기존 별도 검증 범위는 그대로 둔다. 게시에는 현재 source의 필수 리뷰와 정상 MR/PR 병합을 적용한다. 이전 검증 결과를 재사용하되 새 CI 성공으로 바꾸어 기록하지 않는다. 운영 `main` 승격과 서비스 배포는 이 테스트 동기화 범위에 포함하지 않는다.
