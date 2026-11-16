import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'happy-dom',
    include: ['tests/web/**/*.test.js', 'tests/page/**/*.test.tsx', 'tools/api-types/**/*.test.mjs'],
    coverage: {
      provider: 'v8',
      include: ['src/fdstoolkit/ui/static/*.js', 'web/src/**/*.{ts,tsx}', 'tools/api-types/generate.mjs'],
      exclude: ['web/src/api/schema.d.ts'],
      reporter: ['text', 'json-summary'],
      thresholds: { lines: 100, functions: 100, branches: 100, statements: 100 },
    },
  },
});
