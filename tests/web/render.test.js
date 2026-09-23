import { beforeEach, describe, expect, it } from 'vitest';

import { describe as describeValue, renderResult } from '../../src/fdstoolkit/ui/static/app.js';

let target;

beforeEach(() => {
  target = document.createElement('div');
});

describe('renderResult', () => {
  it('offers a download when the payload carries bytes', () => {
    renderResult(target, { name: 'demo.fds', data: 'AA==', size: 131000 });

    expect(target.querySelector('.banner').className).toContain('good');
    expect(target.querySelector('a').download).toBe('demo.fds');
    expect(target.querySelector('.download-size').textContent).toBe('127.9 KiB');
  });

  it('offers every file when the payload carries several', () => {
    const files = [
      { name: 'a.fds', data: 'AA==', size: 10 },
      { name: 'b.fds', data: 'AA==', size: 20 },
    ];

    renderResult(target, { files });

    expect(target.querySelectorAll('a')).toHaveLength(2);
    expect(target.querySelector('.banner').textContent).toContain('2');
  });

  it('does not claim a disk listing is a set of downloads', () => {
    renderResult(target, { files: [{ name: 'GAME', size: 4096, hidden: false }] });

    expect(target.querySelectorAll('a')).toHaveLength(0);
    expect(target.querySelector('table')).not.toBeNull();
  });

  it('shows rendered text as text rather than json', () => {
    renderResult(target, { text: 'Game name: SMB' });

    expect(target.querySelector('pre').textContent).toBe('Game name: SMB');
  });

  it('labels the values of a reported object and keeps the raw response', () => {
    renderResult(target, { grade: 'clean', sides: 2 });

    const keys = [...target.querySelectorAll('dt')].map((node) => node.textContent);
    expect(keys).toEqual(['grade', 'sides']);
    expect(target.querySelector('details summary').textContent).toBe('Show the raw response');
  });

  it('falls back to json when the payload is not an object', () => {
    renderResult(target, 42);

    expect(target.querySelector('pre').textContent).toBe('42');
  });
});

describe('describe', () => {
  it('renders a list of records as a table with one column per key', () => {
    const node = describeValue([
      { index: 0, blocks: 2 },
      { index: 1, blocks: 2 },
    ]);

    expect([...node.querySelectorAll('th')].map((cell) => cell.textContent)).toEqual([
      'index',
      'blocks',
    ]);
    expect(node.querySelectorAll('tr')).toHaveLength(3);
  });

  it('joins a list of plain values', () => {
    expect(describeValue(['FDS001', 'FDS010']).textContent).toBe('FDS001, FDS010');
  });

  it('says so when a list is empty rather than rendering nothing', () => {
    expect(describeValue([]).textContent).toBe('nothing');
  });

  it('nests a labelled view for an object', () => {
    const node = describeValue({ worst: 'error' });

    expect(node.querySelector('dt').textContent).toBe('worst');
  });

  it('renders a scalar directly', () => {
    expect(describeValue('clean').textContent).toBe('clean');
  });

  it('gives a table a column for a key only some records carry', () => {
    const node = describeValue([{ a: 1 }, { b: 2 }]);

    expect([...node.querySelectorAll('th')].map((cell) => cell.textContent)).toEqual(['a', 'b']);
  });
});
