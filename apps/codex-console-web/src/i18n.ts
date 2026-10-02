export const korean = {
  'Root folder': '최상위 폴더',
  'All documents': '전체',
  'Supporting files': '참고·설정',
  'Document types': '문서 종류 필터',
  'Document library': '문서 목록',
  'No matching documents': '검색한 문서가 없습니다',
  'Show document list': '문서 목록 보기',
  'Document view': '문서 보기 방식',
  'Read document': '읽기',
  'Edit source': '편집',
  Skills: '스킬',
  Documents: '문서',
  'Document preview': '문서 미리보기',
  'No unsaved changes': '변경 없음',
  'Save your changes before asking Codex.':
    'Codex에 요청하기 전에 변경을 저장하세요.',

  'Latest saved content': '최신 저장 내용',
  'Keep my draft against this version': '이 버전을 기준으로 내 초안 유지',
  'Use the latest saved content': '최신 저장 내용으로 교체',
  'Instructions and skills': '지침·스킬',
  'Edit the files Codex reads, or ask Codex to improve them.':
    'Codex가 참조하는 원본 문서를 편집하거나 Codex에 개선을 요청하세요.',
  'New document': '문서 만들기',
  'How Codex uses these files': '문서가 적용되는 방식',
  'AGENTS.md supplies persistent instructions. AGENTS.override.md takes precedence in the same folder. More specific folders add their own instructions.':
    'AGENTS.md는 작업 지침입니다. 같은 폴더에서는 AGENTS.override.md가 우선하고, 하위 폴더 지침이 더 구체적인 규칙을 추가합니다.',
  'SKILL.md defines a reusable procedure with a name and description. Codex can choose matching skills automatically; selecting a skill explicitly requests it.':
    'SKILL.md는 이름·설명이 있는 재사용 작업 절차입니다. 설명이 맞으면 Codex가 자동 선택할 수 있고, 체크하면 명시적으로 사용을 요청합니다.',
  'agents/openai.yaml can set allow_implicit_invocation to false. References hold supporting Markdown. Installed plugins and system skills are managed by their installer.':
    'agents/openai.yaml에서 allow_implicit_invocation을 false로 설정하면 자동 호출을 끌 수 있습니다. references에는 참고 문서를 둡니다. 설치된 플러그인·시스템 스킬은 설치 도구로 관리합니다.',
  'Instruction changes apply to new sessions. Start a new session to verify them. Skill discovery is refreshed from the original files.':
    '지침 변경은 새 세션에서 확인하세요. 스킬 목록은 원본 파일에서 다시 불러옵니다.',
  'Official instruction documentation': '공식 지침 문서',
  'Official skill documentation': '공식 스킬 문서',
  'Document scope': '적용 범위',
  'Project documents': '프로젝트 문서',
  'Personal skills': '개인 스킬',
  'Global instructions': '전역 지침·스킬',
  'Search documents': '문서 검색',
  'Loading documents': '문서 불러오는 중',
  'Agent documents': '에이전트 참조 문서',
  Instructions: '지침',
  Skill: '스킬',
  'Skill metadata': '스킬 메타데이터',
  Reference: '참고 문서',
  'No documents in this scope': '이 범위에 문서가 없습니다',
  'Document editor': '문서 편집기',
  'Document content': '문서 내용',
  'Unsaved changes': '저장하지 않은 변경',
  'Ask Codex to edit': 'Codex에 수정 요청',
  'Reload document': '문서 다시 읽기',
  'Load latest version and keep my draft': '최신 버전 확인 후 내 초안 유지',
  'Save your changes before asking Codex. Drafts stay here while navigating the console.':
    'Codex에 요청하기 전에 변경을 저장하세요. 콘솔 메뉴를 이동해도 작성 중인 초안은 유지됩니다.',
  'Choose an agent document': '참조 문서를 선택하세요',
  'Open a file to edit it, or create instructions or a skill at an official location.':
    '파일을 열어 편집하거나 공식 경로에 지침·스킬을 만드세요.',
  'Document type': '문서 종류',
  'Document path': '문서 경로',
  'Paths are relative to the selected scope. Subfolder instructions and skill references are supported.':
    '선택한 범위의 기준 폴더에서 상대 경로를 입력하세요. 하위 폴더 지침과 스킬 참고 문서를 지원합니다.',
  'Open document': '문서 열기',
  'Requested changes': '수정할 내용',
  'Planning proposes changes without editing. Implementation uses the existing Codex permissions and approval flow. Results open in a new session.':
    '계획 모드는 변경안을 제안합니다. 실행 모드는 기존 Codex 권한·승인 절차로 수정합니다. 결과는 새 세션에서 확인합니다.',
  'Send request': '요청 보내기',
  'Explicit skills for this run': '명시적으로 사용할 스킬',
  'Selected skills are explicitly requested. Codex can also choose unselected skills when their descriptions match, unless implicit invocation is disabled.':
    '체크한 스킬은 이번 실행에 명시적으로 요청합니다. 체크하지 않아도 설명이 작업과 맞으면 자동으로 사용할 수 있습니다. 자동 호출을 끈 스킬은 제외됩니다.',
  'This document changed elsewhere. Your draft is preserved; review the latest version before saving.':
    '다른 곳에서 문서가 변경되었습니다. 초안은 유지됩니다. 최신 버전을 확인하고 저장하세요.',
  'Agent documents must be UTF-8 text under 64 KiB.':
    '참조 문서는 64 KiB 이하 UTF-8 텍스트여야 합니다.',
  'SKILL.md needs YAML frontmatter with name and description.':
    'SKILL.md 상단에 name과 description이 있는 YAML 메타데이터가 필요합니다.',

  'Back to sessions': '세션 목록으로',
  Pinned: '고정됨',
  Sessions: '세션',
  'All sessions': '전체 세션',
  'Session views': '세션 보기',
  'Search sessions': '세션 검색',
  'Import Codex session': 'Codex 세션 불러오기',
  'Find conversations, follow running work, and respond to requests.':
    '대화를 이어가고, 실행 상황과 확인이 필요한 요청을 살펴보세요.',
  'No matching sessions': '검색한 세션이 없습니다',
  'No sessions yet': '아직 세션이 없습니다',
  'Session list could not be refreshed. Showing the last received state.':
    '세션 목록을 갱신하지 못했습니다. 마지막으로 받은 목록을 표시합니다.',
  'Template actions': '템플릿 더보기',
  Actions: '동작',
  Status: '상태',
  Task: '작업',
  Resource: '항목',
  Details: '상세',
  'Execution settings': '실행 설정',
  'Search templates': '템플릿 검색',
  'Search templates by name or description': '템플릿 이름이나 설명으로 검색',
  'Templates shown': '표시된 템플릿',
  'No matching templates': '검색한 템플릿이 없습니다',
  'Clear filters': '필터 초기화',
  'No runs from this template yet': '아직 실행 이력이 없습니다',
  'Run this template to see agent status and results here.':
    '템플릿을 실행하면 이곳에서 에이전트 상태와 대화·결과를 확인할 수 있습니다.',
  'Browse native Codex sessions and open them in your workspace.':
    'Codex 원본 세션을 찾아 작업실에서 이어서 확인하세요.',
  'An execution service is unavailable. Showing the last reported agent state.':
    '일부 실행 서비스의 상태를 확인할 수 없습니다. 마지막으로 보고된 에이전트 상태를 표시합니다.',
  Workspace: '작업 경로',
  'Current step': '현재 단계',
  'Codex sessions': 'Codex 세션',
  Finished: '종료',
  'Search tasks by title': '작업 제목으로 검색',
  'Task source': '작업 유형',
  'All sources': '모든 작업 유형',
  'Matching tasks': '표시된 작업',
  'Recent work is shown here. Search by title to find older runs.':
    '최근 작업과 추적 중인 작업을 표시합니다. 이전 이력은 제목으로 검색하세요.',
  'Choose another filter, or start a new task.':
    '다른 조건을 선택하거나 새 작업을 시작하세요.',
  'Pending requests': '대기 중인 요청',
  'Respond to requests': '요청 확인',
  'Open conversation and results': '대화·결과 열기',
  'Agent activity': '에이전트 활동',
  'Close agent activity': '에이전트 활동 닫기',
  'Running agents': '실행 중 에이전트',
  'Recently finished': '최근 종료',
  'Awaiting confirmation': '상태 확인 대기',
  'Result ready': '결과 확인 가능',
  'Loading agent activity': '에이전트 활동 불러오는 중',
  'Updates delayed': '상태 갱신 지연',
  'Updates delayed. Showing the last received state.':
    '상태를 갱신하지 못했습니다. 마지막으로 받은 상태를 표시합니다.',
  'Follow parallel work and return to its results.':
    '병렬로 실행 중인 작업과 종료된 결과를 한곳에서 확인합니다.',
  'Start a task or template. Its agents will appear here.':
    '작업이나 템플릿을 실행하면 이곳에 에이전트 상태가 표시됩니다.',
  'Agent details': '에이전트 상세',
  'List refreshed': '목록 갱신',
  'View all runs': '전체 실행 이력',
  Updated: '갱신',
  Copy: '사본',
  Edit: '편집',
  Implement: '실행',
  'Task templates': '작업 템플릿',
  'Task template': '작업 템플릿',
  'Template run history': '템플릿 실행 이력',
  'Selected template': '선택한 템플릿',
  'Archived template': '보관된 템플릿',
  'Runs from every version of this template. Each run keeps its original settings.':
    '이 템플릿의 모든 버전에서 실행한 작업입니다. 각 작업에는 실행 당시 설정이 보존됩니다.',
  'Template details are unavailable. The history filter is still applied.':
    '템플릿 정보를 불러오지 못했습니다. 이력은 선택한 템플릿으로 계속 제한됩니다.',
  'Run history': '실행 이력',
  Monitoring: '모니터링',
  'Your Codex workspace': 'Codex 작업 공간',
  'Console navigation': '콘솔 메뉴',
  'Open navigation': '메뉴 열기',
  'Save the context once. Start each run in a new Codex session.':
    '작업 맥락을 미리 저장하고, 실행할 때마다 새 Codex 세션에서 작업합니다.',
  'Create template': '템플릿 만들기',
  'Selected service': '선택한 서비스',
  'Show archived templates': '보관한 템플릿 표시',
  'Loading templates': '템플릿 불러오는 중',
  'No templates yet': '아직 저장한 템플릿이 없습니다',
  'Isolated workspace': '별도 작업 공간',
  'Shared workspace': '공유 작업 공간',
  'Request details': '요청 내용',
  'Run template': '실행',
  Duplicate: '복제',
  'Restore template': '템플릿 복원',
  'Archive template': '템플릿 보관',
  'Edit template': '템플릿 편집',
  'Template name': '템플릿 이름',
  Description: '설명',
  'Working directory relative to project': '프로젝트 기준 작업 경로',
  Prompt: '프롬프트',
  'Run inputs': '실행 시 입력값',
  'Use {{name}} in the prompt or context. Values are inserted as text.':
    '프롬프트나 맥락에 {{name}}을 넣으면 실행 시 입력한 값으로 바뀝니다.',
  'Input name': '입력값 이름',
  'Input label': '화면에 표시할 이름',
  'Default value': '기본값',
  Required: '필수',
  'Remove input': '입력값 삭제',
  'Add input': '입력값 추가',
  'Additional context': '추가 맥락',
  'Reference paths, one per line': '참고 파일 경로 (한 줄에 하나)',
  'Template runner is unavailable. Saved templates can still be edited.':
    '템플릿 실행 서비스에 연결할 수 없습니다. 저장한 템플릿은 계속 편집할 수 있습니다.',
  'Codex default': 'Codex 기본 설정',
  'Serialize changes to shared server resources':
    '서버 공용 자원을 사용하는 다른 작업과 동시에 실행하지 않기',
  'Save template': '템플릿 저장',
  'Server observations and native Codex agent activity.':
    '서버 상태와 Codex 에이전트의 활동을 확인합니다.',
  'Each template run keeps its own conversation and execution settings.':
    '각 실행의 대화와 당시 실행 설정을 별도로 보관합니다.',
  'Server resources': '서버 자원',
  Memory: '메모리',
  Swap: '스왑',
  Disk: '디스크',
  'Cgroup limit applied': '적용된 메모리 한도',
  'CPU load': 'CPU 부하',
  'Load averages: 1, 5, 15 minutes': '최근 1분 · 5분 · 15분 평균 부하',
  Available: '사용 가능',
  'Use a task template': '템플릿으로 작업 요청',
  'Codex compatibility': 'Codex 호환성',
  'Installed CLI': '설치된 CLI',
  'Template runner CLI': '템플릿 실행용 CLI',
  'Console contract baseline': '콘솔 검증 기준 버전',
  'Version differences require protocol verification. Run the compatibility template when needed.':
    '버전이 다르면 프로토콜 호환성 확인이 필요합니다. 필요할 때 호환성 업데이트 템플릿을 실행하세요.',
  'Open update templates': '업데이트 템플릿 열기',
  'No active tasks': '진행 중인 작업이 없습니다',
  'Template runs': '템플릿 실행',
  'Template run': '템플릿 작업',
  'Run settings': '실행 당시 설정',
  'Saved request': '실행한 요청',
  'Template version': '템플릿 버전',
  'The template changed. Reload it before saving or running.':
    '템플릿이 변경되었습니다. 다시 불러온 뒤 저장하거나 실행하세요.',
  'The template is unavailable or archived.':
    '템플릿을 찾을 수 없거나 보관된 상태입니다.',
  'Check the required template inputs.': '템플릿의 필수 입력값을 확인하세요.',
  'The request identifier was already used with different inputs.':
    '다른 입력값에 사용된 요청 번호입니다. 템플릿을 다시 열어 실행하세요.',
  'Run the compatibility update template in a separate Codex session.':
    '별도 Codex 세션에서 호환성 업데이트 템플릿을 실행하세요.',
  'Manual recovery instructions': '수동 복구 안내',
  'Session service unavailable. Showing the last reported task state.':
    '세션 서비스에 연결할 수 없어 마지막으로 보고된 작업 상태를 표시합니다.',
  'The selected skill is unavailable. Refresh the task and choose again.':
    '선택한 스킬을 사용할 수 없습니다. 작업을 새로고침하고 다시 선택하세요.',
  'Service status': '서비스 상태',
  'Work overview': '작업 현황',
  'Task workspace': '작업실',
  'Approval needed': '승인 대기',
  'Not loaded': '불러오지 않음',
  Stopped: '중지됨',
  Unknown: '확인 불가',
  'Running a command': '명령 실행 중',
  'Editing files': '파일 수정 중',
  Searching: '검색 중',
  'Delegating work': '하위 작업 분담 중',
  'No agent activity yet': '아직 에이전트 활동이 없습니다',
  'No current step reported': '현재 단계가 보고되지 않았습니다',
  'Codex investigates and operates. This console displays status and your requests.':
    '점검과 운영은 Codex가 수행하며, 콘솔은 상태와 요청을 표시합니다.',
  'Monitoring is unavailable': '상태 모니터링에 연결할 수 없습니다',
  Healthy: '응답 정상',
  Unavailable: '응답 없음',
  'Stale observation': '오래된 관측',
  'Ask Codex to inspect': 'Codex에 점검 요청',
  'Ask Codex to deploy': 'Codex에 배포 요청',
  'Ask Codex to recover': 'Codex에 복구 요청',
  'Prepare a deployment': '배포 준비',
  'Investigate recovery': '복구 방안 조사',
  'Inspect this service': '서비스 점검',
  'Inspect the repository instructions and current state, then explain the proposed action and required approvals.':
    '저장소 지침과 현재 상태를 확인하고, 제안하는 조치와 필요한 승인을 설명해 주세요.',
  'Recover the Codex session service': 'Codex 세션 서비스 복구 안내',
  'Open Codex in the source repository on the server and paste this request.':
    '서버의 소스 저장소에서 별도의 Codex를 열고 아래 요청을 입력하세요.',
  'Recovery request': '복구 요청문',
  'Read AGENTS.md and the Codex Console owner documentation. Inspect the independently supervised management and session services. Diagnose the session connection failure, preserve existing conversations and running work, and propose recovery. Ask before restarting or deploying. Verify the public login, task state, and agent activity after the approved recovery.':
    'AGENTS.md와 Codex 콘솔 운영 문서를 읽고, 별도 실행 중인 관리 화면과 세션 서비스를 점검해 주세요. 기존 대화와 진행 중인 작업을 보존하며 연결 실패 원인을 조사하고 복구 방법을 제안해 주세요. 재시작·배포 전에 승인을 받고, 승인한 복구 후 공개 주소의 로그인·작업 상태·에이전트 활동을 확인해 주세요.',
  'Status filter': '상태 필터',
  'Environment filter': '환경 필터',
  'Purpose filter': '작업 목적 필터',
  'All tasks': '전체 작업',
  'Needs attention': '확인 필요',
  'Not started': '시작 대기',
  'Recent results': '최근 결과',
  'All environments': '전체 환경',
  'All purposes': '전체 목적',
  Development: '개발',
  Inspection: '점검',
  Deployment: '배포',
  Recovery: '복구',
  Unpin: '고정 해제',
  Pin: '고정',
  'Active agents': '활동 중 에이전트',
  'No matching tasks': '해당하는 작업이 없습니다',
  Agents: '에이전트',
  'Isolate this task for parallel work': '병렬 작업을 위한 별도 작업공간 사용',
  'Request draft': '요청 초안',
  'Task purpose': '작업 목적',
  'The concurrency limit is reached. Retry after another task finishes.':
    '동시 실행 한도에 도달했습니다. 다른 작업이 끝난 뒤 다시 요청하세요.',
  'Another operation is using the shared environment. Retry after it finishes.':
    '다른 운영 작업이 환경을 사용 중입니다. 종료 후 다시 요청하세요.',
  'Source agent': '요청한 에이전트',
  'Available skills': '사용 가능한 작업 절차',
  'Use a skill': '작업 절차 사용',
  'Show agent activity': '에이전트 활동 보기',

  'Finish or stop the current turn before changing its mode, model, reasoning effort, or permissions.':
    '모드·모델·추론 강도·권한을 바꾸려면 현재 실행이 끝날 때까지 기다리거나 중단한 뒤 전송하세요.',
  'Planning is read-only. Documents are updated only when requested or when agreed changes affect an existing document.':
    '계획 모드는 읽기 전용입니다. 문서는 작성을 요청하거나 기존 문서에 반영할 사항이 확정되면 갱신합니다.',
  Branch: '브랜치',
  'This workspace is based on a commit without a named branch. Your changes are preserved.':
    '브랜치 이름 없이 커밋을 기준으로 분리된 작업 공간입니다. 변경사항은 보존되어 있습니다.',
  'Git workspace': 'Git 작업 공간',
  'Detached HEAD': '브랜치 없음 (detached HEAD)',
  'No commits': '커밋 없음',
  'Changed files': '변경 파일',
  Staged: '스테이징',
  Unstaged: '미스테이징',
  Untracked: '새 파일',
  Conflicts: '충돌',
  'No tracking branch': '원격 추적 브랜치 없음',
  'Could not load Git state.': 'Git 상태를 불러오지 못했습니다.',
  'Loading Git state…': 'Git 상태 확인 중…',
  'Refresh Git state': 'Git 상태 새로고침',
  'Remote counts use local tracking refs; no automatic fetch.':
    '원격 비교는 로컬 추적 정보 기준입니다. 자동 fetch는 하지 않습니다.',
  Checked: '확인 시각',
  'Restore unsent request': '전송하지 못한 요청 불러오기',
  'The resumed permissions do not match this console. No new request was executed.':
    '재개한 세션의 권한이 콘솔 기록과 일치하지 않습니다. 새 요청은 실행되지 않았습니다.',
  'Next execution': '다음 실행 설정',
  Model: '모델',
  'Model and reasoning': '모델 및 추론 강도',
  'Reasoning effort': '추론 강도',
  'Change settings': '설정 변경',
  'Hide settings': '설정 접기',
  'Loading model catalog…': '모델 목록 불러오는 중…',
  'Could not load models.': '모델 목록을 불러오지 못했습니다.',
  'Codex update required': 'Codex 업데이트 필요',
  'Update instructions': '업데이트 안내',
  'The Codex version does not match this console. A compatibility update is required.':
    'Codex 버전 불일치로 콘솔 호환성 업데이트가 필요합니다.',
  'Administrator: open a terminal on the console server, start codex in the source repository, and paste the prompt below. After deployment, refresh this page.':
    '관리자는 콘솔 서버의 터미널 모드에서 소스 저장소로 이동해 codex를 실행하고 아래 프롬프트를 입력하세요. 배포 완료 후 이 페이지를 새로고침하세요.',
  'Update prompt for Codex CLI': 'Codex CLI 업데이트 프롬프트',
  'Copy prompt': '프롬프트 복사',
  'Prompt copied.': '프롬프트를 복사했습니다.',
  'Copy the selected prompt manually.': '선택된 프롬프트를 직접 복사하세요.',
  Permissions: '실행 권한',
  'Read-only': '읽기 전용',
  'Ask when needed': '필요할 때 승인 요청',
  'YOLO · Full access': 'YOLO · 전체 권한',
  'Reload models': '모델 목록 다시 불러오기',
  'YOLO runs commands without approval or sandbox restrictions.':
    'YOLO는 승인 요청과 샌드박스 제한 없이 명령을 실행합니다.',
  'Execution mode': '실행 모드',
  'Execution status': '현재 실행 상태',
  'Execution steps': '작업 진행 단계',
  Completed: '완료',
  Pending: '대기',
  'Work continues on the server when you leave this page.':
    '페이지를 이동하거나 닫아도 서버에서 작업을 계속합니다.',
  'Reconnecting live updates. Leaving this page does not stop the server task.':
    '실시간 표시를 다시 연결하고 있습니다. 페이지 연결과 서버 작업 실행은 별개입니다.',
  'The selected model or reasoning effort is unavailable. Refresh the model list.':
    '선택한 모델이나 추론 강도를 사용할 수 없습니다. 모델 목록을 새로 불러오세요.',
  'The console stopped after a processing error. Recover the task and check server diagnostics.':
    '콘솔 처리 오류로 실행이 중단되었습니다. 작업 상태를 복구하고 서버 진단을 확인하세요.',
  'Codex output exceeded the connection limit. Recover the existing task.':
    'Codex 출력이 연결 처리 한도를 초과했습니다. 기존 작업 상태를 복구하세요.',

  Files: '파일',
  'Task files': '작업 파일',
  'Attached files': '첨부한 파일',
  'Files for this message': '이번 메시지에 첨부할 파일',
  'Remove from message': '첨부 선택 해제',
  'Attach files': '파일 첨부',
  'Upload files': '파일 업로드',
  'Delete file': '파일 삭제',
  Deleted: '삭제됨',
  Download: '다운로드',
  Done: '선택 완료',
  'Retry upload': '업로드 재시도',
  'Cancel upload': '업로드 취소',
  Uploading: '업로드 중',
  'All file types': '모든 파일 형식',
  'Per file': '파일당',
  Storage: '보관 용량',
  'Drop files here or use Upload files.':
    '파일을 끌어 놓거나 파일 업로드를 눌러 주세요.',
  'Select files to include in your next message. Uploading alone does not send them to Codex.':
    '이번 메시지에 참조할 파일을 선택하세요. 업로드만 한 파일은 Codex에 전달되지 않습니다.',
  'Only selected files are attached to this message.':
    '선택한 파일만 이번 메시지에 첨부합니다. 전송 후 선택이 해제됩니다.',
  'Deselecting a file stops attaching it to new messages. Content already read may remain in the conversation.':
    '선택을 해제하면 이후 메시지에 다시 첨부하지 않습니다. 이미 읽은 내용은 이전 대화에 남을 수 있습니다.',
  'The original will be deleted. Earlier conversation content is retained.':
    '보관된 원본을 삭제합니다. 이전 대화에서 읽은 내용은 남을 수 있습니다.',
  'The file exceeds the upload size limit.':
    '파일당 업로드 용량 제한을 초과했습니다.',
  'The task file storage limit has been reached.':
    '작업의 파일 보관 용량 또는 개수 제한에 도달했습니다.',
  'Select fewer files for this message.':
    '이번 메시지에 첨부할 파일 개수를 줄여 주세요.',
  'The file is unavailable or was deleted.':
    '파일을 찾을 수 없거나 삭제되었습니다.',
  'Use a file name without paths or control characters.':
    '경로 또는 제어 문자가 없는 파일 이름을 사용해 주세요.',
  'The upload timed out. Retry the upload.':
    '업로드 시간이 초과되었습니다. 다시 시도해 주세요.',
  'The upload was cancelled.': '업로드를 취소했습니다.',
  'The file cache is unavailable. Check the server storage settings.':
    '파일 읽기 경로를 준비하지 못했습니다. 서버 저장소 설정을 확인하세요.',
  'Showing the latest 2,000 items. The full conversation remains in Codex.':
    '최근 항목 2,000개를 표시합니다. 전체 대화는 Codex에 보존됩니다.',
  'Codex workspace': 'Codex 작업실',
  'Your private development workspace': '나만의 개발 작업실',
  'Use your existing Codex subscription to turn an idea into a reviewed change.':
    '지금 사용하는 Codex 구독으로 아이디어를 정리하고, 구현하고, 변경사항을 검토하세요.',
  'Owner password': '본인 전용 비밀번호',
  'Sign in': '로그인',
  'Retry connection': '연결 다시 시도',
  Retry: '다시 시도',
  'Loading changes…': '변경사항을 불러오는 중…',
  'Could not load changes.': '변경사항을 불러오지 못했습니다.',
  'Could not load this diff.': '이 파일의 변경 내용을 불러오지 못했습니다.',
  'Sign out': '로그아웃',
  'This password protects the console. Your ChatGPT login stays with Codex.':
    '작업실 접속용 비밀번호입니다. ChatGPT 로그인은 Codex에서 관리합니다.',
  'New task': '새 작업',
  Tasks: '작업 목록',
  History: 'Codex 이력',
  'Search tasks': '작업 검색',
  'Search Codex history': 'Codex 이력 검색',
  'Load more': '더 보기',
  Refresh: '새로고침',
  'Open tasks': '작업 목록 열기',
  Close: '닫기',
  'No tasks yet': '아직 작업이 없습니다',
  'Start with what you want to change.': '바꾸고 싶은 내용을 이야기해 주세요.',
  'Describe a feature or a problem. Codex will inspect the repository and create a plan.':
    '필요한 기능이나 문제를 설명하세요. Codex가 저장소를 살펴보고 계획을 작성합니다.',
  'Task title': '작업 제목',
  'Create task': '작업 만들기',
  Cancel: '취소',
  Plan: '계획',
  Execute: '실행',
  Review: '검토',
  Conversation: '대화',
  Changes: '변경사항',
  'Execution results': '실행 결과',
  Results: '결과물',
  'Describe your request': '요청 내용 입력',
  Send: '보내기',
  'Add instruction': '보충 지시 보내기',
  Stop: '중단',
  'Read-only planning': '읽기 전용 · 계획',
  'Waiting for your response': '답변을 기다리고 있습니다',
  Ready: '준비됨',
  Starting: '시작 중',
  Running: '진행 중',
  Interrupted: '중단됨',
  Failed: '실패',
  'Needs recovery': '상태 확인 필요',
  Reconnecting: '다시 연결하는 중',
  Connected: '연결됨',
  'Subscription connected': '구독 연결됨',
  'Codex unavailable': 'Codex 연결 안 됨',
  'Connect ChatGPT': 'ChatGPT 연결',
  'Open sign-in page': '로그인 페이지 열기',
  'Enter this code on the sign-in page.':
    '로그인 페이지에 이 코드를 입력하세요.',
  Usage: '사용량',
  Used: '사용',
  Resets: '초기화',
  'Usage is unavailable.': '사용량 정보를 제공받지 못했습니다.',
  Document: '문서',
  'Edit document': '문서 편집',
  'Save document': '문서 저장',
  'Discard edits and load latest version':
    '편집 내용 버리고 최신 버전 불러오기',
  'The document changed in another tab. Your edits are preserved. Copy them before loading the latest version.':
    '다른 곳에서 문서가 변경되었습니다. 편집 내용은 유지되며 최신 버전을 불러오기 전에 복사할 수 있습니다.',
  Preview: '미리보기',
  Version: '버전',
  'No document yet. Continue the conversation to create one.':
    '아직 문서가 없습니다. 대화를 진행하면 여기에 정리됩니다.',
  'Execute this plan': '이 계획으로 실행',
  'Execute the saved plan?': '저장된 계획으로 실행할까요?',
  'Codex may edit this checkout and run checks. The approved plan does not authorize publishing or deployment.':
    'Codex가 작업 디렉터리를 편집하고 검사를 실행합니다. 이 승인은 게시나 배포를 포함하지 않습니다.',
  'Save your changes before execution.': '실행 전에 문서 변경을 저장하세요.',
  'View latest version': '최신 버전 보기',
  'No file changes': '변경된 파일이 없습니다',
  'Select a file to inspect its diff.':
    '파일을 선택하면 변경 내용을 볼 수 있습니다.',
  'File changes': '파일 변경 목록',
  'Binary file changed': '바이너리 파일이 변경되었습니다',
  'No commands have run yet.': '아직 실행한 명령이 없습니다.',
  'Command output': '명령 실행 상세',
  'Exit code': '종료 코드',
  'In progress': '진행 중',
  'Command results are execution evidence. Read the final response for tests run and checks skipped.':
    '명령 결과는 실제 실행 기록입니다. 수행한 테스트와 생략한 검사는 최종 답변에서 확인하세요.',
  'Approve once': '이번 실행 허용',
  'Allow for this turn': '이번 턴 동안 허용',
  Decline: '거절',
  'Execution approval': '실행 승인',
  'File change approval': '파일 변경 승인',
  Answer: '답변',
  'Submit answers': '답변 보내기',
  'Additional answer': '직접 답변',
  'Resume conversation': '대화 이어가기',
  'The original CLI conversation is no longer running.':
    '원래 CLI에서 이 대화를 더 이상 실행하고 있지 않습니다.',
  'Confirm before resuming a CLI conversation.':
    'CLI 대화를 이어가기 전에 확인해 주세요.',
  'Recover state': '실행 상태 확인',
  'Review the current diff first. Keep these changes in this task and continue in the same workspace?':
    '먼저 현재 변경사항을 확인하세요. 이 변경을 작업에 포함하고 같은 작업 디렉터리에서 이어가시겠습니까?',
  'Review and confirm the current workspace changes before recovery.':
    '현재 작업 디렉터리의 변경사항을 확인하고 동의한 뒤 복구하세요.',
  'No request will be automatically replayed.':
    '이전 실행 요청을 자동으로 다시 보내지 않습니다.',
  'Isolated checkout': '분리된 작업 디렉터리',
  'Your original changes are preserved. Review the isolated diff before integrating it.':
    '기존 변경은 보존되어 있습니다. 분리된 변경사항을 검토한 뒤 반영하세요.',
  Saved: '저장했습니다',
  'Request failed. Try refreshing the task.':
    '요청을 처리하지 못했습니다. 작업 상태를 새로 확인해 주세요.',
  'Sign in again.': '다시 로그인해 주세요.',
  'Password incorrect or sign-in temporarily locked.':
    '비밀번호가 올바르지 않거나 로그인이 잠시 제한되었습니다.',
  'Connect your ChatGPT account in Codex.':
    'Codex에 ChatGPT 계정을 연결해 주세요.',
  'The saved plan changed. Review the latest version.':
    '저장된 계획이 바뀌었습니다. 최신 계획을 확인해 주세요.',
  'The document changed in another tab. Reload the latest version.':
    '다른 탭에서 문서가 바뀌었습니다. 최신 버전을 다시 불러오세요.',
  'Another task is running. Finish or recover it first.':
    '다른 작업이 진행 중입니다. 먼저 종료하거나 실행 상태를 확인해 주세요.',
  'This task is already running or needs recovery.':
    '이미 진행 중이거나 실행 상태 확인이 필요한 작업입니다.',
  'This request has already been resolved or expired.':
    '이미 처리되었거나 만료된 요청입니다.',
  'The repository changed outside this task. Review it before continuing.':
    '이 작업 외부에서 저장소가 변경되었습니다. 확인한 뒤 이어가세요.',
  'The Codex connection was lost. Check the task state before retrying.':
    'Codex 연결이 끊어졌습니다. 다시 실행하기 전에 작업 상태를 확인하세요.',
  'The subscription usage limit has been reached.':
    '구독 사용량 한도에 도달했습니다.',
  'This path is not available in the console.':
    '작업실에서 접근할 수 없는 경로입니다.',
  'This file or output is too large to display.':
    '표시할 수 있는 파일·출력 크기를 초과했습니다.',
  'Check the entered values.': '입력 내용을 확인해 주세요.',
  'The request body is too large. Reduce the input and retry.':
    '요청 크기가 너무 큽니다. 입력을 줄이고 다시 시도해 주세요.',
  'The request upload timed out. Check the task state before retrying.':
    '요청 전송 시간이 초과됐습니다. 작업 상태를 확인한 뒤 다시 시도해 주세요.',
  'The request upload was cancelled. Check the task state before retrying.':
    '요청 전송이 취소됐습니다. 작업 상태를 확인한 뒤 다시 시도해 주세요.',
  'A template reference file is missing. Check its path before running.':
    '템플릿 참조 파일이 없습니다. 경로를 확인한 뒤 실행해 주세요.',
  'A compatible Codex version is required.':
    '호환되는 Codex 버전이 필요합니다.',
  'The request may have started. Recover its state before retrying.':
    '요청이 이미 시작되었을 수 있습니다. 실행 상태를 먼저 확인하세요.',
  'Codex is configured for a different provider. Select your ChatGPT configuration on the server.':
    'Codex에 다른 공급자가 설정되어 있습니다. 서버에서 ChatGPT용 설정을 선택하세요.',
  'The planning response could not be saved. Ask Codex to retry.':
    '계획 응답을 저장하지 못했습니다. Codex에 다시 요청해 주세요.',
  'The saved document changed during this turn. Review it before retrying.':
    '실행 중 문서가 변경되었습니다. 최신 문서를 확인하고 다시 요청해 주세요.',
  'The previous worktree was removed. This conversation now uses the configured workspace.':
    '이전 워크트리가 정리되어 설정된 작업 폴더에서 대화를 이어갑니다.',
} as const;

export type Copy = keyof typeof korean;
export type Locale = 'ko-KR' | 'en-US';
export type Translate = (key: Copy) => string;
export const translate =
  (locale: Locale): Translate =>
  (key) =>
    locale === 'ko-KR' ? korean[key] : key;

const errors: Record<string, Copy> = {
  instruction_conflict:
    'This document changed elsewhere. Your draft is preserved; review the latest version before saving.',
  instruction_too_large: 'Agent documents must be UTF-8 text under 64 KiB.',
  instruction_not_text: 'Agent documents must be UTF-8 text under 64 KiB.',
  invalid_skill_document:
    'SKILL.md needs YAML frontmatter with name and description.',
  stale_template: 'The template changed. Reload it before saving or running.',
  template_not_found: 'The template is unavailable or archived.',
  template_runner_unavailable:
    'Template runner is unavailable. Saved templates can still be edited.',
  template_inputs_invalid: 'Check the required template inputs.',
  duplicate_request:
    'The request identifier was already used with different inputs.',
  skill_unavailable:
    'The selected skill is unavailable. Refresh the task and choose again.',
  capacity_busy:
    'The concurrency limit is reached. Retry after another task finishes.',
  operations_busy:
    'Another operation is using the shared environment. Retry after it finishes.',
  planning_output_invalid:
    'The planning response could not be saved. Ask Codex to retry.',
  document_conflict:
    'The saved document changed during this turn. Review it before retrying.',
  workspace_removed:
    'The previous worktree was removed. This conversation now uses the configured workspace.',
  sandbox_policy_mismatch:
    'The resumed permissions do not match this console. No new request was executed.',
  model_unavailable:
    'The selected model or reasoning effort is unavailable. Refresh the model list.',
  effort_unavailable:
    'The selected model or reasoning effort is unavailable. Refresh the model list.',
  model_catalog_unavailable:
    'The selected model or reasoning effort is unavailable. Refresh the model list.',
  codex_event_failed:
    'The console stopped after a processing error. Recover the task and check server diagnostics.',
  codex_protocol_error:
    'The console stopped after a processing error. Recover the task and check server diagnostics.',
  codex_event_overflow:
    'Codex output exceeded the connection limit. Recover the existing task.',
  codex_output_limit:
    'Codex output exceeded the connection limit. Recover the existing task.',

  attachment_too_large: 'The file exceeds the upload size limit.',
  attachment_quota_exceeded: 'The task file storage limit has been reached.',
  attachment_selection_limit: 'Select fewer files for this message.',
  attachment_not_found: 'The file is unavailable or was deleted.',
  invalid_filename: 'Use a file name without paths or control characters.',
  attachment_upload_timeout: 'The upload timed out. Retry the upload.',
  attachment_upload_cancelled: 'The upload was cancelled.',
  attachment_cache_unavailable:
    'The file cache is unavailable. Check the server storage settings.',
  unauthenticated: 'Sign in again.',
  login_failed: 'Password incorrect or sign-in temporarily locked.',
  login_required: 'Connect your ChatGPT account in Codex.',
  stale_plan: 'The saved plan changed. Review the latest version.',
  stale_document:
    'The document changed in another tab. Reload the latest version.',
  workspace_busy: 'Another task is running. Finish or recover it first.',
  task_busy: 'This task is already running or needs recovery.',
  turn_settings_mismatch:
    'Finish or stop the current turn before changing its mode, model, reasoning effort, or permissions.',
  request_expired: 'This request has already been resolved or expired.',
  workspace_changed:
    'The repository changed outside this task. Review it before continuing.',
  workspace_confirmation_required:
    'Review and confirm the current workspace changes before recovery.',
  codex_disconnected:
    'The Codex connection was lost. Check the task state before retrying.',
  runtime_restarted:
    'The Codex connection was lost. Check the task state before retrying.',
  usage_limit: 'The subscription usage limit has been reached.',
  path_denied: 'This path is not available in the console.',
  output_too_large: 'This file or output is too large to display.',
  invalid_input: 'Check the entered values.',
  input_too_large: 'The request body is too large. Reduce the input and retry.',
  input_timeout:
    'The request upload timed out. Check the task state before retrying.',
  input_cancelled:
    'The request upload was cancelled. Check the task state before retrying.',
  reference_not_found:
    'A template reference file is missing. Check its path before running.',
  invalid_answer: 'Check the entered values.',
  codex_version_mismatch:
    'The Codex version does not match this console. A compatibility update is required.',
  codex_unavailable: 'Codex unavailable',
  codex_request_uncertain:
    'The request may have started. Recover its state before retrying.',
  subscription_provider_required:
    'Codex is configured for a different provider. Select your ChatGPT configuration on the server.',
};
export const errorCopy = (code: string): Copy =>
  errors[code] ?? 'Request failed. Try refreshing the task.';
export const statusCopy = (status: string): Copy =>
  (
    ({
      idle: 'Ready',
      starting: 'Starting',
      running: 'Running',
      waiting: 'Waiting for your response',
      interrupted: 'Interrupted',
      failed: 'Failed',
      uncertain: 'Needs recovery',
    }) as Record<string, Copy>
  )[status] ?? 'Ready';
