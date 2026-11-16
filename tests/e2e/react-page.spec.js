import { expect, test } from '@playwright/test';

const PREVIEW = 'http://127.0.0.1:8766/static/';
const TITLE = 'Famicom Disk System Toolkit';

test('the React page renders its heading with no page error', async ({ page }) => {
  // Arrange
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => (message.type() === 'error' ? errors.push(message.text()) : undefined));

  // Act
  await page.goto(PREVIEW);

  // Assert
  await expect(page.getByRole('heading', { level: 1, name: TITLE })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});
