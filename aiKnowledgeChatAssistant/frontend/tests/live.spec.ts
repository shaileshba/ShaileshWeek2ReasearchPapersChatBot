import { test, expect } from '@playwright/test';

test('live grounded chat streams and opens the actual cited PDF', async ({ page }) => {
  test.skip(process.env.RUN_LIVE_UI !== '1', 'Requires a funded API key and an active knowledge base.');
  test.setTimeout(240000);
  await page.setViewportSize({ width: 1500, height: 1000 });
  await page.goto('/');
  await expect(page.locator('.document')).toHaveCount(10);
  await page.locator('.document').filter({ hasText: /^\d+BERT/ }).click();
  await page.getByRole('textbox', { name: 'Ask about your research papers' }).fill('What fraction of WordPiece tokens does BERT select for masked language modeling? Give a concise answer.');
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.locator('.assistant')).toBeVisible({ timeout: 180000 });
  await expect(page.locator('.assistant')).toContainText('15');
  await expect(page.locator('.assistant .citations button').first()).toBeVisible();
  const pdfResponse = page.waitForResponse(r => r.url().includes('/pages/') && r.status() === 200);
  await page.locator('.assistant .citations button').first().click();
  await pdfResponse;
  await expect(page.locator('.source-panel img')).toBeVisible();
  await expect(page.locator('.source-panel img')).toHaveJSProperty('complete', true);
  await page.screenshot({ path: 'tests/live-answer.png', fullPage: true });
});
