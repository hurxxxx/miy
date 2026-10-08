import '@/src/platform/i18n';
import '@miy/ui/styles.css';
import '@/src/index.css';
import '@miy/official-suite-web/calendar/fullcalendar-theme.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import OfficialSuiteRoot from './OfficialSuiteRoot';

const root = document.getElementById('root');
if (!root) throw new Error('Official suite root element is missing');
createRoot(root).render(
  <StrictMode>
    <OfficialSuiteRoot />
  </StrictMode>,
);
