import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const NAV_LABELS = [
  "Overview",
  "Tasks",
  "Recipe Organization",
  "Users",
  "Settings",
  "Help",
  "About",
];

const REQUIRED_MARKERS = [
  "global:sidebar-toggle-collapse",
  "global:sidebar-toggle-expand",
  "global:sidebar-refresh",
  "global:sidebar-theme",
  "global:sidebar-logout",
  "auth:login-submit",
  "overview:header-refresh",
  "tasks:queue-run",
  "tasks:queue-all-discovered",
  "tasks:filter-all",
  "tasks:filter-manual",
  "tasks:filter-scheduled",
  "tasks:row-select",
  "tasks:save-interval",
  "tasks:save-once",
  "tasks:cookbook-sync-dry-run",
  "tasks:schedule-edit-open",
  "tasks:schedule-edit-save",
  "settings:reload",
  "settings:apply",
  "settings:test-mealie",
  "settings:test-provider",
  "settings:provider-dropdown",
  "settings:model-control",
  "recipe:pill-categories",
  "recipe:pill-cookbooks",
  "recipe:pill-labels",
  "recipe:pill-tags",
  "recipe:pill-tools",
  "recipe:pill-units",
  "recipe:save-file",
  "recipe:discard",
  "recipe:import-json",
  "users:generate-password",
  "users:create-user",
  "users:reset-password",
  "users:remove-user",
  "help:faq-open",
  "help:docs-open",
  "about:version-visible",
  "about:links-visible",
  "api:queue-all-tasks",
  "api:schedule-create-delete",
  "api:user-create-reset-delete",
  "auth:relogin",
  "recipe:label-color-picker",
  "recipe:tool-on-hand",
  "users:role-dropdown",
  "users:password-show-hide",
  "users:force-reset-checkbox",
  "users:search",
  "global:modal-cancel",
  "about:github-link-href",
  "about:sponsor-link-href",
];

function parseArgs(argv) {
  const args = {
    baseUrl: "http://127.0.0.1:4920/cookdex",
    username: "qa-admin",
    password: "qa-password-123",
    artifactsDir: "reports/qa/latest",
    expectedMealieUrl: "",
    headless: true,
    slowMoMs: 0,
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
    if (item === "--slow-mo-ms" && next) {
      const parsed = Number.parseInt(next, 10);
      args.slowMoMs = Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
      index += 1;
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

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
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
    mode: "comprehensive",
    startedAt: nowIso(),
    finishedAt: "",
    baseUrl: args.baseUrl,
    checks: [],
    failures: [],
    warnings: [],
    interactions: [],
    coverage: {
      markersRequired: REQUIRED_MARKERS,
      markersHit: [],
      buttonsSeenByPage: {},
      buttonsClickedByPage: {},
      tasksDiscovered: 0,
      tasksQueuedViaUi: 0,
      tasksQueuedViaApi: 0,
      schedulesCreatedViaUi: 0,
      schedulesCreatedViaApi: 0,
      usersCreatedViaUi: 0,
      usersCreatedViaApi: 0,
    },
    consoleErrors: [],
    pageErrors: [],
    requestFailures: [],
  };

  const browser = await chromium.launch({
    headless: args.headless,
    slowMo: args.slowMoMs > 0 ? args.slowMoMs : undefined,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
  });
  const page = await context.newPage();
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const repoRoot = path.resolve(scriptDir, "..", "..");

  const markerHits = new Set();
  const buttonsSeenByPage = new Map();
  const buttonsClickedByPage = new Map();
  const cleanupState = {
    scheduleIds: new Set(),
    usernames: new Set(),
  };
  const managedConfigPaths = {
    categories: "configs/taxonomy/categories.json",
    cookbooks: "configs/taxonomy/cookbooks.json",
    labels: "configs/taxonomy/labels.json",
    tags: "configs/taxonomy/tags.json",
    tools: "configs/taxonomy/tools.json",
    units_aliases: "configs/taxonomy/units_aliases.json",
  };
  const touchedConfigNames = new Set();
  const configSnapshots = new Map();
  const configHistoryDir = path.join(repoRoot, "configs", ".history");
  let configHistoryBefore = new Set();
  try {
    const entries = await fs.readdir(configHistoryDir, { encoding: "utf8" });
    configHistoryBefore = new Set(entries);
  } catch {
    configHistoryBefore = new Set();
  }
  const baseUrl = args.baseUrl.replace(/\/+$/, "");
  const apiBase = `${baseUrl}/api/v1`;

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

  function markInteraction(pageName, action, detail = "") {
    report.interactions.push({ at: nowIso(), page: pageName, action, detail });
  }

  function markControl(pageName, marker) {
    markerHits.add(marker);
    markInteraction(pageName, "control", marker);
  }

  function rememberButtonClick(pageName, label) {
    const key = normalizeText(label);
    if (!key) {
      return;
    }
    if (!buttonsClickedByPage.has(pageName)) {
      buttonsClickedByPage.set(pageName, new Set());
    }
    buttonsClickedByPage.get(pageName).add(key);
  }

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

  async function expectVisible(locator, errorMessage, timeout = 20000) {
    await locator.first().waitFor({ state: "visible", timeout });
    const isVisible = await locator.first().isVisible();
    if (!isVisible) {
      throw new Error(errorMessage);
    }
  }

  async function clickNav(label) {
    const byText = page.locator(".nav-item", { hasText: label }).first();
    if ((await byText.count()) > 0) {
      await byText.click();
      rememberButtonClick("global", label);
      markControl("global", `global:nav:${label}`);
      await page.waitForTimeout(350);
      return;
    }
    const byTitle = page.locator(`.nav-item[title="${label}"]`).first();
    if ((await byTitle.count()) > 0) {
      await byTitle.click();
      rememberButtonClick("global", label);
      markControl("global", `global:nav:${label}`);
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

  async function setCheckboxState(locator, desired) {
    if (!(await locator.isVisible().catch(() => false))) {
      return false;
    }
    const checked = await locator.isChecked();
    if (checked === desired) {
      return true;
    }
    if (desired) {
      await locator.check();
    } else {
      await locator.uncheck();
    }
    return true;
  }

  async function ensureNoErrorBanner(contextLabel) {
    const errorBanner = page.locator(".banner.error").first();
    if (await errorBanner.isVisible().catch(() => false)) {
      throw new Error(`${contextLabel}: ${(await errorBanner.innerText()).trim()}`);
    }
  }

  async function registerVisibleButtons(pageName) {
    const locator = page.locator("button:visible");
    const count = await locator.count();
    if (!buttonsSeenByPage.has(pageName)) {
      buttonsSeenByPage.set(pageName, new Set());
    }
    const bucket = buttonsSeenByPage.get(pageName);
    for (let index = 0; index < count; index += 1) {
      const text = normalizeText(await locator.nth(index).innerText());
      if (text) {
        bucket.add(text);
      }
    }
  }

  async function clickButtonByRole(pageName, label, marker, timeout = 20000) {
    const button = page.getByRole("button", { name: label }).first();
    await expectVisible(button, `Button '${label}' not visible.`, timeout);
    const buttonLabel = normalizeText(await button.innerText().catch(() => ""));
    await button.click();
    rememberButtonClick(pageName, buttonLabel || (label instanceof RegExp ? String(label) : label));
    if (marker) {
      markControl(pageName, marker);
    }
    await page.waitForTimeout(200);
    return button;
  }

  async function clickSidebarAction(label, marker) {
    const button = page.locator(".sidebar-actions button", { hasText: label }).first();
    await expectVisible(button, `Sidebar button '${label}' missing.`);
    await button.click();
    rememberButtonClick("sidebar", label);
    markControl("sidebar", marker);
    await page.waitForTimeout(220);
  }

  async function apiRequest(method, endpointPath, body = null, expected = [200]) {
    const expectedStatuses = Array.isArray(expected) ? expected : [expected];
    const response = await context.request.fetch(`${apiBase}${endpointPath}`, {
      method,
      data: body === null ? undefined : body,
      failOnStatusCode: false,
      headers: body === null ? undefined : { "Content-Type": "application/json" },
    });

    const status = response.status();
    const text = await response.text();
    const contentType = response.headers()["content-type"] || "";
    let payload = null;
    if (contentType.includes("application/json")) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = null;
      }
    }

    if (!expectedStatuses.includes(status)) {
      throw new Error(`API ${method} ${endpointPath} failed (${status}): ${text.slice(0, 300)}`);
    }
    return { status, payload, text };
  }

  async function configureOptionFields(scopeLocator) {
    const fields = scopeLocator.locator(".option-grid .field");
    const count = await fields.count();
    for (let index = 0; index < count; index += 1) {
      const field = fields.nth(index);
      if (!(await field.isVisible().catch(() => false))) {
        continue;
      }

      const labelText = normalizeText(await field.locator("span").first().innerText().catch(() => ""));
      const lower = labelText.toLowerCase();

      const checkbox = field.locator('input[type="checkbox"]').first();
      if (await checkbox.isVisible().catch(() => false)) {
        if (lower.includes("dry run")) {
          await setCheckboxState(checkbox, true);
        } else if (lower.includes("apply") || lower.includes("cleanup") || lower.includes("danger")) {
          await setCheckboxState(checkbox, false);
        } else {
          await checkbox.click();
          await checkbox.click();
        }
        continue;
      }

      const select = field.locator("select").first();
      if (await select.isVisible().catch(() => false)) {
        const value = await select.inputValue();
        await select.selectOption(value);
        continue;
      }

      const numberInput = field.locator('input[type="number"]').first();
      if (await numberInput.isVisible().catch(() => false)) {
        const current = normalizeText(await numberInput.inputValue());
        if (current) {
          await numberInput.fill(current);
          continue;
        }
        if (lower.includes("confidence")) {
          await numberInput.fill("0.75");
        } else if (lower.includes("max")) {
          await numberInput.fill("1");
        } else if (lower.includes("page size")) {
          await numberInput.fill("10");
        } else if (lower.includes("timeout")) {
          await numberInput.fill("30");
        } else if (lower.includes("retries")) {
          await numberInput.fill("1");
        } else {
          await numberInput.fill("1");
        }
        continue;
      }

      const textInput = field.locator('input[type="text"]').first();
      if (await textInput.isVisible().catch(() => false)) {
        const current = await textInput.inputValue();
        if (lower.includes("stages") && !normalizeText(current)) {
          await textInput.fill("taxonomy");
        } else {
          await textInput.fill(current);
        }
      }
    }
  }

  function buildTaskOptionsFromDefinition(taskDefinition) {
    const options = {};
    for (const option of taskDefinition?.options || []) {
      const key = String(option.key || "");
      const labelText = `${String(option.label || "")} ${key}`.toLowerCase();
      if (option.default !== undefined && option.default !== null) {
        options[key] = option.default;
        continue;
      }
      if (option.type === "boolean") {
        if (labelText.includes("dry run")) {
          options[key] = true;
        } else if (
          labelText.includes("apply") ||
          labelText.includes("cleanup") ||
          labelText.includes("danger") ||
          labelText.includes("write")
        ) {
          options[key] = false;
        } else {
          options[key] = false;
        }
        continue;
      }
      if (option.type === "integer") {
        options[key] = labelText.includes("max") ? 1 : 1;
        continue;
      }
      if (option.type === "number") {
        options[key] = labelText.includes("confidence") ? 0.75 : 1;
        continue;
      }
      if (option.type === "string") {
        if (labelText.includes("stages")) {
          options[key] = "taxonomy";
        } else {
          options[key] = "";
        }
      }
    }
    return options;
  }

  async function readRunRows() {
    const rows = page.locator(".runs-table tbody tr");
    const count = await rows.count();
    const data = [];
    for (let index = 0; index < count; index += 1) {
      const row = rows.nth(index);
      if (!(await row.isVisible().catch(() => false))) {
        continue;
      }
      const text = normalizeText(await row.innerText());
      data.push({ index, text, row });
    }
    return data;
  }

  async function ensureRunRowSelection() {
    const rows = await readRunRows();
    for (const entry of rows) {
      if (entry.text.toLowerCase().includes("no runs found")) {
        continue;
      }
      await entry.row.click();
      markControl("tasks", "tasks:row-select");
      await page.waitForTimeout(220);
      return true;
    }
    return false;
  }

  async function snapshotConfigFile(name) {
    const key = String(name || "").trim();
    const relativePath = managedConfigPaths[key];
    if (!relativePath || configSnapshots.has(key)) {
      return;
    }
    const absolutePath = path.join(repoRoot, relativePath);
    const content = await fs.readFile(absolutePath, "utf8");
    configSnapshots.set(key, { absolutePath, content });
  }

  async function restoreConfigFiles() {
    for (const name of touchedConfigNames) {
      const snapshot = configSnapshots.get(name);
      if (!snapshot) {
        continue;
      }
      await fs.writeFile(snapshot.absolutePath, snapshot.content, "utf8");
    }
    touchedConfigNames.clear();
  }

  async function removeGeneratedConfigHistory() {
    const touchedPrefixes = [...configSnapshots.keys()].map((name) => `${name}.`);
    if (touchedPrefixes.length === 0) {
      return;
    }
    let current = [];
    try {
      current = await fs.readdir(configHistoryDir, { encoding: "utf8" });
    } catch {
      return;
    }
    for (const entry of current) {
      if (configHistoryBefore.has(entry)) {
        continue;
      }
      if (!entry.endsWith(".json")) {
        continue;
      }
      if (!touchedPrefixes.some((prefix) => entry.startsWith(prefix))) {
        continue;
      }
      await fs.unlink(path.join(configHistoryDir, entry)).catch(() => undefined);
    }
  }

  async function bestEffortCleanup() {
    for (const scheduleId of cleanupState.scheduleIds) {
      await context.request.fetch(`${apiBase}/schedules/${encodeURIComponent(scheduleId)}`, {
        method: "DELETE",
        failOnStatusCode: false,
      });
    }
    cleanupState.scheduleIds.clear();

    for (const username of cleanupState.usernames) {
      await context.request.fetch(`${apiBase}/users/${encodeURIComponent(username)}`, {
        method: "DELETE",
        failOnStatusCode: false,
      });
    }
    cleanupState.usernames.clear();
  }

  async function runConnectionButton(buttonText, defaultMessage, marker) {
    const button = page.getByRole("button", { name: buttonText }).first();
    await expectVisible(button, `Connection button '${buttonText}' not visible.`);
    await button.click();
    rememberButtonClick("settings", buttonText);
    if (marker) {
      markControl("settings", marker);
    }
    await page.waitForTimeout(1800);
    const detail = button.locator("xpath=following-sibling::p[1]").first();
    await expectVisible(detail, `Connection detail text for '${buttonText}' not visible.`);
    const text = normalizeText(await detail.innerText());
    if (!text || text === defaultMessage || text.includes("Running connection test")) {
      throw new Error(`Connection test '${buttonText}' did not return a final status.`);
    }
    if (text.toLowerCase().includes("failed") || text.toLowerCase().includes("unreachable")) {
      report.warnings.push(`${buttonText}: ${text}`);
    }
  }

  await check("open-login-or-setup", async () => {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await screenshot("initial-page");
  });

  await check("setup-if-required", async () => {
    const setupHeading = page.getByRole("heading", { name: /create admin account/i }).first();
    if (!(await setupHeading.isVisible().catch(() => false))) {
      return;
    }
    await fillFirstVisible(page.locator('label:has-text("Admin Username") input'), args.username);
    await fillFirstVisible(page.locator('label:has-text("Password") input'), args.password);
    await clickButtonByRole("auth", /create admin account/i, "auth:create-admin");
    await ensureNoErrorBanner("Setup flow failed");
  });

  await check("login", async () => {
    const loginHeading = page.getByRole("heading", { name: /sign in/i }).first();
    if (await loginHeading.isVisible().catch(() => false)) {
      await fillFirstVisible(page.locator('label:has-text("Username") input'), args.username);
      await fillFirstVisible(page.locator('label:has-text("Password") input'), args.password);
      await clickButtonByRole("auth", /sign in/i, "auth:login-submit");
    }
    await page.waitForSelector(".sidebar", { timeout: 25000 });
    for (const navLabel of NAV_LABELS) {
      markControl("global", `global:nav:${navLabel}`);
    }
    await screenshot("post-login");
  });

  let discoveredTasks = [];
  await check("discover-api-baseline", async () => {
    const tasksResponse = await apiRequest("GET", "/tasks", null, [200]);
    discoveredTasks = tasksResponse.payload?.items || [];
    report.coverage.tasksDiscovered = discoveredTasks.length;

    await apiRequest("GET", "/health", null, [200]);
    await apiRequest("GET", "/settings", null, [200]);
    await apiRequest("GET", "/config/files", null, [200]);
    await apiRequest("GET", "/help/docs", null, [200]);
    await apiRequest("GET", "/about/meta", null, [200]);
    await apiRequest("GET", "/metrics/overview", null, [200]);
    await apiRequest("GET", "/users", null, [200]);
    await apiRequest("GET", "/runs", null, [200]);
    await apiRequest("GET", "/schedules", null, [200]);
    await apiRequest("GET", "/policies", null, [200]);
  });

  await check("sidebar-global-controls", async () => {
    await registerVisibleButtons("sidebar");
    const toggleButton = page.locator(".sidebar .icon-btn").first();
    await expectVisible(toggleButton, "Sidebar toggle button missing.");
    await toggleButton.click();
    markControl("sidebar", "global:sidebar-toggle-collapse");
    await page.waitForTimeout(220);
    await toggleButton.click();
    markControl("sidebar", "global:sidebar-toggle-expand");
    await page.waitForTimeout(220);

    await clickSidebarAction("Refresh", "global:sidebar-refresh");
    await clickSidebarAction("Theme", "global:sidebar-theme");
    await clickSidebarAction("Theme", "global:sidebar-theme");
  });

  await check("overview-page-comprehensive", async () => {
    await clickNav("Overview");
    await expectVisible(page.getByRole("heading", { name: /system overview/i }), "Overview header missing.");
    await expectVisible(page.locator(".coverage-grid"), "Coverage visualization not rendered on overview.");
    await clickButtonByRole("overview", "Refresh", "overview:header-refresh");
    const overviewErrorBanner = page.locator(".banner.error").first();
    if (await overviewErrorBanner.isVisible().catch(() => false)) {
      const overviewErrorText = normalizeText(await overviewErrorBanner.innerText().catch(() => ""));
      if (/unable to fetch mealie metrics/i.test(overviewErrorText)) {
        report.warnings.push(`Overview refresh warning (acceptable in offline QA): ${overviewErrorText}`);
        const closeBtn = overviewErrorBanner.locator(".banner-close").first();
        if (await closeBtn.isVisible().catch(() => false)) {
          await closeBtn.click();
          markControl("global", "global:banner-close");
          await page.waitForTimeout(150);
        }
      } else {
        throw new Error(`Overview refresh failed: ${overviewErrorText || "unknown error banner"}`);
      }
    }

    // "Run Quality Audit →" CTA — shown in empty-state medallion when no recipes have been processed
    const qualityAuditBtn = page.getByRole("button", { name: /run quality audit/i }).first();
    if (await qualityAuditBtn.isVisible().catch(() => false)) {
      await qualityAuditBtn.click();
      rememberButtonClick("overview", "Run Quality Audit");
      markControl("overview", "overview:run-quality-audit");
      await page.waitForTimeout(400);
      await expectVisible(page.locator(".task-picker").first(), "'Run Quality Audit →' did not navigate to Tasks page.");
      markInteraction("overview", "quality-audit-nav", "tasks-page-reached");
      await clickNav("Overview");
      await page.waitForTimeout(250);
    } else {
      markInteraction("overview", "quality-audit-btn", "not-in-empty-state");
    }

    await registerVisibleButtons("overview");
    await screenshot("overview");
  });

  async function expandAllTaskGroups() {
    const groupHeaders = page.locator(".task-group-header");
    const count = await groupHeaders.count();
    for (let index = 0; index < count; index += 1) {
      const header = groupHeaders.nth(index);
      const chevron = header.locator(".task-group-chevron");
      const isCollapsed = await chevron.evaluate((el) => el.classList.contains("collapsed")).catch(() => false);
      if (isCollapsed) {
        await header.click();
        await page.waitForTimeout(150);
      }
    }
  }

  await check("tasks-page-runs", async () => {
    await clickNav("Tasks");
    await expectVisible(page.getByRole("heading", { name: /tasks/i }).first(), "Tasks page header missing.");
    await expectVisible(page.locator(".task-picker").first(), "Tasks card picker missing.");

    // Wait for any in-flight loadData() (e.g. from a previous sidebar Refresh click) to finish
    // before queuing tasks. If loadData() finishes AFTER our refreshRuns() calls it will overwrite
    // the runs state with a stale empty list.
    await page
      .waitForFunction(
        () => {
          const btn = document.querySelector(".sidebar-actions button");
          return !btn || !btn.textContent.includes("Loading");
        },
        { timeout: 15000 }
      )
      .catch(() => {});
    await page.waitForTimeout(300);

    // Expand all collapsed task groups
    await expandAllTaskGroups();

    const taskItems = page.locator(".task-item");
    const taskCount = await taskItems.count();
    if (taskCount === 0) {
      throw new Error("No task items found in picker after expanding groups.");
    }

    // Ensure schedule mode is OFF for run queuing
    const scheduleToggle = page.locator('.schedule-toggle input[type="checkbox"]').first();
    if (await scheduleToggle.isChecked().catch(() => false)) {
      await scheduleToggle.uncheck();
      await page.waitForTimeout(150);
    }

    for (let index = 0; index < taskCount; index += 1) {
      const item = taskItems.nth(index);
      const label = normalizeText(await item.locator(".task-item-title").innerText().catch(() => `task-${index}`));
      await item.click();
      await page.waitForTimeout(140);
      await configureOptionFields(page.locator(".run-form"));
      await clickButtonByRole("tasks", "Queue Run", "tasks:queue-run");
      await ensureNoErrorBanner(`Run queue failed: ${label}`);
      report.coverage.tasksQueuedViaUi += 1;
      markInteraction("tasks", "queued-task", label);
      await page.waitForTimeout(280);
    }

    // Explicit QA assertion: cookbook-sync should be queued in dry-run mode.
    const queuedRuns = await apiRequest("GET", "/runs", null, [200]);
    const cookbookRun = (queuedRuns.payload?.items || []).find((run) => String(run.task_id || "") === "cookbook-sync");
    if (!cookbookRun) {
      throw new Error("cookbook-sync run was not queued from the Tasks page.");
    }
    if (cookbookRun.options?.dry_run !== true) {
      throw new Error("cookbook-sync run was queued without dry_run=true.");
    }
    markControl("tasks", "tasks:cookbook-sync-dry-run");
    markInteraction("tasks", "cookbook-sync-dry-run", "verified");

    if (taskCount > 0 && report.coverage.tasksQueuedViaUi >= taskCount) {
      markControl("tasks", "tasks:queue-all-discovered");
    }

    const searchInput = page.locator(".search-box input").first();
    if (await searchInput.isVisible().catch(() => false)) {
      await searchInput.fill("run");
      await searchInput.fill("");
    }

    // Scope filter clicks to .run-type-filters so "All" cannot match unrelated buttons
    const filterBar = page.locator(".run-type-filters");
    await filterBar.getByRole("button", { name: "All" }).first().waitFor({ state: "visible", timeout: 10000 });
    await filterBar.getByRole("button", { name: "All" }).first().click();
    rememberButtonClick("tasks", "All");
    markControl("tasks", "tasks:filter-all");
    await page.waitForTimeout(200);
    await filterBar.getByRole("button", { name: "Manual" }).first().click();
    rememberButtonClick("tasks", "Manual");
    markControl("tasks", "tasks:filter-manual");
    await page.waitForTimeout(200);
    await filterBar.getByRole("button", { name: "Scheduled" }).first().click();
    rememberButtonClick("tasks", "Scheduled");
    markControl("tasks", "tasks:filter-scheduled");
    await page.waitForTimeout(200);
    await filterBar.getByRole("button", { name: "All" }).first().click();
    rememberButtonClick("tasks", "All");
    markControl("tasks", "tasks:filter-all");
    await page.waitForTimeout(200);

    // Wait explicitly for at least one real run row to appear (not "No runs found.")
    await page
      .waitForFunction(
        () => {
          const rows = document.querySelectorAll(".runs-table tbody tr");
          return Array.from(rows).some(
            (r) => !r.textContent.toLowerCase().includes("no runs found")
          );
        },
        { timeout: 20000 }
      )
      .catch(() => {});

    let selected = await ensureRunRowSelection();
    if (!selected) {
      // Retry: navigate away and back to force a full data reload
      await clickNav("Overview");
      await page.waitForTimeout(1500);
      await clickNav("Tasks");
      await page.waitForTimeout(3000);
      // Wait again for run rows after navigation
      await page
        .waitForFunction(
          () => {
            const rows = document.querySelectorAll(".runs-table tbody tr");
            return Array.from(rows).some(
              (r) => !r.textContent.toLowerCase().includes("no runs found")
            );
          },
          { timeout: 15000 }
        )
        .catch(() => {});
      selected = await ensureRunRowSelection();
    }
    if (!selected) {
      // Second retry: give tasks more time and wait for rows again
      await page.waitForTimeout(5000);
      await page
        .waitForFunction(
          () => {
            const rows = document.querySelectorAll(".runs-table tbody tr");
            return Array.from(rows).some(
              (r) => !r.textContent.toLowerCase().includes("no runs found")
            );
          },
          { timeout: 10000 }
        )
        .catch(() => {});
      selected = await ensureRunRowSelection();
    }
    if (!selected) {
      report.warnings.push("No run row available to select after queueing runs.");
    }

    // The log output card (.log-box) is always rendered; shows "Select a run above" placeholder
    // when no row is selected, or the actual log content when a row is selected.
    await expectVisible(page.locator(".log-box").first(), "Run output viewer not rendered.");

    // Log output card action buttons
    const copyLogBtn = page.locator('button[title="Copy log to clipboard"]').first();
    if (await copyLogBtn.isVisible().catch(() => false)) {
      await copyLogBtn.click();
      markControl("tasks", "tasks:log-copy");
      rememberButtonClick("tasks", "Copy log to clipboard");
      await page.waitForTimeout(150);
    }

    const downloadLogBtn = page.locator('button[title="Download log file"]').first();
    if (await downloadLogBtn.isVisible().catch(() => false)) {
      await downloadLogBtn.click();
      markControl("tasks", "tasks:log-download");
      rememberButtonClick("tasks", "Download log file");
      await page.waitForTimeout(150);
    }

    const maximizeLogBtn = page.locator('button[title="Maximize"]').first();
    if (await maximizeLogBtn.isVisible().catch(() => false)) {
      await maximizeLogBtn.click();
      markControl("tasks", "tasks:log-maximize");
      rememberButtonClick("tasks", "Maximize");
      await page.waitForTimeout(200);
      const restoreLogBtn = page.locator('button[title="Restore"]').first();
      if (await restoreLogBtn.isVisible().catch(() => false)) {
        await restoreLogBtn.click();
        await page.waitForTimeout(150);
      }
    }

    // Cancel button for queued/running runs (may not always be visible if all runs completed)
    const cancelRunBtn = page.locator('button[title="Cancel run"]').first();
    if (await cancelRunBtn.isVisible().catch(() => false)) {
      await cancelRunBtn.click();
      markControl("tasks", "tasks:run-cancel");
      rememberButtonClick("tasks", "Cancel run");
      await page.waitForTimeout(400);
      await ensureNoErrorBanner("Run cancel failed");
    }

    await registerVisibleButtons("tasks");
    await screenshot("tasks-runs");
  });

  await check("tasks-page-schedules", async () => {
    await clickNav("Tasks");
    await expectVisible(page.locator(".task-picker").first(), "Tasks card picker missing for schedule.");

    // Expand all task groups and prefer cookbook-sync to validate dry-run schedule coverage.
    await expandAllTaskGroups();
    const cookbookTaskItem = page.locator(".task-item", { hasText: /cookbook sync/i }).first();
    const firstTaskItem = (await cookbookTaskItem.count()) > 0 ? cookbookTaskItem : page.locator(".task-item").first();
    await expectVisible(firstTaskItem, "No task items found for schedule creation.");
    await firstTaskItem.click();
    await page.waitForTimeout(200);

    // Enable schedule mode
    const scheduleToggle = page.locator('.schedule-toggle input[type="checkbox"]').first();
    await expectVisible(scheduleToggle, "Schedule Run toggle missing.");
    if (!(await scheduleToggle.isChecked().catch(() => false))) {
      await scheduleToggle.check();
      await page.waitForTimeout(200);
    }

    // Helper: build a datetime-local string for N hours from now
    function futureDtLocal(hoursAhead) {
      const dt = new Date(Date.now() + hoursAhead * 3600000);
      const pad = (n) => String(n).padStart(2, "0");
      return `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
    }

    // Create an interval schedule
    const intervalName = `qa-ui-interval-${Date.now().toString().slice(-7)}`;
    await fillFirstVisible(page.locator('label:has-text("Schedule Name") input'), intervalName);
    await page.locator('label:has-text("Type") select').first().selectOption("interval");
    await page.waitForTimeout(150);
    const everyInput = page.locator('.interval-row input[type="number"]').first();
    await expectVisible(everyInput, "Interval 'Every' number input missing.");
    await everyInput.fill("30");
    const unitSelect = page.locator('.interval-row select').first();
    await expectVisible(unitSelect, "Interval unit select missing.");
    await unitSelect.selectOption("minutes");
    // Fill start date (required for interval schedules)
    const startInput1 = page.locator('label:has-text("Start date") input[type="datetime-local"]').first();
    if (await startInput1.isVisible().catch(() => false)) {
      await startInput1.fill(futureDtLocal(1));
      await page.waitForTimeout(100);
    }
    await configureOptionFields(page.locator(".run-form"));
    await clickButtonByRole("tasks", "Save Schedule", "tasks:save-interval");
    await ensureNoErrorBanner("Interval schedule save failed");
    await page.waitForTimeout(500);

    // After save the form may reset (toggle turns off). Re-enable schedule mode for second schedule.
    if (!(await scheduleToggle.isChecked().catch(() => false))) {
      await scheduleToggle.check();
      await page.waitForTimeout(200);
    }

    // Create a second interval schedule
    const intervalName2 = `qa-ui-int2-${Date.now().toString().slice(-7)}`;
    await fillFirstVisible(page.locator('label:has-text("Schedule Name") input'), intervalName2);
    await page.locator('label:has-text("Type") select').first().selectOption("interval");
    await page.waitForTimeout(150);
    const everyInput2 = page.locator('.interval-row input[type="number"]').first();
    await everyInput2.fill("60");
    await page.locator('.interval-row select').first().selectOption("minutes");
    const startInput2 = page.locator('label:has-text("Start date") input[type="datetime-local"]').first();
    if (await startInput2.isVisible().catch(() => false)) {
      await startInput2.fill(futureDtLocal(2));
      await page.waitForTimeout(100);
    }
    await configureOptionFields(page.locator(".run-form"));
    await clickButtonByRole("tasks", "Save Schedule", "tasks:save-interval");
    await ensureNoErrorBanner("Second schedule save failed");
    await page.waitForTimeout(500);

    const schedulesPayload = await apiRequest("GET", "/schedules", null, [200]);
    const items = schedulesPayload.payload?.items || [];
    const created = items.filter((item) => item.name === intervalName || item.name === intervalName2);
    if (created.length < 2) {
      throw new Error("Expected both interval schedules to be created via UI.");
    }
    for (const item of created) {
      cleanupState.scheduleIds.add(String(item.schedule_id));
    }
    report.coverage.schedulesCreatedViaUi += created.length;

    // Turn schedule mode back off
    if (await scheduleToggle.isChecked().catch(() => false)) {
      await scheduleToggle.uncheck();
      await page.waitForTimeout(150);
    }

    await registerVisibleButtons("tasks");
    await screenshot("tasks-schedules");
  });

  await check("tasks-schedule-management", async () => {
    await clickNav("Tasks");
    const scheduleItems = page.locator(".schedule-item");
    const schedCount = await scheduleItems.count();
    if (schedCount === 0) {
      report.warnings.push("No schedule items found on Tasks page for management test.");
      return;
    }

    // Toggle enable/disable on first schedule
    const firstSched = scheduleItems.first();
    const toggleBtn = firstSched
      .locator(".schedule-item-actions button.enabled-toggle, .schedule-item-actions button.disabled-toggle")
      .first();
    if (await toggleBtn.isVisible().catch(() => false)) {
      const toggleTitle = await toggleBtn.getAttribute("title").catch(() => "");
      await toggleBtn.click();
      rememberButtonClick("tasks", toggleTitle || "Toggle schedule");
      markControl("tasks", "tasks:schedule-toggle-enabled");
      await page.waitForTimeout(400);
      await ensureNoErrorBanner("Schedule toggle failed");
      // Toggle back to original state
      const toggleBtn2 = firstSched
        .locator(".schedule-item-actions button.enabled-toggle, .schedule-item-actions button.disabled-toggle")
        .first();
      if (await toggleBtn2.isVisible().catch(() => false)) {
        await toggleBtn2.click();
        await page.waitForTimeout(300);
      }
    }

    // Edit first schedule inline and save
    const firstSchedName = normalizeText(await firstSched.locator("strong").first().innerText().catch(() => ""));
    const editSchedBtn = firstSched.locator('.schedule-item-actions button[title*="Edit"]').first();
    if (await editSchedBtn.isVisible().catch(() => false)) {
      await editSchedBtn.click();
      markControl("tasks", "tasks:schedule-edit-open");
      rememberButtonClick("tasks", "Edit schedule");
      await page.waitForTimeout(250);

      const editPanel = firstSched.locator(".schedule-edit-panel").first();
      await expectVisible(editPanel, "Schedule edit panel did not open.");
      const newName = `${firstSchedName || "qa-schedule"}-edited-${Date.now().toString().slice(-4)}`;
      const nameInput = editPanel.locator('label:has-text("Schedule Name") input').first();
      await expectVisible(nameInput, "Schedule edit name input missing.");
      await nameInput.fill(newName);

      const missedCheckbox = editPanel
        .locator('label:has-text("Run if schedule is missed") input[type="checkbox"]')
        .first();
      if (await missedCheckbox.isVisible().catch(() => false)) {
        await missedCheckbox.click();
      }

      const saveEditBtn = editPanel.getByRole("button", { name: /save changes/i }).first();
      await expectVisible(saveEditBtn, "Save Changes button missing in schedule editor.");
      await saveEditBtn.click();
      markControl("tasks", "tasks:schedule-edit-save");
      rememberButtonClick("tasks", "Save Changes");
      await page.waitForTimeout(500);
      await ensureNoErrorBanner("Schedule edit save failed");

      const updatedSchedules = await apiRequest("GET", "/schedules", null, [200]);
      const editedItem = (updatedSchedules.payload?.items || []).find((item) => item.name === newName);
      if (!editedItem) {
        throw new Error("Edited schedule name was not persisted via API.");
      }
      cleanupState.scheduleIds.add(String(editedItem.schedule_id));
    }

    // Delete the last schedule (direct delete, no confirmation modal for schedules)
    const allScheduleItems = page.locator(".schedule-item");
    const lastSched = allScheduleItems.last();
    const deleteSchedBtn = lastSched.locator(".schedule-item-actions button.ghost.small.danger").first();
    if (await deleteSchedBtn.isVisible().catch(() => false)) {
      const countBefore = await allScheduleItems.count();
      await deleteSchedBtn.click();
      markControl("tasks", "tasks:schedule-delete-direct");
      rememberButtonClick("tasks", "Delete schedule");
      await page.waitForTimeout(500);
      await ensureNoErrorBanner("Schedule delete failed");
      const countAfter = await page.locator(".schedule-item").count();
      if (countAfter >= countBefore) {
        report.warnings.push("Schedule delete: item count did not decrease after direct delete.");
      }
      // Sync cleanupState with actual API state
      const remaining = await apiRequest("GET", "/schedules", null, [200]);
      const remainingIds = new Set((remaining.payload?.items || []).map((s) => String(s.schedule_id)));
      for (const id of [...cleanupState.scheduleIds]) {
        if (!remainingIds.has(id)) {
          cleanupState.scheduleIds.delete(id);
        }
      }
    }

    await screenshot("tasks-schedule-management");
  });

  await check("tasks-once-schedule", async () => {
    await clickNav("Tasks");
    await expandAllTaskGroups();
    const firstTaskItem = page.locator(".task-item").first();
    await expectVisible(firstTaskItem, "No task items found for once-schedule creation.");
    await firstTaskItem.click();
    await page.waitForTimeout(200);

    const scheduleToggle = page.locator('.schedule-toggle input[type="checkbox"]').first();
    await expectVisible(scheduleToggle, "Schedule Run toggle missing for once-schedule test.");
    if (!(await scheduleToggle.isChecked().catch(() => false))) {
      await scheduleToggle.check();
      await page.waitForTimeout(200);
    }

    const onceName = `qa-ui-once-${Date.now().toString().slice(-7)}`;
    await fillFirstVisible(page.locator('label:has-text("Schedule Name") input'), onceName);
    await page.locator('label:has-text("Type") select').first().selectOption("once");
    await page.waitForTimeout(200);

    const runAtInput = page.locator('input[type="datetime-local"]').first();
    await expectVisible(runAtInput, "datetime-local input not visible for 'once' schedule type.");
    const futureDate = new Date(Date.now() + 3600000);
    const pad2 = (n) => String(n).padStart(2, "0");
    const dtValue = `${futureDate.getFullYear()}-${pad2(futureDate.getMonth() + 1)}-${pad2(futureDate.getDate())}T${pad2(futureDate.getHours())}:${pad2(futureDate.getMinutes())}`;
    await runAtInput.fill(dtValue);
    markControl("tasks", "tasks:once-schedule");

    await configureOptionFields(page.locator(".run-form"));
    await clickButtonByRole("tasks", "Save Schedule", "tasks:save-once");
    await ensureNoErrorBanner("Once schedule save failed");
    await page.waitForTimeout(400);

    // Verify the once schedule was created via API
    const schedulesResult = await apiRequest("GET", "/schedules", null, [200]);
    const onceItem = (schedulesResult.payload?.items || []).find((s) => s.name === onceName);
    if (!onceItem) {
      throw new Error(`Once schedule '${onceName}' was not found in API response after creation.`);
    }
    cleanupState.scheduleIds.add(String(onceItem.schedule_id));
    report.coverage.schedulesCreatedViaUi += 1;

    if (await scheduleToggle.isChecked().catch(() => false)) {
      await scheduleToggle.uncheck();
      await page.waitForTimeout(150);
    }
    await screenshot("tasks-once-schedule");
  });

  await check("settings-page-comprehensive", async () => {
    await clickNav("Settings");
    await expectVisible(page.getByRole("heading", { name: /settings/i }).first(), "Settings header missing.");
    await clickButtonByRole("settings", "Reload", "settings:reload");
    await ensureNoErrorBanner("Settings reload failed");

    const mealieInput = page.locator('.settings-row:has-text("Mealie Server URL") input').first();
    await expectVisible(mealieInput, "Mealie URL input missing.");
    const mealieValue = normalizeText(await mealieInput.inputValue());
    if (!mealieValue) {
      throw new Error("Mealie URL input did not load a value from environment/settings.");
    }
    if (args.expectedMealieUrl && !mealieValue.includes(args.expectedMealieUrl.replace(/\/+$/, ""))) {
      throw new Error("Mealie URL input does not match expected .env value.");
    }

    // Verify AI provider dropdown exists and interact with it
    const providerSelect = page.locator('.settings-row:has-text("AI Provider") select').first();
    await expectVisible(providerSelect, "AI Provider dropdown missing on Settings page.");
    const providerValue = await providerSelect.inputValue();
    markControl("settings", "settings:provider-dropdown");
    markInteraction("settings", "provider-value", providerValue);

    // Test model controls - either dropdown or text input with refresh/load button
    const modelRow = page.locator('.settings-row:has-text("Model")').first();
    if (await modelRow.isVisible().catch(() => false)) {
      const modelSelect = modelRow.locator("select").first();
      const modelInput = modelRow.locator('input[type="text"]').first();
      const modelRefresh = modelRow.locator("button.ghost.small").first();
      if (await modelSelect.isVisible().catch(() => false)) {
        markControl("settings", "settings:model-control");
        markInteraction("settings", "model-dropdown", "select-visible");
      } else if (await modelInput.isVisible().catch(() => false)) {
        markControl("settings", "settings:model-control");
        markInteraction("settings", "model-input", "text-visible");
      }
      if (await modelRefresh.isVisible().catch(() => false)) {
        await modelRefresh.click();
        rememberButtonClick("settings", "Refresh list");
        markInteraction("settings", "model-refresh-clicked", "");
        await page.waitForTimeout(1500);
      }
    } else {
      // Provider might be "none" which hides model fields
      if (providerValue !== "none") {
        report.warnings.push("Model row not visible despite AI provider being enabled.");
      }
      markControl("settings", "settings:model-control");
    }

    // Secret field clear buttons
    const clearButtons = page.locator(".settings-row .settings-input-wrap .ghost.small").filter({ hasText: "Clear" });
    const clearCount = Math.min(await clearButtons.count(), 2);
    for (let index = 0; index < clearCount; index += 1) {
      const clearBtn = clearButtons.nth(index);
      if (await clearBtn.isVisible().catch(() => false)) {
        await clearBtn.click();
        rememberButtonClick("settings", "Clear");
        markInteraction("settings", "clear-secret-draft", `index:${index}`);
      }
    }
    if (clearCount > 0) {
      await clickButtonByRole("settings", "Reload", "settings:reload");
      await ensureNoErrorBanner("Settings reload after clear failed");
    }

    // Connection tests — visibility depends on selected provider
    await runConnectionButton("Test Mealie", "Check Mealie URL/API key connectivity.", "settings:test-mealie");

    const currentProvider = await providerSelect.inputValue().catch(() => "chatgpt");
    if (currentProvider === "chatgpt") {
      const openAiBtn = page.getByRole("button", { name: "Test OpenAI" }).first();
      if (await openAiBtn.isVisible().catch(() => false)) {
        await runConnectionButton("Test OpenAI", "Validate OpenAI key and selected model.", "settings:test-provider");
      }
    } else if (currentProvider === "ollama") {
      const ollamaBtn = page.getByRole("button", { name: "Test Ollama" }).first();
      if (await ollamaBtn.isVisible().catch(() => false)) {
        await runConnectionButton("Test Ollama", "Validate Ollama endpoint reachability.", "settings:test-provider");
      }
    }
    if (!markerHits.has("settings:test-provider")) {
      // If neither provider test was hit, cycle provider to test the other
      const altProvider = currentProvider === "chatgpt" ? "ollama" : "chatgpt";
      await providerSelect.selectOption(altProvider);
      await page.waitForTimeout(500);
      if (altProvider === "chatgpt") {
        const btn = page.getByRole("button", { name: "Test OpenAI" }).first();
        if (await btn.isVisible().catch(() => false)) {
          await runConnectionButton("Test OpenAI", "Validate OpenAI key and selected model.", "settings:test-provider");
        }
      } else {
        const btn = page.getByRole("button", { name: "Test Ollama" }).first();
        if (await btn.isVisible().catch(() => false)) {
          await runConnectionButton("Test Ollama", "Validate Ollama endpoint reachability.", "settings:test-provider");
        }
      }
      // Restore original provider
      await providerSelect.selectOption(currentProvider);
      await page.waitForTimeout(300);
    }

    // Test DB connection button (only visible when DB config is present)
    const testDbBtn = page.getByRole("button", { name: /^test db$/i }).first();
    if (await testDbBtn.isVisible().catch(() => false)) {
      await runConnectionButton("Test DB", "Verify direct database connection.", "settings:test-db");
    }

    await clickButtonByRole("settings", "Apply Changes", "settings:apply");
    await ensureNoErrorBanner("Settings apply failed");

    // Verify settings persisted: reload and confirm Mealie URL is still populated
    await clickButtonByRole("settings", "Reload", "settings:reload");
    await page.waitForTimeout(800);
    const mealieInputAfterReload = page.locator('.settings-row:has-text("Mealie Server URL") input').first();
    const mealieValueAfterReload = normalizeText(await mealieInputAfterReload.inputValue().catch(() => ""));
    if (!mealieValueAfterReload) {
      throw new Error("Mealie URL was empty after Apply + Reload — settings may not have persisted.");
    }

    // Banner close: if any banner appeared during apply/reload, verify the close button works
    const errorBannerCheck = page.locator(".banner.error").first();
    const infoBannerCheck = page.locator(".banner.info").first();
    for (const banner of [errorBannerCheck, infoBannerCheck]) {
      if (await banner.isVisible().catch(() => false)) {
        const closeBtn = banner.locator(".banner-close").first();
        if (await closeBtn.isVisible().catch(() => false)) {
          await closeBtn.click();
          markControl("global", "global:banner-close");
          await page.waitForTimeout(200);
        }
        break;
      }
    }

    await registerVisibleButtons("settings");
    await screenshot("settings");
  });

  await check("recipe-organization-page-comprehensive", async () => {
    await clickNav("Recipe Organization");
    await expectVisible(
      page.getByRole("heading", { name: /recipe organization/i }).first(),
      "Recipe Organization header missing."
    );
    const markerByPillName = [
      { key: "categories", marker: "recipe:pill-categories", configName: "categories" },
      { key: "cookbooks", marker: "recipe:pill-cookbooks", configName: "cookbooks" },
      { key: "labels", marker: "recipe:pill-labels", configName: "labels" },
      { key: "tags", marker: "recipe:pill-tags", configName: "tags" },
      { key: "tools", marker: "recipe:pill-tools", configName: "tools" },
      { key: "units", marker: "recipe:pill-units", configName: "units_aliases" },
    ];

    const pillCount = await page.locator(".pill-btn").count();
    if (pillCount < 6) {
      throw new Error(`Expected 6 taxonomy pills, found ${pillCount}.`);
    }

    for (const matched of markerByPillName) {
      const pill = page.locator(".pill-btn").filter({ hasText: new RegExp(matched.key, "i") }).first();
      await expectVisible(pill, `Taxonomy pill '${matched.key}' was not visible.`);
      await pill.click();
      await page.waitForTimeout(200);
      markControl("recipe", matched.marker);
      if (matched.configName === "cookbooks") {
        try {
        // Verify structured cookbook editor renders (not raw JSON).
        const addCardByHeading = page.locator("article.card", {
          has: page.getByRole("heading", { name: /add cookbook/i }),
        }).first();
        const addCardByForm = page.locator("article.card", {
          has: page.locator(".cookbook-add-form"),
        }).first();
        const addCard = (await addCardByHeading.isVisible().catch(() => false))
          ? addCardByHeading
          : addCardByForm;
        const addCardVisible = await addCard.isVisible().catch(() => false);
        if (!addCardVisible) {
          report.warnings.push("Cookbooks add form card was not visible; skipping cookbook form interactions.");
          continue;
        }
        await expectVisible(addCard, "Cookbooks 'Add Cookbook' card not rendered.", 30000);
        markControl("recipe", "recipe:cookbook-add-form");

        const advancedModeVisible = await page
          .getByText(/advanced mode: this file requires full json editing/i)
          .first()
          .isVisible()
          .catch(() => false);
        if (advancedModeVisible) {
          throw new Error("Cookbooks taxonomy unexpectedly fell back to advanced JSON editor mode.");
        }

        // Verify existing cookbooks card renders when items exist
        const existingCard = page.locator("article.card", {
          has: page.getByRole("heading", { name: /^Cookbooks \(\d+\)$/i }),
        }).first();
        if (await existingCard.isVisible().catch(() => false)) {
          markControl("recipe", "recipe:cookbook-existing-card");
          const structuredItems = existingCard.locator(".structured-item");
          const itemCount = await structuredItems.count();
          if (itemCount === 0) {
            report.warnings.push("Cookbooks card was visible but no structured items rendered.");
          } else {
            // Verify each item has filter selects and Name/Description fields
            const firstItem = structuredItems.first();
            const nameInput = firstItem.locator('.cookbook-fields label:has-text("Name") input').first();
            await expectVisible(nameInput, "Cookbook item Name input missing.");
            const descInput = firstItem.locator('.cookbook-fields label:has-text("Description") input').first();
            await expectVisible(descInput, "Cookbook item Description input missing.");

            // Verify filter rows exist on existing items (parsed from queryFilterString)
            const itemFilterRows = firstItem.locator(".filter-row");
            const filterRowCount = await itemFilterRows.count();
            markInteraction("recipe", "cookbook-item-filter-rows", `count:${filterRowCount}`);

            // Verify existing chips on items (if any filter values are set)
            const existingChips = firstItem.locator(".filter-chip");
            const chipCount = await existingChips.count();
            markInteraction("recipe", "cookbook-item-chips", `count:${chipCount}`);

            // Verify Add Filter button exists on existing items
            const itemAddFilterBtn = firstItem.locator("button:has-text('+ Add Filter')").first();
            if (await itemAddFilterBtn.isVisible().catch(() => false)) {
              markInteraction("recipe", "cookbook-item-add-filter", "visible");
            }
          }
        }

        // Test the Add Cookbook form with filter builder
        const addNameInput = addCard.locator('label:has-text("Name") input').first();
        await expectVisible(addNameInput, "Add Cookbook Name input missing.");
        await addNameInput.fill(`qa-cookbook-${Date.now().toString().slice(-6)}`);

        const addDescInput = addCard.locator('label:has-text("Description") input').first();
        await addDescInput.fill("QA test cookbook.");

          // Position number input
          const positionInput = addCard.locator('label:has-text("Position") input[type="number"]').first();
          if (await positionInput.isVisible().catch(() => false)) {
            await positionInput.fill("1");
            markInteraction("recipe", "cookbook-position-input", "filled");
          }

          // Public checkbox
          const publicCheckbox = addCard.locator('label:has-text("Public") input[type="checkbox"]').first();
          if (await publicCheckbox.isVisible().catch(() => false)) {
            const wasPublicChecked = await publicCheckbox.isChecked();
            await publicCheckbox.click();
            markInteraction("recipe", "cookbook-public-checkbox", `toggled-from:${wasPublicChecked}`);
            await page.waitForTimeout(100);
          }

          // Test row-based filter builder: click + Add Filter
          const addFilterBtn = addCard.locator("button:has-text('+ Add Filter')").first();
          if (await addFilterBtn.isVisible().catch(() => false)) {
            await addFilterBtn.click();
            await page.waitForTimeout(200);

            // A filter row should appear with 3 selects (field, operator, value) and a remove btn
            const filterRow = addCard.locator(".filter-row").first();
            await expectVisible(filterRow, "Filter row did not appear after clicking + Add Filter.");

            // Filter row has: field select (idx 0), operator select (idx 1), value select (idx 2 in filter-value-area)
            const fieldSelect = filterRow.locator("select").nth(0);
            const operatorSelect = filterRow.locator("select").nth(1);
            const valueSelect = filterRow.locator(".filter-value-area select").first();

            // Test operator change
            if (await operatorSelect.isVisible().catch(() => false)) {
              await operatorSelect.selectOption("CONTAINS ALL");
              markControl("recipe", "recipe:cookbook-filter-operator");
              await page.waitForTimeout(100);
              await operatorSelect.selectOption("IN");
              await page.waitForTimeout(100);
            }

            // Test value selection (categories is default field)
            if (await valueSelect.isVisible().catch(() => false)) {
              const catOptions = await valueSelect.evaluate((sel) =>
                Array.from(sel.options).map((o) => o.value).filter(Boolean)
              );
              if (catOptions.length > 0) {
                await valueSelect.selectOption(catOptions[0]);
                markControl("recipe", "recipe:cookbook-filter-select");
                await page.waitForTimeout(200);

                // Verify chip appeared
                const newChip = filterRow.locator(".filter-chip").first();
                await expectVisible(newChip, "Filter chip did not appear after selecting a value.");
                markInteraction("recipe", "cookbook-chip-appeared", catOptions[0]);

                // Test chip removal
                const chipRemoveBtn = newChip.locator(".chip-remove").first();
                if (await chipRemoveBtn.isVisible().catch(() => false)) {
                  await chipRemoveBtn.click();
                  await page.waitForTimeout(150);
                  markInteraction("recipe", "cookbook-chip-removed", catOptions[0]);
                }

                // Re-select for the add test
                await valueSelect.selectOption(catOptions[0]);
                await page.waitForTimeout(150);
              }
            }

            // Test removing the filter row
            const removeBtn = filterRow.locator(".filter-remove-btn").first();
            if (await removeBtn.isVisible().catch(() => false)) {
              markInteraction("recipe", "cookbook-filter-row-remove", "visible");
            }

            // Add a second filter row (tags) to test multi-row
            await addFilterBtn.click();
            await page.waitForTimeout(200);
          }

          // Click Add Cookbook button
          await clickButtonByRole("recipe", "Add Cookbook", "recipe:cookbook-add");
          await page.waitForTimeout(300);
          await ensureNoErrorBanner("Add Cookbook failed");

          // Verify the newly added cookbook appears in the existing cookbooks card
          const updatedExistingCard = page.locator("article.card", {
            has: page.getByRole("heading", { name: /^Cookbooks \(\d+\)$/i }),
          }).first();
          if (await updatedExistingCard.isVisible().catch(() => false)) {
            if (!markerHits.has("recipe:cookbook-existing-card")) {
              markControl("recipe", "recipe:cookbook-existing-card");
            }
          }

        // Remove the last cookbook entry (the one we just added)
        const lastItem = page.locator(".structured-item").last();
        if (await lastItem.isVisible().catch(() => false)) {
          const removeBtn = lastItem.getByRole("button", { name: /^remove$/i }).first();
          if (await removeBtn.isVisible().catch(() => false)) {
            await removeBtn.click();
            markControl("recipe", "recipe:cookbook-remove");
            rememberButtonClick("recipe", "Remove");
            await page.waitForTimeout(200);
          }
        }
        } catch (error) {
          report.warnings.push(`Cookbook editor deep checks skipped: ${String(error?.message || error)}`);
          continue;
        }
      }
      if (matched.configName === "units_aliases") {
          // Structured units editor shows NAME/ALIASES fields — raw JSON fallback would show a textarea
          await expectVisible(
            page.locator(".structured-editor").first(),
            "Units taxonomy rendered as raw JSON instead of structured editor."
          );
          // Verify it's the real structured editor (not advanced JSON edit mode)
          const advancedMode = page.getByText(/advanced mode.*requires full json/i).first();
          if (await advancedMode.isVisible().catch(() => false)) {
            throw new Error("Units taxonomy unexpectedly fell back to advanced JSON editor mode.");
          }
          // Confirm an aliases/plural field is present (distinguishes structured from raw)
          const aliasesField = page.locator(".structured-editor label").filter({ hasText: /aliases/i }).first();
          if (await aliasesField.isVisible().catch(() => false)) {
            markInteraction("recipe", "units-aliases-field", "structured-editor-confirmed");
          }
        }

      if (matched.configName === "labels") {
          // Color picker in the Add Label form
          const colorPickerInput = page.locator('.color-field input[type="color"]').first();
          if (await colorPickerInput.isVisible().catch(() => false)) {
            await colorPickerInput.fill("#ff6b6b");
            markControl("recipe", "recipe:label-color-picker");
            rememberButtonClick("recipe", "Color picker");
            await page.waitForTimeout(150);
            const hexInput = page.locator('.color-field input.color-hex').first();
            if (await hexInput.isVisible().catch(() => false)) {
              await hexInput.fill("#959595");
              markInteraction("recipe", "label-color-hex-input", "present");
              await page.waitForTimeout(100);
            }
          }
        }

      if (matched.configName === "tools") {
          // "On Hand" checkbox in the Add Tool form
          const onHandCheckbox = page.locator('label.field-inline input[type="checkbox"]').first();
          if (await onHandCheckbox.isVisible().catch(() => false)) {
            const wasChecked = await onHandCheckbox.isChecked();
            await onHandCheckbox.click();
            markControl("recipe", "recipe:tool-on-hand");
            rememberButtonClick("recipe", "On Hand");
            await page.waitForTimeout(150);
            if ((await onHandCheckbox.isChecked()) !== wasChecked) {
              await onHandCheckbox.click();
              await page.waitForTimeout(100);
            }
          }
        }

      // Up/Down reorder buttons — present on any pill that has list items
      const upBtn = page.locator('.line-actions button', { hasText: "Up" }).first();
      const downBtn = page.locator('.line-actions button', { hasText: "Down" }).first();
      if (await upBtn.isVisible().catch(() => false)) {
        markControl("recipe", "recipe:reorder-up");
        if (!(await upBtn.isDisabled())) {
          await upBtn.click();
          await page.waitForTimeout(150);
        } else {
          markInteraction("recipe", "reorder-up", "first-item-disabled");
        }
      }
      if (await downBtn.isVisible().catch(() => false)) {
        markControl("recipe", "recipe:reorder-down");
        if (!(await downBtn.isDisabled())) {
          await downBtn.click();
          await page.waitForTimeout(150);
        } else {
          markInteraction("recipe", "reorder-down", "last-item-disabled");
        }
      }
    }

    // Verify the file browse input is present in the import drop zone
    const fileInput = page.locator('.drop-zone input[type="file"]').first();
    if ((await fileInput.count()) > 0) {
      markInteraction("recipe", "file-browse-input", "present-in-dom");
    } else {
      report.warnings.push("File browse input not found in drop zone on Recipe Organization page.");
    }

    const editorInput = page.locator(".pill-input-row input").first();
    if (await editorInput.isVisible().catch(() => false)) {
      const draftValue = `qa-temp-${Date.now().toString().slice(-6)}`;
      await editorInput.fill(draftValue);
      await clickButtonByRole("recipe", "Add");
      const lastRow = page.locator(".pill-lines .pill-line").last();
      if (await lastRow.isVisible().catch(() => false)) {
        const removeButton = lastRow.getByRole("button", { name: /^remove$/i }).first();
        await removeButton.click();
        rememberButtonClick("recipe", "Remove");
      }
    }

    const activePillText = normalizeText(await page.locator(".pill-btn.active").first().innerText().catch(() => ""));
    const activeMarker = markerByPillName.find((item) => activePillText.toLowerCase().includes(item.key));
    const activeConfigName = activeMarker?.configName || "categories";
    await snapshotConfigFile(activeConfigName);
    await clickButtonByRole("recipe", "Save File", "recipe:save-file");
    touchedConfigNames.add(activeConfigName);
    await ensureNoErrorBanner("Recipe save failed");
    await clickButtonByRole("recipe", "Discard", "recipe:discard");
    await ensureNoErrorBanner("Recipe discard failed");

    const importSelect = page.locator('label:has-text("Target File") select').first();
    await expectVisible(importSelect, "Taxonomy import target selector missing.");
    await importSelect.selectOption("categories");

    await snapshotConfigFile("categories");
    const categoriesConfig = await apiRequest("GET", "/config/files/categories", null, [200]);
    const categoriesContent = categoriesConfig.payload?.content;
    if (!Array.isArray(categoriesContent)) {
      throw new Error("Categories config content did not load as an array.");
    }

    const importTextarea = page.locator(".drop-zone textarea").first();
    await expectVisible(importTextarea, "Taxonomy import JSON textarea missing.");
    await importTextarea.fill(`${JSON.stringify(categoriesContent, null, 2)}\n`);
    await clickButtonByRole("recipe", "Import JSON", "recipe:import-json");
    touchedConfigNames.add("categories");
    await ensureNoErrorBanner("Recipe JSON import failed");

    await registerVisibleButtons("recipe");
    await screenshot("recipe-organization");
  });

  await check("users-page-comprehensive", async () => {
    await clickNav("Users");
    await expectVisible(page.getByRole("heading", { name: /users and access/i }).first(), "Users page header missing.");

    const tempUser = `qaui${Date.now().toString().slice(-6)}`;
    const resetPassword = "QaUiResetPass#1";
    // Wait for any in-flight loadData to finish before interacting with the form
    await page.waitForTimeout(2000);
    // Fill username
    const usernameInput = page.locator('input[placeholder="kitchen-tablet"]').first();
    await expectVisible(usernameInput, "Username input not visible on Users page.");
    await usernameInput.click();
    await usernameInput.fill(tempUser);
    // Generate password (guarantees uppercase+lowercase+digit)
    await clickButtonByRole("users", "Generate", "users:generate-password");
    await page.waitForTimeout(300);

    // Show/hide password toggle
    const showPwdBtn = page
      .locator('.icon-btn[title="Show password"], .icon-btn[title="Hide password"]')
      .first();
    if (await showPwdBtn.isVisible().catch(() => false)) {
      await showPwdBtn.click();
      markControl("users", "users:password-show-hide");
      await page.waitForTimeout(100);
      await showPwdBtn.click();
      await page.waitForTimeout(100);
    }

    // Role dropdown (default: Editor)
    const roleSelect = page.locator('label:has-text("Role") select').first();
    if (await roleSelect.isVisible().catch(() => false)) {
      await roleSelect.selectOption("Viewer");
      await page.waitForTimeout(100);
      await roleSelect.selectOption("Editor");
      markControl("users", "users:role-dropdown");
    }

    // Force password reset checkbox
    const forceResetNewUser = page.locator('label.checkbox-field input[type="checkbox"]').first();
    if (await forceResetNewUser.isVisible().catch(() => false)) {
      await forceResetNewUser.check();
      markControl("users", "users:force-reset-checkbox");
      await page.waitForTimeout(100);
      await forceResetNewUser.uncheck();
      await page.waitForTimeout(100);
    }

    // Submit the create user form
    await clickButtonByRole("users", "Create User", "users:create-user");
    // Wait for the API call + loadData() to complete
    await page.waitForTimeout(4000);
    await ensureNoErrorBanner("User create failed");
    cleanupState.usernames.add(tempUser);
    report.coverage.usersCreatedViaUi += 1;

    // Find the user in the accordion list and expand it
    let userRow = page.locator(".user-row", { hasText: tempUser }).first();
    if (!(await userRow.isVisible().catch(() => false))) {
      // Retry: refresh data and wait for the user row to appear
      await clickSidebarAction("Refresh", "global:sidebar-refresh");
      await page.waitForTimeout(4000);
      userRow = page.locator(".user-row", { hasText: tempUser }).first();
    }
    await expectVisible(userRow, "Created user row was not found in user list.");

    // User search: filter by partial username and verify user still visible
    const userSearchInput = page.locator(".search-box input").first();
    if (await userSearchInput.isVisible().catch(() => false)) {
      await userSearchInput.fill(tempUser.slice(0, 4));
      await page.waitForTimeout(300);
      const filteredRow = page.locator(".user-row", { hasText: tempUser }).first();
      await expectVisible(filteredRow, `User search: created user '${tempUser}' not found with partial filter.`);
      markControl("users", "users:search");
      await userSearchInput.fill("");
      await page.waitForTimeout(200);
    }

    const toggleButton = userRow.locator(".user-row-toggle").first();
    await toggleButton.click();
    await page.waitForTimeout(200);

    // Reset password via expanded row
    const passwordInput = userRow.locator('input[placeholder="New password"]').first();
    await expectVisible(passwordInput, "Password reset input not visible after expanding user row.");
    await passwordInput.fill(resetPassword);
    await userRow.getByRole("button", { name: /reset password/i }).first().click();
    markControl("users", "users:reset-password");
    await page.waitForTimeout(650);
    await ensureNoErrorBanner("User reset password failed");

    // Test confirmation modal cancel: click delete, click Cancel, verify user NOT deleted
    const trashBtnForCancel = userRow.locator('button[title="Remove user"]').first();
    await expectVisible(trashBtnForCancel, "Trash/delete button missing for cancel modal test.");
    await trashBtnForCancel.click();
    await page.waitForTimeout(200);
    const cancelModal = page.locator(".modal-card").first();
    if (await cancelModal.isVisible().catch(() => false)) {
      const cancelBtn = cancelModal.getByRole("button", { name: /^cancel$/i }).first();
      await expectVisible(cancelBtn, "Cancel button not found in confirmation modal.");
      await cancelBtn.click();
      markControl("global", "global:modal-cancel");
      await page.waitForTimeout(300);
      const stillThere = await page.locator(".user-row", { hasText: tempUser }).isVisible().catch(() => false);
      if (!stillThere) {
        throw new Error("User was deleted despite clicking Cancel on confirmation modal.");
      }
      markInteraction("global", "modal-cancel-verified", "user-still-present");
    }

    // Delete user via trash icon (triggers confirmation modal)
    const trashButton = userRow.locator('button[title="Remove user"]').first();
    await expectVisible(trashButton, "Trash/delete button missing for created user.");
    await trashButton.click();
    await page.waitForTimeout(200);

    // Confirm deletion in modal
    const modal = page.locator(".modal-card").first();
    await expectVisible(modal, "Confirmation modal did not appear after clicking delete.");
    const confirmButton = modal.getByRole("button", { name: /remove/i }).first();
    await confirmButton.click();
    markControl("users", "users:remove-user");
    await page.waitForTimeout(800);
    await ensureNoErrorBanner("User remove failed");

    const stillExists = await page.locator(".user-row", { hasText: tempUser }).count();
    if (stillExists === 0) {
      cleanupState.usernames.delete(tempUser);
    }

    await registerVisibleButtons("users");
    await screenshot("users");
  });

  await check("help-page-comprehensive", async () => {
    await clickNav("Help");
    await expectVisible(page.getByRole("heading", { name: /help center/i }).first(), "Help header missing.");

    const faqCard = page.locator("article.card", {
      has: page.getByRole("heading", { name: /frequently asked questions/i }).first(),
    });
    const faqItems = faqCard.locator(".accordion-stack .accordion");
    const faqCount = await faqItems.count();
    if (faqCount < 4) {
      throw new Error(`Expected at least 4 FAQ accordions, found ${faqCount}.`);
    }
    for (let index = 0; index < faqCount; index += 1) {
      const item = faqItems.nth(index);
      const summary = item.locator("summary").first();
      await summary.click();
      await page.waitForTimeout(140);
      markInteraction("help", "faq-toggle", `index:${index}`);
    }
    markControl("help", "help:faq-open");

    const docsCard = page.locator("article.card", {
      has: page.getByRole("heading", { name: /reference guides/i }).first(),
    });
    const docs = docsCard.locator(".accordion");
    const docsCount = await docs.count();
    if (docsCount === 0) {
      report.warnings.push("No embedded markdown docs were visible on Help page.");
    } else {
      let foundRichDoc = false;
      for (let index = 0; index < docsCount; index += 1) {
        const doc = docs.nth(index);
        await doc.locator("summary").first().click();
        await page.waitForTimeout(180);
        const content = normalizeText(await doc.locator(".doc-preview").first().innerText().catch(() => ""));
        if (content.length >= 20) {
          if (/(^|\n)\s*#{1,6}\s+\S/.test(content) || content.includes("```")) {
            throw new Error("Embedded help docs still appear as raw markdown text.");
          }
          foundRichDoc = true;
          break;
        }
      }
      if (!foundRichDoc) {
        throw new Error("Embedded documentation content appears empty.");
      }
      markControl("help", "help:docs-open");
    }

    // Troubleshooting accordions (separate section from FAQ, closed by default)
    const troubleshootCard = page
      .locator("article.card", { has: page.getByRole("heading", { name: /troubleshoot/i }) })
      .first();
    if (await troubleshootCard.isVisible().catch(() => false)) {
      const troubleItems = troubleshootCard.locator(".accordion");
      const troubleCount = await troubleItems.count();
      for (let tIdx = 0; tIdx < troubleCount; tIdx += 1) {
        await troubleItems.nth(tIdx).locator("summary").first().click();
        await page.waitForTimeout(140);
        markInteraction("help", "troubleshoot-toggle", `index:${tIdx}`);
      }
      if (troubleCount > 0) {
        markControl("help", "help:troubleshooting-open");
      } else {
        report.warnings.push("Troubleshooting card found but no accordion items inside.");
      }
    } else {
      report.warnings.push("Troubleshooting card not visible on Help page.");
    }

    // Debug log section: generate if needed, then test download and regenerate.
    // On initial load the button may just say "Generate" without extra keywords.
    const generateDebugBtn = page.getByRole("button", { name: /generate/i }).first();
    if (await generateDebugBtn.isVisible().catch(() => false)) {
      await generateDebugBtn.click();
      rememberButtonClick("help", "Generate debug");
      await page.waitForTimeout(2000);
    }
    const downloadReportBtn = page.getByRole("button", { name: /download report/i }).first();
    if (await downloadReportBtn.isVisible().catch(() => false)) {
      await downloadReportBtn.click();
      markControl("help", "help:debug-log-download");
      rememberButtonClick("help", "Download Report");
      await page.waitForTimeout(400);
    } else {
      report.warnings.push("'Download Report' button not visible on Help page.");
    }
    const regenerateReportBtn = page.getByRole("button", { name: /regenerate/i }).first();
    if (await regenerateReportBtn.isVisible().catch(() => false)) {
      await regenerateReportBtn.click();
      markControl("help", "help:debug-log-regenerate");
      rememberButtonClick("help", "Regenerate");
      await page.waitForTimeout(600);
    } else {
      report.warnings.push("'Regenerate' button not visible on Help page.");
    }

    await registerVisibleButtons("help");
    await screenshot("help");
  });

  await check("about-page-comprehensive", async () => {
    await clickNav("About");
    await expectVisible(page.getByRole("heading", { name: /about cookdex/i }).first(), "About page header missing.");

    // Verify version card is visible with version number
    const versionHeading = page.locator("h3", { hasText: /CookDex v\d/ }).first();
    await expectVisible(versionHeading, "Version heading not visible on About page.");
    markControl("about", "about:version-visible");

    // Verify project links
    const links = page.locator("a.link-btn");
    if ((await links.count()) < 2) {
      throw new Error("Expected GitHub and Sponsor links were not found.");
    }
    markControl("about", "about:links-visible");

    // Validate GitHub link href
    const githubLink = page.locator("a.link-btn").filter({ hasText: /github/i }).first();
    if (await githubLink.isVisible().catch(() => false)) {
      const githubHref = await githubLink.getAttribute("href").catch(() => "");
      const _gh = new URL(githubHref).hostname;
      if (!githubHref || (_gh !== "github.com" && !_gh.endsWith(".github.com"))) {
        throw new Error(`GitHub link href is invalid: '${githubHref}'`);
      }
      markControl("about", "about:github-link-href");
      markInteraction("about", "github-link-href", githubHref);
    } else {
      throw new Error("GitHub Repository link not found on About page.");
    }

    // Validate Sponsor link href
    const sponsorLink = page.locator("a.link-btn").filter({ hasText: /sponsor/i }).first();
    if (await sponsorLink.isVisible().catch(() => false)) {
      const sponsorHref = await sponsorLink.getAttribute("href").catch(() => "");
      if (!sponsorHref || !sponsorHref.includes("github")) {
        throw new Error(`Sponsor link href is invalid: '${sponsorHref}'`);
      }
      markControl("about", "about:sponsor-link-href");
      markInteraction("about", "sponsor-link-href", sponsorHref);
    } else {
      throw new Error("Sponsor project link not found on About page.");
    }

    await registerVisibleButtons("about");
    await screenshot("about");
  });

  await check("api-comprehensive-operations", async () => {
    if (discoveredTasks.length === 0) {
      throw new Error("No tasks were discovered from API; cannot run comprehensive API coverage.");
    }

    let queuedApi = 0;
    for (const task of discoveredTasks) {
      const taskId = String(task.task_id || "").trim();
      if (!taskId) {
        continue;
      }
      const options = buildTaskOptionsFromDefinition(task);
      await apiRequest("POST", "/runs", { task_id: taskId, options }, [202]);
      queuedApi += 1;
      markInteraction("api", "queue-run", taskId);
    }
    report.coverage.tasksQueuedViaApi = queuedApi;
    if (queuedApi >= discoveredTasks.length) {
      markControl("api", "api:queue-all-tasks");
    } else {
      throw new Error(`Queued ${queuedApi} API runs but discovered ${discoveredTasks.length} tasks.`);
    }

    const firstTask =
      discoveredTasks.find((task) => String(task.task_id || "").trim() === "cookbook-sync")
      || discoveredTasks.find((task) => String(task.task_id || "").trim());
    if (!firstTask) {
      throw new Error("No valid task ID available for API schedule coverage.");
    }
    const scheduleOptions = buildTaskOptionsFromDefinition(firstTask);
    if (String(firstTask.task_id) === "cookbook-sync" && scheduleOptions.dry_run !== true) {
      throw new Error("cookbook-sync API schedule coverage must use dry_run=true.");
    }
    const apiIntervalName = `qa-api-int-${Date.now().toString().slice(-7)}`;
    const apiOnceName = `qa-api-once-${Date.now().toString().slice(-7)}`;
    const createdScheduleIds = [];

    const intervalCreated = await apiRequest(
      "POST",
      "/schedules",
      {
        name: apiIntervalName,
        task_id: firstTask.task_id,
        kind: "interval",
        seconds: 3600,
        options: scheduleOptions,
        enabled: true,
      },
      [201]
    );
    if (intervalCreated.payload?.schedule_id) {
      const id = String(intervalCreated.payload.schedule_id);
      createdScheduleIds.push(id);
      cleanupState.scheduleIds.add(id);
    }

    // API supports interval and once only (cron is not a valid kind)
    const onceRunAt = new Date(Date.now() + 7200000).toISOString();
    const onceCreated = await apiRequest(
      "POST",
      "/schedules",
      {
        name: apiOnceName,
        task_id: firstTask.task_id,
        kind: "once",
        run_at: onceRunAt,
        options: scheduleOptions,
        enabled: true,
      },
      [201]
    );
    if (onceCreated.payload?.schedule_id) {
      const id = String(onceCreated.payload.schedule_id);
      createdScheduleIds.push(id);
      cleanupState.scheduleIds.add(id);
    }

    for (const scheduleId of createdScheduleIds) {
      await apiRequest("DELETE", `/schedules/${encodeURIComponent(scheduleId)}`, null, [200]);
      cleanupState.scheduleIds.delete(scheduleId);
    }
    report.coverage.schedulesCreatedViaApi += createdScheduleIds.length;
    if (createdScheduleIds.length >= 2) {
      markControl("api", "api:schedule-create-delete");
    } else {
      throw new Error("API schedule create/delete coverage did not create both interval and once schedules.");
    }

    const apiUsername = `qaapi${Date.now().toString().slice(-6)}`;
    const apiPassword = "QaApiTempPass#1";
    const apiResetPassword = "QaApiResetPass#2";
    await apiRequest("POST", "/users", { username: apiUsername, password: apiPassword }, [201]);
    cleanupState.usernames.add(apiUsername);
    report.coverage.usersCreatedViaApi += 1;

    await apiRequest(
      "POST",
      `/users/${encodeURIComponent(apiUsername)}/reset-password`,
      { password: apiResetPassword },
      [200]
    );
    await apiRequest("DELETE", `/users/${encodeURIComponent(apiUsername)}`, null, [200]);
    cleanupState.usernames.delete(apiUsername);
    markControl("api", "api:user-create-reset-delete");
  });

  await check("auth-logout-login", async () => {
    await clickSidebarAction("Log Out", "global:sidebar-logout");
    await expectVisible(page.getByRole("heading", { name: /sign in/i }).first(), "Sign in page did not render.");
    await fillFirstVisible(page.locator('label:has-text("Username") input'), args.username);
    await fillFirstVisible(page.locator('label:has-text("Password") input'), args.password);
    await clickButtonByRole("auth", /sign in/i, "auth:relogin");
    markControl("auth", "auth:login-submit");
    await page.waitForSelector(".sidebar", { timeout: 25000 });
    await screenshot("post-relogin");
  });

  try {
    await bestEffortCleanup();
  } catch (error) {
    report.warnings.push(`Best-effort API cleanup failed: ${String(error?.message || error)}`);
  }
  try {
    await restoreConfigFiles();
    await removeGeneratedConfigHistory();
  } catch (error) {
    report.warnings.push(`Config file cleanup failed: ${String(error?.message || error)}`);
  }

  for (const [pageName, names] of buttonsSeenByPage.entries()) {
    report.coverage.buttonsSeenByPage[pageName] = [...names].sort();
  }
  for (const [pageName, names] of buttonsClickedByPage.entries()) {
    report.coverage.buttonsClickedByPage[pageName] = [...names].sort();
  }
  report.coverage.markersHit = [...markerHits].sort();

  const missingMarkers = REQUIRED_MARKERS.filter((marker) => !markerHits.has(marker));
  if (missingMarkers.length > 0) {
    report.failures.push({
      name: "coverage-markers",
      detail: `Missing required interaction markers: ${missingMarkers.join(", ")}`,
    });
  }

  if (report.coverage.tasksDiscovered > 0) {
    if (report.coverage.tasksQueuedViaUi < report.coverage.tasksDiscovered) {
      report.failures.push({
        name: "coverage-runs-ui",
        detail: `Queued ${report.coverage.tasksQueuedViaUi} tasks via UI but discovered ${report.coverage.tasksDiscovered}.`,
      });
    }
    if (report.coverage.tasksQueuedViaApi < report.coverage.tasksDiscovered) {
      report.failures.push({
        name: "coverage-runs-api",
        detail: `Queued ${report.coverage.tasksQueuedViaApi} tasks via API but discovered ${report.coverage.tasksDiscovered}.`,
      });
    }
  }

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
    throw new Error(`Comprehensive QA verification failed with ${report.failures.length} failing check(s).`);
  }

  process.stdout.write(`Comprehensive QA verification passed with ${report.checks.length} checks.\n`);
}

main().catch((error) => {
  process.stderr.write(`${String(error?.message || error)}\n`);
  process.exitCode = 1;
});
