import { describe, expect, it } from 'vitest';

import { typesFor, withoutDocComments } from './generate.mjs';

const SCHEMA = {
  openapi: '3.1.0',
  info: { title: 'toolkit', version: '1' },
  paths: {
    '/api/catalogue': {
      get: {
        summary: 'Catalogue',
        responses: {
          200: {
            description: 'Successful Response',
            content: { 'application/json': { schema: { $ref: '#/components/schemas/Catalogue' } } },
          },
        },
      },
    },
  },
  components: {
    schemas: {
      Catalogue: {
        title: 'Catalogue',
        type: 'object',
        required: ['version'],
        properties: { version: { title: 'Version', type: 'string', description: 'the release' } },
      },
    },
  },
};

describe('withoutDocComments', () => {
  it('drops every doc comment line and keeps the code', () => {
    // Arrange
    const text = '/**\n * header\n */\nexport type A = 1;\n    /** Version */\n    version: string;\n';

    // Act
    const result = withoutDocComments(text);

    // Assert
    expect(result).toBe('export type A = 1;\n    version: string;\n');
  });
});

describe('typesFor', () => {
  it('turns a route schema into types with no comments', async () => {
    // Arrange
    const schema = SCHEMA;

    // Act
    const result = await typesFor(schema);

    // Assert
    expect(result).toContain('"/api/catalogue"');
    expect(result).toContain('version: string;');
    expect(result.includes('/*')).toBe(false);
  });
});
