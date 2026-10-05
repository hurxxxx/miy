import { Button, Dialog, Input } from '@miy/ui';
import {
  BookOpen,
  Check,
  FileText,
  FolderOpen,
  HelpCircle,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import type { components } from './api.generated';
import { errorCopy, type Translate } from './i18n';
import { EmptyState, PageLayout } from './page-layout';
import { Markdown } from './views';
import {
  DocumentFolders,
  linkedDocument,
  relatedGuidance,
} from './instruction-explorer';

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
  admin: 'Administrator skills',
  system: 'System skills',
  plugins: 'Plugin skills',
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
  const [mode, setMode] = useState<'read' | 'edit'>('read');
  const [filter, setFilter] = useState<
    'all' | 'instructions' | 'skill' | 'support'
  >('all');
  const [helpOpen, setHelpOpen] = useState(false);
  const [filesOpen, setFilesOpen] = useState(true);
  const [search, setSearch] = useState('');
  const [searchEntries, setSearchEntries] = useState<Entry[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(false);
  const [createFolder, setCreateFolder] = useState('');
  const [discoveryDirectory, setDiscoveryDirectory] = useState('.');
  const [discovery, setDiscovery] = useState<
    components['schemas']['SkillDiscovery'] | null
  >(null);
  const [discovering, setDiscovering] = useState(false);
  const [discoveryError, setDiscoveryError] = useState(false);
  const discoverySequence = useRef(0);
  const canCreate = !['admin', 'system', 'plugins'].includes(scope);
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
  const resetDiscovery = useCallback(() => {
    ++discoverySequence.current;
    setDiscovery(null);
    setDiscovering(false);
    setDiscoveryError(false);
  }, []);
  const load = useCallback(async () => {
    resetDiscovery();
    setLoading(true);
    try {
      setCatalog(await api<Catalog>('/instructions'));
      setError(null);
    } catch (e) {
      showError(e);
    } finally {
      setLoading(false);
    }
  }, [resetDiscovery]);
  useEffect(() => {
    if (active) void load();
  }, [active, load]);
  useEffect(() => {
    let current = true;
    setSearchEntries(null);
    setSearchError(false);
    setSearching(!!search.trim());
    if (!search.trim() || !active) return;
    const timer = window.setTimeout(() => {
      void api<Catalog>(
        `/instructions?scope=${scope}&q=${encodeURIComponent(search.trim())}`,
      )
        .then((result) => {
          if (current) setSearchEntries(result.entries);
        })
        .catch(() => {
          if (current) setSearchError(true);
        })
        .finally(() => {
          if (current) setSearching(false);
        });
    }, 250);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
  }, [active, search, scope, catalog]);
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
    setFilesOpen(false);
    const draft = !reload && drafts.current.get(identity(entry));
    if (draft) {
      setDocument(draft.document);
      setContent(draft.content);
      setMode(draft.content !== draft.document.content ? 'edit' : 'read');
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
      setMode('read');
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
  const loadLatest = async () => {
    if (!document) return;
    const sequence = ++readSequence.current;
    try {
      const latest = await api<Document>(
        `/instructions/document?scope=${document.scope}&path=${encodeURIComponent(document.path)}`,
      );
      if (
        sequence === readSequence.current &&
        identity(latest) === identity(document)
      ) {
        setLatestDocument(latest);
      }
    } catch (e) {
      if (sequence === readSequence.current) showError(e);
    }
  };
  const matches = (entry: Pick<Entry, 'kind' | 'path'>) =>
    filter === 'all' ||
    entry.kind === filter ||
    (filter === 'support' &&
      ['metadata', 'reference', 'bridge', 'script'].includes(entry.kind));
  const kindOrder = {
    instructions: 0,
    skill: 1,
    metadata: 2,
    reference: 3,
    bridge: 4,
    script: 5,
  };
  const scopedEntries = (catalog?.entries ?? [])
    .filter((e) => e.scope === scope)
    .sort(
      (a, b) =>
        kindOrder[a.kind] - kindOrder[b.kind] || a.path.localeCompare(b.path),
    );
  const entries = (
    search.trim() ? (searchEntries ?? []) : scopedEntries
  ).filter(matches);
  const selectedEntries =
    document?.scope === scope &&
    !document.exists &&
    !entries.some((e) => e.path === document.path) &&
    matches(document)
      ? [...entries, document]
      : entries;
  const kindLabel = (entry: Pick<Entry, 'kind'>) =>
    t(
      entry.kind === 'instructions'
        ? 'Instructions'
        : entry.kind === 'skill'
          ? 'Skill'
          : entry.kind === 'metadata'
            ? 'Skill metadata'
            : entry.kind === 'bridge'
              ? 'Linked instructions'
              : entry.kind === 'script'
                ? 'Skill script'
                : 'Reference',
    );
  const fileLabel = (entry: Pick<Entry, 'kind' | 'path'>) => {
    const parts = entry.path.split('/');
    const skill = parts.indexOf('skills');
    const label = entry.kind === 'skill' ? parts.at(-2)! : parts.at(-1)!;
    const context =
      skill >= 0 && ['metadata', 'reference'].includes(entry.kind)
        ? parts[skill + 1]
        : parts.slice(0, entry.kind === 'skill' ? -2 : -1).join('/') ||
          t('Root folder');
    return { label, context };
  };
  const createDocument = (folder = '') => {
    setCreateFolder(folder);
    const inSkill = /(?:^|\/)(?:\.agents\/)?skills\/[^/]+(?:\/|$)/.test(folder);
    const skillRoot = /(?:^|\/)skills$/.test(folder);
    setKind(
      inSkill
        ? 'reference'
        : skillRoot || scope === 'personal'
          ? 'skill'
          : 'instructions',
    );
    setPath(
      inSkill
        ? `${folder}/guide.md`
        : skillRoot
          ? `${folder}/my-skill/SKILL.md`
          : scope === 'personal'
            ? 'skills/my-skill/SKILL.md'
            : `${folder ? folder + '/' : ''}AGENTS.md`,
    );
    setCreating(true);
  };
  const discover = async () => {
    const sequence = ++discoverySequence.current;
    setDiscovering(true);
    setDiscovery(null);
    setDiscoveryError(false);
    try {
      const result = await api<components['schemas']['SkillDiscovery']>(
        `/codex/skills?directory_name=${encodeURIComponent(discoveryDirectory)}`,
      );
      if (sequence === discoverySequence.current) setDiscovery(result);
    } catch {
      if (sequence === discoverySequence.current) setDiscoveryError(true);
    } finally {
      if (sequence === discoverySequence.current) setDiscovering(false);
    }
  };
  const followLink = (href: string) => {
    if (/^[a-z][a-z\d+.-]*:/i.test(href) || href.startsWith('//')) return false;
    if (!document) return true;
    if (href.startsWith('#')) {
      const slug = (text: string) =>
        text
          .toLowerCase()
          .replace(/[^\p{L}\p{N}\s_-]/gu, '')
          .replace(/\s+/g, '-');
      let name: string;
      try {
        name = decodeURIComponent(href.slice(1));
      } catch {
        setError('document_link_unavailable');
        return true;
      }
      [
        ...window.document.querySelectorAll(
          '.instruction-preview :is(h1,h2,h3,h4,h5,h6)',
        ),
      ]
        .find((h) => slug(h.textContent ?? '') === name)
        ?.scrollIntoView({ block: 'start' });
      return true;
    }
    const linked = linkedDocument(document, href, catalog?.entries ?? []);
    if (linked) {
      setSearch('');
      setFilter('all');
      void open(linked);
    } else setError('document_link_unavailable');
    return true;
  };
  const discovered = discovery?.skills.find(
    (skill) =>
      document &&
      skill.path === `${catalog?.roots[document.scope]}/${document.path}`,
  );
  const guidance = document
    ? relatedGuidance(catalog?.entries ?? [], document)
    : [];
  const selectedLabel = document ? fileLabel(document).label : '';
  const frontmatter =
    document?.kind === 'skill'
      ? content.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)
      : null;
  const renderEntry = (entry: Entry, inFolder = false) => {
    const { label, context } = fileLabel(entry);
    const draft = drafts.current.get(identity(entry));
    const changed =
      document && identity(entry) === identity(document)
        ? dirty
        : !!draft && draft.content !== draft.document.content;
    const Icon =
      entry.kind === 'skill'
        ? Sparkles
        : entry.kind === 'instructions'
          ? BookOpen
          : FileText;
    return (
      <button
        key={identity(entry)}
        aria-label={entry.path}
        title={entry.path}
        disabled={busy}
        aria-current={
          document && identity(entry) === identity(document)
            ? 'page'
            : undefined
        }
        onClick={() => void open(entry)}
      >
        <Icon size={16} aria-hidden="true" />
        <span className="instruction-file-label">
          <strong>{inFolder ? entry.path.split('/').at(-1) : label}</strong>
          <small>
            {kindLabel(entry)}
            {!inFolder && ` · ${context}`}
          </small>
        </span>
        {changed && (
          <span
            className="instruction-draft-dot"
            aria-label={t('Unsaved changes')}
          />
        )}
      </button>
    );
  };
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
            variant="ghost"
            aria-label={t('How Codex uses these files')}
            onClick={() => setHelpOpen(true)}
          >
            <HelpCircle size={17} />
          </Button>
          <Button
            disabled={busy || !canCreate}
            onClick={() => createDocument()}
          >
            <Plus size={16} />
            {t('New document')}
          </Button>
        </>
      }
    >
      <div
        className="instruction-columns"
        data-document-open={!!document}
        data-files-open={filesOpen}
      >
        <section
          className="instruction-library"
          aria-label={t('Document library')}
        >
          <div className="instruction-library-tools">
            <div className="instruction-scope-row">
              <label className="sr-only" htmlFor="instruction-scope">
                {t('Document scope')}
              </label>
              <select
                id="instruction-scope"
                value={scope}
                disabled={busy}
                onChange={(e) => {
                  remember();
                  ++readSequence.current;
                  setScope(e.target.value as Scope);
                  setSearch('');
                  setFilter('all');
                  setDocument(null);
                  setContent('');
                  setLatestDocument(null);
                  setFilesOpen(true);
                }}
              >
                {Object.entries(scopeLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {t(label)}
                  </option>
                ))}
              </select>
              <Button
                variant="ghost"
                size="icon"
                disabled={loading || busy}
                onClick={() => void load()}
                aria-label={t('Refresh')}
              >
                <RefreshCw size={15} />
              </Button>
            </div>
            <div className="instruction-search">
              <Search size={15} aria-hidden="true" />
              <Input
                aria-label={t('Search documents')}
                placeholder={t('Search documents')}
                value={search}
                maxLength={200}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div
              className="instruction-kind-filters"
              role="group"
              aria-label={t('Document types')}
            >
              {(
                [
                  ['all', 'All documents'],
                  ['instructions', 'Instructions'],
                  ['skill', 'Skills'],
                  ['support', 'Supporting files'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  aria-pressed={filter === value}
                  onClick={() => setFilter(value)}
                >
                  {t(label)}
                </button>
              ))}
            </div>
            <div className="instruction-library-summary">
              <span>
                {selectedEntries.length} {t('Documents')}
              </span>
              {catalog && (
                <span title={catalog.roots[scope]} className="instruction-root">
                  <FolderOpen size={12} />
                  {catalog.roots[scope].split('/').at(-1)}
                </span>
              )}
            </div>
            {!canCreate && (
              <p className="instruction-scope-note">
                {t(
                  'Installed files are read-only. Discovery depends on the selected working folder.',
                )}
              </p>
            )}
            {scope === 'plugins' && (
              <p className="instruction-scope-note">
                {t(
                  'Workbench sessions disable plugin and MCP execution. Installed files remain available for inspection.',
                )}
              </p>
            )}
            <details className="instruction-discovery">
              <summary>{t('Codex skill discovery')}</summary>
              <label>
                {t('Working folder')}
                <Input
                  value={discoveryDirectory}
                  maxLength={1000}
                  onChange={(e) => {
                    setDiscoveryDirectory(e.target.value);
                    resetDiscovery();
                  }}
                />
              </label>
              <Button
                disabled={discovering || !discoveryDirectory.trim()}
                onClick={() => void discover()}
              >
                {t('Check discovery')}
              </Button>
              <p role="status">
                {t(
                  discovering
                    ? 'Checking discovery'
                    : discoveryError
                      ? 'Discovery unavailable'
                      : discovery
                        ? 'Discovered skills'
                        : 'Discovery not checked',
                )}
                {discovery ? `: ${discovery.skills.length}` : ''}
              </p>
              {!!discovery?.error_count && (
                <p role="alert">
                  {t('Some skills could not be loaded')}:{' '}
                  {discovery.error_count}
                </p>
              )}
              {discovery && (
                <>
                  <p>
                    {t(
                      'Discovery shows availability for this working folder, not skills already used by a session.',
                    )}
                  </p>
                  <details>
                    <summary>{t('Discovered skill list')}</summary>
                    <ul className="instruction-discovered-skills">
                      {discovery.skills.map((skill, index) => {
                        const entry = catalog?.entries.find(
                          (item) =>
                            skill.path ===
                            `${catalog.roots[item.scope]}/${item.path}`,
                        );
                        return (
                          <li key={`${skill.path}:${index}`}>
                            {entry ? (
                              <button
                                disabled={busy}
                                onClick={() => {
                                  setScope(entry.scope);
                                  setSearch('');
                                  setFilter('all');
                                  void open(entry);
                                }}
                              >
                                {skill.name}
                              </button>
                            ) : (
                              <strong>{skill.name}</strong>
                            )}
                            <span>
                              {t(
                                skill.enabled
                                  ? 'Skill enabled'
                                  : 'Skill disabled',
                              )}
                            </span>
                            <code>{skill.path}</code>
                            {!entry && (
                              <span>
                                {t(
                                  'Discovered by Codex; this path is outside the file editor.',
                                )}
                              </span>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </details>
                  <details>
                    <summary>{t('Instruction discovery settings')}</summary>
                    {discovery.guidance ? (
                      <>
                        <p>
                          {t('Combined project instruction limit')}:{' '}
                          {discovery.guidance.max_bytes} B
                        </p>
                        <p>
                          {t('Fallback filenames')}:{' '}
                          {discovery.guidance.fallback_filenames.join(', ') ||
                            t('No fallback filenames')}
                        </p>
                        <p>
                          {t(
                            'Codex uses at most one non-empty instruction file per folder, from the project root to the working folder. Fallback filenames run in Codex but are not editable here.',
                          )}
                        </p>
                      </>
                    ) : (
                      <p>{t('Instruction settings unavailable')}</p>
                    )}
                  </details>
                </>
              )}
            </details>
          </div>
          <nav className="instruction-files" aria-label={t('Agent documents')}>
            {search.trim() ? (
              selectedEntries.map((entry) => renderEntry(entry))
            ) : (
              <DocumentFolders
                key={scope}
                entries={selectedEntries}
                selected={document?.scope === scope ? document.path : undefined}
                renderFile={(entry) => renderEntry(entry, true)}
                onCreate={canCreate && !busy ? createDocument : undefined}
                t={t}
              />
            )}
            {searching && (
              <p role="status">{t('Searching document contents')}</p>
            )}
            {searchError && <p role="alert">{t('Document search failed')}</p>}
            {loading && !catalog && (
              <p role="status">{t('Loading documents')}</p>
            )}
            {!loading &&
              !searching &&
              !searchError &&
              !selectedEntries.length &&
              catalog && (
                <div className="instruction-no-results">
                  <FileText size={22} />
                  <p>
                    {t(
                      search || filter !== 'all'
                        ? 'No matching documents'
                        : 'No documents in this scope',
                    )}
                  </p>
                  {(search || filter !== 'all') && (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setSearch('');
                        setFilter('all');
                      }}
                    >
                      {t('Clear filters')}
                    </Button>
                  )}
                </div>
              )}
          </nav>
        </section>
        {document ? (
          <section
            className="instruction-editor"
            aria-label={t('Document editor')}
          >
            <header className="instruction-editor-heading">
              <div className="instruction-editor-title">
                <Button
                  className="instruction-mobile-picker"
                  variant="ghost"
                  size="icon"
                  aria-label={t('Show document list')}
                  onClick={() => setFilesOpen((value) => !value)}
                >
                  <FolderOpen size={17} />
                </Button>
                <div>
                  <h2>{selectedLabel}</h2>
                  <small>
                    {kindLabel(document)} · {t(scopeLabels[document.scope])}
                  </small>
                </div>
              </div>
              <div
                className="instruction-mode"
                role="group"
                aria-label={t('Document view')}
              >
                <button
                  aria-pressed={mode === 'read'}
                  onClick={() => setMode('read')}
                >
                  {t('Read document')}
                </button>
                <button
                  aria-pressed={mode === 'edit'}
                  onClick={() => setMode('edit')}
                >
                  {t(document.editable ? 'Edit source' : 'View source')}
                </button>
              </div>
            </header>
            <details className="instruction-location">
              <summary>{document.path}</summary>
              <code>
                {catalog?.roots[document.scope]}/{document.path}
              </code>
            </details>
            <div
              className={`instruction-editor-body ${mode === 'edit' ? 'editing' : ''}`}
            >
              {error && (
                <p className="instruction-alert" role="alert">
                  {t(errorCopy(error))}
                </p>
              )}
              <details className="instruction-context">
                <summary>
                  {t('Document scope and related instructions')}
                  {!document.editable ? ` · ${t('Read-only')}` : ''}
                </summary>
                <p>
                  {t(
                    document.scope === 'project'
                      ? 'These instructions belong to this project folder. Verify changes in a new session.'
                      : 'This document comes from the selected user or installed source.',
                  )}
                </p>
                {document.kind === 'skill' && (
                  <>
                    <p>
                      {t(
                        !discovery
                          ? 'Discovery not checked'
                          : discovered
                            ? discovered.enabled
                              ? 'Skill enabled'
                              : 'Skill disabled'
                            : 'Not in the discovered skills',
                      )}
                    </p>
                    {discovered && (
                      <p>
                        {discovered.name} — {discovered.description}
                      </p>
                    )}
                  </>
                )}
                {guidance.length > 0 && (
                  <>
                    <p>
                      {t(
                        'Related instruction files; an override takes precedence in its folder.',
                      )}
                    </p>
                    {guidance.map((entry) => (
                      <button
                        key={identity(entry)}
                        disabled={busy}
                        onClick={() => {
                          setScope(entry.scope);
                          setSearch('');
                          setFilter('all');
                          void open(entry);
                        }}
                      >
                        {entry.path}
                      </button>
                    ))}
                  </>
                )}
              </details>
              {mode === 'edit' ? (
                <>
                  <label className="sr-only" htmlFor="instruction-content">
                    {t('Document content')}
                  </label>
                  <textarea
                    id="instruction-content"
                    spellCheck={false}
                    value={content}
                    disabled={busy}
                    readOnly={!document.editable}
                    maxLength={65536}
                    aria-keyshortcuts="Control+s Meta+s"
                    onKeyDown={(event) => {
                      if (
                        (event.ctrlKey || event.metaKey) &&
                        event.key.toLowerCase() === 's'
                      ) {
                        event.preventDefault();
                        if (!busy && document.editable) void save();
                      }
                    }}
                    onChange={(e) => {
                      setContent(e.target.value);
                      setSaved(false);
                    }}
                  />
                </>
              ) : (
                <div
                  className="instruction-preview"
                  aria-label={t('Document preview')}
                >
                  {frontmatter && (
                    <details className="instruction-metadata">
                      <summary>{t('Skill metadata')}</summary>
                      <pre>{frontmatter[1]}</pre>
                    </details>
                  )}
                  {document.kind === 'metadata' ||
                  document.kind === 'script' ? (
                    <pre>{content}</pre>
                  ) : (
                    <Markdown
                      onLink={followLink}
                      text={
                        frontmatter
                          ? content.slice(frontmatter[0].length)
                          : content
                      }
                    />
                  )}
                </div>
              )}
              {error === 'instruction_conflict' && (
                <Button disabled={busy} onClick={() => void loadLatest()}>
                  {t('Load latest version and keep my draft')}
                </Button>
              )}
              {latestDocument &&
                identity(latestDocument) === identity(document) && (
                  <section className="stack">
                    <label>
                      {t('Latest saved content')}
                      <textarea
                        readOnly
                        value={latestDocument.content}
                        rows={8}
                      />
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
            </div>
            <footer className="instruction-editor-footer">
              <div className="instruction-save-state" role="status">
                {dirty ? (
                  <>
                    <span className="instruction-draft-dot" />
                    {t('Unsaved changes')}
                  </>
                ) : saved ? (
                  <>
                    <Check size={14} />
                    {t('Saved')}
                  </>
                ) : (
                  t('No unsaved changes')
                )}
                {mode === 'edit' && <kbd>⌘ / Ctrl S</kbd>}
              </div>
              <div className="instruction-actions">
                <Button
                  variant="ghost"
                  size="icon"
                  disabled={busy || dirty}
                  onClick={() => void open(document, true)}
                  aria-label={t('Reload document')}
                >
                  <RefreshCw size={15} />
                </Button>
                <Button
                  disabled={
                    busy || dirty || !document.exists || !document.editable
                  }
                  title={
                    dirty
                      ? t('Save your changes before asking Codex.')
                      : undefined
                  }
                  onClick={() => {
                    setRequest('');
                    setRequestOpen(true);
                  }}
                >
                  <Sparkles size={15} />
                  {t('Ask Codex to edit')}
                </Button>
                <Button
                  variant="primary"
                  disabled={
                    busy || !document.editable || (!dirty && document.exists)
                  }
                  onClick={() => void save()}
                >
                  {t('Save document')}
                </Button>
              </div>
            </footer>
          </section>
        ) : (
          <section className="instruction-editor instruction-editor-empty">
            {error && (
              <p className="instruction-alert" role="alert">
                {t(errorCopy(error))}
              </p>
            )}
            <EmptyState
              icon={<BookOpen size={28} />}
              title={t('Choose an agent document')}
              description={t(
                'Open a file to edit it, or create instructions or a skill at an official location.',
              )}
            />
          </section>
        )}
      </div>
      <Dialog
        open={helpOpen && active}
        onOpenChange={setHelpOpen}
        title={t('How Codex uses these files')}
        closeLabel={t('Close')}
      >
        <div className="instruction-guide">
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
          <p>
            {t(
              'This workspace uses the configured Git repository. Instruction and skill rules do not depend on the project name, language, or framework.',
            )}
          </p>
          <p>
            {t(
              'Codex uses at most one non-empty instruction file per folder, from the project root to the working folder. Fallback filenames run in Codex but are not editable here.',
            )}
          </p>
          <p>
            {t(
              'The editor limit is 64 KiB per file; Codex has a separate combined project instruction limit, normally 32 KiB.',
            )}
          </p>
          <p>
            {t(
              'Codex can discover linked skill folders and load assets on demand. The file editor excludes symlinks and non-text assets; check native discovery for those skills.',
            )}
          </p>
          <p>
            {t(
              'Workbench sessions disable plugin and MCP execution. Installed files remain available for inspection.',
            )}
          </p>
          <p>
            {t(
              'Discovery preserves same-name skills at different paths. Session and template execution still selects by name; use unique names for explicit selection.',
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
        </div>
      </Dialog>
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
                setMode('edit');
                setFilesOpen(false);
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
                const skillFolder = createFolder.match(
                  /^(.*(?:^|\/)skills\/[^/]+)(?:\/.*)?$/,
                )?.[1];
                const prefix = skillFolder
                  ? `${skillFolder}/`
                  : createFolder.endsWith('skills')
                    ? `${createFolder}/my-skill/`
                    : scope === 'project'
                      ? `${createFolder ? createFolder + '/' : ''}.agents/skills/my-skill/`
                      : 'skills/my-skill/';
                setPath(
                  next === 'instructions'
                    ? `${createFolder ? createFolder + '/' : ''}AGENTS.md`
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
