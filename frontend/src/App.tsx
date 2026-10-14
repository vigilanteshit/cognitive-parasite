import { ArrowClockwise, Flask, List, SidebarSimple, WarningCircle, X } from '@phosphor-icons/react';
import { useState } from 'react';
import { Conversation } from './components/Conversation';
import { DocumentDialog } from './components/DocumentDialog';
import { Inspector } from './components/Inspector';
import { Sidebar } from './components/Sidebar';
import { isActive } from './types';
import { useWorkbench } from './useWorkbench';

export default function App() {
  const workbench = useWorkbench();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [documentOpen, setDocumentOpen] = useState(false);
  const [notice, setNotice] = useState('');
  const active = isActive(workbench.execution.run);
  const selectedModel = workbench.models.find(item => item.id === workbench.model);
  const canSend = !!selectedModel?.available;
  const demo = selectedModel ? selectedModel.provider === 'demo' || selectedModel.id === 'demo' : workbench.mode === 'demo';
  return <div className="workbench">
    <a className="skip-link" href="#message">Skip to message</a>
    <Sidebar sessions={workbench.sessions} selected={workbench.session?.id} disabled={workbench.busy || workbench.loading || active} open={sidebarOpen} onClose={() => setSidebarOpen(false)} onSelect={id => { setNotice(''); void workbench.selectSession(id); }} onNew={() => { setNotice(''); void workbench.newSession(); }} onDelete={id => void workbench.removeSession(id)} mode={selectedModel ? demo ? 'demo' : 'live' : workbench.mode} />
    <main className="workspace">
      <header className="workspace-header"><button className="mobile-menu icon-button" aria-label="Open sessions" onClick={() => setSidebarOpen(true)}><List size={22} /></button><div className="workspace-title"><span className="eyebrow"><Flask size={13} /> RESEARCH WORKSPACE</span><h1>{workbench.session?.title || 'New conversation'}</h1></div><div className="header-actions">{demo && <span className="demo-badge"><span className="status-dot" /> Demo mode</span>}<label className="model-control"><span className="sr-only">Model profile</span><select aria-label="Model profile" value={workbench.model} onChange={event => workbench.setModel(event.target.value)} disabled={active || workbench.busy || workbench.loading || !workbench.models.length}>{!workbench.models.length && <option value="">Connecting…</option>}{workbench.models.map(model => <option key={model.id} value={model.id} disabled={!model.available}>{model.label}{!model.available ? ' (unavailable)' : ''}</option>)}</select></label><button className="inspector-toggle icon-button" aria-label="Open research inspector" aria-expanded={inspectorOpen} onClick={() => setInspectorOpen(!inspectorOpen)}><SidebarSimple size={21} /></button></div></header>
      {workbench.error && <div className="error-banner" role="alert"><WarningCircle size={19} /><span>{workbench.error}</span>{!workbench.mode && <button onClick={() => void workbench.initialize()}><ArrowClockwise size={15} />Retry connection</button>}<button className="icon-button" onClick={workbench.clearError} aria-label="Dismiss error"><X size={16} /></button></div>}
      {notice && <div className="notice-banner" role="status"><span>{notice}</span><button className="icon-button" aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={16} /></button></div>}
      <Conversation messages={workbench.session?.messages ?? []} execution={workbench.execution} loading={workbench.loading} busy={workbench.busy} canSend={canSend} demo={demo} onSend={workbench.send} onStop={() => void workbench.cancel()} onResume={() => void workbench.resume()} onDocument={() => setDocumentOpen(true)} onReconnect={workbench.reconnect} />
    </main>
    <Inspector execution={workbench.execution} memories={workbench.memories} open={inspectorOpen} onClose={() => setInspectorOpen(false)} />
    {documentOpen && <DocumentDialog onClose={() => setDocumentOpen(false)} onSubmit={workbench.ingest} onSuccess={chunks => setNotice(`Source added. ${chunks} ${chunks === 1 ? 'chunk is' : 'chunks are'} ready for retrieval.`)} />}
  </div>;
}
