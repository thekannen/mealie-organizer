import React, { useEffect, useMemo, useState } from "react";

function inferBasePath() {
  const known = "/organizer";
  if (window.location.pathname.startsWith(known)) {
    return known;
  }
  return "";
}

const BASE_PATH = inferBasePath();
const API = `${BASE_PATH}/api/v1`;

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
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed (${response.status})`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
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
  for (const option of task.options || []) {
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
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [session, setSession] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [runs, setRuns] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [settings, setSettings] = useState({});
  const [secrets, setSecrets] = useState({});
  const [selectedTask, setSelectedTask] = useState("");
  const [taskValues, setTaskValues] = useState({});
  const [runLog, setRunLog] = useState("");
  const [scheduleForm, setScheduleForm] = useState({
    name: "",
    task_id: "",
    kind: "interval",
    seconds: 3600,
    cron: "0 3 * * *",
    options_json: "{}",
    enabled: true,
  });
  const [configFiles, setConfigFiles] = useState([]);
  const [activeConfig, setActiveConfig] = useState("");
  const [activeConfigBody, setActiveConfigBody] = useState("{}\n");

  const selectedTaskDef = useMemo(
    () => tasks.find((item) => item.task_id === selectedTask) || null,
    [tasks, selectedTask]
  );

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
      const [taskPayload, runPayload, schedulePayload, settingsPayload, configPayload] = await Promise.all([
        api("/tasks"),
        api("/runs"),
        api("/schedules"),
        api("/settings"),
        api("/config/files"),
      ]);
      setTasks(taskPayload.items || []);
      setRuns(runPayload.items || []);
      setSchedules(schedulePayload.items || []);
      setSettings(settingsPayload.settings || {});
      setSecrets(settingsPayload.secrets || {});
      setConfigFiles(configPayload.items || []);
      if (!selectedTask && taskPayload.items?.length) {
        setSelectedTask(taskPayload.items[0].task_id);
      }
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  useEffect(() => {
    refreshSession().then((ok) => {
      if (ok) {
        loadData();
      }
    });
  }, []);

  useEffect(() => {
    if (!selectedTaskDef) {
      return;
    }
    const next = {};
    for (const option of selectedTaskDef.options || []) {
      if (option.default !== undefined && option.default !== null) {
        next[option.key] = option.default;
      }
    }
    setTaskValues(next);
  }, [selectedTaskDef]);

  async function doLogin(event) {
    event.preventDefault();
    try {
      await api("/auth/login", { method: "POST", body: { username, password } });
      setPassword("");
      await refreshSession();
      await loadData();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  async function doLogout() {
    try {
      await api("/auth/logout", { method: "POST" });
      setSession(null);
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  async function triggerRun() {
    if (!selectedTaskDef) {
      return;
    }
    try {
      const options = normalizeTaskOptions(selectedTaskDef, taskValues);
      await api("/runs", {
        method: "POST",
        body: { task_id: selectedTaskDef.task_id, options },
      });
      await loadData();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  async function fetchLog(runId) {
    try {
      const payload = await api(`/runs/${runId}/log`);
      setRunLog(payload);
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  async function togglePolicy(taskId, value) {
    try {
      await api("/policies", {
        method: "PUT",
        body: { policies: { [taskId]: { allow_dangerous: value } } },
      });
      await loadData();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  async function createSchedule(event) {
    event.preventDefault();
    try {
      const options = JSON.parse(scheduleForm.options_json || "{}");
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
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  async function saveSettings() {
    try {
      await api("/settings", {
        method: "PUT",
        body: { settings, secrets },
      });
      await loadData();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  async function openConfig(name) {
    try {
      const payload = await api(`/config/files/${name}`);
      setActiveConfig(name);
      setActiveConfigBody(`${JSON.stringify(payload.content, null, 2)}\n`);
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  async function saveConfig() {
    if (!activeConfig) {
      return;
    }
    try {
      await api(`/config/files/${activeConfig}`, {
        method: "PUT",
        body: { content: JSON.parse(activeConfigBody) },
      });
      await loadData();
    } catch (exc) {
      setError(String(exc.message || exc));
    }
  }

  if (!session) {
    return (
      <main className="shell">
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
          {error ? <pre className="error">{error}</pre> : null}
        </section>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>Mealie Organizer</h1>
          <p>Web control plane for parser, taxonomy, sync, and maintenance automation.</p>
        </div>
        <div className="topbar-actions">
          <button onClick={loadData}>Refresh</button>
          <button onClick={doLogout}>Log Out</button>
        </div>
      </header>

      {error ? <pre className="error">{error}</pre> : null}

      <section className="grid two">
        <article className="panel">
          <h2>Run Task</h2>
          <label className="field">
            <span>Task</span>
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
            <label className="field row muted">
              <span>Allow dangerous options</span>
              <input
                type="checkbox"
                checked={Boolean(selectedTaskDef.policy?.allow_dangerous)}
                onChange={(event) => togglePolicy(selectedTaskDef.task_id, event.target.checked)}
              />
            </label>
          ) : null}
          <button onClick={triggerRun}>Queue Run</button>
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
                {runs.map((run) => (
                  <tr key={run.run_id}>
                    <td>{run.task_id}</td>
                    <td>{run.status}</td>
                    <td>{run.created_at}</td>
                    <td>
                      <button onClick={() => fetchLog(run.run_id)}>View</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <pre className="log">{runLog || "Select a run log to inspect output."}</pre>
        </article>
      </section>

      <section className="grid two">
        <article className="panel">
          <h2>Schedules</h2>
          <form onSubmit={createSchedule} className="form-grid">
            <label className="field">
              <span>Name</span>
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
                    {task.task_id}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Type</span>
              <select
                value={scheduleForm.kind}
                onChange={(event) => setScheduleForm((prev) => ({ ...prev, kind: event.target.value }))}
              >
                <option value="interval">Interval</option>
                <option value="cron">Cron</option>
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
            <label className="field">
              <span>Options JSON</span>
              <textarea
                rows={4}
                value={scheduleForm.options_json}
                onChange={(event) =>
                  setScheduleForm((prev) => ({ ...prev, options_json: event.target.value }))
                }
              />
            </label>
            <label className="field row">
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
          <ul className="list">
            {schedules.map((schedule) => (
              <li key={schedule.schedule_id}>
                <strong>{schedule.name}</strong> {schedule.task_id} {schedule.schedule_kind} next:{" "}
                {schedule.next_run_at || "-"}
              </li>
            ))}
          </ul>
        </article>

        <article className="panel">
          <h2>Settings & Secrets</h2>
          <label className="field">
            <span>Settings JSON</span>
            <textarea
              rows={10}
              value={`${JSON.stringify(settings, null, 2)}`}
              onChange={(event) => {
                try {
                  setSettings(JSON.parse(event.target.value));
                } catch {
                  // Keep editing state in place; parse on save path.
                }
              }}
            />
          </label>
          <label className="field">
            <span>Secrets JSON (plain values overwrite masked values)</span>
            <textarea
              rows={8}
              value={`${JSON.stringify(secrets, null, 2)}`}
              onChange={(event) => {
                try {
                  setSecrets(JSON.parse(event.target.value));
                } catch {
                  // Keep editing state in place; parse on save path.
                }
              }}
            />
          </label>
          <button onClick={saveSettings}>Save Settings</button>
        </article>
      </section>

      <section className="panel">
        <h2>Config Files</h2>
        <div className="config-grid">
          <aside>
            <ul className="list">
              {configFiles.map((item) => (
                <li key={item.name}>
                  <button onClick={() => openConfig(item.name)}>{item.name}</button>
                </li>
              ))}
            </ul>
          </aside>
          <div>
            <h3>{activeConfig || "Choose a config file"}</h3>
            <textarea
              rows={18}
              value={activeConfigBody}
              onChange={(event) => setActiveConfigBody(event.target.value)}
            />
            <button onClick={saveConfig} disabled={!activeConfig}>
              Save Config File
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}