import { Button, Dialog, Input } from '@miy/ui';
import { BookOpen, Plus, RefreshCw, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { components } from './api.generated';
import { errorCopy, type Translate } from './i18n';
import { EmptyState, PageLayout } from './page-layout';

type Catalog = components['schemas']['DocumentCatalog'];
type Document = components['schemas']['DocumentOut'];
type Entry = components['schemas']['DocumentEntry'];
type Scope = Document['scope'];
const identity = (entry: Pick<Entry, 'scope' | 'path'>) =>
  `${entry.scope}:${entry.path}`;
const scopeLabels = {
  project: 'Project documents',
  personal: 'Personal skills',
  global: 'Global instructions',
} as const;

export function Instructions({
  active,
  t,
  onRequest,
}: {
  active: boolean;
  t: Translate;
  onRequest: (
    title: string,
    text: string,
    stage: 'plan' | 'implement',
  ) => Promise<void>;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [scope, setScope] = useState<Scope>('project');
  const [search, setSearch] = useState('');
  const [document, setDocument] = useState<Document | null>(null);
  const [latestDocument, setLatestDocument] = useState<Document | null>(null);
  const [content, setContent] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [creating, setCreating] = useState(false);
  const [kind, setKind] = useState<
    'instructions' | 'skill' | 'metadata' | 'reference'
  >('instructions');
  const [path, setPath] = useState('AGENTS.md');
  const [requestOpen, setRequestOpen] = useState(false);
  const [request, setRequest] = useState('');
  const [stage, setStage] = useState<'plan' | 'implement'>('plan');
  const drafts = useRef(
    new Map<string, { document: Document; content: string }>(),
  );
  const readSequence = useRef(0);
  const dirty = !!document && content !== document.content;
  const showError = (e: unknown) =>
    setError(e instanceof ApiError ? e.code : 'request_failed');
  const remember = () => {
    if (document) drafts.current.set(identity(document), { document, content });
  };
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setCatalog(await api<Catalog>('/instructions'));
      setError(null);
    } catch (e) {
      showError(e);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (active) void load();
  }, [active, load]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (
        dirty ||
        [...drafts.current.values()].some(
          (d) => d.content !== d.document.content,
        )
      ) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const open = async (entry: Pick<Entry, 'scope' | 'path'>, reload = false) => {
    remember();
    const sequence = ++readSequence.current;
    setError(null);
    setLatestDocument(null);
    setSaved(false);
    const draft = !reload && drafts.current.get(identity(entry));
    if (draft) {
      setDocument(draft.document);
      setContent(draft.content);
      return;
    }
    setBusy(true);
    try {
      const doc = await api<Document>(
        `/instructions/document?scope=${entry.scope}&path=${encodeURIComponent(entry.path)}`,
      );
      if (sequence !== readSequence.current) return;
      setDocument(doc);
      setContent(doc.content);
      drafts.current.delete(identity(entry));
    } catch (e) {
      if (sequence === readSequence.current) showError(e);
    } finally {
      if (sequence === readSequence.current) setBusy(false);
    }
  };
  const save = async () => {
    if (!document) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const doc = await api<Document>(
        '/instructions/document',
        {
          scope: document.scope,
          path: document.path,
          revision: document.revision,
          content,
        },
        'PUT',
      );
      setDocument(doc);
      setContent(doc.content);
      drafts.current.delete(identity(doc));
      await load();
      setSaved(true);
    } catch (e) {
      showError(e);
    } finally {
      setBusy(false);
    }
  };
  const entries = (catalog?.entries ?? []).filter(
    (e) =>
      e.scope === scope && e.path.toLowerCase().includes(search.toLowerCase()),
  );
  const selectedEntries =
    document?.scope === scope && !entries.some((e) => e.path === document.path)
      ? [...entries, document]
      : entries;
  return (
    <PageLayout
      hidden={!active}
      className="instructions-view"
      title={t('Instructions and skills')}
      description={t(
        'Edit the files Codex reads, or ask Codex to improve them.',
      )}
      actions={
        <>
          <Button
            disabled={busy}
            onClick={() => {
              setKind(scope === 'personal' ? 'skill' : 'instructions');
              setPath(
                scope === 'personal' ? 'skills/my-skill/SKILL.md' : 'AGENTS.md',
              );
              setCreating(true);
            }}
          >
            <Plus size={16} />
            {t('New document')}
          </Button>
          <Button
            disabled={loading || busy}
            onClick={() => void load()}
            aria-label={t('Refresh')}
          >
            <RefreshCw size={16} />
          </Button>
        </>
      }
    >
      <details className="instruction-guide">
        <summary>{t('How Codex uses these files')}</summary>
        <p>
          {t(
            'AGENTS.md supplies persistent instructions. AGENTS.override.md takes precedence in the same folder. More specific folders add their own instructions.',
          )}
        </p>
        <p>
          {t(
            'SKILL.md defines a reusable procedure with a name and description. Codex can choose matching skills automatically; selecting a skill explicitly requests it.',
          )}
        </p>
        <p>
          {t(
            'agents/openai.yaml can set allow_implicit_invocation to false. References hold supporting Markdown. Installed plugins and system skills are managed by their installer.',
          )}
        </p>
        <p>
          {t(
            'Instruction changes apply to new sessions. Start a new session to verify them. Skill discovery is refreshed from the original files.',
          )}
        </p>
        <a
          href="https://learn.chatgpt.com/docs/agent-configuration/agents-md"
          target="_blank"
          rel="noreferrer"
        >
          {t('Official instruction documentation')}
        </a>
        {' · '}
        <a
          href="https://learn.chatgpt.com/docs/build-skills"
          target="_blank"
          rel="noreferrer"
        >
          {t('Official skill documentation')}
        </a>
      </details>
      <div className="instruction-controls">
        <label>
          {t('Document scope')}
          <select
            value={scope}
            disabled={busy}
            onChange={(e) => {
              remember();
              setScope(e.target.value as Scope);
              setSearch('');
              setDocument(null);
              setContent('');
              setLatestDocument(null);
            }}
          >
            {Object.entries(scopeLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {t(label)}
              </option>
            ))}
          </select>
        </label>
        <Input
          aria-label={t('Search documents')}
          placeholder={t('Search documents')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {catalog && (
        <p className="muted instruction-root">{catalog.roots[scope]}</p>
      )}
      {error && <p role="alert">{t(errorCopy(error))}</p>}
      {loading && !catalog && <p role="status">{t('Loading documents')}</p>}
      <div className="instruction-columns">
        <nav className="instruction-files" aria-label={t('Agent documents')}>
          {selectedEntries.map((entry) => (
            <button
              key={identity(entry)}
              disabled={busy}
              aria-current={
                document && identity(entry) === identity(document)
                  ? 'page'
                  : undefined
              }
              onClick={() => void open(entry)}
            >
              <strong>{entry.path}</strong>
              <small>
                {t(
                  entry.kind === 'instructions'
                    ? 'Instructions'
                    : entry.kind === 'skill'
                      ? 'Skill'
                      : entry.kind === 'metadata'
                        ? 'Skill metadata'
                        : 'Reference',
                )}
                {drafts.current.get(identity(entry))?.content !== undefined &&
                drafts.current.get(identity(entry))?.content !==
                  drafts.current.get(identity(entry))?.document.content
                  ? ' *'
                  : ''}
              </small>
            </button>
          ))}
          {!loading && !selectedEntries.length && catalog && (
            <p className="muted">{t('No documents in this scope')}</p>
          )}
        </nav>
        {document ? (
          <section
            className="instruction-editor"
            aria-label={t('Document editor')}
          >
            <div className="instruction-editor-heading">
              <h2>{document.path}</h2>
              <small>
                {t(scopeLabels[document.scope])}
                {dirty ? ` · ${t('Unsaved changes')}` : ''}
              </small>
            </div>
            <label className="sr-only" htmlFor="instruction-content">
              {t('Document content')}
            </label>
            <textarea
              id="instruction-content"
              spellCheck={false}
              value={content}
              disabled={busy || !document.editable}
              onChange={(e) => {
                setContent(e.target.value);
                setSaved(false);
              }}
              maxLength={65536}
              rows={22}
            />
            <div className="instruction-actions">
              <Button
                variant="primary"
                disabled={
                  busy || !document.editable || (!dirty && document.exists)
                }
                onClick={() => void save()}
              >
                {t('Save document')}
              </Button>
              <Button
                disabled={busy || dirty || !document.exists}
                onClick={() => {
                  setRequest('');
                  setRequestOpen(true);
                }}
              >
                <Sparkles size={16} />
                {t('Ask Codex to edit')}
              </Button>
              {!dirty && (
                <Button
                  disabled={busy}
                  onClick={() => void open(document, true)}
                >
                  {t('Reload document')}
                </Button>
              )}
            </div>
            {error === 'instruction_conflict' && (
              <Button
                disabled={busy}
                onClick={() => {
                  // Keep the local draft while showing the latest content separately.
                  void api<Document>(
                    `/instructions/document?scope=${document.scope}&path=${encodeURIComponent(document.path)}`,
                  )
                    .then((latest) => {
                      setLatestDocument(latest);
                    })
                    .catch(showError);
                }}
              >
                {t('Load latest version and keep my draft')}
              </Button>
            )}
            {latestDocument && (
              <section className="stack">
                <label>
                  {t('Latest saved content')}
                  <textarea readOnly value={latestDocument.content} rows={8} />
                </label>
                <div className="instruction-actions">
                  <Button
                    onClick={() => {
                      setDocument(latestDocument);
                      setLatestDocument(null);
                      setError(null);
                    }}
                  >
                    {t('Keep my draft against this version')}
                  </Button>
                  <Button
                    onClick={() => {
                      setDocument(latestDocument);
                      setContent(latestDocument.content);
                      drafts.current.delete(identity(latestDocument));
                      setLatestDocument(null);
                      setError(null);
                    }}
                  >
                    {t('Use the latest saved content')}
                  </Button>
                </div>
              </section>
            )}
            {saved && <p role="status">{t('Saved')}</p>}
            {dirty && (
              <p className="muted">
                {t(
                  'Save your changes before asking Codex. Drafts stay here while navigating the console.',
                )}
              </p>
            )}
          </section>
        ) : (
          <EmptyState
            icon={<BookOpen size={24} />}
            title={t('Choose an agent document')}
            description={t(
              'Open a file to edit it, or create instructions or a skill at an official location.',
            )}
          />
        )}
      </div>
      <Dialog
        open={creating && active}
        onOpenChange={setCreating}
        title={t('New document')}
        closeLabel={t('Close')}
      >
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            remember();
            setBusy(true);
            void api<Document>(
              `/instructions/document?scope=${scope}&path=${encodeURIComponent(path)}`,
            )
              .then((doc) => {
                const existingDraft = drafts.current.get(identity(doc));
                setDocument(existingDraft?.document ?? doc);
                setContent(
                  existingDraft
                    ? existingDraft.content
                    : doc.exists
                      ? doc.content
                      : doc.kind === 'skill'
                        ? `---\nname: ${path.split('/').at(-2) ?? 'my-skill'}\ndescription: Describe when Codex should use this skill.\n---\n\n# Procedure\n\n`
                        : doc.kind === 'metadata'
                          ? 'policy:\n  allow_implicit_invocation: true\n'
                          : doc.kind === 'instructions'
                            ? '# Agent instructions\n\n'
                            : '# Reference\n\n',
                );
                setCreating(false);
                setLatestDocument(null);
                setSaved(false);
                setError(null);
              })
              .catch(showError)
              .finally(() => setBusy(false));
          }}
        >
          <label>
            {t('Document type')}
            <select
              value={kind}
              onChange={(e) => {
                const next = e.target.value as typeof kind;
                setKind(next);
                const prefix =
                  scope === 'project'
                    ? '.agents/skills/my-skill/'
                    : 'skills/my-skill/';
                setPath(
                  next === 'instructions'
                    ? 'AGENTS.md'
                    : prefix +
                        (next === 'skill'
                          ? 'SKILL.md'
                          : next === 'metadata'
                            ? 'agents/openai.yaml'
                            : 'references/guide.md'),
                );
              }}
            >
              {scope !== 'personal' && (
                <option value="instructions">
                  AGENTS.md / AGENTS.override.md
                </option>
              )}
              <option value="skill">SKILL.md</option>
              <option value="metadata">agents/openai.yaml</option>
              <option value="reference">{t('Reference')}</option>
            </select>
          </label>
          <label>
            {t('Document path')}
            <Input
              required
              value={path}
              maxLength={1000}
              onChange={(e) => setPath(e.target.value)}
            />
          </label>
          <p className="muted">
            {t(
              'Paths are relative to the selected scope. Subfolder instructions and skill references are supported.',
            )}
          </p>
          <Button
            type="submit"
            variant="primary"
            disabled={busy || !path.trim()}
          >
            {t('Open document')}
          </Button>
        </form>
      </Dialog>
      <Dialog
        open={requestOpen && active}
        onOpenChange={setRequestOpen}
        title={t('Ask Codex to edit')}
        closeLabel={t('Close')}
      >
        <form
          className="stack"
          onSubmit={(event) => {
            event.preventDefault();
            if (!document || !catalog) return;
            const absolute = `${catalog.roots[document.scope]}/${document.path}`;
            const text = `Please ${stage === 'plan' ? 'review and propose improvements to' : 'edit'} this Codex document: ${JSON.stringify(absolute)}.\nRead the current file and applicable AGENTS.md instructions first. Follow the official AGENTS.md/SKILL.md format and scope, preserve unrelated edits, and validate the result.\nOnly the requested document and its necessary skill references are in scope. This request does not authorize committing, publishing, or deploying.\n\nUser request:\n${request}`;
            setBusy(true);
            void onRequest(
              `${t('Edit')}: ${document.path}`.slice(0, 200),
              text,
              stage,
            )
              .then(() => setRequestOpen(false))
              .catch(showError)
              .finally(() => setBusy(false));
          }}
        >
          <p className="instruction-root">{document?.path}</p>
          <label>
            {t('Requested changes')}
            <textarea
              required
              value={request}
              onChange={(e) => setRequest(e.target.value)}
              maxLength={16000}
              rows={5}
            />
          </label>
          <label>
            {t('Execution mode')}
            <select
              value={stage}
              onChange={(e) => setStage(e.target.value as typeof stage)}
            >
              <option value="plan">{t('Plan')}</option>
              <option value="implement">{t('Implement')}</option>
            </select>
          </label>
          <p className="muted">
            {t(
              'Planning proposes changes without editing. Implementation uses the existing Codex permissions and approval flow. Results open in a new session.',
            )}
          </p>
          <Button
            variant="primary"
            type="submit"
            disabled={busy || !request.trim()}
          >
            {t('Send request')}
          </Button>
        </form>
      </Dialog>
    </PageLayout>
  );
}
