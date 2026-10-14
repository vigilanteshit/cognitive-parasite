import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MemoryGraph } from './MemoryGraph';
import type { Memory } from '../types';

describe('MemoryGraph', () => {
  it('clearly labels an empty graph as a structure preview, not stored facts', async () => {
    const inspect = vi.fn();
    render(<MemoryGraph kind="semantic" memories={[]} onInspect={inspect} />);
    expect(screen.getByText('Memory structure · no stored records')).toBeInTheDocument();
    expect(screen.getByText('Document')).toBeInTheDocument();
    expect(screen.getByText('Chunk')).toBeInTheDocument();
    expect(screen.getByText('Keywords')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Document:/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Inspect semantic memory' }));
    expect(inspect).toHaveBeenCalledOnce();
  });

  it('selects stored records and exposes full node details using keyboard controls', async () => {
    const user = userEvent.setup();
    const memories: Memory[] = [
      { id: 'a', kind: 'semantic', text: 'First stored fact', document: 'manual.pdf', keywords: ['pressure'] },
      { id: 'b', kind: 'semantic', text: 'Second stored fact', document: 'guide.pdf', page: 3 },
    ];
    render(<MemoryGraph kind="semantic" memories={memories} onInspect={() => {}} />);
    expect(screen.getByRole('button', { name: 'Document: manual.pdf' })).toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Select semantic record' }), 'b');
    expect(screen.queryByRole('button', { name: 'Document: manual.pdf' })).not.toBeInTheDocument();
    const document = screen.getByRole('button', { name: 'Document: guide.pdf' });
    document.focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('status')).toHaveTextContent('guide.pdf · page 3');
  });

  it('connects state to action and keeps machine metadata out of the graph', () => {
    render(<MemoryGraph kind="episodic" memories={[{
      id: 'e1', kind: 'episodic', text: 'Pressure recovered', category: 'Maintenance',
      state: 'Low pressure', action: 'Replace seal', machine: 'Press 7',
    }]} onInspect={() => {}} />);
    const relations = within(screen.getByRole('list', { name: 'Stored relationships' }));
    expect(relations.getByText('Pressure recovered → IN_CATEGORY → Maintenance')).toBeInTheDocument();
    expect(relations.getByText('Pressure recovered → HAS_STATE → Low pressure')).toBeInTheDocument();
    expect(relations.getByText('Low pressure → RESOLVED_BY → Replace seal')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Machine:/ })).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Machine: Press 7');
  });

  it('does not infer a state or an action relationship from incomplete fields', () => {
    render(<MemoryGraph kind="episodic" memories={[{
      id: 'e1', kind: 'episodic', text: 'Observation only', action: 'Unlinked action', machine: 'Press 7',
    }]} onInspect={() => {}} />);
    expect(screen.queryByRole('button', { name: /Action:|State:/ })).not.toBeInTheDocument();
    expect(screen.getByText('No linked fields in this record.')).toBeInTheDocument();
  });

  it.each(['supersedes', 'superseded_by'] as const)('preserves old-to-new direction using %s', async field => {
    const user = userEvent.setup();
    const old: Memory = { id: 'old', kind: 'episodic', text: 'Old procedure' };
    const latest: Memory = { id: 'new', kind: 'episodic', text: 'New procedure' };
    if (field === 'supersedes') latest.supersedes = 'old';
    else old.superseded_by = 'new';
    render(<MemoryGraph kind="episodic" memories={[old, latest]} onInspect={() => {}} />);
    if (field === 'supersedes') await user.selectOptions(screen.getByRole('combobox'), 'new');
    expect(screen.getByText('Old procedure → SUPERSEDED_BY → New procedure')).toBeInTheDocument();
  });

  it('bounds the graph while keeping every stored record selectable', () => {
    const memories: Memory[] = Array.from({ length: 12 }, (_, index) => ({
      id: `s${index}`, kind: 'semantic', text: `Fact ${index}`,
      keywords: Array.from({ length: 20 }, (_, keyword) => `Keyword ${keyword}`),
    }));
    render(<MemoryGraph kind="semantic" memories={memories} onInspect={() => {}} />);
    expect(screen.getAllByRole('option')).toHaveLength(12);
    expect(screen.getAllByRole('button', { name: /^(Chunk|Keyword):/ }).length).toBeLessThanOrEqual(8);
    expect(screen.getByText(/additional linked fields/)).toBeInTheDocument();
  });
});
