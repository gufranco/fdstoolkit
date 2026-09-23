import { describe, expect, it } from 'vitest';

import { bytes, describeLimits, explain, isDownload, named, scalar, words } from
  '../../src/fdstoolkit/ui/static/app.js';

describe('named', () => {
  it('keeps the chosen name when it already carries the wanted suffix', () => {
    expect(named('demo.fds', 'disk.fds')).toBe('demo.fds');
  });

  it('swaps a suffix the command does not produce', () => {
    expect(named('recipe.json', 'disk.fds')).toBe('recipe.fds');
  });

  it('adds the suffix when the chosen name carries none', () => {
    expect(named('dump', 'disk.fds')).toBe('dump.fds');
  });

  it('falls back to the schema default when nothing was chosen', () => {
    expect(named('', 'disk.fds')).toBe('disk.fds');
  });

  it('keeps the chosen name when the default carries no suffix', () => {
    expect(named('demo.fds', '')).toBe('demo.fds');
  });
});

describe('bytes', () => {
  it('reports small sizes in bytes', () => {
    expect(bytes(512)).toBe('512 B');
  });

  it('reports a two-side image in kibibytes', () => {
    expect(bytes(131000)).toBe('127.9 KiB');
  });
});

describe('scalar', () => {
  it('names an absent value rather than printing null', () => {
    expect(scalar(null)).toBe('none');
    expect(scalar(undefined)).toBe('none');
  });

  it('spells booleans out', () => {
    expect(scalar(true)).toBe('yes');
    expect(scalar(false)).toBe('no');
  });

  it('passes numbers and text through', () => {
    expect(scalar(0)).toBe('0');
    expect(scalar('clean')).toBe('clean');
  });
});

describe('words', () => {
  it('turns a field name into something readable', () => {
    expect(words('bad_blocks')).toBe('bad blocks');
  });
});

describe('isDownload', () => {
  it('accepts an entry carrying bytes, a size and a name', () => {
    expect(isDownload({ data: 'AA==', size: 1, name: 'a.fds' })).toBe(true);
  });

  it('refuses a list of disk files, which carry no bytes', () => {
    expect(isDownload({ name: 'GAME', size: 4096 })).toBe(false);
  });

  it('refuses nothing at all', () => {
    expect(isDownload(null)).toBe(false);
  });
});

describe('explain', () => {
  it('passes a plain message through', () => {
    expect(explain('that image is not a disk')).toBe('that image is not a disk');
  });

  it('names the field a validation error came from', () => {
    const detail = [{ loc: ['body', 'bad_blocks'], msg: 'Input should be greater than 0' }];

    expect(explain(detail)).toBe('bad blocks: Input should be greater than 0');
  });

  it('joins several validation errors', () => {
    const detail = [
      { loc: ['body', 'sides'], msg: 'too big' },
      { loc: ['body', 'passes'], msg: 'too small' },
    ];

    expect(explain(detail)).toBe('sides: too big. passes: too small');
  });

  it('keeps a message that names no field', () => {
    expect(explain([{ msg: 'unreadable' }])).toBe('unreadable');
  });

  it('falls back to the raw object when the shape is unknown', () => {
    expect(explain({ odd: true })).toBe('{"odd":true}');
  });
});

describe('describeLimits', () => {
  it('states a range when both ends are known', () => {
    expect(describeLimits({ minimum: 1, maximum: 8 })).toBe('Between 1 and 8.');
  });

  it('states a floor alone', () => {
    expect(describeLimits({ minimum: 0, maximum: null })).toBe('0 or more.');
  });

  it('states a ceiling alone', () => {
    expect(describeLimits({ minimum: null, maximum: 65535 })).toBe('65535 or less.');
  });

  it('states an exact length when both lengths agree', () => {
    expect(describeLimits({ min_length: 3, max_length: 3 })).toBe('Exactly 3 characters.');
  });

  it('states a maximum length', () => {
    expect(describeLimits({ max_length: 8 })).toBe('Up to 8 characters.');
  });

  it('says nothing when the field is unbounded', () => {
    expect(describeLimits({})).toBe('');
  });
});
