import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

function normalizePanelPath(value) {
  const raw = (value || '').trim();
  if (!raw || raw === '/') return '';
  return `/${raw.split('/').filter(Boolean).join('/')}`.replace(/\/$/, '');
}

const panelPath = normalizePanelPath(process.env.PANEL_PATH);

const config = {
  preprocess: vitePreprocess(),
  kit: {
    paths: {
      base: panelPath
    },
    adapter: adapter({
      fallback: 'index.html'
    })
  }
};

export default config;

