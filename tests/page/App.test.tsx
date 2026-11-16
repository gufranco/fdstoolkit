import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../web/src/App';

afterEach(() => {
  document.body.replaceChildren();
});

describe('App', () => {
  it('names the toolkit in its main heading', () => {
    // Arrange
    const expected = 'Famicom Disk System Toolkit';

    // Act
    render(<App />);

    // Assert
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(expected);
  });
});

describe('mount', () => {
  it('renders the page into the root element', async () => {
    // Arrange
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

    // Act
    const loading = import('../../web/src/main');

    // Assert
    await expect(loading).rejects.toThrow('the page has no element with id "root" to render into');
  });
});
