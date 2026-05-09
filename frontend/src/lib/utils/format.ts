import type { GenerateJobStatus } from '$lib/api/types';

function withBasePath(path: string) {
  return `${import.meta.env.BASE_URL.replace(/\/$/, '')}${path}`;
}

export function imageUrl(filename: string) {
  return withBasePath(`/api/image/${encodeURIComponent(filename)}`);
}

export function downloadUrl(filename: string) {
  return withBasePath(`/api/download/${encodeURIComponent(filename)}`);
}

export function filenameFromImageUrl(url: string) {
  return decodeURIComponent(url.split('/').pop() || '');
}

export function formatBytes(totalBytes: number) {
  if (!Number.isFinite(totalBytes) || totalBytes <= 0) return '';
  return `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function stageLabel(job: GenerateJobStatus | null) {
  if (!job?.stage) return '';
  return job.message || job.stage.replaceAll('_', ' ');
}

export async function copyText(text: string) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
}

