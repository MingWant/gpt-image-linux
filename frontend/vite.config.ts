import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

function normalizePanelPath(value: string | undefined) {
  const raw = (value || '').trim();
  if (!raw || raw === '/') return '';
  return `/${raw.split('/').filter(Boolean).join('/')}`.replace(/\/$/, '');
}

const panelPath = normalizePanelPath(process.env.PANEL_PATH);
const apiPrefix = `${panelPath}/api` || '/api';
const healthPath = `${panelPath}/health` || '/health';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      [apiPrefix]: {
        target: 'http://127.0.0.1:9090',
        rewrite: (path) => path.slice(panelPath.length)
      },
      [healthPath]: {
        target: 'http://127.0.0.1:9090',
        rewrite: (path) => path.slice(panelPath.length)
      }
    }
  }
});

