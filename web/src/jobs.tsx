import { useQuery } from '@tanstack/react-query';
import { type ReactElement, useEffect, useRef, useState } from 'react';

import { call, messageOf } from './api';
import { useT } from './language';
import { Banner, DownloadLink, Failure, ResultView } from './result';
import { AnyAnswerSchema, type CommandForm, type Job, JobSchema, type JobState } from './schemas';
import { isDownload } from './values';

export const POLL_MS = 500;
export const POLL_LIMIT = 7200;

const CONFIRMED_BY_DIALOG = 'confirm';
const INSERT_PROMPT = 'put blank disk';
const COMMAND_LANGUAGE = 'en';
const JOB_BANNER = {
  running: 'busy',
  waiting: 'warn',
  failed: 'bad',
  done: 'good',
} as const satisfies Record<JobState, string>;

export function isJobRoute(route: string): boolean {
  return route.startsWith('/api/jobs/');
}

export function erases(chosen: CommandForm): boolean {
  return chosen.fields.some((entry) => entry.hidden && entry.name === CONFIRMED_BY_DIALOG);
}

function settled(current: Job): boolean {
  return current.state === 'done' || current.state === 'failed';
}

export interface EraseDialogProps {
  readonly command: string;
  readonly onAnswer: (go: boolean) => void;
}

export function EraseDialog(props: EraseDialogProps): ReactElement {
  const t = useT();
  const dialog = useRef<HTMLDialogElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    dialog.current!.showModal();
    cancel.current!.focus();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="erase"
      aria-labelledby="erase-title"
      aria-describedby="erase-body"
      onCancel={(event) => {
        event.preventDefault();
        props.onAnswer(false);
      }}
    >
      <h2 id="erase-title">{t('confirm.title')}</h2>
      <p id="erase-body">{t(`confirm.${props.command}`)}</p>
      <div className="dialog-actions">
        <button type="button" className="plain" ref={cancel} onClick={() => { props.onAnswer(false); }}>
          {t('confirm.cancel')}
        </button>
        <button type="button" className="danger" onClick={() => { props.onAnswer(true); }}>
          {t('confirm.go')}
        </button>
      </div>
    </dialog>
  );
}

interface PromptProps {
  readonly job: Job;
  readonly onAnswer: (yes: boolean) => void;
}

function answerKey(asking: Job): string {
  if (asking.command === 'calibrate') {
    return 'job.stepped';
  }
  return asking.prompt.startsWith(INSERT_PROMPT) ? 'job.inserted' : 'job.turned';
}

function TurnPrompt(props: PromptProps): ReactElement {
  const t = useT();
  const [sent, setSent] = useState(false);
  const reply = (yes: boolean): void => {
    setSent(true);
    props.onAnswer(yes);
  };
  const done = answerKey(props.job);
  return (
    <div className="turn" role="alert">
      <p className="prompt" lang={COMMAND_LANGUAGE}>
        {props.job.prompt}
      </p>
      <div className="dialog-actions">
        <button type="button" className="plain" disabled={sent} onClick={() => { reply(false); }}>
          {t('job.stop')}
        </button>
        <button type="button" className="run" disabled={sent} onClick={() => { reply(true); }}>
          {t(done)}
        </button>
      </div>
    </div>
  );
}

function StopControl(props: { readonly stopping: boolean; readonly onStop: () => void }): ReactElement {
  const t = useT();
  const [pressed, setPressed] = useState(false);
  if (props.stopping) {
    return <p className="quiet">{t('job.stopping')}</p>;
  }
  const press = (): void => {
    setPressed(true);
    props.onStop();
  };
  return (
    <div className="dialog-actions">
      <button type="button" className="plain" disabled={pressed} onClick={press}>
        {t('job.stop')}
      </button>
    </div>
  );
}

export interface JobViewProps {
  readonly job: Job;
  readonly onAnswer: (yes: boolean) => void;
  readonly onStop: () => void;
}

export function JobView(props: JobViewProps): ReactElement {
  const t = useT();
  const shown = props.job;
  const failed = shown.state === 'failed';
  return (
    <div className="job">
      <Banner kind={JOB_BANNER[shown.state]}>{t(`job.${shown.state}`)}</Banner>
      {shown.writes && !failed ? <p className="quiet">{t('job.keep')}</p> : null}
      <p className="output-language">{t('job.output')}</p>
      <ol className="steps" lang={COMMAND_LANGUAGE} aria-live="polite">
        {shown.steps.map((step, index) => (
          <li key={index}>{step}</li>
        ))}
      </ol>
      {shown.state === 'waiting' ? <TurnPrompt key={shown.steps.length} job={shown} onAnswer={props.onAnswer} /> : null}
      {shown.stoppable && shown.state === 'running' ? <StopControl stopping={shown.stopping} onStop={props.onStop} /> : null}
      {failed ? (
        <p className="reason" lang={COMMAND_LANGUAGE}>
          {shown.error}
        </p>
      ) : null}
      {failed && isDownload(shown.kept) ? <DownloadLink entry={shown.kept} /> : null}
    </div>
  );
}

function keepPageOpen(event: Event): void {
  event.preventDefault();
}

function useLeaveGuard(active: boolean): void {
  useEffect(() => {
    if (!active) {
      return undefined;
    }
    window.addEventListener('beforeunload', keepPageOpen);
    return () => {
      window.removeEventListener('beforeunload', keepPageOpen);
    };
  }, [active]);
}

export interface JobFollowerProps {
  readonly first: Job;
  readonly pollMs?: number;
  readonly polls?: number;
}

export function JobFollower(props: JobFollowerProps): ReactElement {
  const t = useT();
  const limit = props.polls ?? POLL_LIMIT;
  const [problems, setProblems] = useState<readonly string[]>([]);
  const [job, setJob] = useState(props.first);
  const [polls, setPolls] = useState(0);
  const query = useQuery({
    queryKey: ['job', props.first.id],
    queryFn: async () => {
      const next = await call(JobSchema, { path: `/api/jobs/${props.first.id}`, method: 'GET' }, t);
      setPolls((count) => count + 1);
      setJob(next);
      return next;
    },
    initialData: props.first,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    enabled: !settled(job) && polls < limit,
    refetchInterval: props.pollMs ?? POLL_MS,
  });
  useLeaveGuard(job.writes && !settled(job) && !query.isError);
  const send = (path: string, body: unknown): void => {
    call(AnyAnswerSchema, { path, method: 'POST', body }, t).catch((error: unknown) => {
      setProblems((seen) => [...seen, messageOf(error)]);
    });
  };
  if (query.isError) {
    return <Failure message={messageOf(query.error)} />;
  }
  if (job.state === 'done') {
    return <ResultView payload={job.result} />;
  }
  if (!settled(job) && polls >= limit) {
    return <Banner kind="warn">{t('job.lost')}</Banner>;
  }
  return (
    <>
      <JobView
        job={job}
        onAnswer={(yes) => { send(`/api/jobs/${job.id}/answer`, { yes }); }}
        onStop={() => { send(`/api/jobs/${job.id}/stop`, {}); }}
      />
      {problems.map((problem, index) => (
        <Banner key={`${index}-${problem}`} kind="bad">
          {problem}
        </Banner>
      ))}
    </>
  );
}
