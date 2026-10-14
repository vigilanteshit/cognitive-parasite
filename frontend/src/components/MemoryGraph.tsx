import { useId, useState } from 'react';
import { ArrowCircleUp, BookOpen, Brain, ClockCounterClockwise, Folders, Hash, Sparkle, WarningCircle, Wrench } from '@phosphor-icons/react';
import type { Memory } from '../types';

type Node = { id: string; label: string; type: string; tone: string; detail: string };
type Edge = { from: string; to: string; relation: string };
type Graph = { nodes: Node[]; edges: Edge[]; omitted: number };
type Props = { kind: Memory['kind']; memories: Memory[]; onInspect: () => void };

const positions = [[50, 48], [23, 22], [76, 24], [83, 57], [70, 83], [27, 80], [16, 52], [50, 12]];
const node = (id: string, label: string, type: string, tone: string, detail = label): Node => ({ id, label, type, tone, detail });
const nodeIcons = { Chunk: BookOpen, Experience: Brain, Document: BookOpen, Keyword: Hash, Category: Folders, State: WarningCircle, Action: Wrench, 'Previous version': ClockCounterClockwise, 'New version': ArrowCircleUp };

function storedGraph(memory: Memory, records: Memory[]): Graph {
  const graph: Graph = { nodes: [], edges: [], omitted: 0 };
  const summary = [memory.text, memory.machine && `Machine: ${memory.machine}`, memory.source && `Source: ${memory.source}`].filter(Boolean).join(' · ');
  graph.nodes.push(node(memory.id, memory.text, memory.kind === 'semantic' ? 'Chunk' : 'Experience', 'hub', summary));
  const add = (next: Node, from: string, to: string, relation: string) => {
    if (graph.nodes.some(item => item.id === next.id)) return;
    if (graph.nodes.length === 8) { graph.omitted++; return; }
    graph.nodes.push(next);
    graph.edges.push({ from, to, relation });
  };
  if (memory.document) {
    const id = `${memory.id}:document`;
    const detail = `${memory.document}${memory.page != null ? ` · page ${memory.page}` : ''}`;
    add(node(id, memory.document, 'Document', 'blue', detail), memory.id, id, 'FROM_DOCUMENT');
  }
  if (memory.kind === 'episodic' && memory.category) {
    const id = `${memory.id}:category`;
    add(node(id, memory.category, 'Category', 'blue'), memory.id, id, 'IN_CATEGORY');
  }
  if (memory.state) {
    const stateId = `${memory.id}:state`;
    add(node(stateId, memory.state, 'State', 'amber'), memory.id, stateId, 'HAS_STATE');
    if (memory.action) {
      const actionId = `${memory.id}:action`;
      add(node(actionId, memory.action, 'Action', 'green'), stateId, actionId, 'RESOLVED_BY');
    }
  }
  for (const [id, previous] of [[memory.supersedes, true], [memory.superseded_by, false]] as const) {
    if (!id || id === memory.id) continue;
    const related = records.find(record => record.id === id);
    const label = related?.text || `Memory ${id}`;
    add(node(id, label, previous ? 'Previous version' : 'New version', 'pink'), previous ? id : memory.id, previous ? memory.id : id, 'SUPERSEDED_BY');
  }
  for (const keyword of new Set(memory.keywords ?? [])) {
    if (!keyword.trim()) continue;
    const id = `${memory.id}:keyword:${keyword}`;
    add(node(id, keyword, 'Keyword', 'violet'), memory.id, id, 'HAS_KEYWORD');
  }
  return graph;
}

function schemaGraph(kind: Memory['kind']): Graph {
  const nodes = kind === 'semantic'
    ? [node('memory', 'Chunk', 'Chunk', 'hub'), node('document', 'Document', 'Document', 'blue'), node('keywords', 'Keywords', 'Keyword', 'violet')]
    : [node('memory', 'Experience', 'Experience', 'hub'), node('state', 'State', 'State', 'amber'), node('action', 'Action', 'Action', 'green'), node('previous', 'Previous version', 'Previous version', 'pink')];
  const edges = kind === 'semantic'
    ? [{ from: 'memory', to: 'document', relation: 'FROM_DOCUMENT' }, { from: 'memory', to: 'keywords', relation: 'HAS_KEYWORD' }]
    : [{ from: 'memory', to: 'state', relation: 'HAS_STATE' }, { from: 'state', to: 'action', relation: 'RESOLVED_BY' }, { from: 'previous', to: 'memory', relation: 'SUPERSEDED_BY' }];
  return { nodes, edges, omitted: 0 };
}

export function MemoryGraph({ kind, memories, onInspect }: Props) {
  const id = useId();
  const [selectedId, setSelectedId] = useState('');
  const [inspectedId, setInspectedId] = useState('');
  const records = memories.filter(memory => memory.kind === kind);
  const selected = records.find(record => record.id === selectedId) ?? records[0];
  const graph = selected ? storedGraph(selected, records) : schemaGraph(kind);
  const inspected = graph.nodes.find(item => item.id === inspectedId) ?? graph.nodes[0];
  const title = kind === 'semantic' ? 'Semantic memory' : 'Episodic memory';
  const point = (nodeId: string) => positions[graph.nodes.findIndex(item => item.id === nodeId)];

  return (
    <section className="graph-card" data-kind={kind} aria-labelledby={`${id}-title`}>
      <header className="graph-header">
        <span className="graph-category-icon" aria-hidden="true"><Sparkle weight="fill" size={25} /></span>
        <div><span className="graph-eyebrow">Knowledge graph</span><h2 id={`${id}-title`}>{title}</h2></div>
        <span className="graph-count">{records.length} {records.length === 1 ? 'record' : 'records'}</span>
      </header>
      <p className="graph-description">{kind === 'semantic' ? 'Documents, facts & connections' : 'Experiences, states & actions'}</p>
      <div className="graph-canvas" data-preview={!selected || undefined} aria-label={`${title} ${selected ? 'relationships' : 'schema preview'}`}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <defs><marker id={`${id}-arrow`} viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto"><path d="M 0 0 L 6 3 L 0 6 z" /></marker></defs>
          {graph.edges.map(edge => {
            const [x1, y1] = point(edge.from);
            const [x2, y2] = point(edge.to);
            const length = Math.hypot(x2 - x1, y2 - y1);
            const inset = Math.min(9, length / 3);
            return <line className="graph-edge" key={`${edge.from}-${edge.to}`} x1={x1 + (x2 - x1) / length * inset} y1={y1 + (y2 - y1) / length * inset} x2={x2 - (x2 - x1) / length * inset} y2={y2 - (y2 - y1) / length * inset} markerEnd={`url(#${id}-arrow)`} />;
          })}
        </svg>
        {graph.nodes.map((item, index) => {
          const style = { left: `${positions[index][0]}%`, top: `${positions[index][1]}%` };
          const Icon = nodeIcons[item.type as keyof typeof nodeIcons] ?? Brain;
          const content = <><span className="graph-node-dot"><Icon size={22} weight="duotone" /></span><span className="graph-node-label">{item.label}</span></>;
          return selected
            ? <button key={item.id} type="button" className="graph-node" data-tone={item.tone} data-type={index === 0 ? 'memory' : item.type.toLowerCase().replaceAll(' ', '-')} style={style} title={`${item.type}: ${item.detail}`} aria-label={`${item.type}: ${item.label}`} aria-pressed={inspected.id === item.id} onClick={() => setInspectedId(item.id)}>{content}</button>
            : <span key={item.id} className="graph-node" data-tone={item.tone} data-type={index === 0 ? 'memory' : item.type.toLowerCase().replaceAll(' ', '-')} style={style}>{content}</span>;
        })}
      </div>
      {selected ? <>
        <label className="graph-record-picker"><span>Stored record</span>
          <select aria-label={`Select ${kind} record`} value={selected.id} onChange={event => { setSelectedId(event.target.value); setInspectedId(''); }}>
            {records.map((record, index) => <option key={record.id} value={record.id}>{index + 1}. {record.text.slice(0, 100)}</option>)}
          </select>
        </label>
        <div className="graph-detail" role="status"><strong>{inspected.type}</strong><span>{inspected.detail}</span></div>
        <ul className="sr-only" aria-label="Stored relationships">{graph.edges.map(edge => <li key={`${edge.from}-${edge.to}`}>{graph.nodes.find(item => item.id === edge.from)?.label} → {edge.relation} → {graph.nodes.find(item => item.id === edge.to)?.label}</li>)}</ul>
        {graph.edges.length === 0 && <p className="graph-note">No linked fields in this record.</p>}
        {graph.omitted > 0 && <p className="graph-note">{graph.omitted} additional linked fields · inspect for all details</p>}
      </> : <p className="graph-empty">Memory structure · no stored records</p>}
      <button className="graph-inspect" type="button" onClick={onInspect}>Inspect {kind} memory <span aria-hidden="true">↗</span></button>
    </section>
  );
}
