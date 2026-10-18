import { test, expect } from '@playwright/test';

const summary = { requests: 3, completed: 2, failed: 1, interrupted: 0, running: 0, avg_ttft_ms: 1500, max_ttft_ms: 2000, avg_total_ms: 8500, max_total_ms: 10000 };
const question = { ...summary, question_key: 'what is attention?', question: 'What is attention?', last_asked: '2026-10-18T12:00:00Z' };
const requests = [
  { id: 'completed-example', question: 'What is attention?', created: '2026-10-18T12:00:00Z', model: 'test-model', transport: 'sse', status: 'completed', answerable: 1, ttft_ms: 1000, total_ms: 7000, error: null },
  { id: 'failed-example', question: 'What is attention?', created: '2026-10-18T11:00:00Z', model: 'test-model', transport: 'sse', status: 'failed', answerable: null, ttft_ms: null, total_ms: 500, error: 'OpenAI rate limit reached. Wait briefly and retry.' },
];
function report(rows: unknown[], view = 'questions', empty = false) {
  return { summary: empty ? { ...summary, requests: 0, completed: 0, failed: 0, avg_ttft_ms: null, max_ttft_ms: null, avg_total_ms: null, max_total_ms: null } : summary, rows, total: rows.length, view, limit: 25, offset: 0, recording_since: empty ? null : '2026-10-18T11:00:00Z', generated_at: '2026-10-18T12:01:00Z', timing_definition: 'Server timings. Progress updates do not count as tokens. Only completed requests contribute to averages and maximums.' };
}
test.beforeEach(async ({ page }) => {
  page.on('pageerror', error => console.error('BROWSER ERROR:', error.message));
  await page.route('**/api/documents', route => route.fulfill({ json: { documents: [{ id: 'test-paper', name: 'Test.pdf', pages: 1, status: 'active' }], active_version: { id: 'test-version' } } }));
  await page.route('**/api/health', route => route.fulfill({ json: { api_key_configured: true, model: 'test-model' } }));
});

test('admin displays aggregates, request history, search and mobile layout', async ({ page }) => {
  await page.route('**/api/admin/metrics?**', route => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get('q')) return route.fulfill({ json: report([], params.get('view') || 'questions', true) });
    return route.fulfill({ json: report(params.get('view') === 'requests' ? requests : [question], params.get('view') || 'questions') });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: 'Response performance' })).toBeVisible();
  await expect(page.locator('.admin-stat').filter({ hasText: 'Average first answer' })).toContainText('1.50 s');
  await expect(page.locator('.admin-stat').filter({ hasText: 'Maximum first answer' })).toContainText('2.00 s');
  await expect(page.locator('.admin-stat').filter({ hasText: 'Average total response' })).toContainText('8.50 s');
  await expect(page.getByRole('cell', { name: 'What is attention?', exact: true })).toBeVisible();
  await page.screenshot({ path: 'tests/admin-desktop.png', fullPage: true });
  await page.getByRole('tab', { name: 'Request history' }).click();
  await expect(page.locator('.admin-table tbody tr')).toHaveCount(2);
  await expect(page.getByText('OpenAI rate limit reached. Wait briefly and retry.')).toBeVisible();
  await expect(page.locator('.admin-table tbody tr').filter({ hasText: 'failed' })).toContainText('\u2014');
  await page.getByRole('textbox', { name: 'Search recorded questions' }).fill('missing');
  await expect(page.getByText('No matching questions')).toBeVisible();
  await page.getByRole('textbox', { name: 'Search recorded questions' }).fill('');
  await expect(page.locator('.admin-table tbody tr')).toHaveCount(2);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'tests/admin-mobile.png', fullPage: true });
});

test('admin navigation preserves the current conversation and browser back works', async ({ page }) => {
  await page.route('**/api/admin/metrics?**', route => route.fulfill({ json: report([], 'questions', true) }));
  await page.route('**/api/chat/stream', route => route.fulfill({ contentType: 'text/event-stream', body: 'event: result\ndata: '+JSON.stringify({ answer: 'A preserved response.', answerable: false, sources: [], version: 'test-version', task: 'qa' })+'\n\nevent: done\ndata: {}\n\n' }));
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Ask about your research papers' }).fill('Keep this question');
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.locator('.assistant')).toContainText('A preserved response.');
  await page.getByRole('button', { name: 'Admin performance' }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByText('No recorded questions yet')).toBeVisible();
  await page.getByRole('button', { name: 'Back to chat' }).click();
  await expect(page.locator('.assistant')).toContainText('A preserved response.');
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Response performance' })).toBeVisible();
});

test('admin handles backend errors and retries', async ({ page }) => {
  let fail = true;
  await page.route('**/api/admin/metrics?**', route => fail ? route.fulfill({ status: 503, json: { detail: 'Metrics unavailable temporarily.' } }) : route.fulfill({ json: report([], 'questions', true) }));
  await page.goto('/admin');
  await expect(page.getByRole('alert')).toContainText('Metrics unavailable temporarily.');
  fail = false;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByText('No recorded questions yet')).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});
