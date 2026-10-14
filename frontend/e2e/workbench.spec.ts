import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

async function mockWorkbench(page: Page, limited = false) {
  const session = { id: 's1', title: 'Memory research', updated_at: '2026-10-13T12:00:00Z', messages: [] as { role: string; content: string }[], runs: [] };
  let hasSession = false;
  let complete = false;
  const events = (items: unknown[], cursor = 0) => items.map((event, index) => `id: ${cursor + index + 1}\ndata: ${JSON.stringify(event)}\n\n`).join('');
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let body: unknown;
    if (path === '/api/health') body = { status: 'ok', mode: 'demo' };
    else if (path === '/api/models') body = { models: [{ id: 'demo', label: 'Deterministic demo', provider: 'demo', available: true }, { id: 'unavailable', label: 'Cloud model', provider: 'remote', available: false, reason: 'Not configured' }], default: 'demo' };
    else if (path === '/api/sessions' && request.method() === 'POST') { hasSession = true; body = session; }
    else if (path === '/api/sessions') body = { sessions: hasSession ? [session] : [] };
    else if (path === '/api/sessions/s1') body = session;
    else if (path === '/api/sessions/s1/memories') body = { memories: complete ? [{ id: 'm1', kind: 'semantic', text: 'The user studies cognitive memory.', source: 'Conversation' }] : [] };
    else if (path === '/api/documents') body = { id: 'd1', chunks: 2 };
    else if (path === '/api/sessions/s1/runs') { session.messages.push({ role: 'user', content: request.postDataJSON().message }); body = { id: 'r1', status: 'queued' }; }
    else if (path === '/api/runs/r1/resume') body = { id: 'r1', status: 'queued', event_cursor: 5 };
    else if (path === '/api/runs/r1/events') {
      const resumed = new URL(request.url()).searchParams.has('after');
      const answer = 'Semantic memory stores facts. Episodic memory records experience.';
      const finalStatus = limited && !resumed ? 'limited' : 'completed';
      if (finalStatus === 'completed') { complete = true; session.messages.push({ role: 'assistant', content: answer }); }
      const data = events([
        { type: 'status', message: 'Retrieving session context', step: 1, replace_answer: resumed },
        { type: 'sources', sources: [{ id: 'd1', source: 'Study excerpt', kind: 'document', text: 'Cognitive memory separates factual and experiential knowledge.' }] },
        { type: 'budget', steps: 3, max_steps: 6, input_tokens: 180, output_tokens: 70, max_tokens: 2000 },
        { type: 'token', text: finalStatus === 'limited' ? 'Partial response' : answer },
        { type: 'done', status: finalStatus },
      ], resumed ? 5 : 0);
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: data }); return;
    } else { await route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'Unknown test endpoint' } } }); return; }
    await route.fulfill({ json: body });
  });
}
test('real browser source ingestion, streamed answer, memory and execution inspection', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()); });
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockWorkbench(page); await page.goto('/');
  await expect(page.getByText('Every conversation')).toBeVisible();
  await page.screenshot({ path: 'test-results/workbench-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Add source', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Source title' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add source', exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Add source', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('textbox', { name: 'Source title' }).fill('Study excerpt');
  await page.getByRole('textbox', { name: 'Source text' }).fill('Cognitive memory separates factual and experiential knowledge.');
  await page.getByRole('button', { name: 'Add to this session' }).click();
  await expect(page.getByText('Source added. 2 chunks are ready for retrieval.')).toBeVisible();
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Explain semantic and episodic memory');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText('Semantic memory stores facts. Episodic memory records experience.')).toHaveCount(1);
  await expect(page.getByText('Study excerpt', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Memory' }).click();
  await expect(page.getByText('The user studies cognitive memory.')).toBeVisible();
  await page.getByRole('button', { name: 'Episodic', exact: true }).click();
  await expect(page.getByText('No episodic memory yet')).toBeVisible();
  await page.getByRole('tab', { name: 'Execution' }).click();
  await expect(page.getByText('Completed', { exact: true })).toBeVisible();
  await expect(page.getByText('Retrieving session context')).toBeVisible();
  await page.screenshot({ path: 'test-results/workbench-conversation.png', fullPage: true });
  expect(errors).toEqual([]);
});
test('resumes a limited run without replaying its earlier terminal event', async ({ page }) => {
  await mockWorkbench(page, true); await page.goto('/');
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Explore memory');
  await page.getByRole('button', { name: 'Send message' }).click();
  await page.getByRole('button', { name: 'Resume run' }).click();
  await expect(page.getByText('Semantic memory stores facts. Episodic memory records experience.')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Resume run' })).toHaveCount(0);
});
for (const width of [320, 768, 1024, 1440]) {
  test(`responsive workspace at ${width}px has no horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockWorkbench(page); await page.goto('/');
    await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (width < 1100) {
      await page.getByRole('button', { name: 'Open research inspector' }).click();
      await expect(page.getByRole('tab', { name: 'Sources' })).toBeVisible();
      await page.getByRole('button', { name: 'Close inspector' }).click();
    }
    if (width < 768) {
      await page.getByRole('button', { name: 'Open sessions' }).click();
      await expect(page.getByRole('button', { name: 'New session' })).toBeVisible();
      await page.getByRole('button', { name: 'Close sessions', exact: true }).last().click();
    }
    await page.screenshot({ path: `test-results/workbench-${width}.png`, fullPage: true });
  });
}
