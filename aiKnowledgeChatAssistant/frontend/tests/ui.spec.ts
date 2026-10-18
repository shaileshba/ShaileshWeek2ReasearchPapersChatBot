import { test, expect } from '@playwright/test';

test('real library loads with ten papers and clear library state', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /A clearer view/ })).toBeVisible();
  await expect(page.locator('.document')).toHaveCount(10);
  await expect(page.getByText(/10 papers (ready to index|in your knowledge base)/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
  await page.getByRole('textbox', { name: 'Find a paper' }).fill('BERT');
  await expect(page.locator('.document')).toHaveCount(1);
  await page.getByRole('textbox', { name: 'Find a paper' }).fill('');
  await page.getByRole('textbox', { name: 'Find a paper' }).blur();
  await page.screenshot({ path: 'tests/library-desktop.png', fullPage: true });
});

test('chat renders math, copies questions and responses, and opens source evidence', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  const documents = [{ id: 'test-paper', name: 'Test paper.pdf', pages: 1, status: 'active' }];
  await page.route('**/api/documents', r => r.fulfill({ json: { documents, active_version: { id: 'test-version' } } }));
  await page.route('**/api/health', r => r.fulfill({ json: { api_key_configured: true, model: 'gpt-5.4' } }));
  await page.route('**/api/chat/stream', r => r.fulfill({ contentType: 'text/event-stream', body: 'event: progress\ndata: {"message":"Checking source pages"}\n\nevent: result\ndata: '+JSON.stringify({ answerable: true, answer: 'Test fixture equation: $x=42$. [S1]', sources: [{ source_id: 'S1', document_id: 'test-paper', name: 'Test paper.pdf', page: 1, excerpt: 'Test fixture evidence.' }], version: 'test-version', task: 'qa' })+'\n\nevent: done\ndata: {}\n\n' }));
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Ask about your research papers' }).fill('Explain this equation');
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.locator('.assistant .katex')).toBeVisible();
  await page.getByRole('button', { name: 'Copy question', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Copy question', exact: true })).toContainText('Copied');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('Explain this equation');
  await page.getByRole('button', { name: 'Copy response', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Copy response', exact: true })).toContainText('Copied');
  expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, '\n')).toBe('Test fixture equation: $x=42$. [S1]\n\nSources:\n[S1] Test paper.pdf, PDF page 1');

  await page.getByRole('button', { name: /S1 Test paper p. 1/ }).click();
  await expect(page.getByRole('heading', { name: 'Test paper' })).toBeVisible();
  await expect(page.locator('.page-preview img')).toHaveAttribute('src', '/api/documents/test-paper/pages/1.png');
  await page.getByRole('button', { name: 'Close source' }).click();
  await expect(page.locator('.source-panel')).toHaveCount(0);
  await page.getByRole('button', { name: 'New conversation' }).click();
  await expect(page.getByRole('heading', { name: /A clearer view/ })).toBeVisible();
});

test('mobile layout has no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /A clearer view/ })).toBeVisible();
  await expect(page.locator('.document')).toHaveCount(10);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'tests/library-mobile.png', fullPage: true });
});
