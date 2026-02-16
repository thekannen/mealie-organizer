import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

function parseArgs(argv) {
  const args = {
    baseUrl: "http://127.0.0.1:4920/cookdex",
    username: "qa-admin",
    password: "qa-password-123",
    artifactsDir: "reports/qa/latest",
    expectedMealieUrl: "",
    headless: true,
  };

  for (let index = 2; index < argv.length; index += 1) {
    const item = argv[index];
    const next = argv[index + 1];
    if (item === "--base-url" && next) {
      args.baseUrl = next;
      index += 1;
      continue;
    }
    if (item === "--username" && next) {
      args.username = next;
      index += 1;
      continue;
    }
    if (item === "--password" && next) {
      args.password = next;
      index += 1;
      continue;
    }
    if (item === "--artifacts-dir" && next) {
      args.artifactsDir = next;
      index += 1;
      continue;
    }
    if (item === "--expected-mealie-url" && next) {
      args.expectedMealieUrl = next;
      index += 1;
      continue;
    }
    if (item === "--headed") {
      args.headless = false;
      continue;
    }
  }
  return args;
}

function nowIso() {
  return new Date().toISOString();
}

function sanitizeFilePart(value) {
  return String(value || "")
    .replace(/[^a-z0-9_-]+/gi, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
}

async function ensureDir(dirPath) {
  await fs.mkdir(dirPath, { recursive: true });
}

async function main() {
  const args = parseArgs(process.argv);
  const artifactsDir = path.resolve(args.artifactsDir);
  const screenshotsDir = path.join(artifactsDir, "screenshots");
  await ensureDir(screenshotsDir);

  const report = {
    startedAt: nowIso(),
    finishedAt: "",
    baseUrl: args.baseUrl,
    checks: [],
    failures: [],
    warnings: [],
    consoleErrors: [],
    pageErrors: [],
    requestFailures: [],
  };

  const browser = await chromium.launch({ headless: args.headless });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
  });
  const page = await context.newPage();

  page.on("console", (message) => {
    if (message.type() === "error") {
      const text = message.text();
      // Initial session probe can return 401 before login; treat this as expected.
      if (text.includes("401 (Unauthorized)")) {
        return;
      }
      report.consoleErrors.push(text);
    }
  });
  page.on("pageerror", (error) => {
    report.pageErrors.push(String(error));
  });
  page.on("requestfailed", (request) => {
    report.requestFailures.push({
      url: request.url(),
      method: request.method(),
      error: request.failure()?.errorText || "request_failed",
    });
  });

  async function screenshot(name) {
    const fileName = `${sanitizeFilePart(name)}.png`;
    await page.screenshot({ path: path.join(screenshotsDir, fileName), fullPage: true });
  }

  async function check(name, fn) {
    try {
      await fn();
      report.checks.push({ name, ok: true, detail: "" });
    } catch (error) {
      const detail = String(error?.message || error);
      report.checks.push({ name, ok: false, detail });
      report.failures.push({ name, detail });
      await screenshot(`failure-${name}`);
    }
  }

  async function expectVisible(locator, errorMessage) {
    await locator.first().waitFor({ state: "visible", timeout: 20000 });
    const isVisible = await locator.first().isVisible();
    if (!isVisible) {
      throw new Error(errorMessage);
    }
  }

  async function clickNav(label) {
    const byText = page.locator(".nav-item", { hasText: label }).first();
    if ((await byText.count()) > 0) {
      await byText.click();
      await page.waitForTimeout(350);
      return;
    }
    const byTitle = page.locator(`.nav-item[title="${label}"]`).first();
    if ((await byTitle.count()) > 0) {
      await byTitle.click();
      await page.waitForTimeout(350);
      return;
    }
    throw new Error(`Navigation item '${label}' not found.`);
  }

  async function fillFirstVisible(locator, value) {
    const count = await locator.count();
    for (let index = 0; index < count; index += 1) {
      const item = locator.nth(index);
      if (await item.isVisible()) {
        await item.fill(value);
        return;
      }
    }
    throw new Error("No visible input found for selector.");
  }

  async function runConnectionButton(buttonText, defaultMessage) {
    const button = page.getByRole("button", { name: buttonText }).first();
    await expectVisible(button, `Connection button '${buttonText}' not visible.`);
    await button.click();
    await page.waitForTimeout(1800);
    const detail = button.locator("xpath=following-sibling::p[1]").first();
    await expectVisible(detail, `Connection detail text for '${buttonText}' not visible.`);
    const text = (await detail.innerText()).trim();
    if (!text || text === defaultMessage || text.includes("Running connection test")) {
      throw new Error(`Connection test '${buttonText}' did not return a final status.`);
    }
    if (text.toLowerCase().includes("failed")) {
      report.warnings.push(`${buttonText}: ${text}`);
    }
  }

  await check("open-login-or-setup", async () => {
    await page.goto(args.baseUrl, { waitUntil: "networkidle" });
    await screenshot("initial-page");
  });

  await check("setup-if-required", async () => {
    const setupHeading = page.getByRole("heading", { name: /create admin account/i }).first();
    if (!(await setupHeading.isVisible().catch(() => false))) {
      return;
    }
    await fillFirstVisible(page.locator('label:has-text("Admin Username") input'), args.username);
    await fillFirstVisible(page.locator('label:has-text("Password") input'), args.password);
    await page.getByRole("button", { name: /create admin account/i }).first().click();
    await page.waitForTimeout(1200);
  });

  await check("login", async () => {
    const loginHeading = page.getByRole("heading", { name: /sign in/i }).first();
    if (await loginHeading.isVisible().catch(() => false)) {
      await fillFirstVisible(page.locator('label:has-text("Username") input'), args.username);
      await fillFirstVisible(page.locator('label:has-text("Password") input'), args.password);
      await page.getByRole("button", { name: /sign in/i }).first().click();
    }
    await page.waitForSelector(".sidebar", { timeout: 25000 });
    await screenshot("post-login");
  });

  await check("overview-page", async () => {
    await clickNav("Overview");
    await expectVisible(page.getByRole("heading", { name: /system overview/i }), "Overview header missing.");
    await expectVisible(page.locator(".coverage-grid"), "Coverage visualization not rendered on overview.");
    await screenshot("overview");
  });

  await check("runs-page-and-queue", async () => {
    await clickNav("Runs");
    await expectVisible(page.getByRole("heading", { name: /^runs$/i }), "Runs page header missing.");
    const taskSelect = page.locator('label:has-text("Task") select').first();
    await expectVisible(taskSelect, "Runs task selector missing.");
    const taskOptions = await taskSelect.locator("option").count();
    if (taskOptions > 1) {
      await taskSelect.selectOption({ index: 1 });
    }
    await page.getByRole("button", { name: /queue run/i }).first().click();
    await page.waitForTimeout(1600);
    const errorBanner = page.locator(".banner.error").first();
    if (await errorBanner.isVisible().catch(() => false)) {
      throw new Error(`Run queue failed: ${(await errorBanner.innerText()).trim()}`);
    }
    const viewButtons = page.getByRole("button", { name: /view output/i });
    if ((await viewButtons.count()) > 0) {
      await viewButtons.first().click();
      await page.waitForTimeout(600);
      await expectVisible(page.locator(".log-viewer"), "Run output viewer not rendered.");
    }
    await screenshot("runs");
  });

  await check("schedules-page", async () => {
    await clickNav("Schedules");
    await expectVisible(page.getByRole("heading", { name: /schedules/i }).first(), "Schedules header missing.");
    const scheduleName = `qa-smoke-${Date.now()}`;
    await fillFirstVisible(page.locator('label:has-text("Schedule Name") input'), scheduleName);
    const taskSelect = page.locator('label:has-text("Task") select').first();
    const optionCount = await taskSelect.locator("option").count();
    if (optionCount > 1) {
      await taskSelect.selectOption({ index: 1 });
    }
    await page.getByRole("button", { name: /save schedule/i }).first().click();
    await page.waitForTimeout(1300);
    const errorBanner = page.locator(".banner.error").first();
    if (await errorBanner.isVisible().catch(() => false)) {
      throw new Error(`Schedule save failed: ${(await errorBanner.innerText()).trim()}`);
    }
    const createdRow = page.locator(".schedule-list li", { hasText: scheduleName }).first();
    if (await createdRow.isVisible().catch(() => false)) {
      await createdRow.getByRole("button", { name: /remove/i }).first().click();
      await page.waitForTimeout(700);
    }
    await screenshot("schedules");
  });

  await check("settings-page-and-connection-tests", async () => {
    await clickNav("Settings");
    await expectVisible(page.getByRole("heading", { name: /settings/i }).first(), "Settings header missing.");
    const mealieInput = page.locator('.settings-row:has-text("Mealie Server URL") input').first();
    await expectVisible(mealieInput, "Mealie URL input missing.");
    const mealieValue = (await mealieInput.inputValue()).trim();
    if (!mealieValue) {
      throw new Error("Mealie URL input did not load a value from environment/settings.");
    }
    if (args.expectedMealieUrl && !mealieValue.includes(args.expectedMealieUrl.replace(/\/+$/, ""))) {
      throw new Error("Mealie URL input does not match expected .env value.");
    }
    await runConnectionButton("Test Mealie", "Check Mealie URL/API key connectivity.");
    await runConnectionButton("Test OpenAI API Key", "Validate OpenAI key and selected model.");
    await runConnectionButton("Test Ollama Connection", "Validate Ollama endpoint reachability.");
    await screenshot("settings");
  });

  await check("recipe-organization-page", async () => {
    await clickNav("Recipe Organization");
    await expectVisible(
      page.getByRole("heading", { name: /recipe organization/i }).first(),
      "Recipe Organization header missing."
    );
    const pills = page.locator(".pill-btn");
    const pillCount = await pills.count();
    if (pillCount < 6) {
      throw new Error(`Expected 6 taxonomy pills, found ${pillCount}.`);
    }
    for (let index = 0; index < Math.min(pillCount, 6); index += 1) {
      await pills.nth(index).click();
      await page.waitForTimeout(200);
    }
    await expectVisible(page.getByRole("button", { name: /save file/i }), "Save File button missing.");
    await screenshot("recipe-organization");
  });

  await check("users-page-create-reset-remove", async () => {
    await clickNav("Users");
    await expectVisible(page.getByRole("heading", { name: /users/i }).first(), "Users page header missing.");
    const tempUser = `qa-smoke-${Date.now().toString().slice(-6)}`;
    const tempPassword = "qa-user-pass-01";
    const resetPassword = "qa-user-pass-02";

    await fillFirstVisible(page.locator('label:has-text("Username") input').first(), tempUser);
    await fillFirstVisible(page.locator('label:has-text("Temporary Password") input').first(), tempPassword);
    await page.getByRole("button", { name: /create user/i }).first().click();
    await page.waitForTimeout(1200);

    const row = page.locator("tr", { hasText: tempUser }).first();
    await expectVisible(row, "Created user row was not found.");
    await row.locator('input[placeholder="New password"]').fill(resetPassword);
    await row.getByRole("button", { name: /^reset$/i }).click();
    await page.waitForTimeout(700);
    if ((await row.getByRole("button", { name: /^remove$/i }).count()) > 0) {
      await row.getByRole("button", { name: /^remove$/i }).click();
      await page.waitForTimeout(800);
    }
    await screenshot("users");
  });

  await check("help-page", async () => {
    await clickNav("Help");
    await expectVisible(page.getByRole("heading", { name: /help center/i }).first(), "Help header missing.");
    const faqItems = page.locator(".accordion");
    if ((await faqItems.count()) < 3) {
      throw new Error("Expected setup FAQ accordions are missing.");
    }
    await faqItems.nth(1).locator("summary").click();
    const docs = page.locator(".stacked-cards .accordion");
    if ((await docs.count()) > 0) {
      const firstDoc = docs.first();
      await firstDoc.locator("summary").click();
      await page.waitForTimeout(250);
      const content = (await firstDoc.locator(".doc-preview").first().innerText()).trim();
      if (content.length < 20) {
        throw new Error("Embedded documentation content appears empty.");
      }
    } else {
      report.warnings.push("No embedded markdown docs were visible on Help page.");
    }
    await screenshot("help");
  });

  await check("about-page", async () => {
    await clickNav("About");
    await expectVisible(page.getByRole("heading", { name: /about cookdex/i }).first(), "About page header missing.");
    const links = page.locator("a.link-btn");
    if ((await links.count()) < 2) {
      throw new Error("Expected GitHub and Sponsor links were not found.");
    }
    await screenshot("about");
  });

  if (report.consoleErrors.length > 0) {
    report.warnings.push(`Browser console reported ${report.consoleErrors.length} error message(s).`);
  }
  if (report.pageErrors.length > 0) {
    report.warnings.push(`Page runtime reported ${report.pageErrors.length} uncaught error(s).`);
  }
  if (report.requestFailures.length > 0) {
    report.warnings.push(`Network captured ${report.requestFailures.length} failed request(s).`);
  }

  report.finishedAt = nowIso();
  await fs.writeFile(path.join(artifactsDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");

  await context.close();
  await browser.close();

  if (report.failures.length > 0) {
    throw new Error(`Smoke verification failed with ${report.failures.length} failing check(s).`);
  }

  process.stdout.write(`Smoke verification passed with ${report.checks.length} checks.\n`);
}

main().catch((error) => {
  process.stderr.write(`${String(error?.message || error)}\n`);
  process.exitCode = 1;
});
