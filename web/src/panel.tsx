import { useQuery } from '@tanstack/react-query';
import { type ReactElement, useRef, useState } from 'react';

import { call, messageOf } from './api';
import { collect, FieldControl, invalidIn, missingIn } from './fields';
import { EraseDialog, erases, isJobRoute, JobFollower } from './jobs';
import { useT } from './language';
import { Banner, Failure, ResultView } from './result';
import { AnyAnswerSchema, type CommandForm, HardwareSchema, type Job, JobSchema } from './schemas';
import { sentence, type Translate, words } from './values';

type Outcome =
  | { readonly kind: 'empty' }
  | { readonly kind: 'missing'; readonly names: readonly string[] }
  | { readonly kind: 'invalid'; readonly reasons: readonly string[] }
  | { readonly kind: 'running' }
  | { readonly kind: 'cancelled' }
  | { readonly kind: 'failed'; readonly message: string }
  | { readonly kind: 'result'; readonly payload: unknown }
  | { readonly kind: 'job'; readonly job: Job; readonly resumed: boolean };

interface Asking {
  readonly settle: (go: boolean) => void;
}

function HardwareNotice(): ReactElement {
  const t = useT();
  const query = useQuery({
    queryKey: ['hardware'],
    queryFn: () => call(HardwareSchema, { path: '/api/hardware', method: 'GET' }, t),
  });
  if (query.isPending) {
    return <p className="banner busy" role="status">{t('hardware.checking')}</p>;
  }
  if (query.isError) {
    return <p className="banner bad" role="status">{`${t('hardware.unknown')} ${sentence(messageOf(query.error))}`}</p>;
  }
  const lead = t(query.data.connected ? 'hardware.present' : 'hardware.absent');
  return (
    <p className={`banner ${query.data.connected ? 'good' : 'bad'}`} role="status">
      {`${lead} ${sentence(query.data.detail)}`}
    </p>
  );
}

function EmptyResult(props: { readonly form: CommandForm }): ReactElement {
  const t = useT();
  const needed = props.form.fields
    .filter((spec) => spec.required && spec.kind !== 'auto')
    .map((spec) => words(spec.name));
  return (
    <div className="empty">
      <p>{t('result.empty')}</p>
      {needed.length ? <p className="quiet">{t('result.needs').replace('{fields}', needed.join(', '))}</p> : null}
      <p className="quiet">{t('result.local')}</p>
    </div>
  );
}

function Output(props: { readonly form: CommandForm; readonly outcome: Outcome }): ReactElement {
  const t = useT();
  const shown = props.outcome;
  switch (shown.kind) {
    case 'empty':
      return <EmptyResult form={props.form} />;
    case 'missing':
      return <Banner kind="bad">{t('state.missing').replace('{fields}', shown.names.map(words).join(', '))}</Banner>;
    case 'invalid':
      return (
        <>
          <Banner kind="bad">{t('state.invalid')}</Banner>
          {shown.reasons.map((reason) => (
            <p key={reason} className="reason">
              {reason}
            </p>
          ))}
        </>
      );
    case 'running':
      return <Banner kind="busy">{t('state.running')}</Banner>;
    case 'cancelled':
      return <Banner kind="warn">{t('state.cancelled')}</Banner>;
    case 'failed':
      return <Failure message={shown.message} hint />;
    case 'result':
      return <ResultView payload={shown.payload} />;
    case 'job':
      return (
        <>
          {shown.resumed ? <Banner kind="warn">{t('job.resumed')}</Banner> : null}
          <JobFollower key={shown.job.id} first={shown.job} />
        </>
      );
  }
}

async function launch(
  chosen: CommandForm,
  body: Record<string, unknown>,
  ask: () => Promise<boolean>,
  t: Translate,
): Promise<Outcome> {
  if (!isJobRoute(chosen.route)) {
    const answer = await call(AnyAnswerSchema, { path: chosen.route, method: chosen.method, body }, t);
    return { kind: 'result', payload: answer };
  }
  const erasing = erases(chosen);
  if (erasing && !(await ask())) {
    return { kind: 'cancelled' };
  }
  const started = await call(
    JobSchema,
    { path: chosen.route, method: 'POST', body: erasing ? { ...body, confirm: true } : body },
    t,
  );
  return { kind: 'job', job: started, resumed: false };
}

function refusal(host: HTMLElement, chosen: CommandForm, t: Translate): Outcome | null {
  const empty = missingIn(host, chosen);
  if (empty.length) {
    return { kind: 'missing', names: empty };
  }
  const broken = invalidIn(host, chosen, t);
  return broken.length ? { kind: 'invalid', reasons: broken } : null;
}

export interface PanelProps {
  readonly form: CommandForm;
  readonly resumed?: Job | null;
}

function initialOutcome(started: Job | null | undefined): Outcome {
  return started ? { kind: 'job', job: started, resumed: true } : { kind: 'empty' };
}

export function Panel(props: PanelProps): ReactElement {
  const t = useT();
  const host = useRef<HTMLDivElement>(null);
  const [outcome, setOutcome] = useState<Outcome>(initialOutcome(props.resumed));
  const [missing, setMissing] = useState<readonly string[]>([]);
  const [running, setRunning] = useState(false);
  const [asking, setAsking] = useState<Asking | null>(null);
  const ask = (): Promise<boolean> =>
    new Promise((resolve) => {
      setAsking({ settle: resolve });
    });
  const answer = (go: boolean): void => {
    asking?.settle(go);
    setAsking(null);
  };
  const fail = (error: unknown): void => {
    setOutcome({ kind: 'failed', message: messageOf(error) });
  };
  const run = async (): Promise<void> => {
    const refused = refusal(host.current!, props.form, t);
    if (refused) {
      setMissing(refused.kind === 'missing' ? refused.names : []);
      setOutcome(refused);
      return;
    }
    setRunning(true);
    setOutcome({ kind: 'running' });
    try {
      setOutcome(await launch(props.form, await collect(host.current!, props.form), ask, t));
    } catch (error) {
      fail(error);
    } finally {
      setRunning(false);
    }
  };
  const shownFields = props.form.fields.filter((spec) => spec.kind !== 'auto' && !spec.hidden);
  return (
    <>
      <div className="panel-head">
        <h2 className="command-name">{props.form.command}</h2>
        <span className="route">{`${props.form.method} ${props.form.route}`}</span>
      </div>
      <p className="summary">{t(`summary.${props.form.command}`) || props.form.summary}</p>
      {props.form.needs_hardware ? <HardwareNotice /> : null}
      <div className="columns">
        <div className="fields" ref={host}>
          <p className="group-label">{t('group.inputs')}</p>
          {shownFields.length ? (
            shownFields.map((spec) => (
              <FieldControl
                key={spec.name}
                spec={spec}
                command={props.form.command}
                missing={missing.includes(spec.name)}
                onEdited={(name) => {
                  setMissing((seen) => seen.filter((item) => item !== name));
                }}
              />
            ))
          ) : (
            <p className="field-help">{t('group.nothing')}</p>
          )}
          <button type="button" className="run" disabled={running} onClick={() => { run().catch(fail); }}>
            {t(running ? 'state.running' : 'button.run')}
          </button>
        </div>
        <div className="result">
          <p className="group-label">{t('group.result')}</p>
          <div className="output">
            <Output form={props.form} outcome={outcome} />
          </div>
        </div>
      </div>
      {asking ? <EraseDialog command={props.form.command} onAnswer={answer} /> : null}
    </>
  );
}
