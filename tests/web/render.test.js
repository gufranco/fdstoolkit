import { beforeEach, describe, expect, it } from 'vitest';

import {
  describe as describeValue,
  isChange,
  isProse,
  renderResult,
} from '../../src/fdstoolkit/ui/static/app.js';

let target;

beforeEach(() => {
  target = document.createElement('div');
});

describe('renderResult', () => {
  it('offers the file and reports what came with it', () => {
    renderResult(target, {
      headline: '1 block(s) disagree across the dumps',
      file: { name: 'consensus.fds', data: 'AA==', size: 10 },
      rows: [{ side: 0, block: 3 }],
      ok: false,
    });

    expect(target.querySelector('.banner').textContent).toBe('1 block(s) disagree across the dumps');
    expect(target.querySelector('a').download).toBe('consensus.fds');
    expect(target.textContent).toContain('block');
  });

  it('offers a download when the payload carries bytes', () => {
    renderResult(target, { name: 'demo.fds', data: 'AA==', size: 131000 });

    expect(target.querySelector('.banner').className).toContain('good');
    expect(target.querySelector('a').download).toBe('demo.fds');
    expect(target.querySelector('.download-size').textContent).toBe('127.9 KiB');
  });

  it('offers the capture bundle a dump kept beside the image', () => {
    renderResult(target, {
      name: 'dump.fds',
      data: 'AA==',
      size: 10,
      grade: 'clean',
      captures: { name: 'dump.captures.zip', data: 'AA==', size: 20 },
    });

    const links = [...target.querySelectorAll('a')].map((link) => link.download);

    expect(links).toEqual(['dump.fds', 'dump.captures.zip']);
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

  it('puts the headline in the banner rather than in the value list', () => {
    renderResult(target, { headline: 'side count differs: 2 against 1', identical: false, ok: false });

    expect(target.querySelector('.banner').textContent).toBe('side count differs: 2 against 1');
    expect([...target.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(['identical']);
  });

  it('drops the empty answers once the headline has explained the outcome', () => {
    renderResult(target, {
      headline: 'side count differs: 2 against 1',
      identical: false,
      same_software: null,
      blocks: [],
      differences: [],
      ok: false,
    });

    expect([...target.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(['identical']);
  });

  it('keeps the empty answers when no headline explains them', () => {
    renderResult(target, { rows: [], ok: true });

    expect([...target.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(['rows']);
  });

  it('keeps an answer that carries something alongside the headline', () => {
    renderResult(target, {
      headline: '2 block(s) differ',
      blocks: [{ side: 0, block: 0 }],
      differences: [],
      ok: false,
    });

    expect([...target.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(['blocks']);
    expect(target.querySelector('table')).not.toBeNull();
  });

  it('shows the banner alone when the headline is the whole answer', () => {
    renderResult(target, { headline: '0 file(s) across 2 side(s)', rows: [], ok: true });

    expect(target.querySelector('dl')).toBeNull();
    expect(target.querySelector('.banner').textContent).toBe('0 file(s) across 2 side(s)');
    expect(target.querySelector('details')).not.toBeNull();
  });

  it('does not paint a negative answer as a success', () => {
    renderResult(target, { headline: '2 block(s) differ', ok: false });

    expect(target.querySelector('.banner').className).toContain('warn');
  });

  it('keeps the banner green when the answer is positive', () => {
    renderResult(target, { headline: 'identical', ok: true });

    expect(target.querySelector('.banner').className).toContain('good');
  });

  it('says findings are below when a negative answer carries no headline', () => {
    renderResult(target, { rows: [{ code: 'FDS001' }], ok: false });

    expect(target.querySelector('.banner').textContent).toBe('Done. The answer is below.');
  });

  it('keeps the headline in the raw response', () => {
    renderResult(target, { headline: 'identical', ok: true });

    expect(target.querySelector('details pre').textContent).toContain('headline');
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


const CHANGE = {
  side: 0,
  field: 'game_name',
  description: 'three-letter game code',
  identity: true,
  left: 'SMB',
  right: 'ZLD',
};

describe('change records', () => {
  it('renders a before and after rather than a row of columns', () => {
    const node = describeValue([CHANGE]);

    expect(node.querySelector('table')).toBeNull();
    expect(node.querySelectorAll('.change')).toHaveLength(1);
  });

  it('puts the two values side by side under their own labels', () => {
    const node = describeValue([CHANGE]);
    const sides = [...node.querySelectorAll('.side-value')].map((cell) => cell.textContent);

    expect(sides).toEqual(['SMB', 'ZLD']);
  });

  it('keeps prose out of the chips and gives it its own line', () => {
    const node = describeValue([CHANGE]);

    expect(node.querySelector('.change-note').textContent).toBe('three-letter game code');
    expect([...node.querySelectorAll('.chip-key')].map((n) => n.textContent)).toEqual([
      'side',
      'field',
    ]);
  });

  it('shows a true flag as its name alone, with no yes beside it', () => {
    const node = describeValue([CHANGE]);

    expect(node.querySelector('.chip-flag').textContent).toBe('identity');
    expect(node.textContent).not.toContain('yes');
  });

  it('leaves a false flag out entirely', () => {
    const node = describeValue([{ ...CHANGE, identity: false }]);

    expect(node.querySelector('.chip-flag')).toBeNull();
    expect(node.textContent).not.toContain('identity');
  });

  it('takes the full width so the values are never squeezed', () => {
    const node = describeValue([CHANGE]);

    expect(node.classList.contains('wide')).toBe(true);
  });
});

describe('shape tests', () => {
  it('reads a record carrying both ends as a change', () => {
    expect(isChange([CHANGE])).toBe(true);
    expect(isChange([{ side: 0, block: 0 }])).toBe(false);
  });

  it('treats a phrase as prose and a token as a chip', () => {
    expect(isProse('three-letter game code')).toBe(true);
    expect(isProse('game_name')).toBe(false);
    expect(isProse(0)).toBe(false);
  });
});

describe('wide values', () => {
  it('lifts the label onto its own line so a table gets the whole column', () => {
    const target = document.createElement('div');

    renderResult(target, { rows: [{ a: 1, b: 2, c: 3 }] });

    expect(target.querySelector('dt').classList.contains('wide')).toBe(true);
  });

  it('leaves a short value beside its label', () => {
    const target = document.createElement('div');

    renderResult(target, { grade: 'clean' });

    expect(target.querySelector('dt').classList.contains('wide')).toBe(false);
  });
});
