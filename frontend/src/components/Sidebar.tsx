import { ArrowUpRight, ChatCircleText, Plus, Trash, X } from '@phosphor-icons/react';
import { useState } from 'react';
import type { SessionSummary } from '../types';

interface Props { sessions: SessionSummary[]; selected?: string; disabled: boolean; open: boolean; onClose: () => void; onSelect: (id: string) => void; onNew: () => void; onDelete: (id: string) => void; mode: string }
export function Sidebar({ sessions, selected, disabled, open, onClose, onSelect, onNew, onDelete, mode }: Props) {
  const [deleting, setDeleting] = useState<string | null>(null);
  return <>
    {open && <button className="scrim" aria-label="Close sessions" onClick={onClose} />}
    <aside className={`sidebar ${open ? 'is-open' : ''}`} aria-label="Sessions">
      <a className="wordmark" href="/" aria-label="The Data Parasite home"><span className="brand-mark">p<span /></span><span>THE DATA<br />PARASITE<span className="wordmark-caption">COGNITIVE MEMORY LAB</span></span></a>
      <button className="mobile-close icon-button" onClick={onClose} aria-label="Close sessions"><X size={20} /></button>
      <button className="new-session" onClick={onNew} disabled={disabled}><Plus size={18} /> New session <span>↗</span></button>
      <div className="sidebar-heading"><h2>Sessions</h2><span>{sessions.length.toString().padStart(2, '0')}</span></div>
      <nav className="session-list" aria-label="Saved conversations">
        {!sessions.length && <div className="sidebar-empty"><ChatCircleText size={24} /><p>A clean slate.</p><span>Your conversations will appear here.</span></div>}
        {sessions.map(item => <div className={`session-item ${item.id === selected ? 'selected' : ''}`} key={item.id}>
          <button className="session-select" aria-current={item.id === selected ? 'page' : undefined} disabled={disabled} onClick={() => { onSelect(item.id); onClose(); }}><ChatCircleText size={17} /><span><strong>{item.title || 'Untitled session'}</strong><small>{formatDate(item.updated_at)}</small></span></button>
          <button className="delete-session icon-button" aria-label={`Delete ${item.title || 'untitled session'}`} disabled={disabled} onClick={() => setDeleting(item.id)}><Trash size={15} /></button>
          {deleting === item.id && <div className="delete-confirm"><p>Delete this conversation and its memory?</p><div><button onClick={() => setDeleting(null)}>Keep</button><button className="danger-button" onClick={() => { onDelete(item.id); setDeleting(null); }}>Delete</button></div></div>}
        </div>)}
      </nav>
      <div className="sidebar-footer"><div className="mode-label"><span className="status-dot" />{mode === 'demo' ? 'Deterministic demo' : mode ? 'Connected workbench' : 'Connecting to server'}</div><p>{mode === 'demo' ? 'No credentials required. Responses illustrate the memory workflow.' : 'A local workspace for conversations, evidence, and persistent memory.'}</p><span className="version-label">RESEARCH WORKBENCH <ArrowUpRight size={13} /></span></div>
    </aside>
  </>;
}
function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Saved conversation' : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
