import { ArrowClockwise, ArrowsOut, Brain, List, SidebarSimple, WarningCircle, X } from '@phosphor-icons/react';
import { useRef, useState } from 'react';
import { Conversation } from './components/Conversation';
import { DocumentDialog } from './components/DocumentDialog';
import { Inspector } from './components/Inspector';
import { MemoryGraph } from './components/MemoryGraph';
import { Sidebar } from './components/Sidebar';
import { isActive } from './types';
import { useWorkbench } from './useWorkbench';
import { useFocusTrap } from './useFocusTrap';

export default function App() {
  const workbench = useWorkbench();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [graphsOpen, setGraphsOpen] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<'sources' | 'memory' | 'execution'>('sources');
  const [memoryKind, setMemoryKind] = useState<'all' | 'semantic' | 'episodic'>('all');
  const [documentOpen, setDocumentOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const rail = useRef<HTMLElement>(null);
  useFocusTrap(graphsOpen, rail, () => setGraphsOpen(false));
  const active = isActive(workbench.execution.run);
  const selectedModel = workbench.models.find(item => item.id === workbench.model);
  const canSend = !!selectedModel?.available;
  const demo = selectedModel ? selectedModel.provider === 'demo' || selectedModel.id === 'demo' : workbench.mode === 'demo';
  const inspect = (tab: typeof inspectorTab, kind: typeof memoryKind = 'all') => {
    setInspectorTab(tab); setMemoryKind(kind); setInspectorOpen(true); setGraphsOpen(false);
  };
  const explore = () => {
    if (window.matchMedia('(max-width: 1099px)').matches) setGraphsOpen(true);
    else rail.current?.querySelector<HTMLButtonElement>('.graph-inspect')?.focus();
  };
  return <div className="workbench">
    <a className="skip-link" href="#message">Skip to message</a>
    <Sidebar sessions={workbench.sessions} selected={workbench.session?.id}
      disabled={workbench.busy || workbench.loading || active} open={sidebarOpen}
      onClose={() => setSidebarOpen(false)}
      onSelect={id => { setNotice(''); void workbench.selectSession(id); }}
      onNew={() => { setNotice(''); void workbench.newSession(); }}
      onDelete={id => void workbench.removeSession(id)}
      onExplore={explore} onLibrary={() => inspect('memory')}
      mode={selectedModel ? demo ? 'demo' : 'live' : workbench.mode} />
    <main className="workspace">
      <header className="workspace-header">
        <button className="mobile-menu icon-button" aria-label="Open sessions" onClick={() => setSidebarOpen(true)}><List size={22} /></button>
        <div className="workspace-title"><span className="eyebrow">Your knowledge co-pilot</span><h1>Hello, curious mind.</h1><p>Let’s turn knowledge into <em>brighter ideas.</em></p></div>
        <div className="header-actions">
          {demo && <span className="demo-badge"><span className="status-dot" /> Demo mode</span>}
          <button className="graph-toggle icon-button" aria-label="Open knowledge graphs" aria-expanded={graphsOpen} onClick={() => setGraphsOpen(!graphsOpen)}><Brain size={21} /></button>
          <button className="inspector-toggle icon-button" aria-label="Open research inspector" aria-expanded={inspectorOpen} onClick={() => inspect('sources')}><SidebarSimple size={21} /></button>
        </div>
      </header>
      {workbench.error && <div className="error-banner" role="alert"><WarningCircle size={19} /><span>{workbench.error}</span>{!workbench.mode && <button onClick={() => void workbench.initialize()}><ArrowClockwise size={15} />Retry connection</button>}<button className="icon-button" onClick={workbench.clearError} aria-label="Dismiss error"><X size={16} /></button></div>}
      {notice && <div className="notice-banner" role="status"><span>{notice}</span><button className="icon-button" aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={16} /></button></div>}
      <Conversation messages={workbench.session?.messages ?? []} execution={workbench.execution}
        loading={workbench.loading} busy={workbench.busy} canSend={canSend} demo={demo}
        onSend={workbench.send} onStop={() => void workbench.cancel()} onResume={() => void workbench.resume()}
        onDocument={() => setDocumentOpen(true)} onReconnect={workbench.reconnect}
        onExplore={explore} onSources={() => inspect('sources')}
        models={workbench.models} model={workbench.model} onModel={workbench.setModel} />
    </main>
    {graphsOpen && <button className="graph-scrim" aria-label="Close knowledge graphs" onClick={() => setGraphsOpen(false)} />}
    <aside ref={rail} className={`knowledge-rail ${graphsOpen ? 'is-open' : ''}`} role={graphsOpen ? 'dialog' : undefined} aria-modal={graphsOpen || undefined} aria-label="Knowledge graphs">
      <div className="rail-heading"><span>Connected knowledge</span><button className="mobile-close icon-button" aria-label="Close knowledge graphs" onClick={() => setGraphsOpen(false)}><X size={20} /></button><button className="rail-inspect icon-button" aria-label="Inspect all memory" onClick={() => inspect('memory')}><ArrowsOut size={17} /></button></div>
      <MemoryGraph kind="semantic" memories={workbench.memories} onInspect={() => inspect('memory', 'semantic')} />
      <MemoryGraph kind="episodic" memories={workbench.memories} onInspect={() => inspect('memory', 'episodic')} />
      <button className="execution-link" onClick={() => inspect('execution')}><span className="status-dot" />{active ? 'Working with your memory' : 'Your memory, connected'}<span>View activity →</span></button>
    </aside>
    {inspectorOpen && <button className="inspector-scrim" aria-label="Close research inspector" onClick={() => setInspectorOpen(false)} />}
    <Inspector key={`${inspectorTab}:${memoryKind}`} execution={workbench.execution} memories={workbench.memories}
      open={inspectorOpen} onClose={() => setInspectorOpen(false)} initialTab={inspectorTab} initialKind={memoryKind} />
    {documentOpen && <DocumentDialog onClose={() => setDocumentOpen(false)} onSubmit={workbench.ingest} onSuccess={chunks => setNotice(`Source added. ${chunks} ${chunks === 1 ? 'chunk is' : 'chunks are'} ready for retrieval.`)} />}
  </div>;
}
