import { ArrowUpRight, Books, ChatCircleText, Compass, Desktop, MagnifyingGlass, Plus, Trash, X } from '@phosphor-icons/react';
import { useRef, useState } from 'react';
import { useFocusTrap } from '../useFocusTrap';
import type { SessionSummary } from '../types';

interface Props {
  sessions: SessionSummary[];
  selected?: string;
  disabled: boolean;
  open: boolean;
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onExplore?: () => void;
  onLibrary?: () => void;
  mode: string;
}

export function Sidebar({ sessions, selected, disabled, open, onClose, onSelect, onNew, onDelete, onExplore, onLibrary, mode }: Props) {
  const [deleting, setDeleting] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const container = useRef<HTMLElement>(null);
  useFocusTrap(open, container, onClose);
  const search = query.trim().toLocaleLowerCase();
  const filteredSessions = sessions.filter(item => (item.title || 'Untitled session').toLocaleLowerCase().includes(search));

  function navigate(action: () => void) {
    action();
    onClose();
  }

  return <>
    {open && <button className="scrim" aria-label="Close sessions" onClick={onClose} />}
    <aside ref={container} className={`sidebar ${open ? 'is-open' : ''}`} role={open ? 'dialog' : undefined} aria-modal={open || undefined} aria-label="Workspace navigation">
      <a className="wordmark" href="/" aria-label="The Data Parasite home">
        <span className="nova-brand-mark" aria-hidden="true"><i /><i /><i /><i /><i /><i /></span>
        <span>PARASITE<span className="wordmark-caption">Knowledge co-pilot</span></span>
      </a>
      <button className="mobile-close icon-button" onClick={onClose} aria-label="Close sessions"><X size={20} /></button>
      <div className="sidebar-actions">
        <button className="new-session" onClick={() => navigate(onNew)} disabled={disabled}>
          <Plus size={19} /> New chat <ArrowUpRight size={16} />
        </button>
        <label className="sidebar-search">
          <MagnifyingGlass size={19} aria-hidden="true" />
          <input type="search" aria-label="Search conversations" placeholder="Search" value={query} onChange={event => setQuery(event.target.value)} />
        </label>
        <button className="sidebar-nav-action" onClick={() => onExplore && navigate(onExplore)} disabled={disabled || !onExplore}>
          <Compass size={19} /> Explore
        </button>
        <button className="sidebar-nav-action" onClick={() => onLibrary && navigate(onLibrary)} disabled={disabled || !onLibrary}>
          <Books size={19} /> Library
        </button>
      </div>
      <div className="sidebar-heading"><h2>Recent chats</h2><span>{filteredSessions.length.toString().padStart(2, '0')}</span></div>
      <nav className="session-list" aria-label="Saved conversations">
        {!filteredSessions.length && <div className="sidebar-empty" role="status">
          <ChatCircleText size={24} />
          <p>{search ? 'No matching chats.' : 'A clean slate.'}</p>
          <span>{search ? 'Try another conversation title.' : 'Your conversations will appear here.'}</span>
        </div>}
        {filteredSessions.map(item => <div className={`session-item ${item.id === selected ? 'selected' : ''}`} key={item.id}>
          <button className="session-select" aria-current={item.id === selected ? 'page' : undefined} disabled={disabled} onClick={() => navigate(() => onSelect(item.id))}>
            <ChatCircleText size={17} />
            <span><strong>{item.title || 'Untitled session'}</strong><small>{formatDate(item.updated_at)}</small></span>
          </button>
          <button className="delete-session icon-button" aria-label={`Delete ${item.title || 'untitled session'}`} disabled={disabled} onClick={() => setDeleting(item.id)}><Trash size={15} /></button>
          {deleting === item.id && <div className="delete-confirm">
            <p>Delete this conversation and its memory?</p>
            <div>
              <button onClick={() => setDeleting(null)}>Keep</button>
              <button className="danger-button" disabled={disabled} onClick={() => { onDelete(item.id); setDeleting(null); }}>Delete</button>
            </div>
          </div>}
        </div>)}
      </nav>
      <div className="sidebar-footer">
        <div className="workspace-identity">
          <span className="workspace-avatar"><Desktop size={20} /></span>
          <span className="workspace-label">Local workspace<small>Research workbench</small></span>
        </div>
        <div className="mode-label"><span className="status-dot" />{mode === 'demo' ? 'Deterministic demo' : mode ? 'Connected workbench' : 'Connecting to server'}</div>
        <p>{mode === 'demo' ? 'No credentials required. Responses illustrate the memory workflow.' : mode ? 'Conversations, evidence, and persistent memory.' : 'Waiting for the local server connection.'}</p>
      </div>
    </aside>
  </>;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Saved conversation' : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
