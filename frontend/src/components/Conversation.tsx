import { ArrowUpRight, BookOpen, Brain, CircleNotch, Compass, MagnifyingGlass, Paperclip, Pause, Play, Sparkle } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { isActive } from '../types';
import type { Execution, Message, Model } from '../types';

interface Props { messages: Message[]; execution: Execution; loading: boolean; busy: boolean; canSend: boolean; demo: boolean; onSend: (text: string) => Promise<unknown>; onStop: () => void; onResume: () => void; onDocument: () => void; onReconnect: () => void; onExplore: () => void; onSources: () => void; models: Model[]; model: string; onModel: (id: string) => void }
export function Conversation({ messages, execution, loading, busy, canSend, demo, onSend, onStop, onResume, onDocument, onReconnect, onExplore, onSources, models, model, onModel }: Props) {
  const [draft, setDraft] = useState('');
  const [copied, setCopied] = useState<number | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const active = isActive(execution.run);
  const resumable = execution.run && ['cancelled', 'limited', 'failed'].includes(execution.run.status);
  const send = async () => {
    const text = draft.trim();
    if (!text || busy || active || !canSend) return;
    const sent = await onSend(text);
    if (sent) { setDraft(''); following.current = true; textarea.current?.focus(); }
  };
  useEffect(() => {
    if (viewport.current && following.current && (messages.length || active || execution.answer)) viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [messages, execution.answer, execution.trace, loading, active]);
  useEffect(() => { following.current = true; }, [messages.length]);
  const copy = async (content: string, index: number) => {
    try { await navigator.clipboard.writeText(content); setCopied(index); }
    catch { setCopied(null); }
  };
  return <section className="conversation" aria-label="Conversation">
    <div className="intent-bar" aria-label="Start with your knowledge">
      <button onClick={() => textarea.current?.focus()}><span className="intent-icon"><MagnifyingGlass size={21} /></span><span><strong>Ask anything</strong><small>Clear, sourced answers</small></span></button>
      <button onClick={onDocument} disabled={busy || active || !canSend}><span className="intent-icon"><BookOpen size={21} /></span><span><strong>Analyze</strong><small>Bring your documents</small></span></button>
      <button onClick={() => { setDraft('I would like you to remember: '); textarea.current?.focus(); }} disabled={active || !canSend}><span className="intent-icon"><Brain size={21} /></span><span><strong>Remember</strong><small>Keep valuable experience</small></span></button>
      <button onClick={onExplore}><span className="intent-icon"><Compass size={21} /></span><span><strong>Explore</strong><small>Connect your knowledge</small></span></button>
    </div>
    <div className="conversation-scroll" ref={viewport} onScroll={() => { const view = viewport.current; if (view) following.current = view.scrollHeight - view.scrollTop - view.clientHeight < 100; }}>
      {loading ? <div className="loading-state" role="status"><CircleNotch className="spinner" size={24} /><p>Opening your workspace…</p><div className="skeleton" /><div className="skeleton short" /></div> : !messages.length && !active ? <div className="welcome">
        <span className="welcome-spark" aria-hidden="true"><Sparkle size={32} weight="fill" /></span>
        <h2>Good ideas have<br /><em>great connections.</em></h2>
        <p>Bring what you know. Discover what connects.<br />Build a memory that grows with every conversation.</p>
        <div className="welcome-actions">
          <button onClick={() => { setDraft('How do semantic and episodic memory work together?'); textarea.current?.focus(); }}><Sparkle size={20} /><span><strong>Explore cognitive memory</strong><small>Start with the architecture</small></span><ArrowUpRight size={17} /></button>
          <button onClick={onDocument} disabled={busy || !canSend}><BookOpen size={20} /><span><strong>Ground it in your research</strong><small>Add a document to this session</small></span><ArrowUpRight size={17} /></button>
        </div>
        <div className="welcome-note"><span className="status-dot" />{demo ? 'Local demo · no model calls' : 'Your sources and experiences stay connected'}</div>
      </div> : <div className="message-list">
        {messages.filter(message => message.role !== 'system').map((message, index) => <article className={`message ${message.role}`} key={index}>
          <div className="message-heading"><span className="message-avatar">{message.role === 'user' ? 'Y' : <Sparkle weight="fill" size={21} />}</span><span>{message.role === 'user' ? 'You' : 'Parasite'}</span>{message.role === 'assistant' && <button className="copy-button" onClick={() => void copy(message.content, index)} aria-label="Copy answer">{copied === index ? 'Copied' : 'Copy'}</button>}</div>
          <div className="message-body"><Markdown content={message.content} /></div>
        </article>)}
        {(active || execution.answer) && <article className="message assistant" aria-label="Current response"><div className="message-heading"><span className="message-avatar"><Sparkle weight="fill" size={21} /></span><span>Parasite</span>{active && <span className="writing-label">{execution.answer ? 'Writing' : 'Working'}<span className="typing-dots" /></span>}</div><div className="message-body">{execution.answer ? <Markdown content={execution.answer} /> : <p className="thinking">{execution.trace.at(-1)?.message || 'Preparing the next step…'}</p>}</div></article>}
        {!!execution.sources.length && <button className="sources-link" onClick={onSources}><BookOpen size={15} /> Sources ({execution.sources.length}) <ArrowUpRight size={14} /></button>}
      </div>}
    </div>
    <div className="composer-area">
      {execution.connectionLost && <div className="connection-note" role="status">Connection interrupted. Your run is saved.<button onClick={onReconnect}>Reconnect</button></div>}
      {resumable && <div className="run-note" role="status"><span>{execution.run?.status === 'limited' ? 'Execution reached its budget.' : 'Execution stopped.'} The checkpoint is saved.</span><button onClick={onResume} disabled={busy}><Play size={14} /> Resume run</button></div>}
      <form className={`composer ${active ? 'is-working' : ''}`} onSubmit={event => { event.preventDefault(); void send(); }}>
        <label className="sr-only" htmlFor="message">Message</label>
        <textarea ref={textarea} id="message" placeholder={active ? 'The system is working. Stop the run to continue.' : 'Ask a question or share something to remember…'} value={draft} maxLength={12000} rows={2} disabled={loading || active || !canSend} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} />
        <div className="composer-toolbar"><button className="attach-button" type="button" onClick={onDocument} disabled={busy || active || !canSend}><Paperclip size={18} /> Add source</button><span className="composer-shortcut">Enter to send · Shift + Enter for a new line</span><label className="model-control"><span className="sr-only">Model profile</span><select aria-label="Model profile" value={model} onChange={event => onModel(event.target.value)} disabled={active || busy || loading || !models.length}>{!models.length && <option value="">Connecting…</option>}{models.map(item => <option key={item.id} value={item.id} disabled={!item.available}>{item.label}{!item.available ? ' (unavailable)' : ''}</option>)}</select></label>{active ? <button className="send-button stop-button" type="button" aria-label="Stop run" disabled={busy} onClick={onStop}><Pause size={18} weight="fill" /></button> : <button className="send-button" type="submit" aria-label="Send message" disabled={!draft.trim() || busy || loading || !canSend}>{busy ? <CircleNotch size={20} className="spinner" /> : <ArrowUpRight size={22} weight="bold" />}</button>}</div>
      </form>
      <p className="composer-footnote">{demo ? 'Deterministic demo · Outputs are illustrative research examples.' : 'Research system · Check retrieved evidence before relying on an answer.'}</p>
      <span className="sr-only" role="status" aria-live="polite">{active ? 'Response in progress' : execution.run ? `Run ${execution.run.status}` : ''}</span>
    </div>
  </section>;
}
function Markdown({ content }: { content: string }) {
  return <ReactMarkdown components={{ a: ({ children, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer">{children}</a> }}>{content}</ReactMarkdown>;
}
