import { expect, test } from '@playwright/test';

const TARGET = 44;
const ERASE_TITLE = 'This erases the disk in the drive';
const TURNED = 'The disk is turned over';

async function blankImage(request) {
  const answer = await request.post('/api/blank', {
    data: { sides: 2, formatted: true, game_name: 'E2E' },
  });
  expect(answer.ok()).toBe(true);
  const body = await answer.json();
  return { name: 'game.fds', mimeType: 'application/octet-stream', buffer: Buffer.from(body.data, 'base64') };
}

async function openCommand(page, command) {
  await page.goto(`/?e2e#${command}`);
  await expect(page.locator('#panel .command-name')).toHaveText(command);
}

async function focusRing(page) {
  return page.evaluate(() => {
    const style = getComputedStyle(document.activeElement);
    return {
      text: document.activeElement.textContent,
      outline: Number.parseFloat(style.outlineWidth) * (style.outlineStyle === 'none' ? 0 : 1),
      shadow: style.boxShadow,
    };
  });
}

async function overflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

async function shortControls(page, scope) {
  return page.locator(scope).locator('button, input:not(.offscreen), select, summary, .file-box').evaluateAll(
    (nodes, target) => nodes
      .filter((node) => node.getClientRects().length)
      .map((node) => (node.type === 'checkbox' ? node.closest('label') : node))
      .map((node) => ({ what: node.outerHTML.slice(0, 80), height: node.getBoundingClientRect().height }))
      .filter((entry) => entry.height < target),
    TARGET,
  );
}

async function nothingRunning(request) {
  const answer = await request.get('/api/jobs/current');
  return (await answer.json()).job === null;
}

test.afterEach(async ({ request }) => {
  const { job } = await (await request.get('/api/jobs/current')).json();
  if (job && job.state === 'waiting') {
    await request.post(`/api/jobs/${job.id}/answer`, { data: { yes: false } });
  }
  await expect.poll(() => nothingRunning(request)).toBe(true);
});

test('every control on the page is at least 44 pixels tall', async ({ page }) => {
  await openCommand(page, 'surface');

  expect(await shortControls(page, 'body')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('the erase dialog is modal, labelled and starts on a visible cancel', async ({ page, request }) => {
  await openCommand(page, 'write');
  await page.locator('input[data-field=data]').setInputFiles(await blankImage(request));

  await page.locator('#panel button.run').click();

  const dialog = page.getByRole('dialog', { name: ERASE_TITLE });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate((node) => node.matches(':modal'))).toBe(true);
  const ring = await focusRing(page);
  expect(ring.text).toBe('Cancel');
  expect(ring.outline > 0 || ring.shadow !== 'none').toBe(true);
  expect(await shortControls(page, 'dialog')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);

  await page.keyboard.press('Escape');

  await expect(dialog).toHaveCount(0);
  await expect(page.locator('#panel .output .banner')).toHaveText('Cancelled. Nothing was written.');
  expect(await nothingRunning(request)).toBe(true);
});

test('a two-sided write asks for one turn and offers the backup', async ({ page, request }) => {
  await openCommand(page, 'write');
  await page.locator('input[data-field=data]').setInputFiles(await blankImage(request));
  await page.locator('#panel button.run').click();

  await page.getByRole('dialog', { name: ERASE_TITLE }).getByRole('button', { name: 'Erase and continue' }).click();

  const prompt = page.getByRole('alert');
  await expect(prompt).toContainText('turn the disk over');
  await expect(page.locator('#panel .steps li').first()).toHaveText('reading side 0 before writing it');
  expect(await shortControls(page, '.turn')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);

  await prompt.getByRole('button', { name: TURNED }).click();

  await expect(page.locator('#panel .output .banner')).toHaveText('the disk reads back as written, on this drive');
  await expect(page.getByRole('link', { name: 'Download before.fds' })).toBeVisible();
  expect(await nothingRunning(request)).toBe(true);
});

test('closing the page while a write waits asks first', async ({ page, request }) => {
  await openCommand(page, 'write');
  await page.locator('input[data-field=data]').setInputFiles(await blankImage(request));
  await page.locator('#panel button.run').click();
  await page.getByRole('button', { name: 'Erase and continue' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  let asked = '';
  page.once('dialog', async (dialog) => {
    asked = dialog.type();
    await dialog.dismiss();
  });

  await page.close({ runBeforeUnload: true });
  await expect.poll(() => asked).toBe('beforeunload');

  await page.getByRole('alert').getByRole('button', { name: 'Stop' }).click();
  await expect(page.locator('#panel .output .banner')).toHaveText('The disk operation stopped.');
  expect(await nothingRunning(request)).toBe(true);
});

test('a page opened during a job picks it up instead of starting another', async ({ page, request }) => {
  const started = await request.post('/api/jobs/dump', { data: { sides: 2 } });
  expect(started.ok()).toBe(true);

  await page.goto('/?e2e#info');

  await expect(page.locator('#panel .command-name')).toHaveText('dump');
  const prompt = page.getByRole('alert');
  await expect(prompt).toContainText('turn the disk over');
  await prompt.getByRole('button', { name: TURNED }).click();
  await expect(page.getByRole('link', { name: 'Download dump.fds' })).toBeVisible();
  expect(await nothingRunning(request)).toBe(true);
});

test('a two-sided surface test turns the disk twice and grades clean', async ({ page }) => {
  await openCommand(page, 'surface');
  await expect(page.locator('#panel button.run')).toHaveCount(1);
  await page.locator('select[data-field=sides]').selectOption('2');
  await page.locator('input[data-field=quick]').check();
  await page.locator('select[data-field=finish]').selectOption('blank');
  await page.locator('#panel button.run').click();
  await page.getByRole('button', { name: 'Erase and continue' }).click();

  for (const side of ['B', 'A']) {
    const prompt = page.getByRole('alert').filter({ hasText: `side ${side} faces down` });
    await expect(prompt).toBeVisible();
    await prompt.getByRole('button', { name: TURNED }).click();
  }

  await expect(page.locator('#panel .output .banner')).toHaveText('grade clean');
  await expect(page.getByRole('link', { name: 'Download before.fds' })).toBeVisible();
});

test('a calibration reports every read and a verdict', async ({ page }) => {
  await openCommand(page, 'calibrate');
  await page.locator('select[data-field=mode]').selectOption('head');
  await page.locator('input[data-field=passes]').fill('3');

  await page.locator('#panel button.run').click();

  await expect(page.locator('#panel .output .banner')).toHaveText(/^reads clean: the whole side reads/);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('a dump offers its captures, and reads maps them back at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'dump');
  await page.locator('input[data-field=keep_captures]').check();
  await page.locator('#panel button.run').click();

  const bundle = page.getByRole('link', { name: 'Download dump.captures.zip' });
  await expect(page.getByRole('link', { name: 'Download dump.fds' })).toBeVisible();
  await expect(bundle).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);

  const href = await bundle.getAttribute('href');
  const zip = Buffer.from(href.slice(href.indexOf(',') + 1), 'base64');
  await openCommand(page, 'reads');
  await page.locator('input[data-field=captures]').setInputFiles({
    name: 'dump.captures.zip', mimeType: 'application/zip', buffer: zip,
  });
  await page.locator('#panel button.run').click();

  await expect(page.locator('#panel .output')).toContainText('weak');
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('the calibration disk is written only after the trusted drive is confirmed', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'write');
  await page.locator('input[data-field=calibration]').check();
  await page.locator('#panel button.run').click();
  await page.getByRole('dialog', { name: ERASE_TITLE }).getByRole('button', { name: 'Erase and continue' }).click();

  await expect(page.locator('#panel .output')).toContainText('trusted drive confirmation');
  await expect(page.locator('#panel .output')).toContainText('Clean the read head first');

  await page.locator('input[data-field=trusted_drive]').check();
  await page.locator('#panel button.run').click();
  await page.getByRole('dialog', { name: ERASE_TITLE }).getByRole('button', { name: 'Erase and continue' }).click();

  const prompt = page.getByRole('alert').filter({ hasText: 'side B faces down' });
  await expect(prompt).toBeVisible();
  await expect(page.locator('#panel .steps li').first()).toContainText('Write this disk only on a drive you already trust');
  await prompt.getByRole('button', { name: TURNED }).click();

  await expect(page.locator('#panel .output .banner')).toHaveText('the disk reads back as written, on this drive');
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});
