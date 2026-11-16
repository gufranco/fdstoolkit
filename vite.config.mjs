import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  root: 'web',
  base: '/static/',
  plugins: [react()],
  build: {
    outDir: '../src/fdstoolkit/ui/page',
    emptyOutDir: true,
  },
});
