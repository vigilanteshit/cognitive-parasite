import { BookOpen, Brain, CaretDown, CheckCircle, ListChecks, X } from '@phosphor-icons/react';
import { Fragment, useRef, useState } from 'react';
import { useFocusTrap } from '../useFocusTrap';
import type { Execution, Memory } from '../types';

type Tab = 'sources' | 'memory' | 'execution';
const tabs: { id: Tab; label: string }[] = [{ id: 'sources', label: 'Sources' }, { id: 'memory', label: 'Memory' }, { id: 'execution', label: 'Execution' }];
interface Props { execution: Execution; memories: Memory[]; open: boolean; onClose: () => void; initialTab?: Tab; initialKind?: 'all' | 'semantic' | 'episodic' }
export function Inspector({ execution, memories, open, onClose, initialTab = 'sources', initialKind = 'all' }: Props) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [kind, setKind] = useState<'all' | 'semantic' | 'episodic'>(initialKind);
  const container = useRef<HTMLElement>(null);
  useFocusTrap(open, container, onClose);
  const budget = execution.budget;
  const filtered = memories.filter(item => kind === 'all' || item.kind === kind);
  return <aside ref={container} className={`inspector ${open ? 'is-open' : ''}`} role={open ? 'dialog' : undefined} aria-modal={open || undefined} aria-label="Research inspector">
    <div className="inspector-heading"><div><span className="eyebrow">BEHIND THE ANSWER</span><h2>Research inspector</h2></div><button className="mobile-close icon-button" onClick={onClose} aria-label="Close inspector"><X size={20} /></button></div>
    <div className="inspector-tabs" role="tablist" aria-label="Inspect research" onKeyDown={event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const index = tabs.findIndex(item => item.id === tab);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3;
      setTab(tabs[next].id); document.getElementById(`tab-${tabs[next].id}`)?.focus();
    }}>{tabs.map(item => <button role="tab" id={`tab-${item.id}`} aria-controls={`panel-${item.id}`} aria-selected={item.id === tab} tabIndex={item.id === tab ? 0 : -1} key={item.id} onClick={() => setTab(item.id)}>{item.label}{item.id === 'sources' && execution.sources.length > 0 && <span>{execution.sources.length}</span>}{item.id === 'memory' && memories.length > 0 && <span>{memories.length}</span>}</button>)}</div>
    <div className="inspector-content" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} tabIndex={0}>
      {tab === 'sources' && <><div className="panel-intro"><span className="eyebrow">RETRIEVED EVIDENCE</span><p>Inspect the context selected for the current response.</p></div>{execution.sources.length ? execution.sources.map((source, index) => <details className="evidence-item" key={source.id} open={index === 0}><summary><span className="evidence-number">{(index + 1).toString().padStart(2, '0')}</span><span><strong>{source.document || source.source || 'Retrieved context'}</strong><small>{source.kind.replaceAll('_', ' ')}</small></span><CaretDown size={14} /></summary><p>{source.text}</p><span className="record-id">ID {source.id}</span></details>) : <Empty icon="sources" title="Evidence starts here" text="Send a message to see retrieved sources. Add your own text to give the system research context." />}</>}
      {tab === 'memory' && <><div className="panel-intro"><span className="eyebrow">PERSISTENT CONTEXT</span><p>Semantic facts and episodic experience, scoped to this session.</p></div><div className="memory-filter" aria-label="Filter memory">{(['all', 'semantic', 'episodic'] as const).map(value => <button key={value} aria-pressed={value === kind} onClick={() => setKind(value)}>{value === 'all' ? 'All' : value[0].toUpperCase() + value.slice(1)}</button>)}</div>{filtered.length ? filtered.map(memory => <details className="memory-item" key={memory.id} open><summary><span className={`memory-kind ${memory.kind}`}><Brain size={12} />{memory.kind}</span><CaretDown size={13} /></summary><p>{memory.text}</p>{memory.source && <span className="memory-meta">Source · {memory.source}</span>}{memory.category && <span className="memory-meta">Category · {memory.category}</span>}{memory.supersedes && <span className="memory-meta">Replaces · {memory.supersedes}</span>}<MemoryFields memory={memory} /><span className="record-id">ID {memory.id}</span></details>) : <Empty icon="memory" title={kind === 'all' ? 'Room to remember' : `No ${kind} memory yet`} text="Memory records will appear as the system learns from this conversation. New sessions begin independently." />}</>}
      {tab === 'execution' && <><div className="panel-intro"><span className="eyebrow">OBSERVABLE BY DESIGN</span><p>Follow the steps and budget reported by the server.</p></div><div className="run-summary"><span className="status-dot" /><strong>{execution.run ? statusLabel(execution.run.status) : 'Awaiting a question'}</strong>{execution.run && <span className="record-id">{execution.run.id}</span>}</div>{budget && <div className="budget"><h3>Execution budget</h3><div className="budget-row"><span>Steps</span><strong>{budget.steps} / {budget.max_steps}</strong></div><progress aria-label="Steps used" value={budget.steps} max={Math.max(1, budget.max_steps)} /><div className="budget-row"><span>Tokens</span><strong>{(budget.input_tokens + budget.output_tokens).toLocaleString()} / {budget.max_tokens.toLocaleString()}</strong></div><progress aria-label="Tokens used" value={budget.input_tokens + budget.output_tokens} max={Math.max(1, budget.max_tokens)} /><div className="token-breakdown"><span>Input {budget.input_tokens.toLocaleString()}</span><span>Output {budget.output_tokens.toLocaleString()}</span></div></div>}{execution.trace.length ? <ol className="trace-list">{execution.trace.map((entry, index) => <li key={index}><span className="trace-marker"><CheckCircle size={16} /></span><div>{entry.step != null && <span className="eyebrow">STEP {entry.step}</span>}<p>{entry.message}</p></div></li>)}</ol> : <Empty icon="execution" title="A visible process" text="Execution steps appear during a run. Budgets keep each experiment bounded and checkpoints make stopped runs resumable." />}</>}
    </div>
    <div className="inspector-footer"><span className="status-dot" /> SESSION-SCOPED · SERVER-REPORTED</div>
  </aside>;
}
function Empty({ icon, title, text }: { icon: Tab; title: string; text: string }) {
  const Icon = icon === 'sources' ? BookOpen : icon === 'memory' ? Brain : ListChecks;
  return <div className="inspector-empty"><span className="empty-icon"><Icon size={26} weight="light" /></span><h3>{title}</h3><p>{text}</p></div>;
}
function statusLabel(status: string) { return ({ queued: 'Queued', running: 'In progress', completed: 'Completed', cancelled: 'Stopped', limited: 'Budget reached', failed: 'Failed' })[status] ?? status; }

function MemoryFields({ memory }: { memory: Memory }) {
  const fields = [
    ['Document', memory.document],
    ['Page', memory.page],
    ['Keywords', memory.keywords?.join(', ')],
    ['State', memory.state],
    ['Action', memory.action],
    ['Machine', memory.machine],
    ['Importance', memory.importance != null ? `${Math.round(memory.importance * 100)}%` : undefined],
    ['Recorded', memory.created_at],
    ['Version', memory.legacy != null ? memory.legacy ? 'Earlier version' : 'Current' : undefined],
    ['Successor', memory.superseded_by],
  ].filter(([, value]) => value !== undefined && value !== null && value !== '');
  return <dl className="memory-fields">{fields.map(([label, value]) => <Fragment key={label}><dt>{label}</dt><dd>{value}</dd></Fragment>)}</dl>;
}
