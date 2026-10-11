// App-owned copy and styles; the SDK supplies preferences, not portal UI code.
const ko = {
  title: '내 업무 앱',
  settings: '앱 설정을 확인하는 중입니다.',
  connecting: '플랫폼 로그인과 앱 권한을 확인하는 중입니다.',
  connected: '연결되었습니다.',
  connectFailed:
    '연결하지 못했습니다. 플랫폼에서 로그인한 뒤 다시 시도해 주세요.',
  configFailed: '앱의 서버 설정이 필요합니다.',
  standalone:
    '독립 주소에서 실행 중입니다. 플랫폼에 연결하면 사용자 정보를 확인할 수 있습니다.',
  popupBlocked: '팝업을 허용한 뒤 다시 연결해 주세요.',
  welcome: '환영합니다, ',
  connect: '플랫폼에 연결',
  connectingLabel: '연결 중…',
  description: '이 화면과 API는 앱의 자체 프로세스에서 실행됩니다.',
  notesTitle: '내 메모',
  notesPrivacy: '작성한 메모는 나만 볼 수 있습니다.',
  notesConnected: '내 메모에 연결되었습니다.',
  notesStandalone: '플랫폼에 연결하면 내 메모를 볼 수 있습니다.',
  sessionChanged:
    '연결이 만료되었거나 권한이 변경되었습니다. 다시 연결해 주세요.',
  conflict: '다른 창에서 변경되었습니다. 목록을 새로고침해 주세요.',
  requestFailed: '요청을 처리하지 못했습니다.',
  notesChecked: '저장된 내 메모를 확인했습니다.',
  newNote: '새 메모',
  save: '저장',
  refresh: '새로고침',
  remove: '삭제',
  more: '더 보기',
};
const en = {
  title: 'My work app',
  settings: 'Checking app settings.',
  connecting: 'Checking platform login and app access.',
  connected: 'Connected.',
  connectFailed: 'Could not connect. Sign in to the platform and try again.',
  configFailed: 'App server settings are required.',
  standalone:
    'Running independently. Connect to the platform to view your identity.',
  popupBlocked: 'Allow the popup and try connecting again.',
  welcome: 'Welcome, ',
  connect: 'Connect to platform',
  connectingLabel: 'Connecting…',
  description: 'This screen and API run in the app’s own process.',
  notesTitle: 'My notes',
  notesPrivacy: 'Only you can see your notes.',
  notesConnected: 'Connected to your notes.',
  notesStandalone: 'Connect to the platform to view your notes.',
  sessionChanged: 'Your session expired or access changed. Please reconnect.',
  conflict: 'Another window changed this note. Refresh the list.',
  requestFailed: 'Could not complete the request.',
  notesChecked: 'Your saved notes are up to date.',
  newNote: 'New note',
  save: 'Save',
  refresh: 'Refresh',
  remove: 'Delete',
  more: 'More',
};

export function copyFor(locale) {
  return locale.startsWith('en') ? en : ko;
}

export function applyUIContext(targetDocument, { theme, locale }) {
  // This sample translates Korean/English only. Each app owns its locale fallback.
  const supported = locale.startsWith('en') ? 'en-US' : 'ko-KR';
  targetDocument.documentElement.lang = supported;
  targetDocument.documentElement.dataset.theme = theme;
  targetDocument.documentElement.style.colorScheme = theme;
  return supported;
}
