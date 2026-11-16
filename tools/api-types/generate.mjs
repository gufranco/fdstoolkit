import openapiTS, { astToString } from 'openapi-typescript';

const DOC_COMMENT = /^[ \t]*\/\*\*[\s\S]*?\*\/\r?\n/gm;

export function withoutDocComments(text) {
  return text.replace(DOC_COMMENT, '');
}

export async function typesFor(schema) {
  return withoutDocComments(astToString(await openapiTS(schema)));
}
