import type { Memory, Model, Run, Session, SessionSummary } from './types';

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `Request failed (${response.status}). Please try again.`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export const api = {
  health: () => request<{ status: string; mode: string }>('/health'),
  models: () => request<{ models: Model[]; default: string }>('/models'),
  sessions: () => request<{ sessions: SessionSummary[] }>('/sessions'),
  createSession: () => request<Session>('/sessions', { method: 'POST', body: '{}' }),
  session: (id: string) => request<Session>(`/sessions/${encodeURIComponent(id)}`),
  memories: (id: string) => request<{ memories: Memory[] }>(`/sessions/${encodeURIComponent(id)}/memories`),
  deleteSession: (id: string) => request<void>(`/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  start: (id: string, message: string, model_profile: string) => request<Run>(`/sessions/${encodeURIComponent(id)}/runs`, { method: 'POST', body: JSON.stringify({ message, model_profile }) }),
  cancel: (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  resume: (id: string, model_profile?: string) => request<Run>(`/runs/${encodeURIComponent(id)}/resume`, { method: 'POST', body: JSON.stringify({ model_profile }) }),
  ingest: (session_id: string, title: string, text: string) => request<{ id: string; chunks: number }>('/documents', { method: 'POST', body: JSON.stringify({ session_id, title, text }) }),
};
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Please try again.';
