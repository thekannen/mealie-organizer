import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const NAV_LABELS = [
  "Overview",
  "Runs",
  "Schedules",
  "Settings",
  "Recipe Organization",
  "Users",
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
  "runs:queue-run",
  "runs:queue-all-discovered",
  "runs:filter-all",
  "runs:filter-manual",
  "runs:filter-scheduled",
  "runs:row-select",
  "schedules:save-interval",
  "schedules:save-cron",
  "settings:reload",
  "settings:apply",
  "settings:test-mealie",
  "settings:test-openai",
  "settings:test-ollama",
  "settings:policy-toggle",
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
  "about:refresh-metrics",
  "about:run-health-check",
  "about:view-run-history",
  "api:queue-all-tasks",
  "api:schedule-create-delete",
  "api:user-create-reset-delete",
  "auth:relogin",
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
          await textInput.fill("taxonomy-refresh");
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
          options[key] = "taxonomy-refresh";
        } else {
          options[key] = "";
        }
      }
    }
    return options;
  }

  async function readRunRows() {
    const rows = page.locator(".runs-history-card tbody tr");
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
      markControl("runs", "runs:row-select");
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
    await ensureNoErrorBanner("Overview refresh failed");
    await registerVisibleButtons("overview");
    await screenshot("overview");
  });

  await check("runs-page-comprehensive", async () => {
    await clickNav("Runs");
    await expectVisible(page.getByRole("heading", { name: /^runs$/i }), "Runs page header missing.");
    const taskSelect = page.locator('label:has-text("Task") select').first();
    await expectVisible(taskSelect, "Runs task selector missing.");

    const taskOptions = await taskSelect.evaluate((select) =>
      Array.from(select.options).map((opt) => ({ value: opt.value, label: (opt.textContent || "").trim() }))
    );
    const queueTargets = taskOptions.filter((item) => item.value);
    for (const item of queueTargets) {
      await taskSelect.selectOption(item.value);
      await page.waitForTimeout(140);
      await configureOptionFields(page.locator(".run-builder-card"));
      await clickButtonByRole("runs", "Queue Run", "runs:queue-run");
      await ensureNoErrorBanner(`Run queue failed: ${item.label}`);
      report.coverage.tasksQueuedViaUi += 1;
      markInteraction("runs", "queued-task", item.label);
      await page.waitForTimeout(280);
    }

    if (queueTargets.length > 0 && report.coverage.tasksQueuedViaUi >= queueTargets.length) {
      markControl("runs", "runs:queue-all-discovered");
    }

    const searchInput = page.locator(".runs-history-card .search-box input").first();
    if (await searchInput.isVisible().catch(() => false)) {
      await searchInput.fill("run");
      await searchInput.fill("");
    }

    await clickButtonByRole("runs", "All", "runs:filter-all");
    await clickButtonByRole("runs", "Manual", "runs:filter-manual");
    await clickButtonByRole("runs", "Scheduled", "runs:filter-scheduled");
    await clickButtonByRole("runs", "All", "runs:filter-all");

    const selected = await ensureRunRowSelection();
    if (!selected) {
      report.warnings.push("No run row available to select after queueing runs.");
    }

    await expectVisible(page.locator(".log-viewer"), "Run output viewer not rendered.");
    await registerVisibleButtons("runs");
    await screenshot("runs");
  });

  await check("schedules-page-comprehensive", async () => {
    await clickNav("Schedules");
    await expectVisible(page.getByRole("heading", { name: /schedules/i }).first(), "Schedules header missing.");

    const taskSelect = page.locator('label:has-text("Task") select').first();
    await expectVisible(taskSelect, "Schedules task selector missing.");
    const taskOptions = await taskSelect.evaluate((select) =>
      Array.from(select.options).map((option) => ({ value: option.value, label: (option.textContent || "").trim() }))
    );
    const validTask = taskOptions.find((item) => item.value);
    if (!validTask) {
      throw new Error("No task options available for schedule creation.");
    }
    await taskSelect.selectOption(validTask.value);

    const intervalName = `qa-ui-interval-${Date.now().toString().slice(-7)}`;
    await fillFirstVisible(page.locator('label:has-text("Schedule Name") input'), intervalName);
    await page.locator('label:has-text("Type") select').first().selectOption("interval");
    await fillFirstVisible(page.locator('label:has-text("Seconds") input'), "1800");
    await configureOptionFields(page.locator(".run-builder-card"));
    await clickButtonByRole("schedules", "Save Schedule", "schedules:save-interval");
    await ensureNoErrorBanner("Interval schedule save failed");
    await page.waitForTimeout(500);

    const cronName = `qa-ui-cron-${Date.now().toString().slice(-7)}`;
    await fillFirstVisible(page.locator('label:has-text("Schedule Name") input'), cronName);
    await page.locator('label:has-text("Type") select').first().selectOption("cron");
    await fillFirstVisible(page.locator('label:has-text("Cron Expression") input'), "*/30 * * * *");
    await configureOptionFields(page.locator(".run-builder-card"));
    await clickButtonByRole("schedules", "Save Schedule", "schedules:save-cron");
    await ensureNoErrorBanner("Cron schedule save failed");
    await page.waitForTimeout(500);

    const schedulesPayload = await apiRequest("GET", "/schedules", null, [200]);
    const items = schedulesPayload.payload?.items || [];
    const created = items.filter((item) => item.name === intervalName || item.name === cronName);
    if (created.length < 2) {
      throw new Error("Expected both interval and cron schedules to be created via UI.");
    }
    for (const item of created) {
      cleanupState.scheduleIds.add(String(item.schedule_id));
    }
    report.coverage.schedulesCreatedViaUi += created.length;

    const scheduleSearch = page.locator(".runs-history-card .search-box input").first();
    if (await scheduleSearch.isVisible().catch(() => false)) {
      await scheduleSearch.fill("categorize");
      await scheduleSearch.fill("");
    }

    const firstRow = page.locator(".runs-history-card tbody tr").first();
    if (await firstRow.isVisible().catch(() => false)) {
      const firstText = normalizeText(await firstRow.innerText());
      if (!firstText.toLowerCase().includes("no scheduled runs found")) {
        await firstRow.click();
        markInteraction("schedules", "select-run-row", firstText.slice(0, 120));
      }
    }

    await expectVisible(page.locator(".log-viewer"), "Schedules log viewer not rendered.");
    await registerVisibleButtons("schedules");
    await screenshot("schedules");
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

    const openAiKeyInput = page.locator('.settings-row:has-text("OpenAI API Key") input').first();
    await expectVisible(openAiKeyInput, "OpenAI API Key input missing.");

    const clearButtons = page.locator(".settings-row .settings-input-wrap .ghost.small");
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

    await runConnectionButton("Test Mealie", "Check Mealie URL/API key connectivity.", "settings:test-mealie");
    await runConnectionButton(
      "Test OpenAI API Key",
      "Validate OpenAI key and selected model.",
      "settings:test-openai"
    );
    await runConnectionButton(
      "Test Ollama Connection",
      "Validate Ollama endpoint reachability.",
      "settings:test-ollama"
    );

    const policyItems = page.locator(".policy-list li");
    if ((await policyItems.count()) > 0) {
      const firstPolicy = policyItems.first();
      const policyName = normalizeText(await firstPolicy.locator("strong").first().innerText().catch(() => ""));
      const policyTaskId = normalizeText(await firstPolicy.locator("p").first().innerText().catch(() => ""));
      const policyCheckbox = firstPolicy.locator('input[type="checkbox"]').first();
      const initialValue = await policyCheckbox.isChecked();
      await policyCheckbox.click();
      markControl("settings", "settings:policy-toggle");
      await page.waitForTimeout(650);
      await ensureNoErrorBanner(`Policy toggle failed for ${policyName || "first task"}`);

      if (policyTaskId) {
        await apiRequest("PUT", "/policies", {
          policies: {
            [policyTaskId]: {
              allow_dangerous: initialValue,
            },
          },
        }, [200]);
        await clickButtonByRole("settings", "Reload", "settings:reload");
      } else {
        const reloadedCheckbox = page.locator(".policy-list li").first().locator('input[type="checkbox"]').first();
        const currentValue = await reloadedCheckbox.isChecked();
        if (currentValue !== initialValue) {
          await reloadedCheckbox.click();
          await page.waitForTimeout(650);
        }
      }
      await ensureNoErrorBanner(`Policy reset failed for ${policyName || "first task"}`);
      markInteraction("settings", "policy-restored", policyName || "first task");
    } else {
      throw new Error("No policy toggles available on Settings page.");
    }

    await clickButtonByRole("settings", "Apply Changes", "settings:apply");
    await ensureNoErrorBanner("Settings apply failed");
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

    const pills = page.locator(".pill-btn");
    const pillCount = await pills.count();
    if (pillCount < 6) {
      throw new Error(`Expected 6 taxonomy pills, found ${pillCount}.`);
    }

    for (let index = 0; index < pillCount; index += 1) {
      const pill = pills.nth(index);
      const text = normalizeText(await pill.innerText()).toLowerCase();
      await pill.click();
      await page.waitForTimeout(200);
      const matched = markerByPillName.find((item) => text.includes(item.key));
      if (matched) {
        markControl("recipe", matched.marker);
        if (matched.configName === "cookbooks") {
          await expectVisible(
            page.locator(".cookbook-toolbar").first(),
            "Cookbooks taxonomy rendered as raw JSON instead of structured controls."
          );
          const advancedModeVisible = await page
            .getByText(/advanced mode: this file requires full json editing/i)
            .first()
            .isVisible()
            .catch(() => false);
          if (advancedModeVisible) {
            throw new Error("Cookbooks taxonomy unexpectedly fell back to advanced JSON editor mode.");
          }
        }
        if (matched.configName === "units_aliases") {
          await expectVisible(
            page.locator('.structured-editor label:has-text("Canonical Unit")').first(),
            "Units taxonomy rendered as raw JSON instead of canonical/aliases controls."
          );
        }
      }
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

    const importTextarea = page.locator('label:has-text("JSON Payload") textarea').first();
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
    await clickButtonByRole("users", "Generate", "users:generate-password");
    await fillFirstVisible(page.locator('label:has-text("Username") input').first(), tempUser);
    await clickButtonByRole("users", "Create User", "users:create-user");
    await ensureNoErrorBanner("User create failed");
    cleanupState.usernames.add(tempUser);
    report.coverage.usersCreatedViaUi += 1;

    const row = page.locator("tr", { hasText: tempUser }).first();
    await expectVisible(row, "Created user row was not found.");
    const createdUserRowText = normalizeText(await row.innerText().catch(() => ""));
    if (!createdUserRowText.toLowerCase().includes(tempUser.toLowerCase())) {
      throw new Error("Created user row appears visually wrapped/truncated and username is not readable.");
    }
    await row.locator('input[placeholder="New password"]').fill(resetPassword);
    await row.getByRole("button", { name: /^reset$/i }).first().click();
    markControl("users", "users:reset-password");
    await page.waitForTimeout(650);
    await ensureNoErrorBanner("User reset password failed");

    const userSearchInput = page.locator(".search-box input").first();
    if (await userSearchInput.isVisible().catch(() => false)) {
      await userSearchInput.fill(tempUser);
      await userSearchInput.fill("");
    }

    const removeButton = row.getByRole("button", { name: /^remove$/i }).first();
    await expectVisible(removeButton, "Remove button missing for created user.");
    await removeButton.click();
    markControl("users", "users:remove-user");
    await page.waitForTimeout(800);
    await ensureNoErrorBanner("User remove failed");

    const stillExists = await page.locator("tr", { hasText: tempUser }).count();
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
      has: page.getByRole("heading", { name: /setup faq/i }).first(),
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
      has: page.getByRole("heading", { name: /setup and troubleshooting/i }).first(),
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

    await registerVisibleButtons("help");
    await screenshot("help");
  });

  await check("about-page-comprehensive", async () => {
    await clickNav("About");
    await expectVisible(page.getByRole("heading", { name: /about cookdex/i }).first(), "About page header missing.");

    const links = page.locator("a.link-btn");
    if ((await links.count()) < 2) {
      throw new Error("Expected GitHub and Sponsor links were not found.");
    }

    await clickButtonByRole("about", "Refresh Metrics", "about:refresh-metrics");
    await ensureNoErrorBanner("About refresh metrics failed");
    await clickButtonByRole("about", "Run Health Check", "about:run-health-check");
    await ensureNoErrorBanner("About run health check failed");
    await clickButtonByRole("about", "View Run History", "about:view-run-history");
    await expectVisible(page.getByRole("heading", { name: /^runs$/i }), "View Run History did not navigate to Runs.");

    await clickNav("About");
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

    const firstTask = discoveredTasks.find((task) => String(task.task_id || "").trim());
    if (!firstTask) {
      throw new Error("No valid task ID available for API schedule coverage.");
    }
    const scheduleOptions = buildTaskOptionsFromDefinition(firstTask);
    const apiIntervalName = `qa-api-int-${Date.now().toString().slice(-7)}`;
    const apiCronName = `qa-api-cron-${Date.now().toString().slice(-7)}`;
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

    const cronCreated = await apiRequest(
      "POST",
      "/schedules",
      {
        name: apiCronName,
        task_id: firstTask.task_id,
        kind: "cron",
        cron: "*/20 * * * *",
        options: scheduleOptions,
        enabled: true,
      },
      [201]
    );
    if (cronCreated.payload?.schedule_id) {
      const id = String(cronCreated.payload.schedule_id);
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
      throw new Error("API schedule create/delete coverage did not create both interval and cron schedules.");
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
