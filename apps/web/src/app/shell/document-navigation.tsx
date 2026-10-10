import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/** Resolve a programmatic SPA entry through the same-origin ingress owner. */
export function DocumentNavigation() {
  const location = useLocation();
  const href = `${location.pathname}${location.search}${location.hash}`;
  useEffect(() => {
    window.location.replace(href);
  }, [href]);
  return null;
}
