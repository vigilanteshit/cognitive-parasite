import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Sidebar } from './Sidebar';

function props() {
  return {
    sessions: [
      { id: 'pressure', title: 'Pressure recovery', updated_at: '2026-10-14T12:00:00Z' },
      { id: 'manual', title: 'Machine manual', updated_at: '2026-10-13T12:00:00Z' },
    ],
    disabled: false,
    open: false,
    mode: 'demo',
    onClose: vi.fn(),
    onSelect: vi.fn(),
    onNew: vi.fn(),
    onDelete: vi.fn(),
  };
}

describe('Sidebar', () => {
  it('filters titles case-insensitively, selects the matching session, and restores chats when cleared', async () => {
    const user = userEvent.setup();
    const callbacks = props();
    render(<Sidebar {...callbacks} />);
    const search = screen.getByRole('searchbox', { name: 'Search conversations' });
    await user.type(search, 'PRESSURE');
    expect(screen.queryByRole('button', { name: /^Machine manual/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Pressure recovery/ }));
    expect(callbacks.onSelect).toHaveBeenCalledWith('pressure');
    expect(callbacks.onClose).toHaveBeenCalledOnce();
    await user.clear(search);
    expect(screen.getByRole('button', { name: /^Machine manual/ })).toBeInTheDocument();
  });

  it('opens Explore and Library only when their actions are available and the workspace is idle', async () => {
    const user = userEvent.setup();
    const callbacks = props();
    const onExplore = vi.fn();
    const onLibrary = vi.fn();
    const { rerender } = render(<Sidebar {...callbacks} />);
    expect(screen.getByRole('button', { name: 'Explore' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Library' })).toBeDisabled();
    rerender(<Sidebar {...callbacks} onExplore={onExplore} onLibrary={onLibrary} />);
    await user.click(screen.getByRole('button', { name: 'Explore' }));
    await user.click(screen.getByRole('button', { name: 'Library' }));
    expect(onExplore).toHaveBeenCalledOnce();
    expect(onLibrary).toHaveBeenCalledOnce();
    expect(callbacks.onClose).toHaveBeenCalledTimes(2);
    rerender(<Sidebar {...callbacks} disabled onExplore={onExplore} onLibrary={onLibrary} />);
    await user.click(screen.getByRole('button', { name: 'Explore' }));
    await user.click(screen.getByRole('button', { name: 'Library' }));
    expect(onExplore).toHaveBeenCalledOnce();
    expect(onLibrary).toHaveBeenCalledOnce();
  });

  it('prevents starting another chat while busy and allows it once idle', async () => {
    const user = userEvent.setup();
    const callbacks = props();
    const { rerender } = render(<Sidebar {...callbacks} disabled />);
    const newChat = screen.getByRole('button', { name: 'New chat' });
    expect(newChat).toBeDisabled();
    await user.click(newChat);
    expect(callbacks.onNew).not.toHaveBeenCalled();
    rerender(<Sidebar {...callbacks} />);
    await user.click(newChat);
    expect(callbacks.onNew).toHaveBeenCalledOnce();
  });
});
