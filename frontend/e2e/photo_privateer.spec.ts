import { test, expect } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

test.describe.serial('Photo Privateer End-to-End Test Suite', () => {
  let testPhotoDir: string;
  let testLibraryName: string;

  test.beforeAll(async () => {
    testLibraryName = `E2E Test ${Date.now()}`;
    // Create a temporary fixture folder with mock images (resolving symlinks)
    testPhotoDir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'pp_e2e_photos_')));

    // Create a minimal valid 1x1 JPEG
    const minimalJpeg = Buffer.from([
      0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01,
      0x01, 0x01, 0x00, 0x48, 0x00, 0x48, 0x00, 0x00, 0xff, 0xdb, 0x00, 0x43,
      0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
      0x09, 0x08, 0x0a, 0x0c, 0x14, 0x0d, 0x0c, 0x0b, 0x0b, 0x0c, 0x19, 0x12,
      0x13, 0x0f, 0x14, 0x1d, 0x1a, 0x1f, 0x1e, 0x1d, 0x1a, 0x1c, 0x1c, 0x20,
      0x24, 0x2e, 0x27, 0x20, 0x22, 0x2c, 0x23, 0x1c, 0x1c, 0x28, 0x37, 0x29,
      0x2c, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1f, 0x27, 0x39, 0x3d, 0x38, 0x32,
      0x3c, 0x2e, 0x33, 0x34, 0x32, 0xff, 0xc0, 0x00, 0x0b, 0x08, 0x00, 0x01,
      0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xff, 0xc4, 0x00, 0x1f, 0x00, 0x00,
      0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
      0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
      0x09, 0x0a, 0x0b, 0xff, 0xda, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3f,
      0x00, 0xbf, 0x00, 0xff, 0xd9,
    ]);

    function createUniqueJpeg(tag: string): Buffer {
      const comment = Buffer.from(tag, 'utf-8');
      const comMarker = Buffer.from([
        0xff, 0xfe,
        ((comment.length + 2) >> 8) & 0xff,
        (comment.length + 2) & 0xff,
        ...comment,
      ]);
      return Buffer.concat([
        minimalJpeg.subarray(0, 2),
        comMarker,
        minimalJpeg.subarray(2),
      ]);
    }

    fs.writeFileSync(path.join(testPhotoDir, 'mountain_landscape.jpg'), createUniqueJpeg('mountain_photo'));
    fs.writeFileSync(path.join(testPhotoDir, 'multi_domain_photo.jpg'), createUniqueJpeg('multi_domain_photo'));
    fs.writeFileSync(path.join(testPhotoDir, 'coastal_sunset.jpg'), createUniqueJpeg('coastal_sunset_photo'));
    fs.writeFileSync(path.join(testPhotoDir, 'slow_landscape.jpg'), createUniqueJpeg('slow_cancellation_photo'));
  });


  test.afterAll(async () => {
    try {
      fs.rmSync(testPhotoDir, { recursive: true, force: true });
    } catch {}
  });

  test.beforeEach(async ({ page }) => {
    page.on('dialog', async (dialog) => {
      console.log('[PLAYWRIGHT DIALOG]:', dialog.type(), dialog.message());
      await dialog.accept();
    });
    page.on('console', (msg) => {
      console.log('[BROWSER CONSOLE]:', msg.type(), msg.text());
    });
  });

  const selectTestLibrary = async (page: any) => {
    const option = page.locator('select option', { hasText: testLibraryName });
    await expect(option).toBeAttached({ timeout: 10000 });
    const val = await option.getAttribute('value');
    if (val) {
      await page.locator('select').first().selectOption(val);
    }
  };

  test('Scenario 1: App navigation and Library folder management', async ({ page }) => {
    await page.goto('/');

    // Check App Header branding using exact match
    await expect(page.locator('header').getByText('Photo Privateer', { exact: true })).toBeVisible();

    // Navigate to Settings
    await page.locator('[data-testid="nav-settings"]').click();
    await expect(page.locator('text=Monitored Photograph Folders')).toBeVisible({ timeout: 10000 });

    // Fill folder path and add library
    await page.fill('[data-testid="input-folder-path"]', testPhotoDir);
    await page.fill('[data-testid="input-folder-name"]', testLibraryName);
    await page.click('button:has-text("Add & Index")');

    // Confirm folder is listed in monitored folders
    await expect(
      page.locator('[data-testid="library-item"]').filter({ hasText: testLibraryName })
    ).toBeVisible({ timeout: 10000 });


    // Navigate to Library View
    await page.locator('[data-testid="nav-library"]').click();
    await selectTestLibrary(page);
    await expect(page.locator('text=mountain_landscape.jpg').first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=multi_domain_photo.jpg').first()).toBeVisible();
  });

  test('Scenario 2: Reverse image scan execution with live progress polling', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-testid="nav-library"]').click();
    await selectTestLibrary(page);

    // Verify and select the photo
    const photoTitle = page.locator('p[title="multi_domain_photo.jpg"]').first();
    await expect(photoTitle).toBeVisible({ timeout: 10000 });
    await photoTitle.click();

    // Click "Scan Selected"
    const scanBtn = page.locator('button:has-text("Scan Selected")');
    await expect(scanBtn).toBeEnabled({ timeout: 5000 });
    await scanBtn.click();

    // Verify ScanConfirmModal shows $0.00 mock cost
    await expect(page.locator('text=Confirm Reverse Image Scan')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=$0.00')).toBeVisible();

    // Click Start Scan
    await page.click('button:has-text("Start Scan")');

    // Verify ScanProgressModal opens and displays progress
    await expect(page.locator('text=Scanning Batch...')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Cancel Scan')).toBeVisible();

    // Wait for completion
    await expect(page.locator('text=Batch Completed')).toBeVisible({ timeout: 20000 });

    // Click View Discoveries
    await page.click('button:has-text("View Discoveries")');

    // Modal should close
    await expect(page.locator('text=Batch Completed')).not.toBeVisible();
  });

  test('Scenario 3: Review Queue triage, privacy opt-in, and inspection modal', async ({ page }) => {
    await page.goto('/');

    // Navigate to Review View
    await page.locator('[data-testid="nav-review"]').click();
    await expect(page.locator('text=Needs Review')).toBeVisible({ timeout: 10000 });

    // Look for discovered match cards
    const matchCard = page.locator('div:has-text("Decision")').first();
    // Locate the match card containing remote candidate image preview (FULL match)
    const fullMatchCard = page.locator('div.border', { has: page.locator('text=FULL Match') }).first();
    await expect(fullMatchCard).toBeVisible({ timeout: 10000 });

    const loadPreviewBtn = fullMatchCard.locator('button:has-text("Load preview")');
    await expect(loadPreviewBtn).toBeVisible({ timeout: 5000 });
    await loadPreviewBtn.click();

    // Open Inspect Modal on this match with remote candidate image
    const inspectBtn = fullMatchCard.locator('button:has-text("Inspect")');
    await expect(inspectBtn).toBeVisible({ timeout: 5000 });
    await inspectBtn.click();

    await expect(page.locator('text=Original Photograph')).toBeVisible({ timeout: 5000 });

    // In inspection modal, test privacy opt-in load
    const loadDiscoveredBtn = page.locator('button:has-text("Load Discovered Image")');
    await expect(loadDiscoveredBtn).toBeVisible({ timeout: 5000 });
    await loadDiscoveredBtn.click();

    // Close inspection modal
    await page.locator('button:has-text("Back to Review Queue")').click();

    // Triage first match as APPROVED
    const approveBtn = page.locator('button[title="Approve as legitimate use"]').first();
    await approveBtn.click();
  });

  test('Scenario 4: Settings authentication status and non-destructive library archive', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-testid="nav-settings"]').click();

    // Verify Search Provider & Authentication section
    await expect(page.locator('text=Search Provider & Authentication')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Mock / Demo Provider').first()).toBeVisible();
    await expect(page.getByText('Google Cloud Vision').first()).toBeVisible();

    // Test zero-cost authentication button
    const testAuthBtn = page.locator('button:has-text("Test Authentication")');
    await expect(testAuthBtn).toBeVisible();
    await testAuthBtn.click();

    // Auth result banner should appear
    await expect(
      page.locator('text=Authentication Succeeded').or(page.locator('text=Authentication Failed'))
    ).toBeVisible({ timeout: 10000 });

    // Non-destructive library archiving
    const libCard = page.locator('[data-testid="library-item"]').filter({ hasText: testLibraryName }).first();
    const stopMonitoringBtn = libCard.locator('[data-testid="btn-stop-monitoring"]');
    await expect(stopMonitoringBtn).toBeVisible({ timeout: 5000 });
    await stopMonitoringBtn.click();

    // Should now show archived badge
    await expect(libCard.locator('[data-testid="badge-archived"]')).toBeVisible({ timeout: 10000 });
    const resumeBtn = libCard.locator('[data-testid="btn-resume-monitoring"]');
    await expect(resumeBtn).toBeVisible({ timeout: 5000 });

    // Unarchive to leave library ready for subsequent operations
    await resumeBtn.click();
    await expect(libCard.locator('[data-testid="btn-stop-monitoring"]')).toBeVisible({ timeout: 10000 });
  });

  test('Scenario 5: Cooperative scan cancellation workflow', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-testid="nav-library"]').click();
    await selectTestLibrary(page);

    // Select the slow photo to guarantee deterministic cancellation window
    const photoTitle = page.locator('p[title="slow_landscape.jpg"]').first();
    await expect(photoTitle).toBeVisible({ timeout: 10000 });
    await photoTitle.click();

    const scanBtn = page.locator('button:has-text("Scan Selected")');
    await expect(scanBtn).toBeEnabled({ timeout: 5000 });
    await scanBtn.click();
    await page.click('button:has-text("Start Scan")');

    // Verify ScanProgressModal opens
    await expect(page.locator('text=Scanning Batch...')).toBeVisible({ timeout: 5000 });

    // Click Cancel Scan
    const cancelBtn = page.locator('button:has-text("Cancel Scan")');
    await expect(cancelBtn).toBeVisible({ timeout: 5000 });
    await cancelBtn.click();

    // Verify it enters cancelling / cancelled state
    await expect(
      page.locator('text=Cancelling Scan...').or(page.locator('text=Scan Cancelled'))
    ).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=Scan Cancelled')).toBeVisible({ timeout: 15000 });
  });


  test('Scenario 6: Project batch assignment and filtering', async ({ page }) => {
    await page.goto('/');

    // Navigate to Library
    await page.click('button:has-text("Library")');
    await selectTestLibrary(page);

    // Select a photo
    const photoTitle = page.locator('p[title="mountain_landscape.jpg"]').first();
    await expect(photoTitle).toBeVisible({ timeout: 10000 });
    await photoTitle.click();

    // Click Assign Project
    const assignBtn = page.locator('button:has-text("Assign Project")');
    await expect(assignBtn).toBeVisible();
    await assignBtn.click();

    // Modal opens
    await expect(page.locator('text=Assign Project (1 photo)')).toBeVisible();

    // Type project name
    const projectInput = page.locator('input[placeholder*="Wedding"]');
    await projectInput.fill('Alpine Expedition');

    // Click Apply Project
    await page.click('button:has-text("Apply Project")');

    // Verify badge appears on the photo card
    await expect(page.locator('span[title="Project: Alpine Expedition"]')).toBeVisible({ timeout: 5000 });

    // Filter by project in dropdown
    const projectSelect = page.locator('select').nth(1);
    await projectSelect.selectOption('Alpine Expedition');
    await expect(page.locator('p[title="mountain_landscape.jpg"]')).toBeVisible();

    // Filter by unassigned
    await projectSelect.selectOption('__unassigned__');
    await expect(page.locator('p[title="mountain_landscape.jpg"]')).not.toBeVisible();

    // Reset filter
    await projectSelect.selectOption('');
  });

  test('Scenario 7: Permanent library purge removes DB records while preserving original photos on disk', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-testid="nav-settings"]').click();
    await expect(page.getByText('Monitored Photograph Folders')).toBeVisible({ timeout: 10000 });

    const libCard = page.locator('[data-testid="library-item"]').filter({ hasText: testLibraryName }).first();
    await expect(libCard).toBeVisible({ timeout: 5000 });

    // 1. Archive the library first if not already archived
    const stopMonitoringBtn = libCard.locator('[data-testid="btn-stop-monitoring"]');
    if (await stopMonitoringBtn.isVisible()) {
      await stopMonitoringBtn.click();
      await expect(libCard.locator('[data-testid="badge-archived"]')).toBeVisible({ timeout: 10000 });
    }

    // 2. Permanently remove folder via btn-permanent-remove
    const removeBtn = libCard.locator('[data-testid="btn-permanent-remove"]');
    await expect(removeBtn).toBeVisible({ timeout: 5000 });
    await removeBtn.click();

    // 3. Verify library is gone from UI
    await expect(page.locator('[data-testid="library-item"]').filter({ hasText: testLibraryName })).toHaveCount(0, { timeout: 10000 });

    // 4. Verify original image file remains intact on disk
    const samplePhotoPath = path.join(testPhotoDir, 'mountain_landscape.jpg');
    expect(fs.existsSync(samplePhotoPath)).toBe(true);
  });
});

