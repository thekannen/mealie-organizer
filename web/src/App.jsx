import React, { useEffect, useMemo, useState } from "react";

const NAV_ITEMS = [
  { id: "overview", label: "Overview" },
  { id: "runs", label: "Runs" },
  { id: "schedules", label: "Schedules" },
  { id: "environment", label: "Environment" },
  { id: "config", label: "Taxonomy" },
  { id: "users", label: "Users" },
];

const PAGE_META = {
  overview: {
    title: "System Overview",
    subtitle: "Live status for tasks, runs, schedules, and configuration coverage.",
  },
  runs: {
    title: "Start a Run",
    subtitle: "Pick a task and tune options with plain-language controls.",
  },
  schedules: {
    title: "Automated Schedules",
    subtitle: "Create recurring runs without writing cron JSON by hand.",
  },
  environment: {
    title: "Connections & Preferences",
    subtitle: "Manage runtime settings with friendly labels and secure secret storage.",
  },
  config: {
    title: "Taxonomy Editor",
    subtitle: "Edit supported files as line-based pills with touch-friendly controls.",
  },
  users: {
    title: "Users & Access",
    subtitle: "Create users, rotate passwords, and manage account access.",
  },
};

const CONFIG_LABELS = {
  config: "Advanced Config",
  categories: "Categories",
  tags: "Tags",
  cookbooks: "Cookbooks",
  labels: "Labels",
  tools: "Tools",
  units_aliases: "Unit Aliases",
};

function inferBasePath() {
  const known = "/organizer";
  if (window.location.pathname.startsWith(known)) {
    return known;
  }
  return "";
}

const BASE_PATH = inferBasePath();
const API = `${BASE_PATH}/api/v1`;

function safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function errorMessageFromPayload(payload, status) {
  if (payload && typeof payload === "object") {
    const detail = payload.detail ?? payload.message ?? payload.error;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    return `Request failed (${status})`;
  }
  return `Request failed (${status})`;
}

function normalizeErrorMessage(raw) {
  const text = String(raw || "").trim();
  if (!text) {
    return "Request failed.";
  }
  const parsed = safeJsonParse(text);
  if (parsed && typeof parsed === "object") {
    const detail = parsed.detail ?? parsed.message ?? parsed.error;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
  }
  return text;
}

function buildDefaultOptionValues(taskDefinition) {
  const values = {};
  for (const option of taskDefinition?.options || []) {
    if (option.default !== undefined && option.default !== null) {
      values[option.key] = option.default;
    }
  }
  return values;
}

function parseLineEditorContent(content) {
  if (!Array.isArray(content)) {
    return { mode: "json", listKind: "", items: [] };
  }

  const allStrings = content.every((item) => typeof item === "string");
  if (allStrings) {
    return {
      mode: "line-pills",
      listKind: "string",
      items: content.map((item) => String(item)),
    };
  }

  const allNameObjects = content.every(
    (item) =>
      item &&
      typeof item === "object" &&
      !Array.isArray(item) &&
      typeof item.name === "string" &&
      Object.keys(item).length === 1
  );

  if (allNameObjects) {
    return {
      mode: "line-pills",
      listKind: "name_object",
      items: content.map((item) => String(item.name)),
    };
  }

  return { mode: "json", listKind: "", items: [] };
}

function moveArrayItem(items, fromIndex, toIndex) {
  if (fromIndex === toIndex) {
    return items;
  }
  if (fromIndex < 0 || toIndex < 0 || fromIndex >= items.length || toIndex >= items.length) {
    return items;
  }
  const next = [...items];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  let body = options.body;
  if (body && typeof body !== "string") {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }

  const response = await fetch(`${API}${path}`, {
    ...options,
    headers,
    body,
    credentials: "include",
  });

  const contentType = response.headers.get("content-type") || "";
  let jsonPayload = null;
  let textPayload = "";

  if (contentType.includes("application/json")) {
    try {
      jsonPayload = await response.json();
    } catch {
      jsonPayload = null;
    }
  } else {
    textPayload = await response.text();
  }

  if (!response.ok) {
    if (jsonPayload !== null) {
      throw new Error(errorMessageFromPayload(jsonPayload, response.status));
    }
    throw new Error(textPayload || `Request failed (${response.status})`);
  }

  if (jsonPayload !== null) {
    return jsonPayload;
  }
  return textPayload;
}

function fieldFromOption(option, value, onChange) {
  if (option.type === "boolean") {
    return (
      <label key={option.key} className="field row">
        <span>{option.label}</span>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(option.key, event.target.checked)}
        />
      </label>
    );
  }

  if (option.type === "number") {
    return (
      <label key={option.key} className="field">
        <span>{option.label}</span>
        <input
          type="number"
          value={value ?? ""}
          onChange={(event) => onChange(option.key, event.target.value)}
        />
      </label>
    );
  }

  if (option.type === "integer") {
    return (
      <label key={option.key} className="field">
        <span>{option.label}</span>
        <input
          type="number"
          step="1"
          value={value ?? ""}
          onChange={(event) => onChange(option.key, event.target.value)}
        />
      </label>
    );
  }

  return (
    <label key={option.key} className="field">
      <span>{option.label}</span>
      <input
        type="text"
        value={value ?? ""}
        onChange={(event) => onChange(option.key, event.target.value)}
      />
    </label>
  );
}

function normalizeTaskOptions(task, values) {
  const payload = {};
  for (const option of task?.options || []) {
    const raw = values[option.key];
    if (raw === undefined || raw === null || raw === "") {
      continue;
    }
    if (option.type === "boolean") {
      payload[option.key] = Boolean(raw);
      continue;
    }
    if (option.type === "integer") {
      payload[option.key] = Number.parseInt(String(raw), 10);
      continue;
    }
    if (option.type === "number") {
      payload[option.key] = Number.parseFloat(String(raw));
      continue;
    }
    payload[option.key] = String(raw);
  }
  return payload;
}

export default function App() {
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [setupRequired, setSetupRequired] = useState(false);
  const [registerUsername, setRegisterUsername] = useState("admin");
  const [registerPassword, setRegisterPassword] = useState("");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [session, setSession] = useState(null);
  const [theme, setTheme] = useState(() => {
    const stored = window.localStorage.getItem("mo_webui_theme");
    if (stored === "light" || stored === "dark") {
      return stored;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [activePage, setActivePage] = useState("overview");

  const [tasks, setTasks] = useState([]);
  const [runs, setRuns] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [users, setUsers] = useState([]);
  const [selectedTask, setSelectedTask] = useState("");
  const [taskValues, setTaskValues] = useState({});
  const [runLog, setRunLog] = useState("");

  const [scheduleForm, setScheduleForm] = useState({
    name: "",
    task_id: "",
    kind: "interval",
    seconds: 3600,
    cron: "0 3 * * *",
    enabled: true,
  });
  const [scheduleOptionValues, setScheduleOptionValues] = useState({});

  const [configFiles, setConfigFiles] = useState([]);
  const [activeConfig, setActiveConfig] = useState("");
  const [activeConfigBody, setActiveConfigBody] = useState("{}\n");
  const [activeConfigMode, setActiveConfigMode] = useState("json");
  const [activeConfigListKind, setActiveConfigListKind] = useState("");
  const [activeConfigItems, setActiveConfigItems] = useState([]);
  const [configDraftItem, setConfigDraftItem] = useState("");
  const [dragIndex, setDragIndex] = useState(null);
  const [touchDragState, setTouchDragState] = useState(null);

  const [envSpecs, setEnvSpecs] = useState({});
  const [envDraft, setEnvDraft] = useState({});
  const [envClear, setEnvClear] = useState({});

  const [newUserUsername, setNewUserUsername] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [resetPasswords, setResetPasswords] = useState({});

  const selectedTaskDef = useMemo(
    () => tasks.find((item) => item.task_id === selectedTask) || null,
    [tasks, selectedTask]
  );

  const scheduleTaskDef = useMemo(
    () => tasks.find((item) => item.task_id === scheduleForm.task_id) || null,
    [tasks, scheduleForm.task_id]
  );

  const activePageMeta = PAGE_META[activePage] || PAGE_META.overview;

  const envList = useMemo(
    () =>
      Object.values(envSpecs || {}).sort((a, b) => {
        const aGroup = String(a.group || "");
        const bGroup = String(b.group || "");
        if (aGroup !== bGroup) {
          return aGroup.localeCompare(bGroup);
        }
        return String(a.label || a.key).localeCompare(String(b.label || b.key));
      }),
    [envSpecs]
  );

  const envGroups = useMemo(() => {
    const grouped = new Map();
    for (const item of envList) {
      const group = String(item.group || "General");
      if (!grouped.has(group)) {
        grouped.set(group, []);
      }
      grouped.get(group).push(item);
    }
    return [...grouped.entries()];
  }, [envList]);

  const runStats = useMemo(() => {
    const stats = { queued: 0, running: 0, succeeded: 0, failed: 0, canceled: 0 };
    for (const run of runs) {
      const key = String(run.status || "").toLowerCase();
      if (stats[key] !== undefined) {
        stats[key] += 1;
      }
    }
    return stats;
  }, [runs]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem("mo_webui_theme", theme);
  }, [theme]);

  function clearBanners() {
    setError("");
    setNotice("");
  }

  function handleError(exc) {
    setNotice("");
    setError(normalizeErrorMessage(exc?.message || exc));
  }

  async function refreshSession() {
    try {
      const payload = await api("/auth/session", { method: "GET" });
      setSession(payload);
      setError("");
      return true;
    } catch {
      setSession(null);
      return false;
    }
  }

  async function loadData() {
    try {
      const [taskPayload, runPayload, schedulePayload, settingsPayload, configPayload, usersPayload] =
        await Promise.all([
          api("/tasks"),
          api("/runs"),
          api("/schedules"),
          api("/settings"),
          api("/config/files"),
          api("/users"),
        ]);

      const nextTasks = taskPayload.items || [];
      setTasks(nextTasks);
      setRuns(runPayload.items || []);
      setSchedules(schedulePayload.items || []);
      setConfigFiles(configPayload.items || []);
      setUsers(usersPayload.items || []);

      const nextSpecs = settingsPayload.env || {};
      setEnvSpecs(nextSpecs);
      const nextDraft = {};
      for (const [key, item] of Object.entries(nextSpecs)) {
        nextDraft[key] = item.secret ? "" : String(item.value ?? "");
      }
      setEnvDraft(nextDraft);
      setEnvClear({});

      if (!selectedTask && nextTasks.length > 0) {
        setSelectedTask(nextTasks[0].task_id);
      }

      if (!scheduleForm.task_id && nextTasks.length > 0) {
        setScheduleForm((prev) => ({ ...prev, task_id: nextTasks[0].task_id }));
      }
    } catch (exc) {
      handleError(exc);
    }
  }

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      try {
        const payload = await api("/auth/bootstrap-status");
        if (!active) {
          return;
        }
        const required = Boolean(payload.setup_required);
        setSetupRequired(required);
        if (required) {
          setSession(null);
          return;
        }

        const ok = await refreshSession();
        if (ok) {
          await loadData();
        }
      } catch (exc) {
        if (active) {
          handleError(exc);
        }
      }
    }

    bootstrap();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setTaskValues(buildDefaultOptionValues(selectedTaskDef));
  }, [selectedTaskDef]);

  useEffect(() => {
    setScheduleOptionValues(buildDefaultOptionValues(scheduleTaskDef));
  }, [scheduleTaskDef]);

  async function registerFirstUser(event) {
    event.preventDefault();
    try {
      clearBanners();
      await api("/auth/register", {
        method: "POST",
        body: {
          username: registerUsername,
          password: registerPassword,
        },
      });
      setRegisterPassword("");
      setSetupRequired(false);
      await refreshSession();
      await loadData();
      setNotice("Admin account created.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function doLogin(event) {
    event.preventDefault();
    try {
      clearBanners();
      await api("/auth/login", { method: "POST", body: { username, password } });
      setPassword("");
      await refreshSession();
      await loadData();
      setNotice("Signed in successfully.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function doLogout() {
    try {
      clearBanners();
      await api("/auth/logout", { method: "POST" });
      setSession(null);
    } catch (exc) {
      handleError(exc);
    }
  }

  async function triggerRun() {
    if (!selectedTaskDef) {
      return;
    }
    try {
      clearBanners();
      const options = normalizeTaskOptions(selectedTaskDef, taskValues);
      await api("/runs", {
        method: "POST",
        body: { task_id: selectedTaskDef.task_id, options },
      });
      await loadData();
      setNotice("Run queued.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function fetchLog(runId) {
    try {
      clearBanners();
      const payload = await api(`/runs/${runId}/log`);
      setRunLog(payload);
      setNotice("");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function togglePolicy(taskId, value) {
    try {
      clearBanners();
      await api("/policies", {
        method: "PUT",
        body: { policies: { [taskId]: { allow_dangerous: value } } },
      });
      await loadData();
      setNotice("Policy updated.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function createSchedule(event) {
    event.preventDefault();
    if (!scheduleTaskDef) {
      setError("Select a task before saving a schedule.");
      return;
    }

    try {
      clearBanners();
      const options = normalizeTaskOptions(scheduleTaskDef, scheduleOptionValues);
      await api("/schedules", {
        method: "POST",
        body: {
          name: scheduleForm.name,
          task_id: scheduleForm.task_id,
          kind: scheduleForm.kind,
          seconds: scheduleForm.kind === "interval" ? Number(scheduleForm.seconds) : undefined,
          cron: scheduleForm.kind === "cron" ? scheduleForm.cron : undefined,
          options,
          enabled: Boolean(scheduleForm.enabled),
        },
      });
      await loadData();
      setNotice("Schedule saved.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function deleteSchedule(scheduleId) {
    try {
      clearBanners();
      await api(`/schedules/${scheduleId}`, { method: "DELETE" });
      await loadData();
      setNotice("Schedule removed.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function saveEnvironment() {
    try {
      clearBanners();
      const env = {};
      for (const item of envList) {
        const key = String(item.key);
        const nextValue = String(envDraft[key] ?? "");

        if (item.secret) {
          if (envClear[key] === true) {
            env[key] = null;
            continue;
          }
          if (nextValue.trim() !== "") {
            env[key] = nextValue;
          }
          continue;
        }

        const currentValue = String(item.value ?? "");
        if (nextValue !== currentValue) {
          env[key] = nextValue;
        }
      }

      if (Object.keys(env).length === 0) {
        setNotice("No setting changes to save.");
        return;
      }

      await api("/settings", {
        method: "PUT",
        body: { env },
      });

      await loadData();
      setNotice("Settings updated.");
    } catch (exc) {
      handleError(exc);
    }
  }

  function setConfigEditorState(content) {
    const editor = parseLineEditorContent(content);
    setActiveConfigMode(editor.mode);
    setActiveConfigListKind(editor.listKind);
    setActiveConfigItems(editor.items);
    setConfigDraftItem("");
    setDragIndex(null);
    setTouchDragState(null);
    setActiveConfigBody(`${JSON.stringify(content, null, 2)}\n`);
  }

  async function openConfig(name) {
    try {
      clearBanners();
      const payload = await api(`/config/files/${name}`);
      setActiveConfig(name);
      setConfigEditorState(payload.content);
    } catch (exc) {
      handleError(exc);
    }
  }

  function addConfigLine() {
    const nextValue = configDraftItem.trim();
    if (!nextValue) {
      return;
    }
    setActiveConfigItems((prev) => [...prev, nextValue]);
    setConfigDraftItem("");
  }

  function removeConfigLine(index) {
    setActiveConfigItems((prev) => prev.filter((_, rowIndex) => rowIndex !== index));
  }

  function updateConfigLine(index, value) {
    setActiveConfigItems((prev) => prev.map((item, rowIndex) => (rowIndex === index ? value : item)));
  }

  function moveConfigLine(fromIndex, toIndex) {
    setActiveConfigItems((prev) => moveArrayItem(prev, fromIndex, toIndex));
  }

  function handleLineTouchStart(index, event) {
    const touch = event.touches?.[0];
    if (!touch) {
      return;
    }
    setTouchDragState({ index, startX: touch.clientX });
  }

  function handleLineTouchEnd(index, event) {
    const touch = event.changedTouches?.[0];
    if (!touch || !touchDragState || touchDragState.index !== index) {
      return;
    }
    const deltaX = touch.clientX - touchDragState.startX;
    if (deltaX < -60) {
      removeConfigLine(index);
    }
    setTouchDragState(null);
  }

  async function saveConfig() {
    if (!activeConfig) {
      return;
    }

    try {
      clearBanners();
      let content;
      if (activeConfigMode === "line-pills") {
        const cleanItems = activeConfigItems.map((item) => String(item).trim()).filter(Boolean);
        if (activeConfigListKind === "string") {
          content = cleanItems;
        } else if (activeConfigListKind === "name_object") {
          content = cleanItems.map((name) => ({ name }));
        } else {
          throw new Error("Unsupported line editor mode for this file.");
        }
      } else {
        content = JSON.parse(activeConfigBody);
      }

      await api(`/config/files/${activeConfig}`, {
        method: "PUT",
        body: { content },
      });
      await loadData();
      setNotice("Config saved.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function createUser(event) {
    event.preventDefault();
    try {
      clearBanners();
      await api("/users", {
        method: "POST",
        body: {
          username: newUserUsername,
          password: newUserPassword,
        },
      });
      setNewUserUsername("");
      setNewUserPassword("");
      await loadData();
      setNotice("User created.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function resetUserPassword(usernameValue) {
    const nextPassword = String(resetPasswords[usernameValue] || "");
    if (!nextPassword.trim()) {
      setError("Enter a new password before resetting.");
      return;
    }

    try {
      clearBanners();
      await api(`/users/${encodeURIComponent(usernameValue)}/reset-password`, {
        method: "POST",
        body: { password: nextPassword },
      });
      setResetPasswords((prev) => ({ ...prev, [usernameValue]: "" }));
      setNotice(`Password updated for ${usernameValue}.`);
    } catch (exc) {
      handleError(exc);
    }
  }

  async function deleteUser(usernameValue) {
    try {
      clearBanners();
      await api(`/users/${encodeURIComponent(usernameValue)}`, { method: "DELETE" });
      await loadData();
      setNotice(`User removed: ${usernameValue}`);
    } catch (exc) {
      handleError(exc);
    }
  }

  function renderOverviewPage() {
    const cards = [
      { label: "Tasks", value: tasks.length },
      { label: "Runs", value: runs.length },
      { label: "Schedules", value: schedules.length },
      { label: "Users", value: users.length },
    ];

    return (
      <section className="page-grid">
        <article className="panel">
          <h2>System Snapshot</h2>
          <div className="stats-grid">
            {cards.map((card) => (
              <div className="stat-card" key={card.label}>
                <p className="label">{card.label}</p>
                <p className="value">{card.value}</p>
              </div>
            ))}
          </div>
          <div className="status-row">
            <span className="chip queued">Queued {runStats.queued}</span>
            <span className="chip running">Running {runStats.running}</span>
            <span className="chip success">Succeeded {runStats.succeeded}</span>
            <span className="chip failed">Failed {runStats.failed}</span>
            <span className="chip canceled">Canceled {runStats.canceled}</span>
          </div>
        </article>

        <article className="panel">
          <h2>Recent Runs</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={3}>No runs found yet.</td>
                  </tr>
                ) : (
                  runs.slice(0, 8).map((run) => (
                    <tr key={run.run_id}>
                      <td>{run.task_id}</td>
                      <td>{run.status}</td>
                      <td>{run.created_at}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    );
  }

  function renderRunsPage() {
    return (
      <section className="page-grid two-col">
        <article className="panel">
          <h2>Task Setup</h2>
          <label className="field">
            <span>Choose task</span>
            <select value={selectedTask} onChange={(event) => setSelectedTask(event.target.value)}>
              {tasks.map((task) => (
                <option value={task.task_id} key={task.task_id}>
                  {task.title}
                </option>
              ))}
            </select>
          </label>
          <div className="form-grid">
            {(selectedTaskDef?.options || []).map((option) =>
              fieldFromOption(option, taskValues[option.key], (key, value) =>
                setTaskValues((prev) => ({ ...prev, [key]: value }))
              )
            )}
          </div>
          {selectedTaskDef ? (
            <label className="field row">
              <span>Allow write changes for this task</span>
              <input
                type="checkbox"
                checked={Boolean(selectedTaskDef.policy?.allow_dangerous)}
                onChange={(event) => togglePolicy(selectedTaskDef.task_id, event.target.checked)}
              />
            </label>
          ) : null}
          <button onClick={triggerRun}>Start Run</button>
        </article>

        <article className="panel">
          <h2>Run History</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>When</th>
                  <th>Log</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No runs available yet.</td>
                  </tr>
                ) : (
                  runs.map((run) => (
                    <tr key={run.run_id}>
                      <td>{run.task_id}</td>
                      <td>{run.status}</td>
                      <td>{run.created_at}</td>
                      <td>
                        <button className="secondary" onClick={() => fetchLog(run.run_id)}>
                          View
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <pre className="log">{runLog || "Select a run to preview logs."}</pre>
        </article>
      </section>
    );
  }

  function renderSchedulesPage() {
    return (
      <section className="page-grid two-col">
        <article className="panel">
          <h2>Create Schedule</h2>
          <form onSubmit={createSchedule} className="form-grid">
            <label className="field">
              <span>Schedule name</span>
              <input
                value={scheduleForm.name}
                onChange={(event) => setScheduleForm((prev) => ({ ...prev, name: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>Task</span>
              <select
                value={scheduleForm.task_id}
                onChange={(event) => setScheduleForm((prev) => ({ ...prev, task_id: event.target.value }))}
              >
                <option value="">Select task</option>
                {tasks.map((task) => (
                  <option key={task.task_id} value={task.task_id}>
                    {task.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Run type</span>
              <select
                value={scheduleForm.kind}
                onChange={(event) => setScheduleForm((prev) => ({ ...prev, kind: event.target.value }))}
              >
                <option value="interval">Every X seconds</option>
                <option value="cron">Cron expression</option>
              </select>
            </label>
            {scheduleForm.kind === "interval" ? (
              <label className="field">
                <span>Seconds</span>
                <input
                  type="number"
                  value={scheduleForm.seconds}
                  onChange={(event) => setScheduleForm((prev) => ({ ...prev, seconds: event.target.value }))}
                />
              </label>
            ) : (
              <label className="field">
                <span>Cron</span>
                <input
                  value={scheduleForm.cron}
                  onChange={(event) => setScheduleForm((prev) => ({ ...prev, cron: event.target.value }))}
                />
              </label>
            )}

            {(scheduleTaskDef?.options || []).length > 0 ? (
              <div className="full-row inline-card">
                <h3>Task Options</h3>
                <div className="form-grid">
                  {(scheduleTaskDef?.options || []).map((option) =>
                    fieldFromOption(option, scheduleOptionValues[option.key], (key, value) =>
                      setScheduleOptionValues((prev) => ({ ...prev, [key]: value }))
                    )
                  )}
                </div>
              </div>
            ) : null}

            <label className="field row full-row">
              <span>Enabled</span>
              <input
                type="checkbox"
                checked={Boolean(scheduleForm.enabled)}
                onChange={(event) =>
                  setScheduleForm((prev) => ({ ...prev, enabled: event.target.checked }))
                }
              />
            </label>
            <button type="submit">Save Schedule</button>
          </form>
        </article>

        <article className="panel">
          <h2>Current Schedules</h2>
          <ul className="list">
            {schedules.length === 0 ? (
              <li>No schedules configured yet.</li>
            ) : (
              schedules.map((schedule) => (
                <li key={schedule.schedule_id} className="list-item-row">
                  <div>
                    <strong>{schedule.name}</strong>
                    <p className="muted-text small">
                      {schedule.task_id} | {schedule.schedule_kind} | next {schedule.next_run_at || "-"}
                    </p>
                  </div>
                  <button className="secondary" onClick={() => deleteSchedule(schedule.schedule_id)}>
                    Delete
                  </button>
                </li>
              ))
            )}
          </ul>
        </article>
      </section>
    );
  }

  function renderEnvironmentPage() {
    return (
      <section className="page-grid">
        <article className="panel">
          <h2>Connections & Preferences</h2>
          <p className="muted-text">
            Friendly labels are shown first. Technical keys are available for advanced troubleshooting.
          </p>
          <div className="env-groups">
            {envGroups.map(([groupName, items]) => (
              <section className="env-group" key={groupName}>
                <h3>{groupName}</h3>
                <div className="env-list">
                  {items.map((item) => {
                    const key = String(item.key);
                    const source = String(item.source || "unset");
                    const hasValue = Boolean(item.has_value);
                    return (
                      <div className="env-item" key={key}>
                        <label className="field">
                          <span>{item.label || key}</span>
                          <input
                            type={item.secret ? "password" : "text"}
                            value={envDraft[key] ?? ""}
                            placeholder={item.secret && hasValue ? "stored secret" : ""}
                            onChange={(event) => {
                              const nextValue = event.target.value;
                              setEnvDraft((prev) => ({ ...prev, [key]: nextValue }));
                              if (item.secret && envClear[key]) {
                                setEnvClear((prev) => ({ ...prev, [key]: false }));
                              }
                            }}
                          />
                        </label>
                        <div className="env-meta">
                          <span className="badge">source: {source}</span>
                          <span className="badge">key: {key}</span>
                          {item.secret ? (
                            <button
                              type="button"
                              className="secondary"
                              onClick={() => {
                                setEnvDraft((prev) => ({ ...prev, [key]: "" }));
                                setEnvClear((prev) => ({ ...prev, [key]: true }));
                              }}
                            >
                              Clear Secret
                            </button>
                          ) : null}
                        </div>
                        <p className="muted-text small">{item.description}</p>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
          <button onClick={saveEnvironment}>Save Settings</button>
        </article>
      </section>
    );
  }

  function renderConfigPage() {
    return (
      <section className="page-grid">
        <article className="panel">
          <h2>Taxonomy & Config Files</h2>
          <div className="config-grid">
            <aside>
              <ul className="list">
                {configFiles.length === 0 ? (
                  <li>No managed config files available.</li>
                ) : (
                  configFiles.map((item) => (
                    <li key={item.name}>
                      <button className="secondary" onClick={() => openConfig(item.name)}>
                        {CONFIG_LABELS[item.name] || item.name}
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </aside>
            <div>
              <h3>{CONFIG_LABELS[activeConfig] || "Choose a config file"}</h3>
              {activeConfigMode === "line-pills" ? (
                <section className="pill-editor">
                  <div className="pill-input-row">
                    <input
                      value={configDraftItem}
                      placeholder="Add line and press Enter"
                      onChange={(event) => setConfigDraftItem(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          addConfigLine();
                        }
                      }}
                    />
                    <button type="button" className="secondary" onClick={addConfigLine}>
                      Add
                    </button>
                  </div>
                  <ul className="pill-lines">
                    {activeConfigItems.map((item, index) => (
                      <li
                        key={`${activeConfig}-${index}`}
                        className="pill-line"
                        draggable
                        onDragStart={() => setDragIndex(index)}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => {
                          if (dragIndex !== null) {
                            moveConfigLine(dragIndex, index);
                            setDragIndex(null);
                          }
                        }}
                        onTouchStart={(event) => handleLineTouchStart(index, event)}
                        onTouchEnd={(event) => handleLineTouchEnd(index, event)}
                      >
                        <span className="line-index">{index + 1}</span>
                        <input
                          value={item}
                          onChange={(event) => updateConfigLine(index, event.target.value)}
                        />
                        <div className="line-actions">
                          <button
                            type="button"
                            className="secondary small"
                            onClick={() => moveConfigLine(index, Math.max(index - 1, 0))}
                            disabled={index === 0}
                          >
                            Up
                          </button>
                          <button
                            type="button"
                            className="secondary small"
                            onClick={() =>
                              moveConfigLine(index, Math.min(index + 1, activeConfigItems.length - 1))
                            }
                            disabled={index === activeConfigItems.length - 1}
                          >
                            Down
                          </button>
                          <button
                            type="button"
                            className="secondary small"
                            onClick={() => removeConfigLine(index)}
                          >
                            Remove
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                  <p className="muted-text small">
                    Mobile gestures: swipe left on a line to remove it.
                  </p>
                </section>
              ) : (
                <section>
                  <p className="muted-text small">
                    Advanced mode: this file needs full JSON editing because its structure is not a simple list.
                  </p>
                  <textarea
                    rows={18}
                    value={activeConfigBody}
                    onChange={(event) => setActiveConfigBody(event.target.value)}
                  />
                </section>
              )}

              <button onClick={saveConfig} disabled={!activeConfig}>
                Save File
              </button>
            </div>
          </div>
        </article>
      </section>
    );
  }

  function renderUsersPage() {
    return (
      <section className="page-grid two-col">
        <article className="panel">
          <h2>Create User</h2>
          <form className="form-grid" onSubmit={createUser}>
            <label className="field">
              <span>Username</span>
              <input
                value={newUserUsername}
                onChange={(event) => setNewUserUsername(event.target.value)}
                placeholder="kitchen-tablet"
              />
            </label>
            <label className="field">
              <span>Temporary password</span>
              <input
                type="password"
                value={newUserPassword}
                onChange={(event) => setNewUserPassword(event.target.value)}
                placeholder="At least 8 characters"
              />
            </label>
            <button className="full-row" type="submit">
              Create User
            </button>
          </form>
        </article>

        <article className="panel">
          <h2>Current Users</h2>
          <ul className="list user-list">
            {users.length === 0 ? (
              <li>No users available.</li>
            ) : (
              users.map((item) => (
                <li key={item.username} className="user-row">
                  <div className="user-row-head">
                    <strong>{item.username}</strong>
                    <span className="muted-text small">Created: {item.created_at}</span>
                  </div>
                  <div className="user-row-actions">
                    <input
                      type="password"
                      placeholder="New password"
                      value={resetPasswords[item.username] || ""}
                      onChange={(event) =>
                        setResetPasswords((prev) => ({ ...prev, [item.username]: event.target.value }))
                      }
                    />
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => resetUserPassword(item.username)}
                    >
                      Reset Password
                    </button>
                    {session?.username !== item.username ? (
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => deleteUser(item.username)}
                      >
                        Remove
                      </button>
                    ) : (
                      <span className="badge">active account</span>
                    )}
                  </div>
                </li>
              ))
            )}
          </ul>
        </article>
      </section>
    );
  }

  function renderPage() {
    if (activePage === "runs") {
      return renderRunsPage();
    }
    if (activePage === "schedules") {
      return renderSchedulesPage();
    }
    if (activePage === "environment") {
      return renderEnvironmentPage();
    }
    if (activePage === "config") {
      return renderConfigPage();
    }
    if (activePage === "users") {
      return renderUsersPage();
    }
    return renderOverviewPage();
  }

  if (setupRequired && !session) {
    return (
      <main className="shell auth-shell">
        <section className="panel auth-panel">
          <h1>Set Up Mealie Organizer</h1>
          <p>Create the first admin account to unlock the rest of the app.</p>
          <form onSubmit={registerFirstUser}>
            <label className="field">
              <span>Admin username</span>
              <input
                value={registerUsername}
                onChange={(event) => setRegisterUsername(event.target.value)}
              />
            </label>
            <label className="field">
              <span>Password</span>
              <input
                type="password"
                value={registerPassword}
                onChange={(event) => setRegisterPassword(event.target.value)}
              />
            </label>
            <button type="submit">Create Admin Account</button>
          </form>
          {error ? <div className="banner error">{error}</div> : null}
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="shell auth-shell">
        <section className="panel auth-panel">
          <h1>Mealie Organizer</h1>
          <p>Sign in to manage runs, schedules, and settings.</p>
          <form onSubmit={doLogin}>
            <label className="field">
              <span>Username</span>
              <input value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label className="field">
              <span>Password</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <button type="submit">Sign In</button>
          </form>
          {error ? <div className="banner error">{error}</div> : null}
        </section>
      </main>
    );
  }

  return (
    <main className="shell app-shell">
      <aside className="panel sidebar">
        <div className="sidebar-brand">
          <h1>Mealie Organizer</h1>
          <p className="muted-text">Web UI-first automation control center.</p>
        </div>
        <nav className="navbar">
          <div className="nav-shell vertical">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                className={`nav-btn ${activePage === item.id ? "active" : ""}`}
                onClick={() => setActivePage(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>
        <div className="sidebar-actions">
          <button className="secondary" onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}>
            {theme === "dark" ? "Light Mode" : "Dark Mode"}
          </button>
          <button className="secondary" onClick={loadData}>Refresh</button>
          <button onClick={doLogout}>Log Out</button>
        </div>
      </aside>

      <section className="content-shell">
        <header className="topbar panel">
          <h2>{activePageMeta.title}</h2>
          <p className="muted-text">{activePageMeta.subtitle}</p>
        </header>

        {error ? <div className="banner error">{error}</div> : null}
        {!error && notice ? <div className="banner info">{notice}</div> : null}

        {renderPage()}
      </section>
    </main>
  );
}
