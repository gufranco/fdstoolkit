import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'happy-dom',
    include: ['tests/web/**/*.test.js'],
    coverage: {
      provider: 'v8',
      include: ['src/fdstoolkit/ui/static/*.js'],
      reporter: ['text', 'json-summary'],
      thresholds: { lines: 100, functions: 100, branches: 100, statements: 100 },
    },
  },
});
