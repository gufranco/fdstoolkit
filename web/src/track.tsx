import { Fragment, type ReactElement } from 'react';

import { useT } from './language';
import { type Track, TrackSchema } from './schemas';

type TrackBin = Track['bins'][number];
type TrackBlock = Track['blocks'][number];

interface Segment {
  readonly name: string;
  readonly top: number;
  readonly height: number;
}

const WIDTH = 640;
const MARGIN = 4;
const BAND = 72;
const BLOCK_TOP = MARGIN + BAND + 12;
const BLOCK_HEIGHT = 24;
const LABEL_GAP = 16;
const HEIGHT = BLOCK_TOP + BLOCK_HEIGHT + LABEL_GAP + MARGIN;
const HUNDREDTHS = 100;
const HATCH_SIZE = 6;

export function trackIn(payload: unknown): Track | null {
  const parsed = TrackSchema.safeParse(payload);
  return parsed.success ? parsed.data : null;
}

function rounded(value: number): number {
  return Math.round(value * HUNDREDTHS) / HUNDREDTHS;
}

function scaled(value: number, extent: number): number {
  return extent ? rounded((value / extent) * WIDTH) : 0;
}

function stacked(bar: TrackBin): readonly Segment[] {
  const [short, medium, long, invalid] = bar.classes;
  const sum = short + medium + long + invalid;
  const parts = [
    ['track-short', short],
    ['track-medium', medium],
    ['track-long', long],
    ['track-invalid', invalid],
  ] as const;
  return parts.reduce<{ readonly segments: readonly Segment[]; readonly top: number }>(
    (state, [name, count]) => {
      if (!count) {
        return state;
      }
      const height = rounded((count / sum) * BAND);
      const top = rounded(state.top - height);
      return { segments: [...state.segments, { name, top, height }], top };
    },
    { segments: [], top: MARGIN + BAND },
  ).segments;
}

function BinBar(props: { readonly piece: TrackBin; readonly span: number }): ReactElement {
  const left = scaled(props.piece.start, props.span);
  const across = scaled(props.piece.end - props.piece.start, props.span);
  return (
    <g>
      {stacked(props.piece).map((part) => (
        <rect key={part.name} className={part.name} x={left} y={part.top} width={across} height={part.height} />
      ))}
    </g>
  );
}

function BlockMark(props: { readonly entry: TrackBlock; readonly span: number; readonly hatch: string }): ReactElement {
  const left = scaled(props.entry.start, props.span);
  const across = Math.max(scaled(props.entry.end - props.entry.start, props.span), 1);
  return (
    <g>
      <rect
        className={props.entry.weak ? 'track-block weak' : 'track-block'}
        x={left}
        y={BLOCK_TOP}
        width={across}
        height={BLOCK_HEIGHT}
        fill={props.entry.weak ? `url(#${props.hatch})` : undefined}
      />
      {props.entry.weak ? (
        <text
          className="track-label"
          x={rounded(left + across / 2)}
          y={BLOCK_TOP + BLOCK_HEIGHT + LABEL_GAP}
          textAnchor="middle"
        >
          {props.entry.index}
        </text>
      ) : null}
    </g>
  );
}

function WeakList(props: { readonly weak: readonly TrackBlock[]; readonly side: number }): ReactElement {
  const t = useT();
  const caption = `track-weak-${props.side}`;
  if (!props.weak.length) {
    return <p className="quiet">{t('track.steady')}</p>;
  }
  return (
    <>
      <p className="track-caption" id={caption}>
        {t('track.weak')}
      </p>
      <ul className="track-weak" aria-labelledby={caption}>
        {props.weak.map((found) => (
          <li key={found.index}>{found.label}</li>
        ))}
      </ul>
    </>
  );
}

export function TrackView(props: { readonly track: Track }): ReactElement {
  const t = useT();
  const shown = props.track;
  const title = `track-title-${shown.side}`;
  const hatch = `track-hatch-${shown.side}`;
  const named = t('track.figure').replace('{side}', String(shown.side)).replace('{reads}', String(shown.reads));
  return (
    <figure className="track">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-labelledby={title}>
        <title id={title}>{named}</title>
        <defs>
          <pattern
            id={hatch}
            width={HATCH_SIZE}
            height={HATCH_SIZE}
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line className="track-hatch" x1={0} y1={0} x2={0} y2={HATCH_SIZE} />
          </pattern>
        </defs>
        {shown.bins.map((bin) => (
          <BinBar key={bin.start} piece={bin} span={shown.length} />
        ))}
        {shown.blocks.map((found) => (
          <Fragment key={found.index}>
            <BlockMark entry={found} span={shown.length} hatch={hatch} />
          </Fragment>
        ))}
      </svg>
      <WeakList weak={shown.blocks.filter((found) => found.weak)} side={shown.side} />
    </figure>
  );
}
