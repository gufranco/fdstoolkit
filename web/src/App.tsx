import type { ReactElement } from 'react';

const TITLE = 'Famicom Disk System Toolkit';

export function App(): ReactElement {
  return (
    <div className="shell">
      <header>
        <h1>{TITLE}</h1>
      </header>
    </div>
  );
}
