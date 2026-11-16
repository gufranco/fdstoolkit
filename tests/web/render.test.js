import { beforeEach, describe, expect, it } from 'vitest';

import {
  describe as describeValue,
  renderResult,
} from '../../src/fdstoolkit/ui/static/render.js';
import { fileStems, seeded } from './fakes.js';

const FAKE = seeded('render.test');
const [STEM, OTHER_STEM, THIRD_STEM, FOURTH_STEM, FIFTH_STEM] = fileStems(FAKE, 5);

let target;

beforeEach(() => {
  target = document.createElement('div');
});

describe('renderResult', () => {
  it('offers the file and reports what came with it', () => {
    // Arrange
    const expected = '1 block(s) disagree across the dumps';

    // Act
    renderResult(target, {
      headline: '1 block(s) disagree across the dumps',
      file: { name: `${STEM}.fds`, data: 'AA==', size: 10 },
      rows: [{ side: 0, block: 3 }],
      ok: false,
    });

    // Assert
    expect(target.querySelector('.banner').textContent).toBe(expected);
    expect(target.querySelector('a').download).toBe(`${STEM}.fds`);
    expect(target.textContent).toContain('block');
  });

  it('offers a download when the payload carries bytes', () => {
    // Arrange
    const expected = 'good';

    // Act
    renderResult(target, { name: `${OTHER_STEM}.fds`, data: 'AA==', size: 131000 });

    // Assert
    expect(target.querySelector('.banner').className).toContain(expected);
    expect(target.querySelector('a').download).toBe(`${OTHER_STEM}.fds`);
    expect(target.querySelector('.download-size').textContent).toBe('127.9 KiB');
  });

  it('offers the capture bundle a dump kept beside the image', () => {
    // Arrange
    renderResult(target, {
      name: `${THIRD_STEM}.fds`,
      data: 'AA==',
      size: 10,
      grade: 'clean',
      captures: { name: `${THIRD_STEM}.captures.zip`, data: 'AA==', size: 20 },
    });

    // Act
    const links = [...target.querySelectorAll('a')].map((link) => link.download);

    // Assert
    expect(links).toEqual([`${THIRD_STEM}.fds`, `${THIRD_STEM}.captures.zip`]);
  });

  it('offers every file when the payload carries several', () => {
    // Arrange
    const files = [
      { name: `${FOURTH_STEM}.fds`, data: 'AA==', size: 10 },
      { name: `${FIFTH_STEM}.fds`, data: 'AA==', size: 20 },
    ];

    // Act
    renderResult(target, { files });

    // Assert
    expect(target.querySelectorAll('a')).toHaveLength(2);
    expect(target.querySelector('.banner').textContent).toContain('2');
  });

  it('does not claim a disk listing is a set of downloads', () => {
    // Arrange
    const listing = { files: [{ name: 'GAME', size: 4096, hidden: false }] };

    // Act
    renderResult(target, listing);

    // Assert
    expect(target.querySelectorAll('a')).toHaveLength(0);
    expect(target.querySelector('table')).not.toBeNull();
  });

  it('shows rendered text as text rather than json', () => {
    // Arrange
    const expected = 'Game name: SMB';

    // Act
    renderResult(target, { text: 'Game name: SMB' });

    // Assert
    expect(target.querySelector('pre').textContent).toBe(expected);
  });

  it('labels the values of a reported object and keeps the raw response', () => {
    // Arrange
    renderResult(target, { grade: 'clean', sides: 2 });

    // Act
    const keys = [...target.querySelectorAll('dt')].map((node) => node.textContent);

    // Assert
    expect(keys).toEqual(['grade', 'sides']);
    expect(target.querySelector('details summary').textContent).toBe('Show the raw response');
  });

  it('puts the headline in the banner rather than in the value list', () => {
    // Arrange
    const expected = 'side count differs: 2 against 1';

    // Act
    renderResult(target, { headline: 'side count differs: 2 against 1', identical: false, ok: false });

    // Assert
    expect(target.querySelector('.banner').textContent).toBe(expected);
    expect([...target.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(['identical']);
  });

  it('drops the empty answers once the headline has explained the outcome', () => {
    // Arrange
    const expected = ['identical'];

    // Act
    renderResult(target, {
      headline: 'side count differs: 2 against 1',
      identical: false,
      same_software: null,
      blocks: [],
      differences: [],
      ok: false,
    });

    // Assert
    expect([...target.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(expected);
  });

  it('keeps the empty answers when no headline explains them', () => {
    // Arrange
    const expected = ['rows'];

    // Act
    renderResult(target, { rows: [], ok: true });

    // Assert
    expect([...target.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(expected);
  });

  it('keeps an answer that carries something alongside the headline', () => {
    // Arrange
    const expected = ['blocks'];

    // Act
    renderResult(target, {
      headline: '2 block(s) differ',
      blocks: [{ side: 0, block: 0 }],
      differences: [],
      ok: false,
    });

    // Assert
    expect([...target.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(expected);
    expect(target.querySelector('table')).not.toBeNull();
  });

  it('shows the banner alone when the headline is the whole answer', () => {
    // Arrange
    const answer = { headline: '0 file(s) across 2 side(s)', rows: [], ok: true };

    // Act
    renderResult(target, answer);

    // Assert
    expect(target.querySelector('dl')).toBeNull();
    expect(target.querySelector('.banner').textContent).toBe('0 file(s) across 2 side(s)');
    expect(target.querySelector('details')).not.toBeNull();
  });

  it('does not paint a negative answer as a success', () => {
    // Arrange
    const expected = 'warn';

    // Act
    renderResult(target, { headline: '2 block(s) differ', ok: false });

    // Assert
    expect(target.querySelector('.banner').className).toContain(expected);
  });

  it('keeps the banner green when the answer is positive', () => {
    // Arrange
    const expected = 'good';

    // Act
    renderResult(target, { headline: 'identical', ok: true });

    // Assert
    expect(target.querySelector('.banner').className).toContain(expected);
  });

  it('says findings are below when a negative answer carries no headline', () => {
    // Arrange
    const expected = 'Done. The answer is below.';

    // Act
    renderResult(target, { rows: [{ code: 'FDS001' }], ok: false });

    // Assert
    expect(target.querySelector('.banner').textContent).toBe(expected);
  });

  it('keeps the headline in the raw response', () => {
    // Arrange
    const expected = 'headline';

    // Act
    renderResult(target, { headline: 'identical', ok: true });

    // Assert
    expect(target.querySelector('details pre').textContent).toContain(expected);
  });

  it('falls back to json when the payload is not an object', () => {
    // Arrange
    const expected = '42';

    // Act
    renderResult(target, 42);

    // Assert
    expect(target.querySelector('pre').textContent).toBe(expected);
  });
});

describe('describe', () => {
  it('renders a list of records as a table with one column per key', () => {
    // Arrange
    const expected = [
      'index',
      'blocks',
    ];

    // Act
    const node = describeValue([
      { index: 0, blocks: 2 },
      { index: 1, blocks: 2 },
    ]);

    // Assert
    expect([...node.querySelectorAll('th')].map((cell) => cell.textContent)).toEqual(expected);
    expect(node.querySelectorAll('tr')).toHaveLength(3);
  });

  it('joins a list of plain values', () => {
    // Arrange
    const expected = 'FDS001, FDS010';

    // Act
    const result = describeValue(['FDS001', 'FDS010']).textContent;

    // Assert
    expect(result).toBe(expected);
  });

  it('says so when a list is empty rather than rendering nothing', () => {
    // Arrange
    const expected = 'nothing';

    // Act
    const result = describeValue([]).textContent;

    // Assert
    expect(result).toBe(expected);
  });

  it('nests a labelled view for an object', () => {
    // Arrange
    const expected = 'worst';

    // Act
    const node = describeValue({ worst: 'error' });

    // Assert
    expect(node.querySelector('dt').textContent).toBe(expected);
  });

  it('renders a scalar directly', () => {
    // Arrange
    const expected = 'clean';

    // Act
    const result = describeValue('clean').textContent;

    // Assert
    expect(result).toBe(expected);
  });

  it('gives a table a column for a key only some records carry', () => {
    // Arrange
    const expected = ['a', 'b'];

    // Act
    const node = describeValue([{ a: 1 }, { b: 2 }]);

    // Assert
    expect([...node.querySelectorAll('th')].map((cell) => cell.textContent)).toEqual(expected);
  });
});
