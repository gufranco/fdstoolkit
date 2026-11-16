import { Fragment, type ReactElement, type ReactNode } from 'react';

import { useT } from './language';
import type { Download } from './schemas';
import { TrackView, trackIn } from './track';
import { bytes, isChange, isDownload, isProse, isRecord, scalar, type Translate, words } from './values';

type Entry = readonly [string, unknown];
type Row = Record<string, unknown>;

const SAID_IN_BANNER: ReadonlySet<string> = new Set(['headline', 'ok']);

export function Banner(props: { readonly kind: string; readonly children: ReactNode }): ReactElement {
  return <p className={`banner ${props.kind}`}>{props.children}</p>;
}

export function Failure(props: { readonly message: string; readonly hint?: boolean }): ReactElement {
  const t = useT();
  return (
    <>
      <Banner kind="bad">{t('state.failed')}</Banner>
      <p className="reason">{props.message}</p>
      {props.hint ? <p className="quiet">{t('state.hint')}</p> : null}
    </>
  );
}

export function DownloadLink(props: { readonly entry: Download }): ReactElement {
  const t = useT();
  const row = (
    <div className="download-row">
      <a
        className="download"
        href={`data:application/octet-stream;base64,${props.entry.data}`}
        download={props.entry.name}
      >
        {`${t('button.download')} ${props.entry.name}`}
      </a>
      <span className="download-size">{bytes(props.entry.size)}</span>
    </div>
  );
  const notes = props.entry.notes ?? [];
  if (!notes.length) {
    return row;
  }
  return (
    <div className="download-notes">
      {row}
      {notes.map((note) => (
        <Banner key={note} kind="warn">
          {note}
        </Banner>
      ))}
    </div>
  );
}

function isScalar(item: unknown): boolean {
  return item === null || item === undefined || typeof item !== 'object';
}

function proseOf(item: unknown, t: Translate): string[] {
  if (Array.isArray(item)) {
    return item.some(isProse) ? item.map((part) => scalar(part, t)) : [];
  }
  return isProse(item) ? [scalar(item, t)] : [];
}

function Chip(props: { readonly name: string; readonly value: unknown }): ReactElement {
  const t = useT();
  if (typeof props.value === 'boolean') {
    return (
      <span className="chip">
        <span className="chip-flag">{words(props.name)}</span>
      </span>
    );
  }
  return (
    <span className="chip">
      <span className="chip-key">{words(props.name)}</span>
      <span className="chip-value">{scalar(props.value, t)}</span>
    </span>
  );
}

function Fill(props: { readonly entries: readonly Entry[] }): ReactElement {
  const t = useT();
  const marks = props.entries.filter(([, item]) => proseOf(item, t).length === 0);
  const notes = props.entries.flatMap(([, item]) => proseOf(item, t));
  return (
    <>
      {marks.length ? (
        <p className="change-marks">
          {marks.map(([label, item]) => (
            <Chip key={label} name={label} value={item} />
          ))}
        </p>
      ) : null}
      {notes.map((text, index) => (
        <p key={`${index}-${text}`} className="change-note">
          {text}
        </p>
      ))}
    </>
  );
}

function Side(props: { readonly name: string; readonly value: unknown }): ReactElement {
  const t = useT();
  return (
    <span className="side">
      <span className="side-key">{words(props.name)}</span>
      <span className="side-value">{scalar(props.value, t)}</span>
    </span>
  );
}

function Records(props: { readonly rows: readonly Row[] }): ReactElement {
  return (
    <ul className="changes">
      {props.rows.map((record, index) => (
        <li key={index} className="change">
          <Fill entries={Object.entries(record).filter(([, item]) => !(Array.isArray(item) && item.length === 0))} />
        </li>
      ))}
    </ul>
  );
}

function Changes(props: { readonly rows: readonly Row[] }): ReactElement {
  return (
    <ul className="changes">
      {props.rows.map((record, index) => (
        <li key={index} className="change">
          <Fill
            entries={Object.entries(record).filter(
              ([label, item]) => label !== 'left' && label !== 'right' && item !== false,
            )}
          />
          <p className="change-values">
            <Side name="left" value={record['left']} />
            <Side name="right" value={record['right']} />
          </p>
        </li>
      ))}
    </ul>
  );
}

function Table(props: { readonly rows: readonly Row[] }): ReactElement {
  const t = useT();
  const columns = [...new Set(props.rows.flatMap((record) => Object.keys(record)))];
  return (
    <table className="grid">
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column}>{words(column)}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {props.rows.map((record, index) => (
          <tr key={index}>
            {columns.map((column) => (
              <td key={column}>{scalar(record[column], t)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function hasProse(record: Row, t: Translate): boolean {
  return Object.values(record).some((item) => proseOf(item, t).length > 0);
}

function Rows(props: { readonly rows: readonly Row[] }): ReactElement {
  const t = useT();
  if (isChange(props.rows)) {
    return <Changes rows={props.rows} />;
  }
  return props.rows.some((record) => hasProse(record, t)) ? <Records rows={props.rows} /> : <Table rows={props.rows} />;
}

function recordsIn(item: unknown): Row[] | null {
  if (!Array.isArray(item) || !item.length || item.every(isScalar) || !item.every(isRecord)) {
    return null;
  }
  return item;
}

function Value(props: { readonly value: unknown }): ReactElement {
  const t = useT();
  if (isScalar(props.value)) {
    return <dd>{scalar(props.value, t)}</dd>;
  }
  const rows = recordsIn(props.value);
  if (rows) {
    return (
      <dd className="wide">
        <Rows rows={rows} />
      </dd>
    );
  }
  if (Array.isArray(props.value) && !props.value.length) {
    return (
      <dd>
        <span className="quiet">{t('value.empty')}</span>
      </dd>
    );
  }
  if (Array.isArray(props.value) && props.value.every(isScalar)) {
    return (
      <dd>
        <span>{props.value.map((part) => scalar(part, t)).join(', ')}</span>
      </dd>
    );
  }
  return (
    <dd>
      <Pairs value={props.value as object} />
    </dd>
  );
}

function Pairs(props: { readonly value: object }): ReactElement {
  return (
    <dl className="pairs">
      {Object.entries(props.value).map(([label, item]) => (
        <Fragment key={label}>
          <dt className={recordsIn(item) ? 'wide' : undefined}>{words(label)}</dt>
          <Value value={item} />
        </Fragment>
      ))}
    </dl>
  );
}

function Raw(props: { readonly payload: unknown }): ReactElement {
  const t = useT();
  return (
    <details className="raw">
      <summary>{t('result.raw')}</summary>
      <pre>{JSON.stringify(props.payload, null, 2)}</pre>
    </details>
  );
}

function Verdict(props: { readonly payload: Row }): ReactElement {
  const t = useT();
  const negative = props.payload['ok'] === false;
  const headline = typeof props.payload['headline'] === 'string' ? props.payload['headline'].trim() : '';
  return (
    <Banner kind={negative ? 'warn' : 'good'}>
      {headline || t(negative ? 'state.findings' : 'state.done')}
    </Banner>
  );
}

function carries(item: unknown): boolean {
  return item !== null && item !== undefined && !(Array.isArray(item) && !item.length);
}

function reported(answer: Row): Row {
  const spoken = typeof answer['headline'] === 'string' && answer['headline'].trim() !== '';
  return Object.fromEntries(
    Object.entries(answer)
      .filter(([label]) => !SAID_IN_BANNER.has(label))
      .filter(([, item]) => !spoken || carries(item)),
  );
}

function Reported(props: { readonly payload: Row }): ReactElement | null {
  const rest = reported(props.payload);
  return Object.keys(rest).length ? <Pairs value={rest} /> : null;
}

function filesIn(answer: Row): Download[] | null {
  const files = answer['files'];
  return Array.isArray(files) && files.length && files.every(isDownload) ? files : null;
}

function RecordView(props: { readonly payload: Row }): ReactElement {
  const t = useT();
  const { file, ...rest } = props.payload;
  const files = filesIn(props.payload);
  if (isDownload(file)) {
    return (
      <>
        <Verdict payload={props.payload} />
        <DownloadLink entry={file} />
        <Reported payload={rest} />
      </>
    );
  }
  if (files) {
    return (
      <>
        <Banner kind="good">{t('state.files').replace('{n}', String(files.length))}</Banner>
        {files.map((download) => (
          <DownloadLink key={download.name} entry={download} />
        ))}
      </>
    );
  }
  if (typeof props.payload['text'] === 'string') {
    return (
      <>
        <Verdict payload={props.payload} />
        <pre>{props.payload['text']}</pre>
      </>
    );
  }
  return (
    <>
      <Verdict payload={props.payload} />
      <Reported payload={props.payload} />
      <Raw payload={props.payload} />
    </>
  );
}

export function ResultView(props: { readonly payload: unknown }): ReactElement {
  const t = useT();
  const drawn = trackIn(props.payload);
  if (drawn) {
    return (
      <>
        <Banner kind={drawn.blocks.some((found) => found.weak) ? 'warn' : 'good'}>{drawn.headline}</Banner>
        <TrackView track={drawn} />
      </>
    );
  }
  if (isDownload(props.payload)) {
    const fields: readonly unknown[] = Object.values(props.payload);
    const extra = fields.filter(isDownload);
    return (
      <>
        <Banner kind="good">{t('state.file')}</Banner>
        <DownloadLink entry={props.payload} />
        {extra.map((download) => (
          <DownloadLink key={download.name} entry={download} />
        ))}
      </>
    );
  }
  if (isRecord(props.payload)) {
    return <RecordView payload={props.payload} />;
  }
  return (
    <>
      <Banner kind="good">{t('state.done')}</Banner>
      <pre>{JSON.stringify(props.payload, null, 2)}</pre>
    </>
  );
}
