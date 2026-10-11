/** Suggestions remain metadata; the server owns admission and uniqueness checks. */
export function suggestAppId(title: string, existing: Iterable<string>) {
  const normalized = title.normalize('NFKC').trim().toLocaleLowerCase('en-US');
  let hash = 2166136261;
  for (const character of normalized)
    hash = Math.imul(hash ^ (character.codePointAt(0) ?? 0), 16777619) >>> 0;
  let slug = normalized
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  if (!slug) slug = 'app';
  if (!/^[a-z]/.test(slug)) slug = `app-${slug}`;
  const base = `${slug.slice(0, 45).replace(/-+$/g, '')}-${hash.toString(16).padStart(8, '0')}`;
  const taken = new Set(existing);
  let candidate = base;
  for (let suffix = 2; taken.has(candidate); suffix++) {
    const ending = `-${suffix}`;
    candidate = `${base.slice(0, 64 - ending.length)}${ending}`;
  }
  return candidate;
}

/** A reserved .invalid address identifies local source; no remote is created. */
export function localAppRepository(appId: string) {
  return `https://miy-apps.invalid/local/${encodeURIComponent(appId)}.git`;
}
