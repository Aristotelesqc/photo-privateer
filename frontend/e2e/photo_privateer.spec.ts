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

    // Pre-computed distinct 16x16 JPEGs with separated dHash values:
    // coastal_sunset.jpg and coastal_sunset_variant.jpg have Hamming distance = 1 (perceptual match <= 10).
    // All other pairs have Hamming distance >= 25.
    const jpegFixtures = {
      mountain: Buffer.from(
        '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAQABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5/r7f8Cf8k88Nf9gq1/8ARS18QV9v+BP+SeeGv+wVa/8AopaAP//Z',
        'base64'
      ),
      multi: Buffer.from(
        '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAQABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5/or7f/4QTwf/ANCpof8A4Lof/iaP+EE8H/8AQqaH/wCC6H/4mgD/2Q==',
        'base64'
      ),
      coastal: Buffer.from(
        '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAQABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwCv/wAT34A+KP8AlvqfgvUZfbcjY/ALMAPZZFHYj5Pe9K1Wx1zS7fU9MuY7mzuE3xSp0YfzBByCDyCCDgijVdKsdc0u40zU7aO5s7hNksT9GH8wQcEEcggEYIrwT/ie/AHxR/y31PwXqMvtuRsfgFmAHssijsR8gB//2Q==',
        'base64'
      ),
      coastal_var: Buffer.from(
        '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAQABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwCv/wAT34A+KP8AlvqfgvUZfbcjY/ALMAPZZFHYj5Pd7G+0vxNocd1ayQX+mX0RAJXckqHIZWU/iCpHHIIqTVdKsdc0u40zU7aO5s7hNksT9GH8wQcEEcggEYIrwT/ie/AHxR/y31PwXqMvtuRsfgFmAHssijsR8gB//9k=',
        'base64'
      ),
      slow: Buffer.from(
        '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAQABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDX+MHxguPDF43hzw43l6smx7q7eMMIAQGCKGBDMQQSSCADgZJ+XH+Fnxt1G/1yPQ/Fk32lr6VY7S8SFVKSNgCNlQAFScYbGQTzkHKnxt+FmqX+sS+LNDinv2uPLS7s403yIVUIroAMsuAMjkg88gnbifCT4Sa1e+JbbXNctbvSrPTLhJo454jHLcSqQygKwyEBxlsc9BzkqAf/2Q==',
        'base64'
      ),
    };

    fs.writeFileSync(path.join(testPhotoDir, 'mountain_landscape.jpg'), jpegFixtures.mountain);
    fs.writeFileSync(path.join(testPhotoDir, 'multi_domain_photo.jpg'), jpegFixtures.multi);
    fs.writeFileSync(path.join(testPhotoDir, 'coastal_sunset.jpg'), jpegFixtures.coastal);
    fs.writeFileSync(path.join(testPhotoDir, 'coastal_sunset_variant.jpg'), jpegFixtures.coastal_var);
    fs.writeFileSync(path.join(testPhotoDir, 'slow_landscape.jpg'), jpegFixtures.slow);
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
    // Wait for the indexing request to finish before opening the library (avoids an indexing race)
    const indexed = page.waitForResponse(
      (resp) => /\/api\/libraries\/\d+\/index$/.test(new URL(resp.url()).pathname) && resp.request().method() === 'POST',
      { timeout: 20000 }
    );
    await page.click('button:has-text("Add & Index")');
    expect((await indexed).ok()).toBeTruthy();

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

  test('Scenario 7: Perceptual grouping candidate review and representation consolidation', async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-testid="nav-library"]').click();
    await selectTestLibrary(page);

    // Verify candidate variants banner is visible
    const reviewBtn = page.locator('[data-testid="btn-review-candidates"]');
    await expect(reviewBtn).toBeVisible({ timeout: 10000 });
    await reviewBtn.click();

    // Verify CandidateGroupModal opens
    const modal = page.locator('div.bg-carbon-900').filter({ hasText: 'Perceptual Source Representations' });
    await expect(modal).toBeVisible({ timeout: 5000 });
    await expect(modal.getByText('coastal_sunset.jpg')).toBeVisible();
    await expect(modal.getByText('coastal_sunset_variant.jpg')).toBeVisible();

    // Select coastal_sunset.jpg as the preferred representation regardless of Candidate A / Candidate B order
    const coastalCandidateCard = modal.locator('[data-testid="candidate-card-coastal_sunset.jpg"]');
    await expect(coastalCandidateCard).toBeVisible();
    await coastalCandidateCard.click();

    // Click "Group as Representations"
    const groupBtn = modal.locator('[data-testid="btn-group-representations"]');
    await expect(groupBtn).toBeVisible();
    await groupBtn.click();

    // Because exactly 1 candidate pair was detected, modal auto-closes upon grouping
    await expect(modal).not.toBeVisible({ timeout: 5000 });

    // Verify Primary badge is visible on coastal_sunset.jpg
    const coastalCard = page.locator('[data-testid="photo-card-coastal_sunset.jpg"]');
    await expect(coastalCard).toBeVisible({ timeout: 5000 });
    await expect(coastalCard.locator('[data-testid="badge-primary"]')).toBeVisible({ timeout: 5000 });

    // Verify Variant badge is visible on coastal_sunset_variant.jpg
    const variantCard = page.locator('[data-testid="photo-card-coastal_sunset_variant.jpg"]');
    await expect(variantCard).toBeVisible({ timeout: 5000 });
    await expect(variantCard.locator('[data-testid="badge-variant"]')).toBeVisible({ timeout: 5000 });
  });

  test('Scenario 8: Permanent library purge removes DB records while preserving original photos on disk', async ({ page }) => {
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

