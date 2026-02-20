import React, { useEffect, useMemo, useState } from "react";
import wordmark from "./assets/CookDex_wordmark.png";
import emblem from "./assets/CookDex_light.png";

import { NAV_ITEMS, PAGE_META, CONFIG_LABELS, TAXONOMY_FILE_NAMES, HELP_FAQ } from "./constants";
import {
  api,
  buildDefaultOptionValues,
  fieldFromOption,
  formatDateTime,
  formatRunTime,
  moveArrayItem,
  normalizeCookbookEntries,
  normalizeErrorMessage,
  normalizeTaskOptions,
  normalizeUnitAliasEntries,
  parseAliasInput,
  parseIso,
  parseLineEditorContent,
  renderMarkdownDocument,
  runTypeLabel,
  statusClass,
  userRoleLabel,
} from "./utils.jsx";
import Icon from "./components/Icon";
import CoverageRing from "./components/CoverageRing";

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
    const stored = window.localStorage.getItem("cookdex_webui_theme");
    if (stored === "light" || stored === "dark") {
      return stored;
    }
    return "light";
  });

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activePage, setActivePage] = useState("overview");

  const [tasks, setTasks] = useState([]);
  const [runs, setRuns] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [users, setUsers] = useState([]);

  const [selectedTask, setSelectedTask] = useState("");
  const [taskValues, setTaskValues] = useState({});
  const [runSearch, setRunSearch] = useState("");
  const [runTypeFilter, setRunTypeFilter] = useState("all");
  const [runLog, setRunLog] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");

  const [scheduleSearch, setScheduleSearch] = useState("");
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
  const [activeConfig, setActiveConfig] = useState("categories");
  const [activeConfigBody, setActiveConfigBody] = useState("[]\n");
  const [activeConfigMode, setActiveConfigMode] = useState("line-pills");
  const [activeConfigListKind, setActiveConfigListKind] = useState("name_object");
  const [activeConfigItems, setActiveConfigItems] = useState([]);
  const [activeCookbookItems, setActiveCookbookItems] = useState([]);
  const [activeUnitAliasItems, setActiveUnitAliasItems] = useState([]);
  const [configDraftItem, setConfigDraftItem] = useState("");
  const [cookbookDraft, setCookbookDraft] = useState({
    name: "",
    description: "",
    queryFilterString: "",
    public: false,
    position: 1,
  });
  const [unitDraftCanonical, setUnitDraftCanonical] = useState("");
  const [unitDraftAliases, setUnitDraftAliases] = useState("");
  const [dragIndex, setDragIndex] = useState(null);

  const [importTarget, setImportTarget] = useState("categories");
  const [importJsonText, setImportJsonText] = useState("");

  const [envSpecs, setEnvSpecs] = useState({});
  const [envDraft, setEnvDraft] = useState({});
  const [envClear, setEnvClear] = useState({});
  const [connectionChecks, setConnectionChecks] = useState({
    mealie: { loading: false, ok: null, detail: "" },
    openai: { loading: false, ok: null, detail: "" },
    ollama: { loading: false, ok: null, detail: "" },
  });

  const [newUserUsername, setNewUserUsername] = useState("");
  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserRole, setNewUserRole] = useState("Editor");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [resetPasswords, setResetPasswords] = useState({});

  const [taxonomyItemsByFile, setTaxonomyItemsByFile] = useState({});
  const [helpDocs, setHelpDocs] = useState([]);
  const [overviewMetrics, setOverviewMetrics] = useState(null);
  const [aboutMeta, setAboutMeta] = useState(null);
  const [healthMeta, setHealthMeta] = useState(null);
  const [lastLoadedAt, setLastLoadedAt] = useState("");

  const selectedTaskDef = useMemo(
    () => tasks.find((item) => item.task_id === selectedTask) || null,
    [tasks, selectedTask]
  );

  const scheduleTaskDef = useMemo(
    () => tasks.find((item) => item.task_id === scheduleForm.task_id) || null,
    [tasks, scheduleForm.task_id]
  );

  const activePageMeta = PAGE_META[activePage] || PAGE_META.overview;

  const taskTitleById = useMemo(() => {
    const map = new Map();
    for (const task of tasks) {
      map.set(task.task_id, task.title || task.task_id);
    }
    return map;
  }, [tasks]);

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

  const visibleEnvGroups = useMemo(() => {
    const grouped = new Map();
    for (const item of envList) {
      const groupName = String(item.group || "General");
      if (groupName === "Web UI" || groupName === "Behavior") {
        continue;
      }
      if (!grouped.has(groupName)) {
        grouped.set(groupName, []);
      }
      grouped.get(groupName).push(item);
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

  const filteredRuns = useMemo(() => {
    const source =
      runTypeFilter === "manual"
        ? runs.filter((run) => !run.schedule_id)
        : runTypeFilter === "scheduled"
        ? runs.filter((run) => Boolean(run.schedule_id))
        : runs;
    const query = runSearch.trim().toLowerCase();
    if (!query) {
      return source;
    }
    return source.filter((run) => {
      const taskLabel = taskTitleById.get(run.task_id) || run.task_id;
      const fields = [taskLabel, run.task_id, run.status, runTypeLabel(run), run.triggered_by, run.run_id]
        .join(" ")
        .toLowerCase();
      return fields.includes(query);
    });
  }, [runs, runSearch, runTypeFilter, taskTitleById]);

  const filteredScheduledRuns = useMemo(() => {
    const source = runs.filter((run) => Boolean(run.schedule_id));
    const query = scheduleSearch.trim().toLowerCase();
    if (!query) {
      return source;
    }
    return source.filter((run) => {
      const taskLabel = taskTitleById.get(run.task_id) || run.task_id;
      const fields = [taskLabel, run.task_id, run.status, run.schedule_id || ""].join(" ").toLowerCase();
      return fields.includes(query);
    });
  }, [runs, scheduleSearch, taskTitleById]);

  const filteredUsers = useMemo(() => {
    const query = userSearch.trim().toLowerCase();
    if (!query) {
      return users;
    }
    return users.filter((item) => {
      const username = String(item.username || "");
      const inferredRole = username === session?.username ? "owner" : "editor";
      return `${username} ${inferredRole}`.toLowerCase().includes(query);
    });
  }, [users, userSearch, session]);

  const taxonomyCounts = useMemo(() => {
    const rows = {};
    for (const name of TAXONOMY_FILE_NAMES) {
      const content = taxonomyItemsByFile[name];
      rows[name] = Array.isArray(content) ? content.length : 0;
    }
    return rows;
  }, [taxonomyItemsByFile]);

  const overviewTotals = useMemo(() => {
    const liveTotals = overviewMetrics?.totals || {};
    return {
      recipes: liveTotals.recipes ?? 0,
      ingredients: liveTotals.ingredients ?? 0,
      categories: liveTotals.categories ?? taxonomyCounts.categories ?? 0,
      tags: liveTotals.tags ?? taxonomyCounts.tags ?? 0,
      tools: liveTotals.tools ?? taxonomyCounts.tools ?? 0,
      labels: liveTotals.labels ?? taxonomyCounts.labels ?? 0,
      units: liveTotals.units ?? taxonomyCounts.units_aliases ?? 0,
    };
  }, [overviewMetrics, taxonomyCounts]);

  const overviewCoverage = useMemo(
    () => overviewMetrics?.coverage || { categories: 0, tags: 0, tools: 0 },
    [overviewMetrics]
  );

  const sortedRuns = useMemo(() => {
    const copy = [...runs];
    copy.sort((a, b) => {
      const aTs = parseIso(a.started_at || a.created_at)?.getTime() || 0;
      const bTs = parseIso(b.started_at || b.created_at)?.getTime() || 0;
      return bTs - aTs;
    });
    return copy;
  }, [runs]);

  const runsTodayCount = useMemo(() => {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    return sortedRuns.filter((run) => {
      const ts = parseIso(run.started_at || run.created_at)?.getTime() || 0;
      return ts >= start;
    }).length;
  }, [sortedRuns]);

  const latestFailureLabel = useMemo(() => {
    const failed = sortedRuns.find((run) => String(run.status || "").toLowerCase() === "failed");
    if (!failed) {
      return "None";
    }
    const ts = parseIso(failed.finished_at || failed.started_at || failed.created_at);
    if (!ts) {
      return "Unknown";
    }
    const deltaMs = Date.now() - ts.getTime();
    const deltaDays = Math.floor(deltaMs / (24 * 60 * 60 * 1000));
    if (deltaDays <= 0) {
      return "Today";
    }
    return `${deltaDays}d ago`;
  }, [sortedRuns]);

  const upcomingScheduleCount = useMemo(() => {
    const now = Date.now();
    const nextDay = now + 24 * 60 * 60 * 1000;
    return schedules.filter((schedule) => {
      const ts = parseIso(schedule.next_run_at)?.getTime();
      return Boolean(ts && ts >= now && ts <= nextDay);
    }).length;
  }, [schedules]);

  const taskMixRows = useMemo(() => {
    const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const counts = new Map();
    for (const run of runs) {
      const ts = parseIso(run.started_at || run.created_at)?.getTime();
      if (!ts || ts < weekAgo) {
        continue;
      }
      const taskId = String(run.task_id || "");
      const key = taskTitleById.get(taskId) || taskId || "Unknown";
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    const rows = [...counts.entries()]
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 3);
    const total = rows.reduce((sum, row) => sum + row.count, 0) || 1;
    return rows.map((row) => ({ ...row, percent: Math.round((row.count / total) * 100) }));
  }, [runs, taskTitleById]);

  const upcomingScheduleRows = useMemo(() => {
    const rows = [...schedules]
      .filter((schedule) => parseIso(schedule.next_run_at))
      .sort((a, b) => {
        const aTs = parseIso(a.next_run_at)?.getTime() || Number.MAX_SAFE_INTEGER;
        const bTs = parseIso(b.next_run_at)?.getTime() || Number.MAX_SAFE_INTEGER;
        return aTs - bTs;
      })
      .slice(0, 3);

    return rows.map((schedule) => ({
      id: schedule.schedule_id,
      label: taskTitleById.get(schedule.task_id) || schedule.task_id || schedule.name || "Scheduled task",
      nextRun: formatDateTime(schedule.next_run_at),
    }));
  }, [schedules, taskTitleById]);

  const latestRun = useMemo(() => sortedRuns[0] || null, [sortedRuns]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem("cookdex_webui_theme", theme);
  }, [theme]);

  useEffect(() => {
    setTaskValues(buildDefaultOptionValues(selectedTaskDef));
  }, [selectedTaskDef]);

  useEffect(() => {
    setScheduleOptionValues(buildDefaultOptionValues(scheduleTaskDef));
  }, [scheduleTaskDef]);

  function clearBanners() {
    setError("");
    setNotice("");
  }

  function handleError(exc) {
    setNotice("");
    setError(normalizeErrorMessage(exc?.message || exc));
  }

  function setConfigEditorState(content, configName = activeConfig) {
    const editor = parseLineEditorContent(content, configName);
    setActiveConfigMode(editor.mode);
    setActiveConfigListKind(editor.listKind);
    setActiveConfigItems(editor.mode === "line-pills" ? editor.items : []);
    setActiveCookbookItems(editor.mode === "cookbook-cards" ? editor.items : []);
    setActiveUnitAliasItems(editor.mode === "unit-aliases" ? editor.items : []);
    setConfigDraftItem("");
    setCookbookDraft({
      name: "",
      description: "",
      queryFilterString: "",
      public: false,
      position: Math.max(1, (editor.mode === "cookbook-cards" ? editor.items.length : 0) + 1),
    });
    setUnitDraftCanonical("");
    setUnitDraftAliases("");
    setDragIndex(null);
    setActiveConfigBody(`${JSON.stringify(content, null, 2)}\n`);
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

  async function loadTaxonomyContent() {
    const responses = await Promise.all(
      TAXONOMY_FILE_NAMES.map((name) => api(`/config/files/${name}`).catch(() => null))
    );

    const next = {};
    for (const payload of responses) {
      if (!payload || !payload.name) {
        continue;
      }
      next[payload.name] = payload.content;
    }
    setTaxonomyItemsByFile(next);

    if (activeConfig && next[activeConfig]) {
      setConfigEditorState(next[activeConfig], activeConfig);
    } else if (!activeConfig && next.categories) {
      setActiveConfig("categories");
      setConfigEditorState(next.categories, "categories");
    }
  }

  async function loadData() {
    try {
      const [
        taskPayload,
        runPayload,
        schedulePayload,
        settingsPayload,
        configPayload,
        usersPayload,
        helpPayload,
        metricsPayload,
        aboutPayload,
        healthPayload,
      ] = await Promise.all([
        api("/tasks"),
        api("/runs"),
        api("/schedules"),
        api("/settings"),
        api("/config/files"),
        api("/users"),
        api("/help/docs").catch(() => ({ items: [] })),
        api("/metrics/overview").catch(() => null),
        api("/about/meta").catch(() => null),
        api("/health").catch(() => null),
      ]);

      const nextTasks = taskPayload.items || [];
      const nextRuns = runPayload.items || [];
      const nextSchedules = schedulePayload.items || [];

      setTasks(nextTasks);
      setRuns(nextRuns);
      setSchedules(nextSchedules);
      setConfigFiles(configPayload.items || []);
      setUsers(usersPayload.items || []);
      setHelpDocs(helpPayload.items || []);
      setOverviewMetrics(metricsPayload);
      setAboutMeta(aboutPayload);
      setHealthMeta(healthPayload);
      setLastLoadedAt(new Date().toISOString());

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

      await loadTaxonomyContent();
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
      setRuns([]);
      setSchedules([]);
      setUsers([]);
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
      setRunLog(payload || "");
      setSelectedRunId(runId);
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
      setNotice("Task policy updated.");
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

  function configDraftValue(index, value) {
    setActiveConfigItems((prev) => prev.map((item, rowIndex) => (rowIndex === index ? value : item)));
  }

  function addConfigLine() {
    const value = configDraftItem.trim();
    if (!value) {
      return;
    }
    setActiveConfigItems((prev) => [...prev, value]);
    setConfigDraftItem("");
  }

  function removeConfigLine(index) {
    setActiveConfigItems((prev) => prev.filter((_, rowIndex) => rowIndex !== index));
  }

  function moveConfigLine(fromIndex, toIndex) {
    setActiveConfigItems((prev) => moveArrayItem(prev, fromIndex, toIndex));
  }

  function updateCookbookEntry(index, key, value) {
    setActiveCookbookItems((prev) =>
      prev.map((item, rowIndex) => (rowIndex === index ? { ...item, [key]: value } : item))
    );
  }

  function addCookbookEntry() {
    const name = String(cookbookDraft.name || "").trim();
    if (!name) {
      return;
    }
    const parsedPosition = Number.parseInt(String(cookbookDraft.position || ""), 10);
    const nextPosition = Number.isFinite(parsedPosition) && parsedPosition > 0 ? parsedPosition + 1 : 1;
    setActiveCookbookItems((prev) => [
      ...prev,
      {
        name,
        description: String(cookbookDraft.description || "").trim(),
        queryFilterString: String(cookbookDraft.queryFilterString || "").trim(),
        public: Boolean(cookbookDraft.public),
        position: Number.isFinite(parsedPosition) && parsedPosition > 0 ? parsedPosition : prev.length + 1,
      },
    ]);
    setCookbookDraft((prev) => ({
      ...prev,
      name: "",
      description: "",
      queryFilterString: "",
      public: false,
      position: nextPosition,
    }));
  }

  function removeCookbookEntry(index) {
    setActiveCookbookItems((prev) => prev.filter((_, rowIndex) => rowIndex !== index));
  }

  function moveCookbookEntry(fromIndex, toIndex) {
    setActiveCookbookItems((prev) => moveArrayItem(prev, fromIndex, toIndex));
  }

  function updateUnitAliasEntry(index, key, value) {
    if (key === "aliases") {
      const aliases = Array.isArray(value) ? value : parseAliasInput(value);
      setActiveUnitAliasItems((prev) =>
        prev.map((item, rowIndex) => (rowIndex === index ? { ...item, aliases } : item))
      );
      return;
    }
    setActiveUnitAliasItems((prev) =>
      prev.map((item, rowIndex) => (rowIndex === index ? { ...item, [key]: value } : item))
    );
  }

  function addUnitAliasEntry() {
    const canonical = String(unitDraftCanonical || "").trim();
    if (!canonical) {
      return;
    }
    const aliases = parseAliasInput(unitDraftAliases);
    setActiveUnitAliasItems((prev) => [...prev, { canonical, aliases }]);
    setUnitDraftCanonical("");
    setUnitDraftAliases("");
  }

  function removeUnitAliasEntry(index) {
    setActiveUnitAliasItems((prev) => prev.filter((_, rowIndex) => rowIndex !== index));
  }

  function moveUnitAliasEntry(fromIndex, toIndex) {
    setActiveUnitAliasItems((prev) => moveArrayItem(prev, fromIndex, toIndex));
  }

  async function openConfig(name) {
    try {
      clearBanners();
      const payload = await api(`/config/files/${name}`);
      setActiveConfig(name);
      setConfigEditorState(payload.content, name);
    } catch (exc) {
      handleError(exc);
    }
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
          content = cleanItems;
        }
      } else if (activeConfigMode === "cookbook-cards") {
        content = normalizeCookbookEntries(activeCookbookItems);
      } else if (activeConfigMode === "unit-aliases") {
        content = normalizeUnitAliasEntries(activeUnitAliasItems);
      } else {
        const parsed = JSON.parse(activeConfigBody);
        content = parsed;
      }

      await api(`/config/files/${activeConfig}`, {
        method: "PUT",
        body: { content },
      });

      if (TAXONOMY_FILE_NAMES.includes(activeConfig) && Array.isArray(content)) {
        setTaxonomyItemsByFile((prev) => ({ ...prev, [activeConfig]: content }));
      }

      setConfigEditorState(content, activeConfig);
      await loadData();
      setNotice(`${CONFIG_LABELS[activeConfig] || activeConfig} saved.`);
    } catch (exc) {
      handleError(exc);
    }
  }

  async function importTaxonomyJson() {
    try {
      clearBanners();
      const target = importTarget;
      const payload = JSON.parse(importJsonText);
      if (!Array.isArray(payload)) {
        setError("Imported JSON must be an array for taxonomy files.");
        return;
      }

      await api(`/config/files/${target}`, {
        method: "PUT",
        body: { content: payload },
      });

      setImportJsonText("");
      if (activeConfig === target) {
        setConfigEditorState(payload, target);
      }
      await loadData();
      setNotice(`${CONFIG_LABELS[target] || target} imported from JSON.`);
    } catch (exc) {
      handleError(exc);
    }
  }

  function generateTemporaryPassword() {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%";
    let value = "";
    for (let index = 0; index < 14; index += 1) {
      value += chars[Math.floor(Math.random() * chars.length)];
    }
    setNewUserPassword(value);
  }

  async function createUser(event) {
    event.preventDefault();
    try {
      clearBanners();
      await api("/users", {
        method: "POST",
        body: { username: newUserUsername, password: newUserPassword },
      });
      setNewUserUsername("");
      setNewUserEmail("");
      setNewUserRole("Editor");
      setNewUserPassword("");
      await loadData();
      setNotice("User created.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function resetUserPassword(usernameValue) {
    const nextPassword = String(resetPasswords[usernameValue] || "").trim();
    if (!nextPassword) {
      setError("Enter a replacement password first.");
      return;
    }
    try {
      clearBanners();
      await api(`/users/${encodeURIComponent(usernameValue)}/reset-password`, {
        method: "POST",
        body: { password: nextPassword },
      });
      setResetPasswords((prev) => ({ ...prev, [usernameValue]: "" }));
      setNotice(`Password reset for ${usernameValue}.`);
    } catch (exc) {
      handleError(exc);
    }
  }

  async function deleteUser(usernameValue) {
    try {
      clearBanners();
      await api(`/users/${encodeURIComponent(usernameValue)}`, { method: "DELETE" });
      await loadData();
      setNotice(`Removed ${usernameValue}.`);
    } catch (exc) {
      handleError(exc);
    }
  }

  function draftOverrideValue(key) {
    const value = String(envDraft[key] ?? "").trim();
    if (!value) {
      return null;
    }
    return value;
  }

  async function runConnectionTest(kind) {
    try {
      setConnectionChecks((prev) => ({
        ...prev,
        [kind]: { loading: true, ok: null, detail: "Running connection test..." },
      }));

      const body = {
        mealie_url: draftOverrideValue("MEALIE_URL"),
        mealie_api_key: envClear.MEALIE_API_KEY ? "" : draftOverrideValue("MEALIE_API_KEY"),
        openai_api_key: envClear.OPENAI_API_KEY ? "" : draftOverrideValue("OPENAI_API_KEY"),
        openai_model: draftOverrideValue("OPENAI_MODEL"),
        ollama_url: draftOverrideValue("OLLAMA_URL"),
        ollama_model: draftOverrideValue("OLLAMA_MODEL"),
      };

      const result = await api(`/settings/test/${kind}`, {
        method: "POST",
        body,
      });

      setConnectionChecks((prev) => ({
        ...prev,
        [kind]: {
          loading: false,
          ok: Boolean(result.ok),
          detail: String(result.detail || (result.ok ? "Connection validated." : "Connection failed.")),
        },
      }));
    } catch (exc) {
      setConnectionChecks((prev) => ({
        ...prev,
        [kind]: {
          loading: false,
          ok: false,
          detail: normalizeErrorMessage(exc?.message || exc),
        },
      }));
    }
  }

  function renderOverviewPage() {
    const recipeTotal = Math.max(1, Number(overviewTotals.recipes) || 0);
    const unitsCoverage = Math.max(
      0,
      Math.min(100, Math.round(((overviewTotals.units || 0) / Math.max(overviewTotals.ingredients || 1, 1)) * 100))
    );
    const progressRows = [
      { key: "categories", label: "Categories", value: overviewCoverage.categories || 0 },
      { key: "tags", label: "Tags", value: overviewCoverage.tags || 0 },
      { key: "tools", label: "Tools", value: overviewCoverage.tools || 0 },
      { key: "units", label: "Units Normalized", value: unitsCoverage },
    ];

    return (
      <section className="page-grid overview-grid">
        <article className="card tone-soft intro-card">
          <h3>Good morning. Your organizer is healthy and ready.</h3>
          <p>No failed runs in the latest window. {upcomingScheduleCount} schedules are due in the next 24 hours.</p>
          {!overviewMetrics?.ok && overviewMetrics?.reason ? (
            <p className="muted tiny">{overviewMetrics.reason}</p>
          ) : null}
        </article>

        <section className="overview-stats">
          <article className="card stat-card">
            <p className="label">Tasks</p>
            <p className="value">{tasks.length}</p>
          </article>
          <article className="card stat-card">
            <p className="label">Runs Today</p>
            <p className="value">{runsTodayCount}</p>
          </article>
          <article className="card stat-card">
            <p className="label">Schedules</p>
            <p className="value">{schedules.length}</p>
          </article>
          <article className="card stat-card">
            <p className="label">Users</p>
            <p className="value">{users.length}</p>
          </article>
        </section>

        <article className="card chart-panel">
          <div className="card-head">
            <h3>Recipe Organization Results</h3>
            <p>How categorizer changes are being applied across your recipe library.</p>
          </div>

          <div className="coverage-grid">
            <CoverageRing
              label="Categories Applied"
              value={overviewCoverage.categories}
              helper={`${Math.round(overviewCoverage.categories || 0)}% categorized`}
              detail={`${Math.round((recipeTotal * (overviewCoverage.categories || 0)) / 100)} of ${recipeTotal} recipes`}
              tone="accent"
            />
            <CoverageRing
              label="Tags Applied"
              value={overviewCoverage.tags}
              helper={`${Math.round(overviewCoverage.tags || 0)}% tagged`}
              detail={`${Math.round((recipeTotal * (overviewCoverage.tags || 0)) / 100)} of ${recipeTotal} recipes`}
              tone="olive"
            />
            <CoverageRing
              label="Tools Assigned"
              value={overviewCoverage.tools}
              helper={`${Math.round(overviewCoverage.tools || 0)}% with tools`}
              detail={`${Math.round((recipeTotal * (overviewCoverage.tools || 0)) / 100)} of ${recipeTotal} recipes`}
              tone="terracotta"
            />
          </div>

          <h4>Coverage by Taxonomy Field</h4>
          <div className="progress-list">
            {progressRows.map((row) => {
              const percent = Math.max(0, Math.min(100, Math.round(Number(row.value) || 0)));
              return (
                <div className="progress-row" key={row.key}>
                  <span>{row.label}</span>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${percent}%` }} />
                  </div>
                  <span>{percent}%</span>
                </div>
              );
            })}
          </div>
          <p className="muted tiny">Source: latest categorizer task and Mealie metadata sync.</p>
        </article>

        <article className="card quick-view">
          <h3>Quick View Data</h3>
          <p className="muted">High-signal operational data without leaving Overview.</p>
          <ul className="kv-list">
            <li>
              <span>Upcoming schedules (24h)</span>
              <strong>{upcomingScheduleCount}</strong>
            </li>
            <li>
              <span>Queued runs</span>
              <strong>{runStats.queued}</strong>
            </li>
            <li>
              <span>Last failure</span>
              <strong>{latestFailureLabel}</strong>
            </li>
          </ul>

          <div className="top-usage">
            <h4>Task Mix This Week</h4>
            <ul>
              {taskMixRows.map((item) => (
                <li key={`taskmix-${item.name}`}>
                  <span>{item.name}</span>
                  <span>{item.percent}%</span>
                </li>
              ))}
              {taskMixRows.length === 0 ? <li className="muted">No runs in the last seven days.</li> : null}
            </ul>

            <h4>Next Scheduled Jobs</h4>
            <ul>
              {upcomingScheduleRows.map((item) => (
                <li key={`next-${item.id}`}>
                  <span>{item.nextRun}</span>
                  <span>{item.label}</span>
                </li>
              ))}
              {upcomingScheduleRows.length === 0 ? <li className="muted">No scheduled jobs in the queue.</li> : null}
            </ul>
          </div>
        </article>
      </section>
    );
  }

  function renderRunsPage() {
    const selectedRun = runs.find((item) => item.run_id === selectedRunId) || null;

    return (
      <section className="page-grid runs-page">
        <article className="card run-builder-card">
          <h3>Start a Run</h3>
          <p className="muted">Queue one-off tasks for immediate execution.</p>

          <div className="run-form">
            <label className="field">
              <span>Task</span>
              <select value={selectedTask} onChange={(event) => setSelectedTask(event.target.value)}>
                <option value="">Choose task</option>
                {tasks.map((task) => (
                  <option key={task.task_id} value={task.task_id}>
                    {task.title}
                  </option>
                ))}
              </select>
            </label>

            {(selectedTaskDef?.options || []).length > 0 ? (
              <div className="option-grid">
                {(selectedTaskDef?.options || []).map((option) =>
                  fieldFromOption(option, taskValues[option.key], (key, value) =>
                    setTaskValues((prev) => ({ ...prev, [key]: value }))
                  )
                )}
              </div>
            ) : (
                <p className="muted tiny">This task has no additional options.</p>
              )}

            <button type="button" className="primary" onClick={triggerRun}>
              <Icon name="play" />
              Queue Run
            </button>
          </div>
        </article>

        <article className="card runs-history-card">
          <div className="card-head split">
            <div>
              <h3>All Runs</h3>
              <p>Manual and scheduled runs are shown together.</p>
            </div>
            <label className="search-box">
              <Icon name="search" />
                <input
                  value={runSearch}
                  onChange={(event) => setRunSearch(event.target.value)}
                  placeholder="Search task, type, or status"
                />
              </label>
            </div>

          <div className="run-type-filters">
            <button
              type="button"
              className={`chip-btn ${runTypeFilter === "all" ? "active" : ""}`}
              onClick={() => setRunTypeFilter("all")}
            >
              All
            </button>
            <button
              type="button"
              className={`chip-btn ${runTypeFilter === "manual" ? "active" : ""}`}
              onClick={() => setRunTypeFilter("manual")}
            >
              Manual
            </button>
            <button
              type="button"
              className={`chip-btn ${runTypeFilter === "scheduled" ? "active" : ""}`}
              onClick={() => setRunTypeFilter("scheduled")}
            >
              Scheduled
            </button>
          </div>

          <div className="table-wrap">
            <table className="runs-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Run Time</th>
                </tr>
              </thead>
              <tbody>
                {filteredRuns.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No runs found.</td>
                  </tr>
                ) : (
                  filteredRuns.map((run) => (
                    <tr
                      key={run.run_id}
                      className={selectedRunId === run.run_id ? "selected-row" : ""}
                      onClick={() => fetchLog(run.run_id)}
                    >
                      <td>{taskTitleById.get(run.task_id) || run.task_id}</td>
                      <td>{runTypeLabel(run)}</td>
                      <td>
                        <span className={`status-pill ${statusClass(run.status)}`}>{run.status}</span>
                      </td>
                      <td>{formatRunTime(run)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="log-section">
            <div className="log-head">
              <h4>Selected Run Output</h4>
              <span className="muted tiny">
                {selectedRun
                  ? `${taskTitleById.get(selectedRun.task_id) || selectedRun.task_id} | ${runTypeLabel(
                      selectedRun
                    )} | ${formatRunTime(selectedRun)}`
                  : "Select any row above to inspect its full formatted output."}
              </span>
            </div>
            <pre className="log-viewer">{runLog || "Select any row above to inspect its full formatted output."}</pre>
          </div>
        </article>
      </section>
    );
  }

  function renderSchedulesPage() {
    const selectedScheduleRun =
      runs.find((item) => item.run_id === selectedRunId && item.schedule_id) || filteredScheduledRuns[0] || null;

    return (
      <section className="page-grid schedules-page">
        <article className="card run-builder-card">
          <h3>Create Schedule</h3>
          <form className="run-form" onSubmit={createSchedule}>
            <label className="field">
              <span>Schedule Name</span>
              <input
                value={scheduleForm.name}
                onChange={(event) => setScheduleForm((prev) => ({ ...prev, name: event.target.value }))}
                placeholder="Morning cleanup"
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

            <div className="option-grid two">
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
                  <span>Cron Expression</span>
                  <input
                    value={scheduleForm.cron}
                    onChange={(event) => setScheduleForm((prev) => ({ ...prev, cron: event.target.value }))}
                  />
                </label>
              )}
            </div>

            {(scheduleTaskDef?.options || []).length > 0 ? (
              <div className="option-grid">
                {(scheduleTaskDef?.options || []).map((option) =>
                  fieldFromOption(option, scheduleOptionValues[option.key], (key, value) =>
                    setScheduleOptionValues((prev) => ({ ...prev, [key]: value }))
                  )
                )}
              </div>
            ) : null}

            <label className="field field-inline">
              <span>Enabled</span>
              <input
                type="checkbox"
                checked={Boolean(scheduleForm.enabled)}
                onChange={(event) => setScheduleForm((prev) => ({ ...prev, enabled: event.target.checked }))}
              />
            </label>

            <button type="submit" className="primary">
              <Icon name="save" />
              Save Schedule
            </button>
          </form>
        </article>

        <article className="card runs-history-card">
          <div className="card-head split">
            <div>
              <h3>Schedule Activity</h3>
              <p>Recent schedule-triggered runs and outcomes.</p>
            </div>
            <label className="search-box">
              <Icon name="search" />
                <input
                  value={scheduleSearch}
                  onChange={(event) => setScheduleSearch(event.target.value)}
                  placeholder="Search task or status"
                />
              </label>
            </div>

          <div className="table-wrap">
            <table className="users-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Run Time</th>
                </tr>
              </thead>
              <tbody>
                {filteredScheduledRuns.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No scheduled runs found.</td>
                  </tr>
                ) : (
                  filteredScheduledRuns.map((run) => (
                    <tr
                      key={run.run_id}
                      className={selectedRunId === run.run_id ? "selected-row" : ""}
                      onClick={() => fetchLog(run.run_id)}
                    >
                      <td>{taskTitleById.get(run.task_id) || run.task_id}</td>
                      <td>{runTypeLabel(run)}</td>
                      <td>
                        <span className={`status-pill ${statusClass(run.status)}`}>{run.status}</span>
                      </td>
                      <td>{formatRunTime(run)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="log-section">
            <div className="log-head">
              <h4>Latest log preview</h4>
              <span className="muted tiny">
                {selectedScheduleRun
                  ? `${taskTitleById.get(selectedScheduleRun.task_id) || selectedScheduleRun.task_id} | ${formatRunTime(
                      selectedScheduleRun
                    )}`
                  : "Select a scheduled run to preview output."}
              </span>
            </div>
            <pre className="log-viewer">{runLog || "Select a scheduled run to preview output."}</pre>
          </div>
        </article>
      </section>
    );
  }

  function renderSettingsPage() {
    return (
      <section className="page-grid recipe-grid">
        <article className="card">
          <div className="card-head split">
            <div>
              <h3>Live Environment Settings</h3>
              <p>Manage connection and AI settings used by background tasks.</p>
            </div>
            <button className="ghost" onClick={loadData}>
              <Icon name="refresh" />
              Reload
            </button>
          </div>

          <div className="settings-groups">
            {visibleEnvGroups.map(([group, items]) => (
              <section key={group} className="settings-group">
                <h4>{group}</h4>
                <div className="settings-rows">
                  {items.map((item) => {
                    const key = String(item.key);
                    const hasValue = Boolean(item.has_value);
                    const source = String(item.source || "unset");
                    return (
                      <div key={key} className="settings-row">
                        <div className="settings-labels">
                          <label>{item.label || key}</label>
                          <p>{item.description}</p>
                          <div className="meta-line">
                            <span>{key}</span>
                            <span>{source}</span>
                          </div>
                        </div>
                        <div className="settings-input-wrap">
                          <input
                            type={item.secret ? "password" : "text"}
                            value={envDraft[key] ?? ""}
                            placeholder={item.secret && hasValue ? "Stored secret" : ""}
                            onChange={(event) => {
                              const next = event.target.value;
                              setEnvDraft((prev) => ({ ...prev, [key]: next }));
                              if (item.secret && envClear[key]) {
                                setEnvClear((prev) => ({ ...prev, [key]: false }));
                              }
                            }}
                          />
                          {item.secret ? (
                            <button
                              type="button"
                              className="ghost small"
                              onClick={() => {
                                setEnvDraft((prev) => ({ ...prev, [key]: "" }));
                                setEnvClear((prev) => ({ ...prev, [key]: true }));
                              }}
                            >
                              Clear
                            </button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>

          <button className="primary" onClick={saveEnvironment}>
            <Icon name="save" />
            Apply Changes
          </button>
        </article>

        <aside className="stacked-cards">
          <article className="card">
            <h3>Connection Tests</h3>
            <p className="muted">Validate saved or draft values before running long jobs.</p>

            <div className="connection-tests">
              <button
                className="ghost"
                onClick={() => runConnectionTest("mealie")}
                disabled={connectionChecks.mealie.loading}
              >
                {connectionChecks.mealie.loading ? "Testing..." : "Test Mealie"}
              </button>
              <p className={`tiny ${connectionChecks.mealie.ok === false ? "danger-text" : ""}`}>
                {connectionChecks.mealie.detail || "Check Mealie URL/API key connectivity."}
              </p>

              <button
                className="ghost"
                onClick={() => runConnectionTest("openai")}
                disabled={connectionChecks.openai.loading}
              >
                {connectionChecks.openai.loading ? "Testing..." : "Test OpenAI API Key"}
              </button>
              <p className={`tiny ${connectionChecks.openai.ok === false ? "danger-text" : ""}`}>
                {connectionChecks.openai.detail || "Validate OpenAI key and selected model."}
              </p>

              <button
                className="ghost"
                onClick={() => runConnectionTest("ollama")}
                disabled={connectionChecks.ollama.loading}
              >
                {connectionChecks.ollama.loading ? "Testing..." : "Test Ollama Connection"}
              </button>
              <p className={`tiny ${connectionChecks.ollama.ok === false ? "danger-text" : ""}`}>
                {connectionChecks.ollama.detail || "Validate Ollama endpoint reachability."}
              </p>
            </div>
          </article>

          <article className="card">
            <h3>Task Safety Policies</h3>
            <p className="muted">Enable dangerous writes per task when you are ready to apply changes.</p>
            <ul className="policy-list">
              {tasks.map((task) => (
                <li key={task.task_id}>
                  <div>
                    <strong>{task.title}</strong>
                    <p className="tiny muted">{task.task_id}</p>
                  </div>
                  <label className="field-inline tiny-toggle">
                    <span>Allow writes</span>
                    <input
                      type="checkbox"
                      checked={Boolean(task.policy?.allow_dangerous)}
                      onChange={(event) => togglePolicy(task.task_id, event.target.checked)}
                    />
                  </label>
                </li>
              ))}
            </ul>
          </article>
        </aside>
      </section>
    );
  }

  function renderRecipeOrganizationPage() {
    const activeContentCount =
      activeConfigMode === "cookbook-cards"
        ? activeCookbookItems.length
        : activeConfigMode === "unit-aliases"
        ? activeUnitAliasItems.length
        : activeConfigMode === "line-pills"
        ? activeConfigItems.length
        : Array.isArray(taxonomyItemsByFile[activeConfig])
        ? taxonomyItemsByFile[activeConfig].length
        : 0;

    return (
      <section className="page-grid settings-grid">
        <article className="card">
          <h3>Recipe Organization</h3>
          <p className="muted">Edit taxonomy values using pill-style controls and save directly to JSON files.</p>

          <div className="taxonomy-pills">
            {TAXONOMY_FILE_NAMES.map((name) => (
              <button
                key={name}
                className={`pill-btn ${activeConfig === name ? "active" : ""}`}
                onClick={() => {
                  setActiveConfig(name);
                  openConfig(name);
                }}
              >
                {CONFIG_LABELS[name]}
                <span>{taxonomyCounts[name] || 0}</span>
              </button>
            ))}
          </div>

          {activeConfigMode === "line-pills" ? (
            <section className="pill-editor">
              <div className="pill-input-row">
                <input
                  value={configDraftItem}
                  placeholder="Add a value and press Enter"
                  onChange={(event) => setConfigDraftItem(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      addConfigLine();
                    }
                  }}
                />
                <button className="ghost" type="button" onClick={addConfigLine}>
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
                  >
                    <span className="line-index">{index + 1}</span>
                    <input value={item} onChange={(event) => configDraftValue(index, event.target.value)} />
                    <div className="line-actions">
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => moveConfigLine(index, Math.max(index - 1, 0))}
                        disabled={index === 0}
                      >
                        Up
                      </button>
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => moveConfigLine(index, Math.min(index + 1, activeConfigItems.length - 1))}
                        disabled={index === activeConfigItems.length - 1}
                      >
                        Down
                      </button>
                      <button type="button" className="ghost small" onClick={() => removeConfigLine(index)}>
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="muted tiny">Drag items to reorder. Use advanced mode only if needed.</p>
            </section>
          ) : activeConfigMode === "cookbook-cards" ? (
            <section className="structured-editor">
              <div className="structured-toolbar cookbook-toolbar">
                <label className="field">
                  <span>Name</span>
                  <input
                    value={cookbookDraft.name}
                    onChange={(event) => setCookbookDraft((prev) => ({ ...prev, name: event.target.value }))}
                    placeholder="Weeknight Dinner"
                  />
                </label>
                <label className="field">
                  <span>Description</span>
                  <input
                    value={cookbookDraft.description}
                    onChange={(event) => setCookbookDraft((prev) => ({ ...prev, description: event.target.value }))}
                    placeholder="Quick and reliable evening meals."
                  />
                </label>
                <label className="field">
                  <span>Query Filter</span>
                  <input
                    value={cookbookDraft.queryFilterString}
                    onChange={(event) =>
                      setCookbookDraft((prev) => ({ ...prev, queryFilterString: event.target.value }))
                    }
                    placeholder='tags.name IN ["Weeknight"]'
                  />
                </label>
                <label className="field">
                  <span>Position</span>
                  <input
                    type="number"
                    min="1"
                    value={cookbookDraft.position}
                    onChange={(event) => setCookbookDraft((prev) => ({ ...prev, position: event.target.value }))}
                  />
                </label>
                <label className="field field-inline">
                  <span>Public</span>
                  <input
                    type="checkbox"
                    checked={Boolean(cookbookDraft.public)}
                    onChange={(event) => setCookbookDraft((prev) => ({ ...prev, public: event.target.checked }))}
                  />
                </label>
                <button className="ghost" type="button" onClick={addCookbookEntry}>
                  Add Cookbook
                </button>
              </div>

              <ul className="structured-list">
                {activeCookbookItems.map((item, index) => (
                  <li key={`${activeConfig}-${index}`} className="structured-item">
                    <div className="structured-item-grid cookbook-fields">
                      <label className="field">
                        <span>Name</span>
                        <input
                          value={item.name}
                          onChange={(event) => updateCookbookEntry(index, "name", event.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span>Description</span>
                        <input
                          value={item.description}
                          onChange={(event) => updateCookbookEntry(index, "description", event.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span>Query Filter</span>
                        <input
                          value={item.queryFilterString}
                          onChange={(event) => updateCookbookEntry(index, "queryFilterString", event.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span>Position</span>
                        <input
                          type="number"
                          min="1"
                          value={item.position}
                          onChange={(event) => updateCookbookEntry(index, "position", event.target.value)}
                        />
                      </label>
                      <label className="field field-inline">
                        <span>Public</span>
                        <input
                          type="checkbox"
                          checked={Boolean(item.public)}
                          onChange={(event) => updateCookbookEntry(index, "public", event.target.checked)}
                        />
                      </label>
                    </div>
                    <div className="line-actions">
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => moveCookbookEntry(index, Math.max(index - 1, 0))}
                        disabled={index === 0}
                      >
                        Up
                      </button>
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => moveCookbookEntry(index, Math.min(index + 1, activeCookbookItems.length - 1))}
                        disabled={index === activeCookbookItems.length - 1}
                      >
                        Down
                      </button>
                      <button type="button" className="ghost small" onClick={() => removeCookbookEntry(index)}>
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="muted tiny">
                Cookbook rows stay structured with filters, descriptions, visibility, and ordering.
              </p>
            </section>
          ) : activeConfigMode === "unit-aliases" ? (
            <section className="structured-editor">
              <div className="structured-toolbar">
                <label className="field">
                  <span>Canonical Unit</span>
                  <input
                    value={unitDraftCanonical}
                    onChange={(event) => setUnitDraftCanonical(event.target.value)}
                    placeholder="Teaspoon"
                  />
                </label>
                <label className="field">
                  <span>Aliases (comma separated)</span>
                  <input
                    value={unitDraftAliases}
                    onChange={(event) => setUnitDraftAliases(event.target.value)}
                    placeholder="t, tsp, tsp."
                  />
                </label>
                <button className="ghost" type="button" onClick={addUnitAliasEntry}>
                  Add Unit
                </button>
              </div>

              <ul className="structured-list">
                {activeUnitAliasItems.map((item, index) => (
                  <li key={`${activeConfig}-${index}`} className="structured-item">
                    <div className="structured-item-grid">
                      <label className="field">
                        <span>Canonical Unit</span>
                        <input
                          value={item.canonical}
                          onChange={(event) => updateUnitAliasEntry(index, "canonical", event.target.value)}
                        />
                      </label>
                      <label className="field">
                        <span>Aliases (comma separated)</span>
                        <input
                          value={item.aliases.join(", ")}
                          onChange={(event) => updateUnitAliasEntry(index, "aliases", event.target.value)}
                        />
                      </label>
                    </div>
                    <div className="line-actions">
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => moveUnitAliasEntry(index, Math.max(index - 1, 0))}
                        disabled={index === 0}
                      >
                        Up
                      </button>
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => moveUnitAliasEntry(index, Math.min(index + 1, activeUnitAliasItems.length - 1))}
                        disabled={index === activeUnitAliasItems.length - 1}
                      >
                        Down
                      </button>
                      <button type="button" className="ghost small" onClick={() => removeUnitAliasEntry(index)}>
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="muted tiny">Maintain canonical units and aliases without switching to raw JSON.</p>
            </section>
          ) : (
            <section>
              <p className="muted tiny">Advanced mode: this file requires full JSON editing.</p>
              <textarea
                rows={18}
                value={activeConfigBody}
                onChange={(event) => setActiveConfigBody(event.target.value)}
              />
            </section>
          )}

          <div className="split-actions">
            <div className="split-actions-group">
              <button className="primary" onClick={saveConfig} disabled={!activeConfig}>
                <Icon name="save" />
                Save File
              </button>
              <button
                className="ghost"
                type="button"
                onClick={() => {
                  if (activeConfig) {
                    openConfig(activeConfig);
                  }
                }}
              >
                Discard
              </button>
            </div>
            <span className="muted tiny">{activeContentCount} values in current file</span>
          </div>
        </article>

        <aside className="stacked-cards">
          <article className="card">
            <h3>Import from JSON</h3>
            <p className="muted">Upload JSON to add or replace recipe organization values.</p>

            <label className="field">
              <span>Target File</span>
              <select value={importTarget} onChange={(event) => setImportTarget(event.target.value)}>
                {TAXONOMY_FILE_NAMES.map((name) => (
                  <option key={name} value={name}>
                    {CONFIG_LABELS[name]}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>JSON Payload</span>
              <textarea
                rows={12}
                value={importJsonText}
                onChange={(event) => setImportJsonText(event.target.value)}
                placeholder='[ {"name": "One"}, {"name": "Two"} ]'
              />
            </label>

            <button className="primary" onClick={importTaxonomyJson}>
              <Icon name="upload" />
              Import JSON
            </button>
            <p className="muted tiny">Supports categories, cookbooks, labels, tags, tools, and units.</p>
          </article>
        </aside>
      </section>
    );
  }

  function renderUsersPage() {
    return (
      <section className="page-grid settings-grid users-grid">
        <article className="card">
          <h3>Create User</h3>
          <p className="muted">Create accounts for household members or shared kitchen devices.</p>

          <form className="run-form" onSubmit={createUser}>
            <label className="field">
              <span>Username</span>
              <input
                value={newUserUsername}
                onChange={(event) => setNewUserUsername(event.target.value)}
                placeholder="kitchen-tablet"
              />
            </label>

            <label className="field">
              <span>Email (optional)</span>
              <input
                value={newUserEmail}
                onChange={(event) => setNewUserEmail(event.target.value)}
                placeholder="tablet@kitchen.local"
              />
            </label>

            <label className="field">
              <span>Role</span>
              <select value={newUserRole} onChange={(event) => setNewUserRole(event.target.value)}>
                <option value="Editor">Editor</option>
                <option value="Viewer">Viewer</option>
                <option value="Owner">Owner</option>
              </select>
            </label>

            <label className="field">
              <span>Temporary Password</span>
              <div className="password-row">
                <input
                  type="password"
                  value={newUserPassword}
                  onChange={(event) => setNewUserPassword(event.target.value)}
                  placeholder="At least 8 characters"
                />
                <button type="button" className="ghost" onClick={generateTemporaryPassword}>
                  Generate
                </button>
              </div>
            </label>

            <div className="password-helper">
              <Icon name="shield" />
              <span>Use a strong temporary password and rotate after first login.</span>
            </div>

            <button type="submit" className="primary">
              <Icon name="users" />
              Create User
            </button>
          </form>
        </article>

        <article className="card">
          <div className="card-head split">
            <div>
              <h3>Current Users</h3>
              <p>Reset passwords and remove inactive accounts.</p>
            </div>
            <label className="search-box">
              <Icon name="search" />
              <input
                value={userSearch}
                onChange={(event) => setUserSearch(event.target.value)}
                placeholder="Search username or role"
              />
            </label>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last Active</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredUsers.length === 0 ? (
                  <tr>
                    <td colSpan={5}>No users found.</td>
                  </tr>
                ) : (
                  filteredUsers.map((item) => (
                    <tr key={item.username}>
                      <td>
                        <strong>{item.username}</strong>
                      </td>
                      <td>
                        <span className="nowrap">{userRoleLabel(item.username, session?.username)}</span>
                      </td>
                      <td>
                        <span className="status-pill success">
                          {session?.username === item.username ? "Active Session" : "Active"}
                        </span>
                      </td>
                      <td>
                        <span className="nowrap">{formatDateTime(item.created_at)}</span>
                      </td>
                      <td className="users-actions-cell">
                        <div className="user-actions">
                          <input
                            type="password"
                            placeholder="New password"
                            value={resetPasswords[item.username] || ""}
                            onChange={(event) =>
                              setResetPasswords((prev) => ({ ...prev, [item.username]: event.target.value }))
                            }
                          />
                          <button className="ghost" onClick={() => resetUserPassword(item.username)}>
                            Reset
                          </button>
                          {session?.username !== item.username ? (
                            <button className="ghost" onClick={() => deleteUser(item.username)}>
                              Remove
                            </button>
                          ) : (
                            <span className="muted tiny">Cannot remove current account</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <p className="muted tiny">
            {users.length} users total | {users.length} active | 0 disabled
          </p>
        </article>
      </section>
    );
  }

  function renderHelpPage() {
    return (
      <section className="page-grid settings-grid help-grid">
        <article className="card">
          <h3>Setup and Troubleshooting</h3>
          <p className="muted">Embedded markdown from the repository docs for in-app guidance.</p>

          <div className="accordion-stack compact">
            {helpDocs.length === 0 ? (
              <p className="muted tiny">No embedded docs were found in this deployment.</p>
            ) : (
              helpDocs.map((doc) => (
                <details className="accordion" key={doc.id}>
                  <summary>
                    <Icon name="info" />
                    <span>{doc.title}</span>
                    <Icon name="chevron" />
                  </summary>
                  <div className="doc-preview markdown-preview">{renderMarkdownDocument(doc.content)}</div>
                </details>
              ))
            )}
          </div>
        </article>

        <aside className="stacked-cards">
          <article className="card">
            <h3>Setup FAQ</h3>
            <p className="muted">Quick answers for first-time setup and common safe workflows.</p>

            <div className="accordion-stack">
              {HELP_FAQ.map((item, index) => (
                <details className="accordion" key={item.question} open={index === 0}>
                  <summary>
                    <Icon name="help" />
                    <span>{item.question}</span>
                    <Icon name="chevron" />
                  </summary>
                  <p>{item.answer}</p>
                </details>
              ))}
            </div>
          </article>
        </aside>
      </section>
    );
  }

  function renderAboutPage() {
    const appVersion = aboutMeta?.app_version || healthMeta?.version || "-";
    const backendStatus = healthMeta?.ok === false ? "Degraded" : "Connected";
    const lastSyncLabel = lastLoadedAt ? formatDateTime(lastLoadedAt) : "-";

    return (
      <section className="page-grid settings-grid about-grid">
        <article className="card">
          <h3>Library Metrics</h3>
          <p className="muted">Current Mealie library and managed taxonomy counts.</p>

          <div className="metric-grid">
            <article>
              <span>Recipes</span>
              <strong>{overviewTotals.recipes}</strong>
            </article>
            <article>
              <span>Ingredients</span>
              <strong>{overviewTotals.ingredients}</strong>
            </article>
            <article>
              <span>Tools</span>
              <strong>{overviewTotals.tools}</strong>
            </article>
            <article>
              <span>Categories</span>
              <strong>{overviewTotals.categories}</strong>
            </article>
            <article>
              <span>Cookbooks</span>
              <strong>{taxonomyCounts.cookbooks || 0}</strong>
            </article>
            <article>
              <span>Tags</span>
              <strong>{overviewTotals.tags}</strong>
            </article>
            <article>
              <span>Labels</span>
              <strong>{overviewTotals.labels}</strong>
            </article>
            <article>
              <span>Units</span>
              <strong>{overviewTotals.units}</strong>
            </article>
          </div>

          <div className="about-actions">
            <button className="primary" onClick={loadData}>
              <Icon name="refresh" />
              Refresh Metrics
            </button>
            <span className="muted tiny">Metrics refresh from local state and Mealie API.</span>
          </div>
        </article>

        <article className="card">
          <h3>Automation Activity</h3>
          <p className="muted">
            Last run:{" "}
            {latestRun ? `${formatDateTime(latestRun.finished_at || latestRun.started_at || latestRun.created_at)}` : "-"} |{" "}
            {latestRun ? `${taskTitleById.get(latestRun.task_id) || latestRun.task_id}` : "No runs yet"} |{" "}
            {latestRun ? `${latestRun.status}` : "n/a"}
          </p>
          <div className="about-actions">
            <button className="ghost" onClick={loadData}>
              <Icon name="refresh" />
              Run Health Check
            </button>
            <button className="ghost" onClick={() => setActivePage("runs")}>
              <Icon name="play" />
              View Run History
            </button>
          </div>
        </article>

        <aside className="stacked-cards">
          <article className="card">
            <h3>Version</h3>
            <p className="muted">CookDex {appVersion}</p>
            <p className="tiny muted">Web UI runtime version: {aboutMeta?.webui_version || "-"}</p>
          </article>

          <article className="card">
            <h3>Project Links</h3>
            <a
              className="link-btn"
              href={aboutMeta?.links?.github || "https://github.com/thekannen/cookdex"}
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="external" />
              Open GitHub Repository
            </a>
            <a
              className="link-btn"
              href={aboutMeta?.links?.sponsor || "https://github.com/sponsors/thekannen"}
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="external" />
              Sponsor the Project
            </a>
          </article>

          <article className="card">
            <h3>Application Details</h3>
            <ul className="kv-list">
              <li>
                <span>License</span>
                <strong>MIT</strong>
              </li>
              <li>
                <span>Build Channel</span>
                <strong>Stable</strong>
              </li>
              <li>
                <span>Backend</span>
                <strong>{backendStatus}</strong>
              </li>
              <li>
                <span>Environment</span>
                <strong>Self-hosted</strong>
              </li>
              <li>
                <span>Last Sync</span>
                <strong>{lastSyncLabel}</strong>
              </li>
            </ul>
          </article>

          <article className="card">
            <h3>Why this app exists</h3>
            <p className="muted">
              CookDex is designed for home server users who want powerful cleanup and organization workflows without
              command-line complexity.
            </p>
          </article>
        </aside>
      </section>
    );
  }

  function renderPage() {
    if (activePage === "runs") return renderRunsPage();
    if (activePage === "schedules") return renderSchedulesPage();
    if (activePage === "settings") return renderSettingsPage();
    if (activePage === "recipe-organization") return renderRecipeOrganizationPage();
    if (activePage === "users") return renderUsersPage();
    if (activePage === "help") return renderHelpPage();
    if (activePage === "about") return renderAboutPage();
    return renderOverviewPage();
  }

  if (setupRequired && !session) {
    return (
      <main className="auth-shell">
        <section className="auth-left">
          <img src={wordmark} alt="CookDex" className="auth-wordmark" />
          <p className="auth-badge">First-time setup made simple</p>
          <h1>Manage recipe automation without the CLI.</h1>
          <p>
            CookDex gives clear controls for taxonomy, scheduling, and task runs while keeping defaults safe for daily
            use.
          </p>
          <div className="auth-points">
            <p>No YAML edits needed for standard setup.</p>
            <p>Runtime settings are grouped with plain descriptions.</p>
            <p>No recipe data changes happen until you explicitly run tasks.</p>
          </div>
        </section>

        <section className="auth-card">
          <h2>Create Admin Account</h2>
          <p>This account can manage users, schedules, settings, and runs.</p>
          <form onSubmit={registerFirstUser}>
            <label className="field">
              <span>Admin Username</span>
              <input
                value={registerUsername}
                onChange={(event) => setRegisterUsername(event.target.value)}
                placeholder="admin"
              />
            </label>
            <label className="field">
              <span>Password</span>
              <input
                type="password"
                value={registerPassword}
                onChange={(event) => setRegisterPassword(event.target.value)}
                placeholder="At least 8 characters"
              />
            </label>
            <button type="submit" className="primary">
              <Icon name="users" />
              Create Admin Account
            </button>
          </form>
          {error ? <div className="banner error">{error}</div> : null}
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="auth-shell">
        <section className="auth-left">
          <img src={wordmark} alt="CookDex" className="auth-wordmark" />
          <p className="eyebrow">Welcome back.</p>
          <h1>Sign in to your CookDex workspace.</h1>
          <p>Control runs, schedules, settings, and recipe organization from one desktop-first interface.</p>
        </section>

        <section className="auth-card">
          <h2>Sign In</h2>
          <p>Use your CookDex user credentials.</p>
          <form onSubmit={doLogin}>
            <label className="field">
              <span>Username</span>
              <input value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label className="field">
              <span>Password</span>
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
            </label>
            <button type="submit" className="primary">
              <Icon name="play" />
              Sign In
            </button>
          </form>
          {error ? <div className="banner error">{error}</div> : null}
        </section>
      </main>
    );
  }

  const showHeaderBreadcrumb = activePage === "overview";
  const showHeaderRefresh = activePage === "overview";

  return (
    <main className="app-shell">
      <aside className={`sidebar ${sidebarCollapsed ? "collapsed" : ""}`}>
        <div className="sidebar-top">
          <div className="brand-wrap">
            <img src={sidebarCollapsed ? emblem : wordmark} alt="CookDex" className="brand-mark" />
            {!sidebarCollapsed ? <p className="muted tiny">Web UI-first automation control center.</p> : null}
          </div>
          <button className="icon-btn" onClick={() => setSidebarCollapsed((prev) => !prev)} aria-label="Toggle sidebar">
            <Icon name="menu" />
          </button>
        </div>

        <nav className="sidebar-nav">
          <p className="muted tiny">Workspace</p>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${activePage === item.id ? "active" : ""}`}
              onClick={() => setActivePage(item.id)}
              title={item.label}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="user-chip">
            <span className="avatar">{String(session.username || "u").slice(0, 1).toUpperCase()}</span>
            <div>
              <strong>{session.username}</strong>
              <p className="tiny muted">Owner</p>
            </div>
          </div>

          <div className="sidebar-actions">
            <button className="ghost" onClick={loadData} title="Refresh data">
              <Icon name="refresh" />
              <span>Refresh</span>
            </button>
            <button
              className="ghost"
              onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
              title="Toggle theme"
            >
              <Icon name="settings" />
              <span>Theme</span>
            </button>
            <button className="ghost" onClick={doLogout} title="Log out">
              <Icon name="logout" />
              <span>Log Out</span>
            </button>
          </div>
        </div>
      </aside>

      <section className="content-shell">
        <header className="page-header card">
          <div>
            {showHeaderBreadcrumb ? <p className="eyebrow">Home / {activePageMeta.title}</p> : null}
            <h2>{activePageMeta.title}</h2>
            <p className="muted">{activePageMeta.subtitle}</p>
          </div>
          {showHeaderRefresh ? (
            <button className="ghost" onClick={loadData}>
              <Icon name="refresh" />
              Refresh
            </button>
          ) : null}
        </header>

        {error ? <div className="banner error">{error}</div> : null}
        {!error && notice ? <div className="banner info">{notice}</div> : null}

        {renderPage()}
      </section>
    </main>
  );
}

