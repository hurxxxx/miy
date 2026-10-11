import { Folder } from 'lucide-react';
import { Link } from 'react-router-dom';

import { cn } from '@miy/ui';
import { buildAppHref } from '@miy/contracts/app-routes';
import type { FolderNode } from './folder-tree-model';

export function FolderTreeRow({
  activeFolderId,
  folder,
  level,
}: {
  activeFolderId: string | null;
  folder: FolderNode;
  level: number;
}) {
  const path = `${buildAppHref({ routeId: 'files.root' })}?folder=${encodeURIComponent(folder.id)}`;
  return (
    <>
      <Link
        to={path}
        className={cn(
          'sidebar-submenu-item ml-1',
          activeFolderId === folder.id && 'sidebar-submenu-item-active',
        )}
        style={{ paddingLeft: `${12 + level * 12}px` }}
      >
        <Folder size={14} className="text-app-ink/55" />
        <span className="sidebar-submenu-label truncate">{folder.name}</span>
      </Link>
      {folder.children.map((child) => (
        <FolderTreeRow
          key={child.id}
          activeFolderId={activeFolderId}
          folder={child}
          level={level + 1}
        />
      ))}
    </>
  );
}
