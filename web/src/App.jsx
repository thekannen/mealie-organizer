import React, { useEffect, useMemo, useState } from "react";
import wordmark from "./assets/CookDex_wordmark.png";
import emblem from "./assets/CookDex_light.png";

import { NAV_ITEMS, PAGE_META, CONFIG_LABELS, TAXONOMY_FILE_NAMES, HELP_FAQ, HELP_TROUBLESHOOTING } from "./constants";
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
  parseQueryFilter,
  buildQueryFilter,
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

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.localStorage.getItem("cookdex_sidebar") === "collapsed");
  const [activePage, setActivePage] = useState(() => {
    const stored = window.localStorage.getItem("cookdex_page");
    return stored || "overview";
  });

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
    filterSelections: { categories: [], tags: [] },
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
  const [availableModels, setAvailableModels] = useState({ openai: [], ollama: [] });

  const [newUserUsername, setNewUserUsername] = useState("");
  const [newUserRole, setNewUserRole] = useState("Editor");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [userSearch, setUserSearch] = useState("");
  const [resetPasswords, setResetPasswords] = useState({});
  const [expandedUser, setExpandedUser] = useState(null);
  const [confirmModal, setConfirmModal] = useState(null);

  const [taxonomyItemsByFile, setTaxonomyItemsByFile] = useState({});
  const [helpDocs, setHelpDocs] = useState([]);
  const [overviewMetrics, setOverviewMetrics] = useState(null);
  const [aboutMeta, setAboutMeta] = useState(null);
  const [healthMeta, setHealthMeta] = useState(null);
  const [lastLoadedAt, setLastLoadedAt] = useState("");
  const [isLoading, setIsLoading] = useState(false);

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
    const GROUP_ORDER = { Connection: 0, AI: 1 };
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
    return [...grouped.entries()].sort(
      (a, b) => (GROUP_ORDER[a[0]] ?? 99) - (GROUP_ORDER[b[0]] ?? 99)
    );
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

  const availableFilterOptions = useMemo(() => {
    const extractNames = (items) => {
      if (!Array.isArray(items)) return [];
      return items
        .map((item) => (typeof item === "string" ? item : item?.name || null))
        .filter(Boolean);
    };
    return {
      categories: extractNames(taxonomyItemsByFile.categories),
      tags: extractNames(taxonomyItemsByFile.tags),
    };
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
    window.localStorage.setItem("cookdex_page", activePage);
  }, [activePage]);

  useEffect(() => {
    window.localStorage.setItem("cookdex_sidebar", sidebarCollapsed ? "collapsed" : "expanded");
  }, [sidebarCollapsed]);

  useEffect(() => {
    setTaskValues(buildDefaultOptionValues(selectedTaskDef));
  }, [selectedTaskDef]);

  useEffect(() => {
    setScheduleOptionValues(buildDefaultOptionValues(scheduleTaskDef));
  }, [scheduleTaskDef]);

  const bannerTimer = React.useRef(null);

  function clearBanners() {
    setError("");
    setNotice("");
    clearTimeout(bannerTimer.current);
  }

  function showNotice(msg, ms = 5000) {
    setNotice(msg);
    clearTimeout(bannerTimer.current);
    if (msg) bannerTimer.current = setTimeout(() => { setNotice(""); }, ms);
  }

  function handleError(exc) {
    setNotice("");
    clearTimeout(bannerTimer.current);
    setError(normalizeErrorMessage(exc?.message || exc));
  }

  function setConfigEditorState(content, configName = activeConfig) {
    const editor = parseLineEditorContent(content, configName);
    setActiveConfigMode(editor.mode);
    setActiveConfigListKind(editor.listKind);
    setActiveConfigItems(editor.mode === "line-pills" ? editor.items : []);
    setActiveCookbookItems(
      editor.mode === "cookbook-cards"
        ? editor.items.map((item) => ({
            ...item,
            filterSelections: parseQueryFilter(item.queryFilterString),
          }))
        : []
    );
    setActiveUnitAliasItems(editor.mode === "unit-aliases" ? editor.items : []);
    setConfigDraftItem("");
    setCookbookDraft({
      name: "",
      description: "",
      queryFilterString: "",
      filterSelections: { categories: [], tags: [] },
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

  const CACHE_KEY = "cookdex_data_cache";
  const CACHE_TTL = 5 * 60 * 1000; // 5 minutes
  const staleTimer = React.useRef(null);

  function applyData(data) {
    const nextTasks = data.tasks?.items || [];
    const nextRuns = data.runs?.items || [];
    const nextSchedules = data.schedules?.items || [];

    setTasks(nextTasks);
    setRuns(nextRuns);
    setSchedules(nextSchedules);
    setConfigFiles(data.config?.items || []);
    setUsers(data.users?.items || []);
    setHelpDocs(data.help?.items || []);
    setOverviewMetrics(data.metrics);
    setAboutMeta(data.about);
    setHealthMeta(data.health);
    setLastLoadedAt(data.timestamp);

    const nextSpecs = data.settings?.env || {};
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
  }

  function scheduleAutoRefresh() {
    clearTimeout(staleTimer.current);
    staleTimer.current = setTimeout(() => { loadData(); }, CACHE_TTL);
  }

  function loadCachedData() {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return false;
      const cached = JSON.parse(raw);
      if (Date.now() - cached.savedAt > CACHE_TTL) return false;
      applyData(cached);
      scheduleAutoRefresh();
      return true;
    } catch { return false; }
  }

  async function loadData() {
    if (isLoading) return;
    setIsLoading(true);
    showNotice("Refreshing data\u2026", 30000);
    try {
      const [
        taskPayload, runPayload, schedulePayload, settingsPayload,
        configPayload, usersPayload, helpPayload,
        metricsPayload, aboutPayload, healthPayload,
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

      const data = {
        tasks: taskPayload, runs: runPayload, schedules: schedulePayload,
        settings: settingsPayload, config: configPayload, users: usersPayload,
        help: helpPayload, metrics: metricsPayload, about: aboutPayload,
        health: healthPayload, timestamp: new Date().toISOString(), savedAt: Date.now(),
      };

      applyData(data);

      try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(data)); } catch {}

      await loadTaxonomyContent();
      clearBanners();
      scheduleAutoRefresh();
    } catch (exc) {
      handleError(exc);
    } finally {
      setIsLoading(false);
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
          if (!loadCachedData()) {
            await loadData();
          } else {
            loadTaxonomyContent();
          }
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
      showNotice("Admin account created.");
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
      showNotice("Signed in successfully.");
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
      showNotice("Run queued.");
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
      showNotice("Task policy updated.");
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
      showNotice("Schedule saved.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function deleteSchedule(scheduleId) {
    try {
      clearBanners();
      await api(`/schedules/${scheduleId}`, { method: "DELETE" });
      await loadData();
      showNotice("Schedule removed.");
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
        showNotice("No setting changes to save.");
        return;
      }

      await api("/settings", {
        method: "PUT",
        body: { env },
      });

      await loadData();
      showNotice("Settings updated.");
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
        queryFilterString: cookbookDraft.queryFilterString,
        filterSelections: { ...(cookbookDraft.filterSelections || { categories: [], tags: [] }) },
        public: Boolean(cookbookDraft.public),
        position: Number.isFinite(parsedPosition) && parsedPosition > 0 ? parsedPosition : prev.length + 1,
      },
    ]);
    setCookbookDraft((prev) => ({
      ...prev,
      name: "",
      description: "",
      queryFilterString: "",
      filterSelections: { categories: [], tags: [] },
      public: false,
      position: nextPosition,
    }));
  }

  function updateCookbookFilterSelections(index, newSelections) {
    setActiveCookbookItems((prev) =>
      prev.map((item, i) =>
        i === index
          ? { ...item, filterSelections: newSelections, queryFilterString: buildQueryFilter(newSelections) }
          : item
      )
    );
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
      showNotice(`${CONFIG_LABELS[activeConfig] || activeConfig} saved.`);
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
      showNotice(`${CONFIG_LABELS[target] || target} imported from JSON.`);
    } catch (exc) {
      handleError(exc);
    }
  }

  function generateTemporaryPassword() {
    const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    const lower = "abcdefghijkmnopqrstuvwxyz";
    const digits = "23456789";
    const all = upper + lower + digits + "!@#$%";
    const pick = (s) => s[Math.floor(Math.random() * s.length)];
    const required = [pick(upper), pick(lower), pick(digits)];
    for (let i = required.length; i < 14; i += 1) required.push(pick(all));
    for (let i = required.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [required[i], required[j]] = [required[j], required[i]];
    }
    setNewUserPassword(required.join(""));
    setShowPassword(true);
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
      setNewUserRole("Editor");
      setNewUserPassword("");
      await loadData();
      showNotice("User created.");
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
      showNotice(`Password reset for ${usernameValue}.`);
    } catch (exc) {
      handleError(exc);
    }
  }

  function deleteUser(usernameValue) {
    setConfirmModal({
      message: `Remove user "${usernameValue}"? This cannot be undone.`,
      action: async () => {
        try {
          clearBanners();
          await api(`/users/${encodeURIComponent(usernameValue)}`, { method: "DELETE" });
          await loadData();
          showNotice(`Removed ${usernameValue}.`);
        } catch (exc) {
          handleError(exc);
        }
      },
    });
  }

  function draftOverrideValue(key) {
    const value = String(envDraft[key] ?? "").trim();
    if (!value) {
      return null;
    }
    return value;
  }

  async function fetchAvailableModels(kind) {
    const body = {
      openai_api_key: envClear.OPENAI_API_KEY ? "" : draftOverrideValue("OPENAI_API_KEY"),
      ollama_url: draftOverrideValue("OLLAMA_URL"),
    };
    try {
      const result = await api(`/settings/models/${kind}`, { method: "POST", body });
      if (Array.isArray(result.models)) {
        setAvailableModels((prev) => ({ ...prev, [kind]: result.models }));
      }
    } catch (exc) {
      console.warn(`Failed to fetch ${kind} models:`, exc?.message || exc);
    }
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

      if (result.ok && (kind === "openai" || kind === "ollama")) {
        fetchAvailableModels(kind);
      }
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
    return (
      <section className="page-grid overview-grid">
        <article className="card tone-soft intro-card">
          <h3>Good morning. Your organizer is healthy and ready.</h3>
          <div className="status-row">
            <span className="status-pill success">Queued {runStats.queued}</span>
            <span className="status-pill neutral">Scheduled {upcomingScheduleCount}</span>
            {runStats.failed > 0 && <span className="status-pill error">Failed {runStats.failed}</span>}
          </div>
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
          <h3>Coverage</h3>
          <div className="coverage-grid">
            <CoverageRing label="Categories" value={overviewCoverage.categories} tone="accent" />
            <CoverageRing label="Tags" value={overviewCoverage.tags} tone="olive" />
            <CoverageRing label="Tools" value={overviewCoverage.tools} tone="terracotta" />
          </div>
        </article>

        <article className="card quick-view">
          <h3>Activity</h3>
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

        <article className="card library-metrics">
          <h3>Library</h3>
          <div className="metric-grid">
            <article><span>Recipes</span><strong>{overviewTotals.recipes}</strong></article>
            <article><span>Ingredients</span><strong>{overviewTotals.ingredients}</strong></article>
            <article><span>Tools</span><strong>{overviewTotals.tools}</strong></article>
            <article><span>Categories</span><strong>{overviewTotals.categories}</strong></article>
            <article><span>Cookbooks</span><strong>{taxonomyCounts.cookbooks || 0}</strong></article>
            <article><span>Tags</span><strong>{overviewTotals.tags}</strong></article>
            <article><span>Labels</span><strong>{overviewTotals.labels}</strong></article>
            <article><span>Units</span><strong>{overviewTotals.units}</strong></article>
          </div>
          {!overviewMetrics?.ok && overviewMetrics?.reason ? (
            <p className="banner error"><span>{overviewMetrics.reason}</span></p>
          ) : null}
        </article>
      </section>
    );
  }

  function renderTasksPage() {
    const selectedRun = runs.find((item) => item.run_id === selectedRunId) || null;

    function formatScheduleTiming(schedule) {
      if (schedule.kind === "cron") return `Cron ${schedule.cron || ""}`;
      const secs = Number(schedule.seconds || 0);
      if (secs >= 3600) return `Every ${Math.round(secs / 3600)}h`;
      if (secs >= 60) return `Every ${Math.round(secs / 60)}m`;
      return `Every ${secs}s`;
    }

    return (
      <section className="page-grid tasks-grid">
        <div className="stacked-cards">
          <article className="card">
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

          {schedules.length > 0 ? (
            <article className="card">
              <h3>Saved Schedules</h3>
              <p className="muted">{schedules.length} schedule{schedules.length !== 1 ? "s" : ""} configured.</p>
              <ul className="schedule-list">
                {schedules.map((schedule) => (
                  <li key={schedule.schedule_id}>
                    <div>
                      <strong>{schedule.name || schedule.schedule_id}</strong>
                      <p className="tiny muted">
                        {taskTitleById.get(schedule.task_id) || schedule.task_id} · {formatScheduleTiming(schedule)}
                      </p>
                    </div>
                    <div className="schedule-item-actions">
                      <span className={`status-pill ${schedule.enabled !== false ? "success" : "neutral"}`}>
                        {schedule.enabled !== false ? "Enabled" : "Disabled"}
                      </span>
                      <button className="ghost small" onClick={() => deleteSchedule(schedule.schedule_id)}>
                        <Icon name="x" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </article>
          ) : null}

          <article className="card">
            <h3>New Schedule</h3>
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
        </div>

        <article className="card">
          <div className="card-head split">
            <div>
              <h3>All Activity</h3>
              <p>Manual and scheduled runs shown together.</p>
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

  const GROUP_ICONS = { Connection: "link", AI: "wand" };

  function renderSettingsPage() {
    return (
      <section className="page-grid settings-grid">
        <article className="card">
          <div className="card-head split">
            <div>
              <h3><Icon name="settings" /> Environment Settings</h3>
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
                <h4><Icon name={GROUP_ICONS[group] || "settings"} /> {group}</h4>
                <div className="settings-rows">
                  {items.map((item) => {
                    const key = String(item.key);
                    const provider = envDraft["CATEGORIZER_PROVIDER"] || "chatgpt";
                    if (key !== "CATEGORIZER_PROVIDER" && provider === "none") return null;
                    if (provider === "chatgpt" && (key === "OLLAMA_URL" || key === "OLLAMA_MODEL")) return null;
                    if (provider === "ollama" && (key === "OPENAI_MODEL" || key === "OPENAI_API_KEY")) return null;
                    const hasValue = Boolean(item.has_value);
                    const source = String(item.source || "unset");
                    const draftValue = envDraft[key] ?? "";
                    const onChangeDraft = (next) => {
                      setEnvDraft((prev) => ({ ...prev, [key]: next }));
                      if (item.secret && envClear[key]) {
                        setEnvClear((prev) => ({ ...prev, [key]: false }));
                      }
                    };

                    const modelKind = key === "OPENAI_MODEL" ? "openai" : key === "OLLAMA_MODEL" ? "ollama" : null;
                    const modelList = modelKind ? availableModels[modelKind] || [] : [];

                    let inputElement;
                    if (key === "CATEGORIZER_PROVIDER") {
                      inputElement = (
                        <select value={draftValue || "chatgpt"} onChange={(e) => onChangeDraft(e.target.value)}>
                          <option value="none">None (AI disabled)</option>
                          <option value="chatgpt">ChatGPT (OpenAI)</option>
                          <option value="ollama">Ollama (Local)</option>
                        </select>
                      );
                    } else if (modelKind && modelList.length > 0) {
                      inputElement = (
                        <>
                          <select value={draftValue} onChange={(e) => onChangeDraft(e.target.value)}>
                            {!draftValue && <option value="">Select a model…</option>}
                            {modelList.map((m) => (
                              <option key={m} value={m}>{m}</option>
                            ))}
                          </select>
                          <button type="button" className="ghost small" onClick={() => fetchAvailableModels(modelKind)}>
                            <Icon name="refresh" /> Refresh list
                          </button>
                        </>
                      );
                    } else if (modelKind) {
                      inputElement = (
                        <>
                          <input
                            type="text"
                            value={draftValue}
                            placeholder={item.default || ""}
                            onChange={(e) => onChangeDraft(e.target.value)}
                          />
                          <button type="button" className="ghost small" onClick={() => fetchAvailableModels(modelKind)}>
                            <Icon name="refresh" /> Load models
                          </button>
                        </>
                      );
                    } else {
                      inputElement = (
                        <input
                          type={item.secret ? "password" : "text"}
                          value={draftValue}
                          placeholder={item.secret && hasValue ? "Stored secret" : ""}
                          onChange={(e) => onChangeDraft(e.target.value)}
                        />
                      );
                    }

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
                          {inputElement}
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
            <h3><Icon name="check-circle" /> Connection Tests</h3>
            <p className="muted">Validate saved or draft values before running long jobs.</p>

            <div className="connection-tests">
              {[
                { id: "mealie", label: "Test Mealie", hint: "Check Mealie URL/API key connectivity." },
                { id: "openai", label: "Test OpenAI", hint: "Validate OpenAI key and selected model.", provider: "chatgpt" },
                { id: "ollama", label: "Test Ollama", hint: "Validate Ollama endpoint reachability.", provider: "ollama" },
              ].filter((test) => {
                const p = envDraft["CATEGORIZER_PROVIDER"] || "chatgpt";
                return !test.provider || (p !== "none" && p === test.provider);
              })
              .map((test) => {
                const state = connectionChecks[test.id] || {};
                return (
                  <div key={test.id} className="connection-test-item">
                    <button
                      className="ghost"
                      onClick={() => runConnectionTest(test.id)}
                      disabled={state.loading}
                    >
                      <Icon name={state.loading ? "refresh" : "zap"} />
                      {state.loading ? "Testing\u2026" : test.label}
                    </button>
                    <p className={`tiny ${state.ok === false ? "danger-text" : state.ok === true ? "success-text" : ""}`}>
                      {state.detail || test.hint}
                    </p>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="card">
            <h3><Icon name="info" /> About AI Integration</h3>
            <p className="muted">AI is optional. The following tasks use the configured provider when enabled:</p>
            <ul className="ai-task-list">
              <li>
                <strong>Categorize Recipes</strong>
                <p className="tiny muted">Classifies recipes into categories, tags, and tools using AI prompts.</p>
              </li>
              <li>
                <strong>Ingredient Parser</strong>
                <p className="tiny muted">Falls back to OpenAI when the built-in NLP parser has low confidence.</p>
              </li>
            </ul>
            {(envDraft["CATEGORIZER_PROVIDER"] || "chatgpt") === "none" && (
              <p className="tiny muted" style={{ marginTop: "0.4rem" }}>
                AI is currently disabled. Tasks that require a provider will be skipped or use NLP-only parsing.
              </p>
            )}
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
          <p className="muted">Select a file below to add, edit, or reorder values.</p>

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
              <p className="muted tiny">Drag items to reorder.</p>
            </section>
          ) : activeConfigMode === "cookbook-cards" ? (
            <section className="structured-editor">
              <article className="card">
                <div className="card-head">
                  <h4>Add Cookbook</h4>
                </div>
                <div className="cookbook-add-form">
                  <div className="cookbook-add-fields">
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
                        onChange={(event) =>
                          setCookbookDraft((prev) => ({ ...prev, description: event.target.value }))
                        }
                        placeholder="Quick and reliable evening meals."
                      />
                    </label>
                  </div>

                  {[
                    { key: "categories", label: "Categories" },
                    { key: "tags", label: "Tags" },
                  ].map((group) => {
                    const selected = cookbookDraft.filterSelections[group.key] || [];
                    const options = (availableFilterOptions[group.key] || []).filter(
                      (v) => !selected.includes(v)
                    );
                    return (
                      <label key={group.key} className="field">
                        <span>{group.label}</span>
                        <div className="filter-select-row">
                          <select
                            value=""
                            onChange={(event) => {
                              const val = event.target.value;
                              if (!val) return;
                              setCookbookDraft((prev) => {
                                const newSelections = {
                                  ...prev.filterSelections,
                                  [group.key]: [...(prev.filterSelections[group.key] || []), val],
                                };
                                return {
                                  ...prev,
                                  filterSelections: newSelections,
                                  queryFilterString: buildQueryFilter(newSelections),
                                };
                              });
                            }}
                          >
                            <option value="">Select {group.label.toLowerCase()}...</option>
                            {options.map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                          {selected.length > 0 && (
                            <div className="filter-chips">
                              {selected.map((val) => (
                                <span key={val} className="filter-chip">
                                  {val}
                                  <button
                                    type="button"
                                    className="chip-remove"
                                    onClick={() => {
                                      setCookbookDraft((prev) => {
                                        const newSelections = {
                                          ...prev.filterSelections,
                                          [group.key]: (prev.filterSelections[group.key] || []).filter(
                                            (v) => v !== val
                                          ),
                                        };
                                        return {
                                          ...prev,
                                          filterSelections: newSelections,
                                          queryFilterString: buildQueryFilter(newSelections),
                                        };
                                      });
                                    }}
                                  >
                                    <Icon name="x" />
                                  </button>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </label>
                    );
                  })}

                  <div className="cookbook-add-actions">
                    <label className="field">
                      <span>Position</span>
                      <input
                        type="number"
                        min="1"
                        value={cookbookDraft.position}
                        onChange={(event) =>
                          setCookbookDraft((prev) => ({ ...prev, position: event.target.value }))
                        }
                      />
                    </label>
                    <label className="field field-inline">
                      <span>Public</span>
                      <input
                        type="checkbox"
                        checked={Boolean(cookbookDraft.public)}
                        onChange={(event) =>
                          setCookbookDraft((prev) => ({ ...prev, public: event.target.checked }))
                        }
                      />
                    </label>
                    <button className="ghost" type="button" onClick={addCookbookEntry}>
                      Add Cookbook
                    </button>
                  </div>
                </div>
              </article>

              {activeCookbookItems.length > 0 && (
                <article className="card">
                  <div className="card-head">
                    <h4>Cookbooks ({activeCookbookItems.length})</h4>
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
                        </div>

                        {[
                          { key: "categories", label: "Categories" },
                          { key: "tags", label: "Tags" },
                        ].map((group) => {
                          const sel = (item.filterSelections || {})[group.key] || [];
                          const opts = (availableFilterOptions[group.key] || []).filter(
                            (v) => !sel.includes(v)
                          );
                          return (
                            <label key={group.key} className="field">
                              <span>{group.label}</span>
                              <div className="filter-select-row">
                                <select
                                  value=""
                                  onChange={(event) => {
                                    const val = event.target.value;
                                    if (!val) return;
                                    updateCookbookFilterSelections(index, {
                                      ...(item.filterSelections || { categories: [], tags: [] }),
                                      [group.key]: [...sel, val],
                                    });
                                  }}
                                >
                                  <option value="">Select {group.label.toLowerCase()}...</option>
                                  {opts.map((opt) => (
                                    <option key={opt} value={opt}>
                                      {opt}
                                    </option>
                                  ))}
                                </select>
                                {sel.length > 0 && (
                                  <div className="filter-chips">
                                    {sel.map((val) => (
                                      <span key={val} className="filter-chip">
                                        {val}
                                        <button
                                          type="button"
                                          className="chip-remove"
                                          onClick={() => {
                                            updateCookbookFilterSelections(index, {
                                              ...(item.filterSelections || { categories: [], tags: [] }),
                                              [group.key]: sel.filter((v) => v !== val),
                                            });
                                          }}
                                        >
                                          <Icon name="x" />
                                        </button>
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </label>
                          );
                        })}

                        <div className="cookbook-item-footer">
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
                              onClick={() =>
                                moveCookbookEntry(index, Math.min(index + 1, activeCookbookItems.length - 1))
                              }
                              disabled={index === activeCookbookItems.length - 1}
                            >
                              Down
                            </button>
                            <button
                              type="button"
                              className="ghost small"
                              onClick={() => removeCookbookEntry(index)}
                            >
                              Remove
                            </button>
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </article>
              )}
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
              <p className="muted tiny">Define units and their aliases.</p>
            </section>
          ) : (
            <section>
              <p className="muted tiny">This file uses a structured format. Edit the JSON directly below.</p>
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
            <h3><Icon name="upload" /> Import from JSON</h3>
            <p className="muted">Drop a .json file, browse for one, or paste JSON below.</p>

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

            <div
              className={`drop-zone ${importJsonText ? "has-content" : ""}`}
              onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("drag-over"); }}
              onDragLeave={(e) => { e.currentTarget.classList.remove("drag-over"); }}
              onDrop={(e) => {
                e.preventDefault();
                e.currentTarget.classList.remove("drag-over");
                const file = e.dataTransfer.files?.[0];
                if (file) {
                  const reader = new FileReader();
                  reader.onload = () => setImportJsonText(reader.result);
                  reader.readAsText(file);
                }
              }}
            >
              <textarea
                rows={8}
                value={importJsonText}
                onChange={(event) => setImportJsonText(event.target.value)}
                placeholder='Drop a .json file here or paste JSON content&#10;&#10;[ {"name": "One"}, {"name": "Two"} ]'
              />
              {!importJsonText && (
                <div className="drop-zone-hint">
                  <Icon name="upload" />
                  <span>Drop .json file or <label className="link-text">browse<input type="file" accept=".json,application/json" hidden onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      const reader = new FileReader();
                      reader.onload = () => setImportJsonText(reader.result);
                      reader.readAsText(file);
                    }
                    e.target.value = "";
                  }} /></label></span>
                </div>
              )}
            </div>

            <button className="primary" onClick={importTaxonomyJson} disabled={!importJsonText.trim()}>
              <Icon name="upload" />
              Import JSON
            </button>
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
                  type={showPassword ? "text" : "password"}
                  value={newUserPassword}
                  onChange={(event) => setNewUserPassword(event.target.value)}
                  placeholder="At least 8 characters"
                />
                <button type="button" className="ghost icon-btn" onClick={() => setShowPassword((v) => !v)} title={showPassword ? "Hide password" : "Show password"}>
                  <Icon name={showPassword ? "eye-off" : "eye"} />
                </button>
                <button type="button" className="ghost" onClick={generateTemporaryPassword}>
                  Generate
                </button>
              </div>
            </label>

            <button type="submit" className="primary">
              <Icon name="users" />
              Create User
            </button>
          </form>
        </article>

        <article className="card">
          <div className="card-head split">
            <h3>Current Users</h3>
            <label className="search-box">
              <Icon name="search" />
              <input
                value={userSearch}
                onChange={(event) => setUserSearch(event.target.value)}
                placeholder="Search"
              />
            </label>
          </div>

          <ul className="user-list">
            {filteredUsers.length === 0 ? (
              <li className="muted">No users found.</li>
            ) : (
              filteredUsers.map((item) => {
                const isMe = session?.username === item.username;
                const isOpen = expandedUser === item.username;
                return (
                  <li key={item.username} className={`user-row${isOpen ? " open" : ""}`}>
                    <div className="user-row-header">
                      <button type="button" className="user-row-toggle" onClick={() => setExpandedUser(isOpen ? null : item.username)}>
                        <strong>{item.username}</strong>
                        <span className="user-row-meta">
                          <span className="status-pill neutral">{userRoleLabel(item.username, session?.username)}</span>
                          {isMe && <span className="status-pill success">You</span>}
                        </span>
                        <Icon name="chevron" className={`row-chevron${isOpen ? " rotated" : ""}`} />
                      </button>
                      {!isMe && (
                        <button type="button" className="ghost danger-text icon-btn" title="Remove user" onClick={() => deleteUser(item.username)}>
                          <Icon name="trash" />
                        </button>
                      )}
                    </div>
                    {isOpen && (
                      <div className="user-row-body">
                        <div className="password-row">
                          <input
                            type="text"
                            placeholder="New password"
                            value={resetPasswords[item.username] || ""}
                            onChange={(event) =>
                              setResetPasswords((prev) => ({ ...prev, [item.username]: event.target.value }))
                            }
                          />
                          <button className="ghost" onClick={() => resetUserPassword(item.username)}>
                            Reset Password
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })
            )}
          </ul>

          <p className="muted tiny">{users.length} user{users.length !== 1 ? "s" : ""}</p>
        </article>
      </section>
    );
  }

  function renderHelpPage() {
    return (
      <section className="page-grid settings-grid help-grid">
        <div className="stacked-cards">
          <article className="card">
            <h3>Frequently Asked Questions</h3>
            <p className="muted">Common workflows and quick answers for daily use.</p>

            <div className="accordion-stack">
              {HELP_FAQ.map((item, index) => (
                <details className="accordion" key={item.question} open={index === 0}>
                  <summary>
                    <Icon name={item.icon || "help"} />
                    <span>{item.question}</span>
                    <Icon name="chevron" />
                  </summary>
                  <p>{item.answer}</p>
                </details>
              ))}
            </div>
          </article>

          <article className="card">
            <h3>Troubleshooting</h3>
            <p className="muted">Common issues grouped by area.</p>

            <div className="accordion-stack">
              {HELP_TROUBLESHOOTING.map((section) => (
                <details className="accordion" key={section.title}>
                  <summary>
                    <Icon name={section.icon || "info"} />
                    <span>{section.title}</span>
                    <Icon name="chevron" />
                  </summary>
                  <div className="doc-preview">
                    <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                      {section.items.map((tip, idx) => (
                        <li key={idx} className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.3rem" }}>
                          {tip}
                        </li>
                      ))}
                    </ul>
                  </div>
                </details>
              ))}
            </div>
          </article>
        </div>

        <aside className="stacked-cards">
          <article className="card">
            <h3>Reference Guides</h3>
            <p className="muted">Embedded documentation you can read without leaving the app.</p>

            <div className="accordion-stack">
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
        </aside>
      </section>
    );
  }

  function renderAboutPage() {
    const appVersion = aboutMeta?.app_version || healthMeta?.version || "-";
    const backendStatus = healthMeta?.ok === false ? "Degraded" : "Connected";
    const lastSyncLabel = lastLoadedAt ? formatDateTime(lastLoadedAt) : "-";

    return (
      <section className="page-grid about-grid">
          <article className="card">
            <h3><Icon name="info" /> CookDex v{appVersion}</h3>
            <ul className="kv-list">
              <li>
                <span>Backend</span>
                <strong>{backendStatus}</strong>
              </li>
              <li>
                <span>Last Sync</span>
                <strong>{lastSyncLabel}</strong>
              </li>
              <li>
                <span>License</span>
                <strong>MIT</strong>
              </li>
              <li>
                <span>Environment</span>
                <strong>Self-hosted</strong>
              </li>
            </ul>
          </article>

          <article className="card">
            <h3><Icon name="external" /> Project Links</h3>
            <a
              className="link-btn"
              href={aboutMeta?.links?.github || "https://github.com/thekannen/cookdex"}
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="github" />
              GitHub Repository
            </a>
            <a
              className="link-btn"
              href={aboutMeta?.links?.sponsor || "https://github.com/sponsors/thekannen"}
              target="_blank"
              rel="noreferrer"
            >
              <Icon name="heart" />
              Sponsor the Project
            </a>
          </article>

          <article className="card">
            <h3><Icon name="help" /> Why this app exists</h3>
            <p className="muted">
              CookDex is designed for home server users who want powerful cleanup and organization workflows without
              command-line complexity.
            </p>
          </article>
      </section>
    );
  }

  function renderPage() {
    if (activePage === "tasks") return renderTasksPage();
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
            CookDex guides setup, keeps labels human-friendly, and protects secrets by default.
          </p>
          <div className="auth-points">
            <p>One admin account unlocks the full workspace.</p>
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
          <p className="muted tiny">Already set up? Reload the page after creating your account to sign in.</p>
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="auth-shell">
        <section className="auth-left">
          <img src={wordmark} alt="CookDex" className="auth-wordmark" />
          <p className="auth-badge">Welcome back</p>
          <h1>Sign in to your CookDex workspace.</h1>
          <p>CookDex guides setup, keeps labels human-friendly, and protects secrets by default.</p>
          <div className="auth-points">
            <p>Run tasks manually or on a schedule from one interface.</p>
            <p>Manage taxonomy files, categories, and cookbooks visually.</p>
            <p>Review run history and logs without touching the command line.</p>
          </div>
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

  const showHeaderBreadcrumb = false;
  const showHeaderRefresh = false;

  return (
    <main className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className={`sidebar ${sidebarCollapsed ? "collapsed" : ""}`}>
        <div className="sidebar-top">
          <div className="brand-wrap">
            <img src={sidebarCollapsed ? emblem : wordmark} alt="CookDex" className="brand-mark" />
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
            <span className="avatar"><Icon name="user" /></span>
            <div>
              <p className="tiny muted">Signed in as</p>
              <strong>{session.username}</strong>
            </div>
            <span className="role-badge">Owner</span>
          </div>

          <div className="sidebar-actions">
            <div className="sidebar-actions-row">
              <button className="ghost" onClick={loadData} title="Refresh data" disabled={isLoading}>
                <Icon name="refresh" className={isLoading ? "spin" : ""} />
                <span>{isLoading ? "Loading\u2026" : "Refresh"}</span>
              </button>
              <button
                className="ghost"
                onClick={() => setTheme((prev) => (prev === "dark" ? "light" : "dark"))}
                title="Toggle theme"
              >
                <Icon name="contrast" />
                <span>Theme</span>
              </button>
            </div>
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

        {error ? <div className="banner error"><span>{error}</span><button className="banner-close" onClick={() => setError("")}><Icon name="x" /></button></div> : null}
        {!error && notice ? <div className="banner info"><span>{notice}</span><button className="banner-close" onClick={clearBanners}><Icon name="x" /></button></div> : null}

        {renderPage()}
      </section>

      {confirmModal && (
        <div className="modal-backdrop" onClick={() => setConfirmModal(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <p>{confirmModal.message}</p>
            <div className="modal-actions">
              <button className="ghost" onClick={() => setConfirmModal(null)}>Cancel</button>
              <button className="primary danger" onClick={() => { setConfirmModal(null); confirmModal.action(); }}>Remove</button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

