import { StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import './styles/app.css';
import './styles/results.css';

import { App } from './App';

const ROOT_ID = 'root';

function mount(): Root {
  const host = document.getElementById(ROOT_ID);
  if (host === null) {
    throw new Error(`the page has no element with id "${ROOT_ID}" to render into`);
  }
  const root = createRoot(host);
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
  return root;
}

export const root = mount();
