import { readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';
import { fileStems, gameNames, seeded } from '../page/fakes';

const FAKE = seeded('page.spec');
const [GAME] = gameNames(FAKE, 1);
const [STEM, OTHER_STEM] = fileStems(FAKE, 2);

const TARGET = 44;
const ERASE_TITLE = 'This erases the disk in the drive';
const TURNED = 'The disk is turned over';

async function blankImage(request) {
  const answer = await request.post('/api/blank', {
    data: { sides: 2, formatted: true, game_name: GAME },
  });
  expect(answer.ok()).toBe(true);
  const body = await answer.json();
  return { name: `${STEM}.fds`, mimeType: 'application/octet-stream', buffer: Buffer.from(body.data, 'base64') };
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

test('the page loads only from this machine and reports no error', async ({ page, baseURL }) => {
  // Arrange
  const requested = [];
  const errors = [];
  page.on('request', (request) => requested.push(request.url()));
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => (message.type() === 'error' ? errors.push(message.text()) : undefined));

  // Act
  await openCommand(page, 'info');

  // Assert
  expect(requested.length).toBeGreaterThan(0);
  expect(requested.filter((url) => !url.startsWith(baseURL))).toEqual([]);
  expect(errors).toEqual([]);
});

test('every control on the page is at least 44 pixels tall', async ({ page }) => {
  // Arrange
  const expected = [];

  // Act
  await openCommand(page, 'surface');

  // Assert
  expect(await shortControls(page, 'body')).toEqual(expected);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('a result is styled by the result stylesheet', async ({ page }) => {
  // Arrange
  await openCommand(page, 'blank');

  // Act
  await page.locator('#panel .run').click();

  // Assert
  const banner = page.locator('#panel .output .banner').first();
  await expect(banner).toHaveCSS('padding', '10px 14px');
  await expect(page.locator('footer')).toHaveCSS('padding-top', '16px');
});

test('the erase dialog is modal, labelled and starts on a visible cancel', async ({ page, request }) => {
  // Arrange
  await openCommand(page, 'write');
  await page.locator('input[data-field=data]').setInputFiles(await blankImage(request));

  // Act
  await page.locator('#panel button.run').click();

  // Assert
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
  // Arrange
  await openCommand(page, 'write');
  await page.locator('input[data-field=data]').setInputFiles(await blankImage(request));
  await page.locator('#panel button.run').click();

  // Act
  await page.getByRole('dialog', { name: ERASE_TITLE }).getByRole('button', { name: 'Erase and continue' }).click();

  // Assert
  const prompt = page.getByRole('alert');
  await expect(prompt).toContainText('turn the disk over');
  await expect(page.locator('#panel .steps li').first()).toHaveText('reading side 0 before writing it');
  expect(await shortControls(page, '.turn')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  await prompt.getByRole('button', { name: TURNED }).click();
  await expect(page.locator('#panel .output .banner')).toHaveText('the disk reads back as written, on this drive, grade clean');
  await expect(page.getByRole('link', { name: 'Download before.fds' })).toBeVisible();
  expect(await nothingRunning(request)).toBe(true);
});

test('closing the page while a write waits asks first', async ({ page, request }) => {
  // Arrange
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

  // Act
  await expect(page.locator('#panel .output .banner')).toHaveText('The disk operation stopped.');

  // Assert
  expect(await nothingRunning(request)).toBe(true);
});

test('a page opened during a job picks it up instead of starting another', async ({ page, request }) => {
  // Arrange
  const started = await request.post('/api/jobs/dump', { data: { sides: 2 } });

  // Act
  await page.goto('/?e2e#info');

  // Assert
  expect(started.ok()).toBe(true);
  await expect(page.locator('#panel .command-name')).toHaveText('dump');
  const prompt = page.getByRole('alert');
  await expect(prompt).toContainText('turn the disk over');
  await prompt.getByRole('button', { name: TURNED }).click();
  await expect(page.getByRole('link', { name: 'Download dump.fds' })).toBeVisible();
  expect(await nothingRunning(request)).toBe(true);
});

test('a two-sided surface test turns the disk twice and grades clean', async ({ page }) => {
  // Arrange
  await openCommand(page, 'surface');
  await expect(page.locator('#panel button.run')).toHaveCount(1);
  await page.locator('select[data-field=sides]').selectOption('2');
  await page.locator('input[data-field=quick]').check();
  await page.locator('select[data-field=finish]').selectOption('blank');
  await page.locator('#panel button.run').click();

  // Act
  await page.getByRole('button', { name: 'Erase and continue' }).click();

  // Assert
  for (const side of ['B', 'A']) {
    const prompt = page.getByRole('alert').filter({ hasText: `side ${side} label faces up` });
    await expect(prompt).toBeVisible();
    await prompt.getByRole('button', { name: TURNED }).click();
  }
  await expect(page.locator('#panel .output .banner')).toHaveText('grade clean');
  await expect(page.getByRole('link', { name: 'Download before.fds' })).toBeVisible();
});

test('a calibration reports every read and a verdict', async ({ page }) => {
  // Arrange
  await openCommand(page, 'calibrate');
  await page.locator('select[data-field=mode]').selectOption('head');
  await page.locator('input[data-field=passes]').fill('3');
  await page.locator('#panel button.run').click();

  // Act
  await expect(page.locator('#panel .output .banner')).toHaveText(/^reads clean: the whole side reads/);

  // Assert
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('a dump offers its captures, and reads maps them back at phone width', async ({ page }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'dump');
  await page.locator('input[data-field=keep_captures]').check();

  // Act
  await page.locator('#panel button.run').click();

  // Assert
  const bundle = page.getByRole('link', { name: 'Download dump.captures.zip' });
  await expect(page.getByRole('link', { name: 'Download dump.fds' })).toBeVisible();
  await expect(bundle).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  const href = await bundle.getAttribute('href');
  const zip = Buffer.from(href.slice(href.indexOf(',') + 1), 'base64');
  await openCommand(page, 'reads');
  await page.locator('input[data-field=captures]').setInputFiles({
    name: `${OTHER_STEM}.captures.zip`, mimeType: 'application/zip', buffer: zip,
  });
  await page.locator('#panel button.run').click();
  await expect(page.locator('#panel .output')).toContainText('weak');
  await expect(page.locator('#panel .output')).toContainText('unclassed');
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('a dump lands in the logbook, and log shows it for the drive at phone width', async ({ page }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'dump');
  await page.locator('#panel button.run').click();
  await expect(page.getByRole('link', { name: 'Download dump.fds' })).toBeVisible();
  await openCommand(page, 'log');

  // Act
  await page.locator('input[data-field=drive]').fill('drive');
  await page.locator('#panel button.run').click();

  // Assert
  const output = page.locator('#panel .output');
  await expect(output).toContainText('drive drive');
  await expect(output.locator('pre')).toContainText('  dump  ');
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('a session check logs a baseline for the drive at phone width', async ({ page }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'session');

  // Act
  await page.locator('#panel button.run').click();

  // Assert
  const output = page.locator('#panel .output');
  await expect(output).toContainText(/first check of drive drive logged|the drive reads as it did/);
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('a rescue hands back its reads and the image once the side settles at phone width', async ({ page }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'rescue');

  // Act
  await page.locator('#panel button.run').click();

  // Assert
  await expect(page.getByRole('link', { name: 'Download rescue.zip' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download rescue.fds' })).toBeVisible();
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('a track draws a side from captures and names its weak block at phone width', async ({ page }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'track');
  await page.locator('input[data-field=captures]').setInputFiles('tests/fixtures/captures/weak-block.zip');

  // Act
  await page.locator('#panel button.run').click();

  // Assert
  await expect(page.getByRole('img', { name: /Pulse classes along side 0 across 3 read/ })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Weak blocks' })).toHaveText(
    'block 3, file data: 1 pulse(s) differ across 3 read(s), 0 invalid',
  );
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('triage of two disks failing in the same place names the drive at phone width', async ({ page }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'triage');
  const buffer = readFileSync('tests/fixtures/captures/weak-block.zip');
  await page.locator('input[data-field=bundles]').setInputFiles([
    { name: `${STEM}.captures.zip`, mimeType: 'application/zip', buffer },
    { name: `${OTHER_STEM}.captures.zip`, mimeType: 'application/zip', buffer },
  ]);

  // Act
  await page.locator('#panel button.run').click();

  // Assert
  const output = page.locator('#panel .output');
  await expect(output).toContainText('1 position(s) fail on every disk: the drive');
  await expect(output).toContainText('fails on every disk (disk 1, disk 2), so it is the drive');
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('erase asks first, then leaves no block and offers the backup at phone width', async ({ page }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'erase');
  await page.locator('#panel button.run').click();

  // Act
  await page.getByRole('dialog', { name: ERASE_TITLE }).getByRole('button', { name: 'Erase and continue' }).click();

  // Assert
  await expect(page.locator('#panel .output')).toContainText('every side reads back with no block');
  await expect(page.getByRole('link', { name: 'Download before.fds' })).toBeVisible();
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('a kiosk-stamped write with no serial set is refused before anything is written', async ({ page, request }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'write');
  await page.locator('input[data-field=data]').setInputFiles(await blankImage(request));
  await page.locator('input[data-field=as_kiosk]').check();

  // Act
  await page.locator('#panel button.run').click();
  await page.getByRole('dialog', { name: ERASE_TITLE }).getByRole('button', { name: 'Erase and continue' }).click();

  // Assert
  await expect(page.locator('#panel .output')).toContainText('FDSTOOLKIT_KIOSK_SERIAL');
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('duplicate asks for each disk and counts the verified copies at phone width', async ({ page, request }) => {
  // Arrange
  await page.setViewportSize({ width: 320, height: 700 });
  await openCommand(page, 'duplicate');
  await page.locator('input[data-field=data]').setInputFiles(await blankImage(request));
  await page.locator('#panel button.run').click();
  await page.getByRole('dialog', { name: ERASE_TITLE }).getByRole('button', { name: 'Erase and continue' }).click();

  // Act
  await page.getByRole('button', { name: 'The disk is in' }).click();
  await page.getByRole('button', { name: TURNED }).click();

  // Assert
  await expect(page.locator('#panel .output')).toContainText('1 of 1 copies verified');
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test('the calibration disk is written only after the trusted drive is confirmed', async ({ page }) => {
  // Arrange
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
  const prompt = page.getByRole('alert').filter({ hasText: 'side B label faces up' });
  await expect(prompt).toBeVisible();
  await expect(page.locator('#panel .steps li').first()).toContainText('Write this disk only on a drive you already trust');
  await prompt.getByRole('button', { name: TURNED }).click();

  // Act
  await expect(page.locator('#panel .output .banner')).toHaveText('the disk reads back as written, on this drive, grade clean');

  // Assert
  expect(await shortControls(page, '#panel')).toEqual([]);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});
