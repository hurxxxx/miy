import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { connectApp } from '@miy/app-sdk';
import './style.css';
import { applyUIContext, copyFor } from './presentation.mjs';

function App() {
  const [config, setConfig] = useState(null);
  const [session, setSession] = useState(null);
  const [notes, setNotes] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('settings');
  const [locale, setLocale] = useState('ko-KR');
  const connection = useRef(null);
  const copy = copyFor(locale);

  async function request(token, path, options = {}) {
    const response = await fetch(path, {
      ...options,
      signal: options.signal ?? connection.current?.signal,
      credentials: 'omit',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
    });
    if ([401, 403].includes(response.status)) {
      setSession(null);
      setNotes([]);
      setCursor(null);
      throw new Error('sessionChanged');
    }
    if (!response.ok)
      throw new Error(response.status === 409 ? 'conflict' : 'requestFailed');
    return response.status === 204 ? null : response.json();
  }

  async function load(
    token,
    after = null,
    signal = connection.current?.signal,
  ) {
    const result = await request(
      token,
      `/api/notes${after ? `?after=${encodeURIComponent(after)}` : ''}`,
      { signal },
    );
    if (signal?.aborted) return;
    setNotes((previous) =>
      after ? [...previous, ...result.items] : result.items,
    );
    setCursor(result.next_cursor);
  }

  async function connect(settings, hostWindow) {
    connection.current?.abort();
    const controller = new AbortController();
    connection.current = controller;
    const { signal } = controller;
    setBusy(true);
    setStatus('connecting');
    setSession(null);
    try {
      const next = await connectApp({
        platformOrigin: settings.platform_origin,
        installationId: settings.installation_id,
        hostWindow,
        signal,
        onUIContext: (value) => setLocale(applyUIContext(document, value)),
      });
      if (signal?.aborted) return;
      await load(next.token, null, signal);
      if (signal?.aborted) return;
      setSession(next);
      setStatus('notesConnected');
    } catch (error) {
      if (!signal.aborted) {
        setStatus(
          error.message === 'sessionChanged'
            ? 'sessionChanged'
            : 'connectFailed',
        );
        controller.abort();
        setBusy(false);
      }
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/config', { signal: controller.signal, cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw new Error('configFailed');
        const settings = await response.json();
        if (controller.signal.aborted) return;
        setConfig(settings);
        if (window.parent !== window) await connect(settings, window.parent);
        else setStatus('notesStandalone');
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus('configFailed');
      });
    return () => {
      controller.abort();
      connection.current?.abort();
    };
  }, []);

  function startConnection() {
    const path = `/apps/${encodeURIComponent(config.app_id)}/installed/${encodeURIComponent(config.installation_id)}?connect=popup`;
    const host =
      window.parent !== window
        ? window.parent
        : window.open(
            new URL(path, config.platform_origin).href,
            'miy-app-connect',
            'popup,width=560,height=640',
          );
    if (!host) {
      setStatus('popupBlocked');
      return;
    }
    void connect(config, host);
  }

  async function operation(callback) {
    const signal = connection.current?.signal;
    setBusy(true);
    try {
      await callback();
      if (!signal?.aborted) setStatus('notesChecked');
    } catch (error) {
      if (!signal?.aborted) {
        setStatus(
          ['sessionChanged', 'conflict', 'requestFailed'].includes(
            error.message,
          )
            ? error.message
            : 'requestFailed',
        );
      }
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }

  return (
    <main>
      <h1>{copy.notesTitle}</h1>
      <p>{copy.notesPrivacy}</p>
      <p role="status">{copy[status]}</p>
      <button disabled={!config || busy} onClick={startConnection}>
        {copy.connect}
      </button>
      {session && (
        <>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void operation(async () => {
                await request(session.token, '/api/notes', {
                  method: 'POST',
                  body: JSON.stringify({ text: draft }),
                });
                setDraft('');
                await load(session.token);
              });
            }}
          >
            <label htmlFor="note">{copy.newNote}</label>
            <textarea
              id="note"
              required
              maxLength={4000}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            <button disabled={busy || !draft.trim()}>{copy.save}</button>
          </form>
          <button
            disabled={busy}
            onClick={() => void operation(() => load(session.token))}
          >
            {copy.refresh}
          </button>
          <ul>
            {notes.map((note) => (
              <li key={note.id}>
                <p style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                  {note.payload.text}
                </p>
                <button
                  disabled={busy}
                  onClick={() =>
                    void operation(async () => {
                      await request(
                        session.token,
                        `/api/notes/${note.id}?expected_version=${note.version}`,
                        { method: 'DELETE' },
                      );
                      await load(session.token);
                    })
                  }
                >
                  {copy.remove}
                </button>
              </li>
            ))}
          </ul>
          {cursor && (
            <button
              disabled={busy}
              onClick={() => void operation(() => load(session.token, cursor))}
            >
              {copy.more}
            </button>
          )}
        </>
      )}
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
