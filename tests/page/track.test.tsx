import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { Track } from '../../web/src/schemas';
import { TrackView, trackIn } from '../../web/src/track';
import { ResultView } from '../../web/src/result';

const LENGTH = 1000;

function track(overrides: Partial<Track> = {}): Track {
  return {
    headline: 'side 0, 3 read(s), 1000 values, 2 blocks, 1 weak',
    side: 0,
    reads: 3,
    length: LENGTH,
    bins: [
      { start: 0, end: 500, classes: [250, 150, 90, 10] },
      { start: 500, end: 1000, classes: [0, 0, 0, 0] },
    ],
    blocks: [
      {
        index: 0,
        kind: 'disk info',
        start: 100,
        end: 300,
        weak: false,
        unstable: 0,
        invalid: 0,
        missing: 0,
        label: 'block 0, disk info: steady',
      },
      {
        index: 3,
        kind: 'file data',
        start: 600,
        end: 900,
        weak: true,
        unstable: 4,
        invalid: 1,
        missing: 0,
        label: 'block 3, file data: 4 pulse(s) differ across 3 read(s), 1 invalid',
      },
    ],
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
});

describe('trackIn', () => {
  it('reads a track answer and nothing else', () => {
    // Arrange
    const answer = track();

    // Act
    const found = [trackIn(answer), trackIn({ headline: 'clean' }), trackIn(null)];

    // Assert
    expect(found).toEqual([answer, null, null]);
  });
});

describe('TrackView', () => {
  it('draws the side as a figure a screen reader can name', () => {
    // Arrange
    const shown = track();

    // Act
    render(<TrackView track={shown} />);

    // Assert
    const figure = screen.getByRole('img', {
      name: 'Pulse classes along side 0 across 3 read(s); weak blocks are hatched and numbered.',
    });
    expect(figure.tagName.toLowerCase()).toBe('svg');
  });

  it('numbers a weak block in the drawing and reads its figures out in a list', () => {
    // Arrange
    const shown = track();

    // Act
    const { container } = render(<TrackView track={shown} />);

    // Assert
    expect(container.querySelector('text.track-label')!.textContent).toBe('3');
    expect(container.querySelectorAll('rect.track-block.weak')).toHaveLength(1);
    expect(screen.getByRole('list', { name: 'Weak blocks' }).textContent).toBe(
      'block 3, file data: 4 pulse(s) differ across 3 read(s), 1 invalid',
    );
  });

  it('stacks each bin by its pulse classes and skips an empty bin', () => {
    // Arrange
    const shown = track();

    // Act
    const { container } = render(<TrackView track={shown} />);

    // Assert
    expect(container.querySelectorAll('rect.track-short')).toHaveLength(1);
    expect(container.querySelectorAll('rect.track-invalid')).toHaveLength(1);
    expect(container.querySelector('rect.track-short')!.getAttribute('height')).toBe('36');
  });

  it('says every block is steady when none is weak', () => {
    // Arrange
    const shown = track({ blocks: [], headline: 'side 1, 1 read(s), 1000 values, 0 blocks, 0 weak' });

    // Act
    render(<TrackView track={shown} />);

    // Assert
    expect(screen.getByText('Every block is steady across the reads.').className).toBe('quiet');
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('draws nothing along an empty read', () => {
    // Arrange
    const shown = track({ length: 0, bins: [], blocks: [] });

    // Act
    const { container } = render(<TrackView track={shown} />);

    // Assert
    expect(container.querySelectorAll('rect')).toHaveLength(0);
  });
});

describe('ResultView with a track', () => {
  it('shows a track answer as its drawing under the headline', () => {
    // Arrange
    const answer = track();

    // Act
    const { container } = render(<ResultView payload={answer} />);

    // Assert
    expect(container.querySelector('.banner')!.textContent).toBe(answer.headline);
    expect(container.querySelector('figure.track svg')).not.toBeNull();
  });
});

describe('TrackView of a read with no length', () => {
  it('draws its marks at the start rather than dividing by nothing', () => {
    // Arrange
    const shown = track({ length: 0, bins: [{ start: 0, end: 0, classes: [1, 0, 0, 0] }], blocks: [] });

    // Act
    const { container } = render(<TrackView track={shown} />);

    // Assert
    const bar = container.querySelector('rect.track-short')!;
    expect([bar.getAttribute('x'), bar.getAttribute('width')]).toEqual(['0', '0']);
  });
});

describe('ResultView with a steady track', () => {
  it('heads a track with no weak block as good news', () => {
    // Arrange
    const answer = track({ blocks: [] });

    // Act
    const { container } = render(<ResultView payload={answer} />);

    // Assert
    expect(container.querySelector('.banner')!.className).toBe('banner good');
  });
});
