import { useEffect, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import {
  firstPartyUiOwner,
  reloadFirstPartyDocument,
  type FirstPartyUiOwner,
} from './first-party-navigation';

/** Router push/replace/back already owns the URL and native history state. */
export function FirstPartyDocumentBoundary({
  owner,
  children,
}: {
  owner: FirstPartyUiOwner;
  children: ReactNode;
}) {
  const location = useLocation();
  const crossesOwner = firstPartyUiOwner(location.pathname) !== owner;
  useEffect(() => {
    if (crossesOwner) reloadFirstPartyDocument();
  }, [crossesOwner, location.key]);
  return crossesOwner ? null : children;
}
