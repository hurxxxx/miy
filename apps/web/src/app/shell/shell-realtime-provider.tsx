import { RealtimeProvider, useRealtime } from '@miy/platform-web/realtime';
import type { ReactNode } from 'react';
import { ShellRealtimeProvider } from './shell-realtime-context';

function ShellRealtimeBridge({ children }: { children: ReactNode }) {
  return (
    <ShellRealtimeProvider value={useRealtime()}>
      {children}
    </ShellRealtimeProvider>
  );
}

/** Both trusted first-party UI roots use the same live platform realtime contexts. */
export function DefaultShellRealtimeProvider({
  children,
  token,
}: {
  children: ReactNode;
  token: string | null;
}) {
  return (
    <RealtimeProvider token={token}>
      <ShellRealtimeBridge>{children}</ShellRealtimeBridge>
    </RealtimeProvider>
  );
}
