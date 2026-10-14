import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage } from './api';
import { emptyExecution, isActive } from './types';
import type { Execution, Memory, Model, Run, RunEvent, Session, SessionSummary } from './types';

export function useWorkbench() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState('');
  const [mode, setMode] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [execution, setExecution] = useState<Execution>(emptyExecution);
  const stream = useRef<EventSource | null>(null);
  const generation = useRef(0);
  const actionLock = useRef(false);

  const refreshList = useCallback(async () => setSessions((await api.sessions()).sessions), []);
  const connect = useCallback((run: Run, sessionId: string, after?: number) => {
    stream.current?.close();
    const current = generation.current;
    let lastId = after ?? 0;
    setExecution(previous => ({ ...previous, run, answer: '', connectionLost: false }));
    const events = new EventSource(`/api/runs/${encodeURIComponent(run.id)}/events${after != null ? `?after=${after}` : ''}`);
    stream.current = events;
    events.onopen = () => setExecution(previous => ({ ...previous, connectionLost: false }));
    events.onerror = () => {
      if (current === generation.current) setExecution(previous => ({ ...previous, connectionLost: true }));
    };
    events.onmessage = async message => {
      if (current !== generation.current) return;
      const id = Number(message.lastEventId);
      if (id && id <= lastId) return;
      if (id) lastId = id;
      let event: RunEvent;
      try { event = JSON.parse(message.data) as RunEvent; }
      catch { events.close(); setError('The server returned an unreadable event. Reconnect to recover this run.'); setExecution(previous => ({ ...previous, connectionLost: true })); return; }
      setExecution(previous => {
        switch (event.type) {
          case 'token': return { ...previous, answer: previous.answer + event.text };
          case 'status': return { ...previous, answer: event.replace_answer ? '' : previous.answer, trace: [...previous.trace, { message: event.message, step: event.step }], run: { ...run, status: 'running' } };
          case 'sources': return { ...previous, sources: [...new Map([...previous.sources, ...event.sources].map(source => [source.id, source])).values()] };
          case 'budget': return { ...previous, budget: event };
          case 'memory': return event.message ? { ...previous, trace: [...previous.trace, { message: event.message }] } : previous;
          case 'error': return { ...previous, trace: [...previous.trace, { message: event.message }] };
          case 'done': return { ...previous, run: { ...run, status: event.status, event_cursor: lastId }, answer: event.answer ?? previous.answer, connectionLost: false };
          default: return previous;
        }
      });
      if (event.type === 'error') setError(event.message);
      if (event.type === 'memory' && event.memory) {
        const memory = event.memory;
        setMemories(previous => [...previous.filter(item => item.id !== memory.id), memory]);
      }
      if (event.type === 'done') {
        events.close();
        try {
          const [saved, stored] = await Promise.all([api.session(sessionId), api.memories(sessionId)]);
          if (current !== generation.current) return;
          setSession(saved); setMemories(stored.memories);
          setExecution(previous => ({ ...previous, answer: event.status === 'completed' ? '' : previous.answer }));
          await refreshList();
        } catch (failure) { if (current === generation.current) setError(errorMessage(failure)); }
      }
    };
  }, [refreshList]);

  const selectSession = useCallback(async (id: string) => {
    const current = ++generation.current;
    stream.current?.close(); setLoading(true); setError(''); setExecution(emptyExecution);
    try {
      const [saved, stored] = await Promise.all([api.session(id), api.memories(id)]);
      if (current !== generation.current) return;
      setSession(saved); setMemories(stored.memories);
      const last = saved.runs?.at(-1);
      if (last) {
        setExecution({ ...emptyExecution, run: last, answer: last.status === 'completed' ? '' : last.answer ?? '' });
        if (isActive(last)) connect(last, id);
      }
    } catch (failure) { if (current === generation.current) { setSession(null); setError(errorMessage(failure)); } }
    finally { if (current === generation.current) setLoading(false); }
  }, [connect]);

  const initialize = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true); setError('');
    try {
      const [health, profiles, listed] = await Promise.all([api.health(), api.models(), api.sessions()]);
      if (current !== generation.current) return;
      setMode(health.mode); setModels(profiles.models); setModel(profiles.default); setSessions(listed.sessions);
      if (listed.sessions.length) await selectSession(listed.sessions[0].id);
      else { setSession(null); setLoading(false); }
    } catch (failure) { if (current === generation.current) { setError(`Cannot connect to the workbench. ${errorMessage(failure)}`); setLoading(false); } }
  }, [selectSession]);
  useEffect(() => { void initialize(); return () => { generation.current++; stream.current?.close(); }; }, [initialize]);

  async function action<T>(work: () => Promise<T>): Promise<T | undefined> {
    if (actionLock.current) return;
    actionLock.current = true; setBusy(true); setError('');
    try { return await work(); }
    catch (failure) { setError(errorMessage(failure)); }
    finally { actionLock.current = false; setBusy(false); }
  }
  const newSession = () => action(async () => {
    const created = await api.createSession();
    await refreshList(); await selectSession(created.id);
    return created;
  });
  const send = (message: string) => action(async () => {
    if (isActive(execution.run)) return false;
    const selected = session ?? await api.createSession();
    const run = await api.start(selected.id, message, model);
    setSession({ ...selected, messages: [...(selected.messages ?? []), { role: 'user', content: message }] });
    setExecution(emptyExecution); connect(run, selected.id); await refreshList();
    return true;
  });
  const cancel = () => action(async () => { if (execution.run) await api.cancel(execution.run.id); });
  const resume = () => action(async () => {
    if (!execution.run || !session) return;
    const run = await api.resume(execution.run.id, model);
    // The cursor skips the prior terminal event; answer nodes may regenerate their output.
    connect(run, session.id, run.event_cursor ?? execution.run.event_cursor);
  });
  const reconnect = () => { if (session && execution.run) { setExecution(emptyExecution); connect(execution.run, session.id); } };
  const removeSession = (id: string) => action(async () => {
    await api.deleteSession(id);
    const listed = (await api.sessions()).sessions; setSessions(listed);
    if (session?.id === id) {
      generation.current++; stream.current?.close(); setExecution(emptyExecution); setMemories([]); setSession(null);
      if (listed.length) await selectSession(listed[0].id);
    }
  });
  const ingest = (title: string, text: string) => action(async () => {
    const selected = session ?? await api.createSession();
    const result = await api.ingest(selected.id, title, text);
    if (!session) { await refreshList(); await selectSession(selected.id); }
    else setMemories((await api.memories(selected.id)).memories);
    return result;
  });
  return { sessions, session, memories, models, model, setModel, mode, loading, busy, error, clearError: () => setError(''), execution, initialize, selectSession, newSession, send, cancel, resume, reconnect, removeSession, ingest };
}
