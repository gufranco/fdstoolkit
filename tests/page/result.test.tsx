import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { Banner, DownloadLink, Failure, ResultView } from '../../web/src/result';
import { fileStems, gameNames, seeded } from './fakes';

const FAKE = seeded('result.test');
const [GAME = '', OTHER_GAME = ''] = gameNames(FAKE, 2);
const [STEM = '', OTHER_STEM = '', THIRD_STEM = ''] = fileStems(FAKE, 3);

function shown(payload: unknown): HTMLElement {
  return render(<ResultView payload={payload} />).container;
}

afterEach(() => {
  cleanup();
});

describe('Banner', () => {
  it('draws a banner of the kind given', () => {
    // Arrange
    const message = 'the disk reads back as written';

    // Act
    const { container } = render(<Banner kind="good">{message}</Banner>);

    // Assert
    const node = container.querySelector('p')!;
    expect([node.className, node.textContent]).toEqual(['banner good', message]);
  });
});

describe('DownloadLink', () => {
  it('offers the bytes under their name with the size beside them', () => {
    // Arrange
    const entry = { name: `${STEM}.fds`, data: 'AQ==', size: 131000 };

    // Act
    const { container } = render(<DownloadLink entry={entry} />);

    // Assert
    const link = container.querySelector('a.download')!;
    expect(link.getAttribute('href')).toBe('data:application/octet-stream;base64,AQ==');
    expect(link.getAttribute('download')).toBe(`${STEM}.fds`);
    expect(link.textContent).toBe(`Download ${STEM}.fds`);
    expect(container.querySelector('.download-size')!.textContent).toBe('127.9 KiB');
  });

  it('puts the notes a file carries under it as warnings', () => {
    // Arrange
    const entry = { name: `${STEM}.fds`, data: 'AQ==', size: 1, notes: ['[FDS016] lost'] };

    // Act
    const { container } = render(<DownloadLink entry={entry} />);

    // Assert
    expect(container.querySelector('.download-notes .banner.warn')!.textContent).toBe('[FDS016] lost');
  });
});

describe('ResultView', () => {
  it('offers a file and every other file the answer carries', () => {
    // Arrange
    const payload = {
      name: `${STEM}.fds`,
      data: 'AA==',
      size: 10,
      grade: 'clean',
      captures: { name: `${STEM}.captures.zip`, data: 'AA==', size: 20 },
    };

    // Act
    const container = shown(payload);

    // Assert
    const links = [...container.querySelectorAll('a')].map((link) => link.getAttribute('download'));
    expect(links).toEqual([`${STEM}.fds`, `${STEM}.captures.zip`]);
    expect(container.querySelector('.banner')!.textContent).toBe('Your file is ready.');
  });

  it('offers the file and reports what came with it', () => {
    // Arrange
    const payload = {
      headline: '1 block(s) disagree across the dumps',
      file: { name: `${OTHER_STEM}.fds`, data: 'AA==', size: 10 },
      rows: [{ side: 0, block: 3 }],
      ok: false,
    };

    // Act
    const container = shown(payload);

    // Assert
    expect(container.querySelector('.banner')!.className).toBe('banner warn');
    expect(container.querySelector('a')!.getAttribute('download')).toBe(`${OTHER_STEM}.fds`);
    expect(container.querySelector('table.grid th')!.textContent).toBe('side');
  });

  it('offers a file alone when nothing else is worth saying', () => {
    // Arrange
    const payload = { headline: '', file: { name: `${OTHER_STEM}.fds`, data: 'AA==', size: 1 } };

    // Act
    const container = shown(payload);

    // Assert
    expect(container.querySelector('dl')).toBeNull();
    expect(container.querySelector('.banner')!.textContent).toBe('Done.');
  });

  it('offers every file of a list', () => {
    // Arrange
    const payload = {
      files: [
        { name: `${STEM}.fds`, data: 'AA==', size: 10 },
        { name: `${THIRD_STEM}.fds`, data: 'AA==', size: 20 },
      ],
    };

    // Act
    const container = shown(payload);

    // Assert
    expect(container.querySelectorAll('a')).toHaveLength(2);
    expect(container.querySelector('.banner')!.textContent).toBe('2 files are ready.');
  });

  it('prints a text report as it came', () => {
    // Arrange
    const payload = { text: `Game name: ${GAME}`, ok: true };

    // Act
    const container = shown(payload);

    // Assert
    expect(container.querySelector('pre')!.textContent).toBe(`Game name: ${GAME}`);
  });

  it('lays a record out as pairs, with the raw answer folded away', () => {
    // Arrange
    const payload = { headline: 'clean', grade: 'clean', passes: 2, sides: [], weak: null };

    // Act
    const container = shown(payload);

    // Assert
    const terms = [...container.querySelectorAll('dt')].map((node) => node.textContent);
    expect(terms).toEqual(['grade', 'passes']);
    expect(container.querySelector('details.raw summary')!.textContent).toBe('Show the raw response');
  });

  it('keeps empty and absent values when the answer has no headline', () => {
    // Arrange
    const payload = { sides: [], weak: null, files: [1, 2], ok: true };

    // Act
    const container = shown(payload);

    // Assert
    const values = [...container.querySelectorAll('dd')].map((node) => node.textContent);
    expect(values).toEqual(['nothing', 'none', '1, 2']);
  });

  it('nests a record inside a record', () => {
    // Arrange
    const payload = { drive: { connected: true, mixed: [{ a: 1 }, 2] } };

    // Act
    const container = shown(payload);

    // Assert
    expect(container.querySelectorAll('dl')).toHaveLength(4);
    expect(container.querySelector('dl dl dd')!.textContent).toBe('yes');
  });

  it('shows rows that carry prose as records with chips and notes', () => {
    // Arrange
    const payload = {
      rows: [
        { side: 0, hidden: true, note: 'the block failed its checksum', tags: [], names: ['a b', 'c'], codes: ['x1', 'x2'] },
      ],
    };

    // Act
    const container = shown(payload);

    // Assert
    const item = container.querySelector('ul.changes li.change')!;
    expect([...item.querySelectorAll('.chip-key')].map((node) => node.textContent)).toEqual(['side', 'codes']);
    expect(item.querySelector('.chip-flag')!.textContent).toBe('hidden');
    expect([...item.querySelectorAll('.change-note')].map((node) => node.textContent)).toEqual([
      'the block failed its checksum',
      'a b',
      'c',
    ]);
    expect(container.querySelector('dt.wide')!.textContent).toBe('rows');
  });

  it('shows a record whose every value is prose without a line of chips', () => {
    // Arrange
    const payload = { rows: [{ note: 'the block failed its checksum' }] };

    // Act
    const container = shown(payload);

    // Assert
    expect(container.querySelector('.change-marks')).toBeNull();
  });

  it('shows changes as a before and after', () => {
    // Arrange
    const payload = {
      changes: [
        { side: 0, field: 'game_name', identity: true, moved: false, left: GAME, right: OTHER_GAME },
      ],
    };

    // Act
    const container = shown(payload);

    // Assert
    const sides = [...container.querySelectorAll('.side-value')].map((node) => node.textContent);
    expect(sides).toEqual([GAME, OTHER_GAME]);
    expect(container.querySelectorAll('.chip')).toHaveLength(3);
  });

  it('says findings came back when the answer is negative and has no headline', () => {
    // Arrange
    const payload = { ok: false, weak: 2 };

    // Act
    const container = shown(payload);

    // Assert
    expect(container.querySelector('.banner')!.className).toBe('banner warn');
    expect(container.querySelector('.banner')!.textContent).toBe('Done. The answer is below.');
  });

  it('prints any other answer as it came', () => {
    // Arrange
    const payload = 'just text';

    // Act
    const container = shown(payload);

    // Assert
    expect(container.querySelector('pre')!.textContent).toBe('"just text"');
    expect(container.querySelector('.banner')!.textContent).toBe('Done.');
  });
});

describe('Failure', () => {
  it('says the command failed, why, and with a hint when asked', () => {
    // Arrange
    const reason = 'that image is not a disk';

    // Act
    const { container } = render(<Failure message={reason} hint />);

    // Assert
    const texts = [...container.querySelectorAll('p')].map((node) => [node.className, node.textContent]);
    expect(texts).toEqual([
      ['banner bad', 'That did not work.'],
      ['reason', reason],
      ['quiet', 'Check that the file is a Disk System image and that every required field is filled.'],
    ]);
  });

  it('leaves the hint out unless asked', () => {
    // Arrange
    const reason = 'the server is gone';

    // Act
    const { container } = render(<Failure message={reason} />);

    // Assert
    expect(container.querySelectorAll('p')).toHaveLength(2);
  });
});
