import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import type { RunEvent, Session } from './types';

class FakeEvents {
  static connections: FakeEvents[] = [];
  onmessage: ((event: { data: string; lastEventId: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;
  constructor(public url: string) { FakeEvents.connections.push(this); }
  close() { this.closed = true; }
  emit(event: RunEvent, id: number) { this.onmessage?.({ data: JSON.stringify(event), lastEventId: String(id) }); }
}
let saved: Session;
let fetchMock: ReturnType<typeof vi.fn<(path: string, init?: RequestInit) => Promise<Response>>>;
beforeEach(() => {
  FakeEvents.connections = [];
  saved = { id: 's1', title: 'New session', updated_at: new Date().toISOString(), messages: [], runs: [] };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    let body: unknown;
    if (path === '/api/health') body = { status: 'ok', mode: 'demo' };
    else if (path === '/api/models') body = { models: [{ id: 'demo', label: 'Local demo', provider: 'demo', available: true }], default: 'demo' };
    else if (path === '/api/sessions' && init?.method === 'POST') body = saved;
    else if (path === '/api/sessions') body = { sessions: [] };
    else if (path === '/api/sessions/s1/memories') body = { memories: [] };
    else if (path === '/api/sessions/s1') body = saved;
    else if (path === '/api/sessions/s1/runs') { const sent = JSON.parse(String(init?.body)); saved.messages.push({ role: 'user', content: sent.message }); body = { id: 'r1', status: 'queued' }; }
    else if (path === '/api/runs/r1/cancel') body = { id: 'r1', status: 'cancelled' };
    else if (path === '/api/runs/r1/resume') body = { id: 'r1', status: 'queued', event_cursor: 4 };
    else if (path === '/api/documents') body = { id: 'd1', chunks: 2 };
    else throw Error(`Unexpected API path ${path}`);
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('EventSource', FakeEvents);
});
describe('research workbench', () => {
  it('identifies demo mode and presents an honest empty workspace', async () => {
    render(<App />);
    expect(await screen.findByText('Deterministic demo')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Every conversation/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled();
  });
  it('updates mode labels when a live model is selected despite the demo server default', async () => {
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (path: string, init?: RequestInit) => path === '/api/models' ? new Response(JSON.stringify({ models: [{ id: 'demo', label: 'Local demo', provider: 'demo', available: true }, { id: 'live', label: 'Live model', provider: 'openai', available: true }], default: 'demo' })) : original(path, init));
    const user = userEvent.setup(); render(<App />); await screen.findByText('Deterministic demo');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Model profile' }), 'live');
    expect(screen.queryByText('Demo mode')).not.toBeInTheDocument();
    expect(screen.queryByText('Deterministic demo')).not.toBeInTheDocument();
    expect(screen.getByText('Connected workbench')).toBeInTheDocument();
    expect(screen.getByText('Research system · Check retrieved evidence before relying on an answer.')).toBeInTheDocument();
  });
  it('streams a response, exposes evidence, and refreshes persisted memory on completion', async () => {
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Deterministic demo');
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Remember my research topic');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await waitFor(() => expect(FakeEvents.connections).toHaveLength(1));
    const connection = FakeEvents.connections[0];
    await act(async () => {
      connection.emit({ type: 'status', message: 'Retrieving session context', step: 1 }, 1);
      connection.emit({ type: 'sources', sources: [{ id: 'd1', source: 'Research note', kind: 'document', text: 'Cognitive systems remember experience.' }] }, 2);
      connection.emit({ type: 'token', text: 'I will remember your topic.' }, 3);
      connection.emit({ type: 'token', text: 'I will remember your topic.' }, 3);
    });
    expect(screen.getByText('I will remember your topic.')).toBeInTheDocument();
    expect(screen.getByText('Research note')).toBeInTheDocument();
    saved = { ...saved, messages: [...saved.messages, { role: 'assistant', content: 'I will remember your topic.' }] };
    await act(async () => connection.emit({ type: 'done', status: 'completed' }, 4));
    await waitFor(() => expect(connection.closed).toBe(true));
    expect(screen.getAllByText('I will remember your topic.')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Stop run' })).not.toBeInTheDocument();
  });
  it('stops and resumes a checkpoint after the terminal event cursor', async () => {
    const user = userEvent.setup(); render(<App />); await screen.findByText('Deterministic demo');
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'Explore memory');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    await screen.findByRole('button', { name: 'Stop run' });
    await user.click(screen.getByRole('button', { name: 'Stop run' }));
    expect(fetchMock).toHaveBeenCalledWith('/api/runs/r1/cancel', expect.objectContaining({ method: 'POST' }));
    await act(async () => {
      FakeEvents.connections[0].emit({ type: 'token', text: 'The saved partial answer' }, 3);
      FakeEvents.connections[0].emit({ type: 'done', status: 'cancelled' }, 4);
    });
    expect(await screen.findByText('The saved partial answer')).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Resume run' }));
    await waitFor(() => expect(FakeEvents.connections).toHaveLength(2));
    expect(FakeEvents.connections[1].url).toBe('/api/runs/r1/events?after=4');
  });
  it('keeps a failed message editable and reports the server error', async () => {
    const user = userEvent.setup(); render(<App />); await screen.findByText('Deterministic demo');
    fetchMock.mockImplementationOnce(async () => new Response(JSON.stringify(saved)));
    fetchMock.mockImplementationOnce(async () => new Response(JSON.stringify({ error: { code: 'provider_unavailable', message: 'This model is unavailable.' } }), { status: 503 }));
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'My unsent message');
    await user.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This model is unavailable.');
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('My unsent message');
  });
  it('indexes a source with an explicit session and reports its real chunk count', async () => {
    const user = userEvent.setup(); render(<App />); await screen.findByText('Deterministic demo');
    await user.click(screen.getByRole('button', { name: 'Add source' }));
    await user.type(screen.getByRole('textbox', { name: 'Source title' }), 'Study note');
    await user.type(screen.getByRole('textbox', { name: 'Source text' }), 'Memory is context.');
    await user.click(screen.getByRole('button', { name: 'Add to this session' }));
    expect(await screen.findByText('Source added. 2 chunks are ready for retrieval.')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('/api/documents', expect.objectContaining({ body: JSON.stringify({ session_id: 's1', title: 'Study note', text: 'Memory is context.' }) }));
  });
});
