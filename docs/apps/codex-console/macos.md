# macOS Workbench 호스트 설치

기본 운영 문서는 [Linux 설치·systemd 서비스](README.md#설치)를 기준으로 한다. 이 문서는
macOS에서 달라지는 실행 도구·LaunchAgent·데이터 이전만 다룬다. 인증·저장소·권한·검증 계약은
[공통 Workbench 문서](README.md)를 따른다.

소유자로 로그인한 Mac에서는 `launchd`의 사용자 LaunchAgent로 관리·세션·템플릿 세 프로세스를
실행한다. Docker Desktop은 개발 대상 앱을 실행하는 도구로 사용하며 Workbench 자체를 띄우지
않는다. 소스 밖의 전용 영구 디렉터리에 DB·첨부·Codex 세션을 보관한다. 개인 CLI의 기존
`~/.codex`와 병합하지 않고 전용 `CODEX_HOME`을 유지한다. 일반 작업의 계획/승인/YOLO 선택은
그대로 적용하며, 호스트 YOLO는 해당 Mac 사용자 계정의 접근 범위에서 실행된다.

1. [공통 설치 조건](README.md#설치)을 만족하는 **Mac용** Python과 버전별 고정 Codex를 준비한다. Linux 바이너리,
   virtualenv, `node_modules`를 복사해 재사용하지 않는다. `scripts/build-codex-console.sh`로
   새 릴리스를 만들고 별도 `current` 링크를 선택한다.
2. 소유자 전용 0600 환경 파일에 기존 origin·세 포트·작업 경로·권한을 유지하면서
   `MIY_CODEX_CONSOLE_DATABASE_URL`, `MIY_CODEX_CONSOLE_ATTACHMENT_CACHE`, `CODEX_HOME`을
   실제 호스트 경로로 지정한다. CLI 두 경로는 검증한 Mac용 고정 파일을 선택하고
   `MIY_CODEX_CONSOLE_WEB_DIST`는 선택한 릴리스의 정적 파일을 가리킨다.
   `--env-file`은 이 파일을 셸 실행이나 변수 치환 없이 읽어 자식 Codex에도 전달한다.
3. 새 설치에만 migration·비밀번호 초기화를 수행한다. 기존 설치 이전에서는 아래 데이터 이전
   절차를 먼저 완료하며 `set-password`로 기존 웹 로그인을 초기화하지 않는다.
4. 설치 도구로 세 plist를 생성한다. 이 명령은 실행 중 서비스를 중지하거나 새 서비스를
   시작하지 않는다. 기존 plist 교체는 모든 작업 종료·서비스 중지 후 `--replace`로 수행한다.

```bash
workbench_root="$HOME/.local/share/miy-workbench"
python3 scripts/install-workbench-launchd.py \
  --release "$workbench_root/current" \
  --env-file "$workbench_root/config/console.env" \
  --logs "$workbench_root/logs"
for role in session templates management; do
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.miy.workbench.$role.plist"
done
```

LaunchAgent는 이 사용자의 로그인 시 시작되고 로그아웃 시 종료된다. 설치 시 저장한 `PATH`에
Git·Node·pnpm·uv·Docker CLI가 모두 있어야 한다. 상태 확인은
`launchctl print "gui/$(id -u)/com.miy.workbench.session"`과 세 포트의 `/healthz`를 사용한다.
업데이트/중지는 root·하위 agent·승인 대기 작업이 모두 끝난 후 management부터
`launchctl bootout "gui/$(id -u)/com.miy.workbench.<role>"`로 중지하고, 새 릴리스를 선택한 뒤
위 `bootstrap`을 수행한다. 키·세션·환경 파일 내용을 진단 출력에 노출하지 않는다.
macOS에서는 Linux `/proc` 메모리 관측이 제공되지 않으며 디스크·CPU·부하 관측은 유지한다.
별도 Linux executor가 필요한 격리 앱 실행 기능은 해당 executor 설정을 그대로 사용한다.

## Docker에서 호스트로 데이터 이전

- root와 하위 작업·응답 대기가 모두 끝났는지 확인하고 management로의 새 접수를 막는다.
  Workbench 전용 SQLite는 online backup으로 무결성을 검증하고, 세 Workbench 프로세스를
  중지한 뒤 전용 `CODEX_HOME` 전체와 등록 credential·첨부 데이터를 별도 0700 디렉터리에 복사한다.
  원래 Docker 볼륨과 이미지는 복구용으로 유지한다. 실행 중 SQLite 본체만 복사하지 않는다.
- DB의 작업·이벤트·첨부·브랜치 연결·요약·웹 세션 수와 원본 bytes를 비교한다. 경로·내용을
  출력하지 않고 전용 파일 소유자를 호스트 사용자로 맞춘다. 새 `CODEX_HOME`에서 공식
  `thread/read`·`thread/resume`으로 같은 thread ID와 기존 이력을 확인한다. 검증 중 새 턴을 시작하지 않는다.
- Codex **0.162.1**의 paginated thread는 DB에 이전 rollout 절대 경로를 저장한다. 공개 resume의
  `path` 지정도 stale path로 거절되므로, 경로가 바뀌면 중지된 **복사본**에만 버전 한정
  [이전 도구](../../../scripts/relocate-workbench-codex.py)를 적용한다. 대상 rollout의 실제 경로·
  session ID와 DB 무결성을 검사하고 원본 index를 백업한 뒤 `state_5.sqlite`의
  `threads.rollout_path`만 이전한다. 대화 ID·내용·history DB·rollout bytes는 수정하지 않는다.
  이는 설치 이전용 어댑터이며 실행 중 Workbench는 native DB를 직접 변경하지 않는다.

  ```bash
  /absolute/path/to/verified-python3 scripts/relocate-workbench-codex.py \
    --home "$workbench_root/codex" --previous-home /var/lib/miy-codex \
    --backup "$workbench_root/backups/native-state-before-relocation.sqlite3" \
    --codex-binary /absolute/path/to/pinned/codex --services-stopped
  ```

- 작업 준비 helper의 Python·uv·pnpm·private runtime 경로도 Mac 도구로 바꾼다. 이전 Linux
  의존성 캐시는 보존하되 호스트에서 실행하지 않는다. `task_setup`은 Linux/macOS에서 동일한
  lockfile·작업별 격리 규칙으로 새 의존성을 준비하며 서비스를 임의로 시작하지 않는다.
- Docker의 Workbench 세 서비스는 자동 재시작을 끄고, 기존 Compose 기본 시작 대상에서도
  제외한다. 두 실행기가 같은 대화 저장소를 동시에 사용하지 않게 한다. 데이터 볼륨 삭제나
  `compose down -v`는 이전 절차에 포함하지 않는다.
- 같은 관리 URL에서 로그인·기존 작업·첨부·동일 대화 재개·Docker 조회를 확인한다. 실패하면
  호스트 프로세스를 중지하고 보존한 컨테이너·볼륨으로 복원한다. 호스트에서 새 작업이 생긴 뒤에는
  이전 스냅샷으로 바로 되돌리지 말고 최신 DB와 native 세션을 먼저 보존한다.
