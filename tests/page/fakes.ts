import { en, Faker } from '@faker-js/faker';

export const FAKE_SEED = 1986;

const GAME_NAME_LENGTH = 3;
const HASH_BASE = 31;
const HASH_MODULUS = 2147483647;

function seedOf(scope: string): number {
  return [...`${FAKE_SEED}:${scope}`].reduce(
    (hash, char) => (hash * HASH_BASE + (char.codePointAt(0) ?? 0)) % HASH_MODULUS,
    0,
  );
}

export function seeded(scope: string): Faker {
  const generator = new Faker({ locale: [en] });
  generator.seed(seedOf(scope));
  return generator;
}

export function gameNames(generator: Faker, count: number): string[] {
  return generator.helpers.uniqueArray(
    () => generator.string.alpha({ length: GAME_NAME_LENGTH, casing: 'upper' }),
    count,
  );
}

export function fileStems(generator: Faker, count: number): string[] {
  return generator.helpers.uniqueArray(() => generator.word.noun().toLowerCase(), count);
}
