import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

test('Active selection, historical browsing, sibling fallback and archival recovery', async ({ page, request }) => {
  // Reuse the existing synthetic JPEG, never a photographer's source file.
  const fixtureSource = fs.readFileSync(path.join(import.meta.dirname, 'photo_privateer.spec.ts'), 'utf8');
  const encoded = fixtureSource.match(/mountain: Buffer\.from\(\s*'([^']+)'/)?.[1];
  if (!encoded) throw new Error('Existing synthetic JPEG fixture missing');
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'pp_eligibility_')));
  const libraries: number[] = [];
  const photos: Record<string, { id: number; library: number; file: string }> = {};
  try {
    for (const name of ['active', 'sibling', 'archived', 'disabled', 'offline']) {
      const dir = path.join(root, name);
      fs.mkdirSync(dir);
      const file = path.join(dir, `${name}.jpg`);
      fs.writeFileSync(file, Buffer.from(encoded, 'base64'));
      const created = await request.post('/api/libraries', { data: { path: dir, name: `Eligibility ${name}` } });
      expect(created.ok()).toBeTruthy();
      const lib = await created.json();
      libraries.push(lib.id);
      expect((await request.post(`/api/libraries/${lib.id}/index`)).ok()).toBeTruthy();
      const listed = await (await request.get(`/api/photos?library_id=${lib.id}`)).json();
      photos[name] = { id: listed.images[0].id, library: lib.id, file };
    }
    const group = await request.post('/api/groups', { data: { image_ids: [photos.active.id, photos.sibling.id, photos.archived.id], preferred_image_id: photos.archived.id } });
    expect(group.ok()).toBeTruthy();
    await request.post(`/api/libraries/${photos.archived.library}/archive`);
    await request.patch(`/api/libraries/${photos.disabled.library}`, { data: { enabled: false } });
    fs.unlinkSync(photos.sibling.file);
    fs.unlinkSync(photos.offline.file);
    await page.goto('/');
    const include = page.getByRole('checkbox', { name: 'Include archived / disabled' });
    await expect(include).not.toBeChecked();
    await expect(page.getByTestId('photo-card-archived.jpg')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Select offline.jpg', exact: true })).toBeDisabled();
    await expect(page.getByTestId('photo-card-sibling.jpg').getByText('Search via group')).toBeVisible();
    await include.check();
    await expect(page.getByTestId('photo-card-archived.jpg').getByText('Archived', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Select archived.jpg', exact: true })).toBeDisabled();
    await expect(page.getByTestId('photo-card-disabled.jpg').getByText('Monitoring disabled')).toBeVisible();
    await page.reload();
    await expect(include).toBeChecked();
    await page.getByRole('button', { name: 'Select active.jpg', exact: true }).click();
    await page.getByRole('button', { name: 'Select all eligible', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Scan Selected (2)', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Scan Selected (2)', exact: true }).click();
    // Server projection collapses the two selectable representations into one call.
    await expect(page.getByRole('button', { name: /Start Scan/ })).toBeVisible();
    await request.post(`/api/libraries/${photos.active.library}/archive`);
    const failure = page.waitForEvent('dialog').then(async (dialog) => {
      expect(dialog.message()).toContain('Settings');
      await dialog.accept();
    });
    await page.getByRole('button', { name: /Start Scan/ }).click();
    await failure;
    await expect(page.getByRole('button', { name: 'Select active.jpg', exact: true })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Select sibling.jpg', exact: true })).toBeDisabled();
    await request.post(`/api/libraries/${photos.active.library}/unarchive`);
    await page.reload();
    await expect(page.getByRole('button', { name: 'Select active.jpg', exact: true })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Select sibling.jpg', exact: true })).toBeEnabled();
    await include.uncheck();
    await expect(page.getByTestId('photo-card-archived.jpg')).toHaveCount(0);
    // Rejected launches created neither sessions nor provider calls for these sources.
    const sessions = await (await request.get('/api/scans/history')).json();
    expect(sessions).toEqual([]);
  } finally {
    try {
      for (const id of libraries) await request.delete(`/api/libraries/${id}`);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  }
});
