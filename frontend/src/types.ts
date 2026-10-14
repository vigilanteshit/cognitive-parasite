export interface Model { id: string; label: string; provider: string; available: boolean; reason?: string }
export interface Message { role: 'user' | 'assistant' | 'system'; content: string }
export interface SessionSummary { id: string; title: string; updated_at: string }
export type RunStatus = 'queued' | 'running' | 'completed' | 'cancelled' | 'limited' | 'failed';
export interface Run { id: string; status: RunStatus; event_cursor?: number; answer?: string }
export interface Session extends SessionSummary { messages: Message[]; runs?: Run[] }
export interface Memory {
  id: string; kind: 'semantic' | 'episodic'; text: string; source?: string;
  created_at?: string; supersedes?: string; superseded_by?: string; category?: string;
  document?: string; page?: number; keywords?: string[]; state?: string; action?: string;
  machine?: string; importance?: number; legacy?: boolean;
}
export interface Source { id: string; text: string; source: string; kind: string; document?: string; page?: number }
export interface Budget { steps: number; max_steps: number; input_tokens: number; output_tokens: number; max_tokens: number }
export type RunEvent =
  | { type: 'token'; text: string }
  | { type: 'status'; message: string; step?: string | number; replace_answer?: boolean }
  | { type: 'sources'; sources: Source[] }
  | ({ type: 'budget' } & Budget)
  | { type: 'memory'; memory?: Memory; message?: string }
  | { type: 'done'; status: RunStatus; answer?: string }
  | { type: 'error'; message: string };
export interface TraceEntry { message: string; step?: string | number }
export interface Execution { run: Run | null; answer: string; sources: Source[]; trace: TraceEntry[]; budget: Budget | null; connectionLost: boolean }
export const emptyExecution: Execution = { run: null, answer: '', sources: [], trace: [], budget: null, connectionLost: false };
export const isActive = (run: Run | null) => !!run && ['queued', 'running'].includes(run.status);
