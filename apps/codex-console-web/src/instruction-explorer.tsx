import { FolderOpen, Plus } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import type { components } from './api.generated';
import type { Translate } from './i18n';

type Entry = components['schemas']['DocumentEntry'];
type Node = { path: string; files: Entry[]; folders: Map<string, Node> };

export function linkedDocument(current: Entry, href: string, entries: Entry[]) {
  if (/^[a-z][a-z\d+.-]*:/i.test(href) || href.startsWith('//')) return null;
  try {
    const url = new URL(href, `https://documents.invalid/${current.path}`);
    const path = decodeURIComponent(url.pathname).slice(1);
    return (
      entries.find((e) => e.scope === current.scope && e.path === path) ?? null
    );
  } catch {
    return null;
  }
}

export function relatedGuidance(entries: Entry[], selected: Entry) {
  const folder = selected.path.split('/').slice(0, -1).join('/');
  return entries
    .filter((e) => {
      if (e.kind !== 'instructions') return false;
      if (e.scope === 'global') return true;
      if (e.scope !== 'project' || selected.scope !== 'project') return false;
      const parent = e.path.split('/').slice(0, -1).join('/');
      return !parent || folder === parent || folder.startsWith(`${parent}/`);
    })
    .sort((a, b) =>
      a.scope === b.scope
        ? a.path.split('/').length - b.path.split('/').length ||
          a.path.localeCompare(b.path)
        : a.scope === 'global'
          ? -1
          : 1,
    );
}

export function DocumentFolders({
  entries,
  selected,
  renderFile,
  onCreate,
  t,
}: {
  entries: Entry[];
  selected: string | undefined;
  renderFile: (entry: Entry) => ReactNode;
  onCreate?: (folder: string) => void;
  t: Translate;
}) {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const root: Node = { path: '', files: [], folders: new Map() };
  for (const entry of entries) {
    let node = root;
    const parts = entry.path.split('/');
    for (const part of parts.slice(0, -1)) {
      const path = node.path ? `${node.path}/${part}` : part;
      if (!node.folders.has(part))
        node.folders.set(part, { path, files: [], folders: new Map() });
      node = node.folders.get(part)!;
    }
    node.files.push(entry);
  }
  useEffect(() => {
    if (selected)
      setClosed(
        (previous) =>
          new Set(
            [...previous].filter((path) => !selected.startsWith(`${path}/`)),
          ),
      );
  }, [selected]);
  const folderPaths = (node: Node): string[] =>
    [...node.folders.values()].flatMap((folder) => [
      folder.path,
      ...folderPaths(folder),
    ]);
  const render = (node: Node): ReactNode => (
    <>
      {node.files.map(renderFile)}
      {[...node.folders.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([name, folder]) => (
          <details
            key={folder.path}
            className="instruction-folder"
            open={!closed.has(folder.path)}
            onToggle={(event) => {
              const open = event.currentTarget.open;
              setClosed((previous) => {
                if (previous.has(folder.path) === !open) return previous;
                const next = new Set(previous);
                if (open) next.delete(folder.path);
                else next.add(folder.path);
                return next;
              });
            }}
          >
            <summary title={folder.path}>
              <FolderOpen size={14} />
              <span>{name}</span>
              {onCreate && (
                <button
                  type="button"
                  className="instruction-folder-create"
                  title={t('New document here')}
                  aria-label={`${t('New document here')}: ${folder.path}`}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    onCreate(folder.path);
                  }}
                >
                  <Plus size={12} />
                </button>
              )}
            </summary>
            <div className="instruction-folder-children">{render(folder)}</div>
          </details>
        ))}
    </>
  );
  return (
    <>
      <div className="instruction-folder-tools">
        <button onClick={() => setClosed(new Set())}>
          {t('Expand folders')}
        </button>
        <button onClick={() => setClosed(new Set(folderPaths(root)))}>
          {t('Collapse folders')}
        </button>
      </div>
      {render(root)}
    </>
  );
}
