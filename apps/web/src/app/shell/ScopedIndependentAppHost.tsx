import { useParams } from 'react-router-dom';
import { IndependentAppHost } from '@/src/platform/apps/IndependentAppHost';
import { NotFoundView } from '@/src/platform/auth/settings-pages';

/** A composition scope limits rendered routes; the server still enforces admission. */
export function ScopedIndependentAppHost({
  appIds,
}: {
  appIds?: readonly string[];
}) {
  const { appId } = useParams();
  if (appIds && (!appId || !appIds.includes(appId))) return <NotFoundView />;
  return <IndependentAppHost />;
}
