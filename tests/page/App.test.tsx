import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../web/src/App';
import { serve, settle } from './harness';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('App', () => {
  it('names the toolkit in its main heading and lists the command families', async () => {
    // Arrange
    serve();

    // Act
    render(<App />);
    await settle();

    // Assert
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Famicom Disk System Toolkit');
    expect(screen.getByRole('navigation', { name: 'Command families' }).querySelectorAll('button')).toHaveLength(6);
  });
});

describe('mount', () => {
  afterEach(async () => {
    const entry = await import('../../web/src/main');
    act(() => {
      entry.root.unmount();
    });
  });

  it('renders the page into the root element', async () => {
    // Arrange
    serve();
    const root = document.createElement('div');
    root.id = 'root';
    document.body.append(root);

    // Act
    await import('../../web/src/main');

    // Assert
    const heading = await screen.findByRole('heading', { level: 1 });
    expect(root.contains(heading)).toBe(true);
  });
});

describe('mount without a root', () => {
  it('refuses to start and names the element it needs', async () => {
    // Arrange
    vi.resetModules();
    document.body.replaceChildren();

    // Act
    const loading = import('../../web/src/main');

    // Assert
    await expect(loading).rejects.toThrow('the page has no element with id "root" to render into');
  });
});
