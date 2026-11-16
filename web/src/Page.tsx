import { useQuery } from '@tanstack/react-query';
import { type ReactElement, useEffect, useReducer, useState } from 'react';

import { call, messageOf } from './api';
import { initialLanguage, rememberLanguage, tolerateRefusal, translate } from './i18n';
import { LanguageContext } from './language';
import { Panel } from './panel';
import { Failure } from './result';
import { CatalogueSchema, type CommandForm, CurrentJobSchema } from './schemas';
import { familiesOf, NOTHING_SELECTED, select, selectedForm, visible } from './selection';
import type { Translate } from './values';

const LANGUAGES = [
  ['en', 'English'],
  ['ja', '日本語'],
] as const;

function wantedCommand(): string {
  return window.location.hash.replace('#', '');
}

function remember(target: string): void {
  try {
    window.history.replaceState(null, '', `#${target}`);
  } catch (error) {
    tolerateRefusal(error);
  }
}

function Languages(props: { readonly language: string; readonly onChoose: (code: string) => void }): ReactElement {
  return (
    <nav className="languages" aria-label="Language">
      {LANGUAGES.map(([code, caption]) => (
        <button
          key={code}
          type="button"
          data-language={code}
          aria-pressed={props.language === code}
          onClick={() => { props.onChoose(code); }}
        >
          {caption}
        </button>
      ))}
    </nav>
  );
}

interface ListProps {
  readonly entries: readonly CommandForm[];
  readonly selected: string;
  readonly onPick: (chosen: CommandForm) => void;
  readonly speak: Translate;
}

function CommandList(props: ListProps): ReactElement {
  if (!props.entries.length) {
    return (
      <ul className="command-list" id="commands">
        <li className="no-match">{props.speak('list.none')}</li>
      </ul>
    );
  }
  return (
    <ul className="command-list" id="commands">
      {props.entries.map((entry) => (
        <li key={entry.command}>
          <button
            type="button"
            aria-current={entry.command === props.selected}
            onClick={() => { props.onPick(entry); }}
          >
            <span className="item-name">{entry.command}</span>
            <span className="item-summary">{props.speak(`summary.${entry.command}`) || entry.summary}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function useHashFollowing(known: readonly CommandForm[], follow: (wanted: string) => void): void {
  useEffect(() => {
    const onHash = (): void => {
      follow(wantedCommand());
    };
    window.addEventListener('hashchange', onHash);
    return () => {
      window.removeEventListener('hashchange', onHash);
    };
  }, [known, follow]);
}

export function Page(): ReactElement {
  const [language, setLanguage] = useState(initialLanguage);
  const t: Translate = (phrase) => translate(language, phrase);
  const [selection, dispatch] = useReducer(select, NOTHING_SELECTED);
  const catalogue = useQuery({
    queryKey: ['catalogue'],
    queryFn: () => call(CatalogueSchema, { path: '/api/catalogue', method: 'GET' }, t),
  });
  const known = catalogue.data?.forms ?? [];
  const current = useQuery({
    queryKey: ['current-job'],
    queryFn: () => call(CurrentJobSchema, { path: '/api/jobs/current', method: 'GET' }, t),
    enabled: catalogue.isSuccess,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const resumedJob = current.data?.job ?? null;
  const resumedForm = known.find((entry) => entry.command === resumedJob?.command);
  useEffect(() => {
    document.documentElement.setAttribute('lang', language);
  }, [language]);
  useEffect(() => {
    dispatch({ type: 'show', wanted: wantedCommand(), forms: known });
  }, [known]);
  useEffect(() => {
    if (resumedForm) {
      dispatch({ type: 'command', form: resumedForm });
    }
  }, [resumedForm]);
  useHashFollowing(known, (wanted) => {
    dispatch({ type: 'show', wanted, forms: known });
  });
  const chosen = selectedForm(selection, known);
  const choose = (code: string): void => {
    setLanguage(code);
    rememberLanguage(code);
  };
  const pick = (entry: CommandForm): void => {
    dispatch({ type: 'command', form: entry });
    remember(entry.command);
  };
  return (
    <LanguageContext value={t}>
      <div className="shell">
        <header>
          <div>
            <h1>{t('title')}</h1>
            <p className="tagline">{t('tagline')}</p>
          </div>
          <Languages language={language} onChoose={choose} />
        </header>
        <nav className="families" id="families" aria-label="Command families">
          {familiesOf(known, catalogue.data?.families ?? []).map((group) => (
            <button
              key={group}
              type="button"
              data-family={group}
              aria-pressed={group === selection.family}
              onClick={() => {
                const first = known.find((entry) => entry.family === group)!;
                dispatch({ type: 'family', first });
                remember(first.command);
              }}
            >
              {t(`family.${group}`) || group}
            </button>
          ))}
        </nav>
        <div className="layout">
          <aside className="sidebar">
            <label className="search">
              <span>{t('page.filter')}</span>
              <input
                type="search"
                id="search"
                placeholder={t('page.filter')}
                value={selection.filter}
                onChange={(event) => {
                  dispatch({ type: 'filter', text: event.currentTarget.value, forms: known });
                }}
              />
            </label>
            <CommandList entries={visible(selection, known)} selected={selection.command} onPick={pick} speak={t} />
          </aside>
          <main className="panel" id="panel" data-command={chosen?.command}>
            {catalogue.isError ? <Failure message={messageOf(catalogue.error)} /> : null}
            {chosen ? (
              <Panel
                key={chosen.command}
                form={chosen}
                resumed={resumedJob?.command === chosen.command ? resumedJob : null}
              />
            ) : (
              <p className="summary">{t('panel.none')}</p>
            )}
          </main>
        </div>
        <footer>
          <p>{t('footer.cli')}</p>
        </footer>
      </div>
    </LanguageContext>
  );
}
