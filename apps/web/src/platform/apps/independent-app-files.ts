import { apiFetchJson } from '@/src/platform/api/client';
import type { ApiSchema } from '@/src/platform/api/types';
import {
  checkedIndependentFileMetadata,
  checkedIndependentSelectedFile,
  type IndependentFileSelectionMetadata,
  type IndependentFileSelectionRequest,
} from './independent-app-host';

const filesApi = '/api/v1/independent-apps/_files';
const context = (request: IndependentFileSelectionRequest) => ({
  schema_version: 1,
  installation_id: request.installation_id,
  audience: request.audience,
  selection_id: request.selection_id,
  selection_request: request.selection_request,
});

export type FileCandidatePage = Pick<
  ApiSchema<'FileCandidatesOut'>,
  'items' | 'next_cursor' | 'incomplete'
>;

/** The trusted host receives metadata only; file bytes stay on the app read path. */
export function parseFileCandidatePage(
  value: unknown,
  request: IndependentFileSelectionRequest,
): FileCandidatePage {
  const invalid = () => {
    throw new Error('invalid-file-candidates');
  };
  if (!value || typeof value !== 'object' || Array.isArray(value))
    return invalid();
  const page = value as Record<string, unknown>;
  if (
    Object.keys(page).length !== 7 ||
    page.schema_version !== 1 ||
    page.installation_id !== request.installation_id ||
    page.audience !== request.audience ||
    page.selection_id !== request.selection_id ||
    !Array.isArray(page.items) ||
    page.items.length > 25 ||
    typeof page.incomplete !== 'boolean' ||
    !(
      page.next_cursor === null ||
      (typeof page.next_cursor === 'string' &&
        page.next_cursor.length > 0 &&
        page.next_cursor.length <= 2048 &&
        /^[\x21-\x7e]+$/.test(page.next_cursor))
    )
  )
    return invalid();
  const items: IndependentFileSelectionMetadata[] = [];
  const ids = new Set<string>();
  for (const item of page.items) {
    const checked = checkedIndependentFileMetadata(item);
    if (!checked || ids.has(checked.file_id)) return invalid();
    ids.add(checked.file_id);
    items.push(checked);
  }
  return {
    items,
    next_cursor: page.next_cursor as string | null,
    incomplete: page.incomplete,
  };
}

async function post(
  suffix: 'candidates' | 'authorize-selection',
  token: string,
  body: object,
  signal: AbortSignal,
): Promise<unknown> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal.addEventListener('abort', cancel, { once: true });
  if (signal.aborted) controller.abort();
  let rejectCancelled!: () => void;
  const cancelled = new Promise<never>((_, reject) => {
    rejectCancelled = () => reject(new Error('file-selection-unavailable'));
    controller.signal.addEventListener('abort', rejectCancelled, {
      once: true,
    });
    if (controller.signal.aborted) rejectCancelled();
  });
  const timeout = setTimeout(cancel, 8000);
  try {
    return await Promise.race([
      apiFetchJson<unknown>(`${filesApi}/${suffix}`, token, {
        method: 'POST',
        body: JSON.stringify(body),
        signal: controller.signal,
        credentials: 'omit',
        redirect: 'error',
        cache: 'no-store',
      }),
      cancelled,
    ]);
  } finally {
    clearTimeout(timeout);
    signal.removeEventListener('abort', cancel);
    controller.signal.removeEventListener('abort', rejectCancelled);
    controller.abort();
  }
}

export async function getFileCandidates(
  token: string,
  request: IndependentFileSelectionRequest,
  query: string,
  cursor: string | null,
  signal: AbortSignal,
) {
  if (query.length > 120 || (cursor !== null && cursor.length > 2048))
    throw new Error('invalid-file-query');
  return parseFileCandidatePage(
    await post(
      'candidates',
      token,
      {
        ...context(request),
        query,
        cursor,
        limit: 25,
      },
      signal,
    ),
    request,
  );
}

export async function authorizeFileSelection(
  token: string,
  request: IndependentFileSelectionRequest,
  file: IndependentFileSelectionMetadata,
  signal: AbortSignal,
) {
  const value = await post(
    'authorize-selection',
    token,
    {
      ...context(request),
      file_id: file.file_id,
      expected_version: file.version,
    },
    signal,
  );
  const selected = checkedIndependentSelectedFile(value, request);
  if (
    !selected ||
    selected.file.file_id !== file.file_id ||
    selected.file.version !== file.version ||
    selected.file.name !== file.name ||
    selected.file.content_type !== file.content_type ||
    selected.file.size_bytes !== file.size_bytes
  )
    throw new Error('invalid-selected-file');
  return selected;
}
