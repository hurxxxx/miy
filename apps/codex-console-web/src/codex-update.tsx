import { Button, Dialog } from '@miy/ui';
import { useRef, useState } from 'react';
import type { Locale, Translate } from './i18n';

const prompts: Record<Locale, string> = {
  'ko-KR': `Codex 콘솔에서 codex_version_mismatch 오류가 발생합니다. 현재 설치된 Codex CLI와 호환되도록 콘솔을 수정하고 실제 서비스에 반영해 주세요.

1. 이 저장소의 AGENTS.md와 docs/apps/codex-console/README.md를 읽고, 실제 콘솔 서비스가 사용하는 Codex 버전·바이너리와 배포된 콘솔 계약을 확인하세요.
2. 공식 app-server 프로토콜 변경을 조사하고 필요한 코드·생성 계약·테스트·문서를 수정하세요. 버전·호환성 검사, 승인·권한 검사 또는 테스트를 제거하거나 약화해서 통과시키지 마세요. 관련 없는 변경과 기존 작업·인증·설정을 보존하세요.
3. 관련 계약 검사와 테스트·빌드를 수행하고, 실제 구독 연결과 모델 목록 조회를 확인하세요.
4. 검증된 관련 변경만 커밋하고 저장소 정책에 따라 GitLab origin에 푸시하세요. 보호 브랜치와 필수 검토·검사 절차를 준수하세요.
5. docs/apps/codex-console/README.md의 배포 완료 확인 절차에 따라 콘솔 전용 릴리스를 준비하고, 진행 중인 작업의 안전한 종료를 확인한 뒤 백업·필요한 migration·릴리스 전환·서비스 재시작까지 수행하세요. 소스 푸시나 miy 배포만으로 완료 처리하지 마세요.
6. 공개 콘솔에서 로그인, 모델 목록과 선택, 버전 오류 해소를 브라우저로 확인하고 커밋·푸시·배포 결과와 검증 결과를 보고하세요. 실패한 검증이 있으면 적용을 중단하고 이유를 보고하세요.

이 요청은 위 호환성 수정에 필요한 관련 변경의 커밋·푸시와 콘솔 전용 배포·서비스 재시작을 승인합니다.`,
  'en-US': `Codex Console reports codex_version_mismatch. Update the console to support the installed Codex CLI and apply the fix to the running service.

1. Read this repository's AGENTS.md and docs/apps/codex-console/README.md. Verify the Codex binary and version used by the actual service and the deployed console contract.
2. Investigate official app-server protocol changes and update the necessary code, generated contracts, tests, and documentation. Do not remove or weaken version, compatibility, approval, permission checks, or tests to make them pass. Preserve unrelated changes, existing tasks, authentication, and configuration.
3. Run the relevant contract checks, tests, and build, and verify the actual subscription connection and model catalog.
4. Commit only the verified changes for this fix and push to GitLab origin following repository policy. Respect protected branches and required reviews and checks.
5. Follow the deployment completion procedure in docs/apps/codex-console/README.md. Prepare a separate console release, confirm running work has safely finished, then perform the backup, any required migrations, release switch, and service restart. A source push or miy deployment alone does not complete this task.
6. Verify login, model listing and selection, and resolution of the version error in the public console using a browser. Report the commit, push, deployment, and validation results. If validation fails, stop the rollout and report why.

This request authorizes the commits, push, console-only deployment, and service restart needed for this compatibility fix.`,
};

export function CodexUpdateGuide({
  open,
  onOpenChange,
  locale,
  t,
  openTemplates,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  locale: Locale;
  t: Translate;
  openTemplates: () => void;
}) {
  const prompt = useRef<HTMLTextAreaElement>(null);
  const [copyStatus, setCopyStatus] = useState<'copied' | 'manual' | null>(
    null,
  );
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('Codex update required')}
      closeLabel={t('Close')}
    >
      <div className="stack">
        <p>
          {t(
            'The Codex version does not match this console. A compatibility update is required.',
          )}
        </p>
        <p>
          {t(
            'Run the compatibility update template in a separate Codex session.',
          )}
        </p>
        <Button
          variant="primary"
          onClick={() => {
            onOpenChange(false);
            openTemplates();
          }}
        >
          {t('Open update templates')}
        </Button>
        <details>
          <summary>{t('Manual recovery instructions')}</summary>
          <p>
            {t(
              'Administrator: open a terminal on the console server, start codex in the source repository, and paste the prompt below. After deployment, refresh this page.',
            )}
          </p>
          <textarea
            className="codex-update-prompt"
            aria-label={t('Update prompt for Codex CLI')}
            ref={prompt}
            readOnly
            rows={10}
            value={prompts[locale]}
            onFocus={(event) => event.currentTarget.select()}
          />
          <Button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(prompts[locale]);
                setCopyStatus('copied');
              } catch {
                prompt.current?.focus();
                prompt.current?.select();
                setCopyStatus('manual');
              }
            }}
          >
            {t('Copy prompt')}
          </Button>
          <span role="status">
            {copyStatus === 'copied' && t('Prompt copied.')}
            {copyStatus === 'manual' && t('Copy the selected prompt manually.')}
          </span>
        </details>
      </div>
    </Dialog>
  );
}
