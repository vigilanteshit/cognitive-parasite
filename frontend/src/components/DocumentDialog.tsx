import { BookOpen, CircleNotch, X } from '@phosphor-icons/react';
import { useEffect, useRef, useState } from 'react';

interface Props { onClose: () => void; onSubmit: (title: string, text: string) => Promise<{ id: string; chunks: number } | undefined>; onSuccess: (chunks: number) => void }
export function DocumentDialog({ onClose, onSubmit, onSuccess }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleInput = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); titleInput.current?.focus(); }, []);
  const close = () => { dialog.current?.close(); onClose(); };
  return <dialog ref={dialog} className="document-dialog" aria-labelledby="document-title" onCancel={event => { event.preventDefault(); if (!saving) close(); }}>
    <div className="dialog-heading"><BookOpen size={22} /><button className="icon-button" aria-label="Close add source" onClick={close} disabled={saving}><X size={20} /></button></div>
    <h2 id="document-title">Bring your own evidence.</h2><p className="dialog-description">Paste a research excerpt, note, or reference. It will be indexed for retrieval in this session.</p>
    <form onSubmit={async event => { event.preventDefault(); if (!title.trim() || !text.trim() || saving) return; setSaving(true); setError(''); try { const result = await onSubmit(title.trim(), text.trim()); if (result) { onSuccess(result.chunks); close(); } else setError('The source could not be added. Check your connection and try again.'); } catch { setError('The source could not be added. Please try again.'); } finally { setSaving(false); } }}>
      <label htmlFor="source-title">Source title</label><input ref={titleInput} id="source-title" value={title} onChange={event => setTitle(event.target.value)} maxLength={200} required placeholder="e.g. Cognitive memory research notes" disabled={saving} />
      <label htmlFor="source-text">Source text</label><textarea id="source-text" rows={8} value={text} onChange={event => setText(event.target.value)} maxLength={100000} required placeholder="Paste the text you want the system to retrieve…" disabled={saving} />
      <span className="dialog-hint">Plain text · {text.length.toLocaleString()} / 100,000 characters</span>{error && <p className="dialog-error" role="alert">{error}</p>}
      <div className="dialog-actions"><button className="secondary-button" type="button" onClick={close} disabled={saving}>Cancel</button><button className="primary-button" type="submit" disabled={!title.trim() || !text.trim() || saving}>{saving && <CircleNotch className="spinner" size={17} />}{saving ? 'Indexing source…' : 'Add to this session'}</button></div>
    </form>
  </dialog>;
}
