import { expect, test } from '@playwright/test';

test('real backend persists learned memory and retrieves an ingested source', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  const createdResponse = page.waitForResponse(response => response.url().endsWith('/api/sessions') && response.request().method() === 'POST');
  await page.getByRole('button', { name: /New chat/ }).click();
  const createdSession = await (await createdResponse).json();
  await page.getByRole('button', { name: 'Add source', exact: true }).click();
  await page.getByRole('textbox', { name: 'Source title' }).fill('Synthetic pump manual');
  await page.getByRole('textbox', { name: 'Source text' }).fill('The training pump needs a pressure inspection every twelve months.');
  await page.getByRole('button', { name: 'Add to this session' }).click();
  await expect(page.getByText('Source added. 1 chunk is ready for retrieval.')).toBeVisible();
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('What pressure inspection does the training pump need?');
  const firstDone = page.waitForResponse(response => new URL(response.url()).pathname === `/api/sessions/${createdSession.id}` && response.request().method() === 'GET');
  await page.getByRole('button', { name: 'Send message' }).click();
  expect((await (await firstDone).json()).runs.at(-1).status).toBe('completed');
  await expect(page.locator('.message.assistant .message-body').last()).toContainText('The training pump needs a pressure inspection every twelve months.');
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('I prefer green tea.');
  const secondDone = page.waitForResponse(response => new URL(response.url()).pathname === `/api/sessions/${createdSession.id}` && response.request().method() === 'GET');
  await page.getByRole('button', { name: 'Send message' }).click();
  expect((await (await secondDone).json()).runs.at(-1).status).toBe('completed');
  await page.getByRole('button', { name: 'Open research inspector' }).click();
  await page.getByRole('tab', { name: /^Memory/ }).click();
  await expect(page.locator('.memory-item p').filter({ hasText: 'I prefer green tea.' })).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: 'test-results/live-workbench-desktop.png', fullPage: true });
  await page.reload();
  await expect(page.getByText('I prefer green tea.', { exact: true }).first()).toBeVisible();
  await page.setViewportSize({ width: 320, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/live-workbench-mobile.png', fullPage: true });
  expect(errors).toEqual([]);
  // Delete only the synthetic session created by this test.
  await request.delete(`/api/sessions/${createdSession.id}`);
});
