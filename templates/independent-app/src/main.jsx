import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { connectApp } from '@miy/app-sdk';
import './style.css';
import { applyUIContext, copyFor } from './presentation.mjs';

function App() {
  const [config, setConfig] = useState(null);
  const [identity, setIdentity] = useState(null);
  const [status, setStatus] = useState('settings');
  const [connecting, setConnecting] = useState(false);
  const [locale, setLocale] = useState('ko-KR');
  const connection = useRef(null);
  const copy = copyFor(locale);

  async function connect(settings, hostWindow) {
    connection.current?.abort();
    const controller = new AbortController();
    connection.current = controller;
    const { signal } = controller;
    setConnecting(true);
    setStatus('connecting');
    try {
      const session = await connectApp({
        platformOrigin: settings.platform_origin,
        installationId: settings.installation_id,
        hostWindow,
        signal,
        onUIContext: (value) => setLocale(applyUIContext(document, value)),
      });
      const response = await fetch('/api/me', {
        headers: { Authorization: `Bearer ${session.token}` },
        credentials: 'omit',
        cache: 'no-store',
        signal,
      });
      if (!response.ok) throw new Error('connectFailed');
      const person = await response.json();
      if (signal?.aborted) return;
      setIdentity(person);
      setStatus('connected');
      // The pilot reads identity once and never persists a token in browser storage.
      // Business requests must use the app-scoped token and revalidate it on the server.
    } catch {
      if (signal?.aborted) return;
      setIdentity(null);
      setStatus('connectFailed');
      controller.abort();
      setConnecting(false);
    } finally {
      if (!signal?.aborted) setConnecting(false);
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
        else setStatus('standalone');
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus('configFailed');
      });
    return () => {
      controller.abort();
      connection.current?.abort();
    };
  }, []);

  const startConnection = () => {
    if (window.parent !== window) {
      void connect(config, window.parent);
      return;
    }
    const path = `/apps/${encodeURIComponent(config.app_id)}/installed/${encodeURIComponent(config.installation_id)}?connect=popup`;
    const host = window.open(
      new URL(path, config.platform_origin).href,
      'miy-app-connect',
      'popup,width=560,height=640',
    );
    if (!host) {
      setStatus('popupBlocked');
      return;
    }
    void connect(config, host);
  };

  return (
    <main>
      <p className="eyebrow">MIY independent app · protocol v1</p>
      <h1>{copy.title}</h1>
      <p role="status">{copy[status]}</p>
      {identity && (
        <p>
          {copy.welcome}
          <strong>{identity.display_name}</strong>
        </p>
      )}
      <button
        type="button"
        disabled={!config || connecting}
        onClick={startConnection}
      >
        {connecting ? copy.connectingLabel : copy.connect}
      </button>
      <p>{copy.description}</p>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
