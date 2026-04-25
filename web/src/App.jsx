import React, { useEffect, useMemo, useRef, useState } from "react";
import wordmark from "./assets/CookDex_wordmark.png";
import emblem from "./assets/CookDex_light.png";

import { BASE_PATH, NAV_ITEMS, PAGE_META, CONFIG_LABELS, TAXONOMY_FILE_NAMES } from "./constants";
import {
  api,
  moveArrayItem,
  normalizeCookbookEntries,
  normalizeErrorMessage,
  normalizeLabelEntries,
  normalizeToolEntries,
  normalizeUnitEntries,
  parseAliasInput,
  parseQueryFilter,
  buildQueryFilter,
  FILTER_FIELDS,
  FILTER_OPERATORS,
  parseLineEditorContent,
  isOwnerRole,
  userRoleLabel,
} from "./utils.jsx";
import Icon from "./components/Icon";
import RecipeWorkspacePage from "./pages/recipe-workspace/RecipeWorkspacePage";
import AboutPage from "./pages/about/AboutPage";
import HelpPage from "./pages/help/HelpPage";
import UsersPage from "./pages/users/UsersPage";
import RecipeSourcesPage from "./pages/recipe-sources/RecipeSourcesPage";
import SettingsPage from "./pages/settings/SettingsPage";
import OverviewPage from "./pages/overview/OverviewPage";
import TasksPage from "./pages/tasks/TasksPage";

function canAccessNavItem(item, role) {
  return !item.ownerOnly || isOwnerRole(role);
}

function sanitizeCachedDataForRole(data, role) {
  if (!data || typeof data !== "object" || isOwnerRole(role)) {
    return data;
  }
  return {
    ...data,
    users: { items: [] },
    settings: null,
  };
}

export default function App() {
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [setupRequired, setSetupRequired] = useState(false);
  const [registerUsername, setRegisterUsername] = useState("admin");
  const [registerPassword, setRegisterPassword] = useState("");
  const [registerPasswordConfirm, setRegisterPasswordConfirm] = useState("");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [session, setSession] = useState(null);
  const sessionRef = useRef(null);

  const [theme, setTheme] = useState(() => {
    const stored = window.localStorage.getItem("cookdex_webui_theme");
    if (stored === "light" || stored === "dark") {
      return stored;
    }
    return "light";
  });

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.localStorage.getItem("cookdex_sidebar") === "collapsed");
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [activePage, setActivePage] = useState(() => {
    // Derive initial page from URL pathname (e.g. /cookdex/tasks → "tasks").
    const path = window.location.pathname.replace(/\/+$/, "");
    const base = BASE_PATH.replace(/\/+$/, "");
    const relative = base ? path.replace(base, "") : path;
    const segment = relative.replace(/^\/+/, "").split("/")[0] || "";
    const validIds = NAV_ITEMS.map((item) => item.id);
    if (segment && validIds.includes(segment)) return segment;
    // Fall back to localStorage for root URL visits.
    const stored = window.localStorage.getItem("cookdex_page");
    return stored || "overview";
  });

  const [tasks, setTasks] = useState([]);
  const [runs, setRuns] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [users, setUsers] = useState([]);

  const [configFiles, setConfigFiles] = useState([]);
  const [activeConfig, setActiveConfig] = useState("categories");
  const [activeConfigBody, setActiveConfigBody] = useState("[]\n");
  const [activeConfigMode, setActiveConfigMode] = useState("line-pills");
  const [activeConfigListKind, setActiveConfigListKind] = useState("name_object");
  const [activeConfigItems, setActiveConfigItems] = useState([]);
  const [activeCookbookItems, setActiveCookbookItems] = useState([]);
  const [activeToolItems, setActiveToolItems] = useState([]);
  const [activeLabelItems, setActiveLabelItems] = useState([]);
  const [activeUnitItems, setActiveUnitItems] = useState([]);
  const [toolDraft, setToolDraft] = useState({ name: "", onHand: false });
  const [labelDraft, setLabelDraft] = useState({ name: "", color: "#959595" });
  const [unitDraft, setUnitDraft] = useState({ name: "", pluralName: "", abbreviation: "", pluralAbbreviation: "", description: "", fraction: true, useAbbreviation: false, aliases: [] });
  const [configDraftItem, setConfigDraftItem] = useState("");
  const [cookbookDraft, setCookbookDraft] = useState({
    name: "",
    description: "",
    queryFilterString: "",
    filterRows: [],
    public: false,
    position: 1,
  });
  const [dragIndex, setDragIndex] = useState(null);

  const [taxonomyBootstrapMode, setTaxonomyBootstrapMode] = useState("replace");
  const [starterPackMode, setStarterPackMode] = useState("merge");
  const [taxonomyActionLoading, setTaxonomyActionLoading] = useState("");
  const [taxonomySetupFiles, setTaxonomySetupFiles] = useState([...TAXONOMY_FILE_NAMES]);

  const [confirmModal, setConfirmModal] = useState(null);
  const [forcedResetPending, setForcedResetPending] = useState(false);
  const [forcedResetPassword, setForcedResetPassword] = useState("");
  const [forcedResetShowPass, setForcedResetShowPass] = useState(false);

  const [taxonomyItemsByFile, setTaxonomyItemsByFile] = useState({});
  const [overviewMetrics, setOverviewMetrics] = useState(null);
  const [qualityMetrics, setQualityMetrics] = useState(null);
  const [aboutMeta, setAboutMeta] = useState(null);
  const [healthMeta, setHealthMeta] = useState(null);
  const [lastLoadedAt, setLastLoadedAt] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [taskHandoff, setTaskHandoff] = useState(null);

  const openConfigRequestRef = useRef(0);

  const taskTitleById = useMemo(() => {
    const map = new Map();
    for (const task of tasks) {
      map.set(task.task_id, task.title || task.task_id);
    }
    return map;
  }, [tasks]);

  const activePageMeta = PAGE_META[activePage] || PAGE_META.overview;
  const visibleNavItems = useMemo(
    () => NAV_ITEMS.filter((item) => canAccessNavItem(item, session?.role)),
    [session]
  );



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
      tools: extractNames(taxonomyItemsByFile.tools),
    };
  }, [taxonomyItemsByFile]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem("cookdex_webui_theme", theme);
  }, [theme]);

  useEffect(() => {
    window.localStorage.setItem("cookdex_page", activePage);
    // Keep URL in sync when activePage changes (e.g. from popstate).
    const base = BASE_PATH.replace(/\/+$/, "");
    const target = activePage === "overview"
      ? (base || "/")
      : `${base}/${activePage}`;
    if (window.location.pathname.replace(/\/+$/, "") !== target.replace(/\/+$/, "")) {
      window.history.replaceState({ page: activePage }, "", target);
    }
  }, [activePage]);

  useEffect(() => {
    if (!session) return;
    const currentNav = NAV_ITEMS.find((item) => item.id === activePage);
    if (currentNav && !canAccessNavItem(currentNav, session.role)) {
      navigateTo("overview");
    }
  }, [activePage, session]);

  function navigateTo(pageId) {
    const base = BASE_PATH.replace(/\/+$/, "");
    const url = pageId === "overview" ? (base || "/") : `${base}/${pageId}`;
    window.history.pushState({ page: pageId }, "", url);
    setActivePage(pageId);
  }

  useEffect(() => {
    function onPopState(event) {
      if (event.state?.page) {
        setActivePage(event.state.page);
        return;
      }
      // Parse page from URL for manually typed URLs or external links.
      const path = window.location.pathname.replace(/\/+$/, "");
      const base = BASE_PATH.replace(/\/+$/, "");
      const relative = base ? path.replace(base, "") : path;
      const segment = relative.replace(/^\/+/, "").split("/")[0] || "";
      const validIds = NAV_ITEMS.map((item) => item.id);
      setActivePage(segment && validIds.includes(segment) ? segment : "overview");
    }
    // Set initial state so the first page has history state for back navigation.
    window.history.replaceState({ page: activePage }, "");
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    window.localStorage.setItem("cookdex_sidebar", sidebarCollapsed ? "collapsed" : "expanded");
  }, [sidebarCollapsed]);

  // Lazy-load taxonomy content only when navigating to pages that need it.
  const taxonomyLoaded = React.useRef(false);
  useEffect(() => {
    if (!session) return;
    if (activePage === "recipe-organization" || (activePage === "settings" && isOwnerRole(session.role))) {
      if (!taxonomyLoaded.current) {
        taxonomyLoaded.current = true;
        loadTaxonomyContent();
      }
    }
  }, [activePage, session]);

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

  function formatRuleSyncNotice(ruleSync, { quietIfUnchanged = true } = {}) {
    if (!ruleSync || typeof ruleSync !== "object") return "";
    const updated = Boolean(ruleSync.updated);
    if (!updated && quietIfUnchanged) return "";
    const removed = Number(ruleSync.removed_total || 0);
    const generated = Number(ruleSync.generated_total || 0);
    const canonicalized = Number(ruleSync.canonicalized_total || 0);
    const parts = [];
    if (generated > 0) parts.push(`generated ${generated} default rule${generated === 1 ? "" : "s"}`);
    if (removed > 0) parts.push(`removed ${removed} stale rule${removed === 1 ? "" : "s"}`);
    if (canonicalized > 0) {
      parts.push(`normalized ${canonicalized} target name${canonicalized === 1 ? "" : "s"}`);
    }
    if (parts.length > 0) {
      return `Tag rules synchronized: ${parts.join(", ")}.`;
    }
    if (Boolean(ruleSync.created)) return "Tag rules file initialized and synchronized.";
    return "Tag rules synchronized.";
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
            filterRows: parseQueryFilter(item.queryFilterString),
          }))
        : []
    );
    setActiveToolItems(editor.mode === "tool-cards" ? editor.items : []);
    setActiveLabelItems(editor.mode === "label-cards" ? editor.items : []);
    setActiveUnitItems(editor.mode === "unit-cards" ? editor.items : []);
    setConfigDraftItem("");
    setCookbookDraft({
      name: "",
      description: "",
      queryFilterString: "",
      filterRows: [],
      public: false,
      position: Math.max(1, (editor.mode === "cookbook-cards" ? editor.items.length : 0) + 1),
    });
    setDragIndex(null);
    setActiveConfigBody(`${JSON.stringify(content, null, 2)}\n`);
  }

  async function refreshSession() {
    try {
      const payload = await api("/auth/session", { method: "GET" });
      sessionRef.current = payload;
      setSession(payload);
      setError("");
      if (!isOwnerRole(payload.role)) {
        patchCachedData((cached) => sanitizeCachedDataForRole(cached, payload.role));
      }
      if (payload.force_reset) setForcedResetPending(true);
      return payload;
    } catch {
      sessionRef.current = null;
      setSession(null);
      return null;
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
  const overviewMetricsLoadingRef = React.useRef(false);

  function hasDataKey(data, key) {
    return Object.prototype.hasOwnProperty.call(data || {}, key);
  }

  function saveCachedData(partial, currentSession, { merge = false } = {}) {
    try {
      let existing = {};
      if (merge) {
        const raw = sessionStorage.getItem(CACHE_KEY);
        existing = raw ? JSON.parse(raw) : {};
      }
      const next = sanitizeCachedDataForRole(
        {
          ...existing,
          ...partial,
          savedAt: partial.savedAt || Date.now(),
          timestamp: partial.timestamp || existing.timestamp || new Date().toISOString(),
        },
        currentSession?.role
      );
      sessionStorage.setItem(CACHE_KEY, JSON.stringify(next));
      return next;
    } catch (e) {
      console.warn("sessionStorage unavailable:", e);
      return null;
    }
  }

  function patchCachedData(mutator) {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return;
      const cached = JSON.parse(raw);
      const next = mutator(cached);
      if (!next || typeof next !== "object") return;
      next.savedAt = Date.now();
      if (!next.timestamp) {
        next.timestamp = new Date().toISOString();
      }
      sessionStorage.setItem(CACHE_KEY, JSON.stringify(next));
    } catch (e) {
      console.warn("sessionStorage unavailable:", e);
    }
  }

  function applyData(data) {
    if (hasDataKey(data, "tasks")) {
      setTasks(data.tasks?.items || []);
    }
    if (hasDataKey(data, "runs")) {
      setRuns(data.runs?.items || []);
    }
    if (hasDataKey(data, "schedules")) {
      setSchedules(data.schedules?.items || []);
    }
    if (hasDataKey(data, "config")) {
      setConfigFiles(data.config?.items || []);
    }
    if (hasDataKey(data, "users")) {
      setUsers(data.users?.items || []);
    }
    if (hasDataKey(data, "metrics")) {
      setOverviewMetrics(data.metrics);
    }
    if (hasDataKey(data, "quality")) {
      setQualityMetrics(data.quality);
    }
    if (hasDataKey(data, "about")) {
      setAboutMeta(data.about);
    }
    if (hasDataKey(data, "health")) {
      setHealthMeta(data.health);
    }
    if (hasDataKey(data, "timestamp")) {
      setLastLoadedAt(data.timestamp);
    }
  }

  function scheduleAutoRefresh() {
    clearTimeout(staleTimer.current);
    staleTimer.current = setTimeout(() => { loadData(); }, CACHE_TTL);
  }

  function loadCachedData(currentSession) {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (!raw) return false;
      const cached = sanitizeCachedDataForRole(JSON.parse(raw), currentSession?.role);
      if (Date.now() - cached.savedAt > CACHE_TTL) return false;
      applyData(cached);
      scheduleAutoRefresh();
      return true;
    } catch { return false; }
  }

  const prevRunsRef = React.useRef([]);

  async function refreshRuns() {
    try {
      const payload = await api("/runs");
      const nextRuns = payload?.items || [];
      const prev = prevRunsRef.current;
      const qualityJustFinished = nextRuns.some((run) => {
        if (run.task_id !== "health-check") return false;
        if (run.status !== "succeeded") return false;
        const old = prev.find((r) => r.run_id === run.run_id);
        return !old || old.status !== "succeeded";
      });
      // Detect run status transitions for success/failure micro-feedback.
      if (prev.length > 0) {
        for (const run of nextRuns) {
          const old = prev.find((r) => r.run_id === run.run_id);
          if (old && old.status === "running" && run.status === "succeeded") {
            const title = taskTitleById.get(run.task_id) || run.task_id;
            showNotice(`\u2705 ${title} completed successfully.`);
          } else if (old && old.status === "running" && run.status === "failed") {
            const title = taskTitleById.get(run.task_id) || run.task_id;
            showNotice(`\u274C ${title} failed.`);
          }
        }
      }
      prevRunsRef.current = nextRuns;
      setRuns(nextRuns);
      if (qualityJustFinished) {
        api("/metrics/quality").then((q) => setQualityMetrics(q)).catch(() => {});
      }
    } catch (exc) { handleError(exc); }
  }

  async function refreshSchedules() {
    try {
      const payload = await api("/schedules");
      const nextSchedules = payload?.items || [];
      setSchedules(nextSchedules);
      patchCachedData((cached) => ({ ...cached, schedules: { items: nextSchedules } }));
    } catch (exc) { handleError(exc); }
  }

  async function refreshUsers() {
    if (!isOwnerRole(session?.role)) {
      setUsers([]);
      return;
    }
    try {
      const payload = await api("/users");
      setUsers(payload?.items || []);
    } catch (exc) { handleError(exc); }
  }

  async function refreshTasks() {
    try {
      const payload = await api("/tasks");
      setTasks(payload?.items || []);
    } catch (exc) { handleError(exc); }
  }

  async function refreshOverviewMetrics(currentSession = session) {
    if (!currentSession || currentSession.force_reset || overviewMetricsLoadingRef.current) {
      return;
    }
    overviewMetricsLoadingRef.current = true;
    try {
      const metricsPayload = await api("/metrics/overview").catch(() => null);
      const activeSession = sessionRef.current;
      if (
        !activeSession ||
        activeSession.force_reset ||
        activeSession.username !== currentSession.username
      ) {
        return;
      }
      setOverviewMetrics(metricsPayload);
      patchCachedData((cached) =>
        sanitizeCachedDataForRole({ ...cached, metrics: metricsPayload }, currentSession?.role)
      );
    } catch {
      // Live Mealie metrics are useful on the overview page, but they should not
      // block local task and activity data from loading.
    } finally {
      overviewMetricsLoadingRef.current = false;
    }
  }

  async function loadData(currentSession = session) {
    if (isLoading) return;
    setIsLoading(true);
    showNotice("Refreshing local data\u2026", 30000);
    try {
      const isOwner = isOwnerRole(currentSession?.role);
      const [
        taskPayload, runPayload, schedulePayload, settingsPayload,
        configPayload, usersPayload,
        qualityPayload, aboutPayload, healthPayload,
      ] = await Promise.all([
        api("/tasks"),
        api("/runs"),
        api("/schedules"),
        isOwner ? api("/settings") : Promise.resolve(null),
        api("/config/files"),
        isOwner ? api("/users") : Promise.resolve({ items: [] }),
        api("/metrics/quality").catch(() => null),
        api("/about/meta").catch(() => null),
        api("/health").catch(() => null),
      ]);

      const data = sanitizeCachedDataForRole({
        tasks: taskPayload, runs: runPayload, schedules: schedulePayload,
        settings: settingsPayload, config: configPayload, users: usersPayload,
        quality: qualityPayload,
        about: aboutPayload, health: healthPayload,
        timestamp: new Date().toISOString(), savedAt: Date.now(),
      }, currentSession?.role);

      applyData(data);

      saveCachedData(data, currentSession, { merge: true });

      clearBanners();
      scheduleAutoRefresh();
      refreshOverviewMetrics(currentSession);
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

        const nextSession = await refreshSession();
        if (nextSession) {
          if (nextSession.force_reset) {
            return;
          }
          if (!loadCachedData(nextSession)) {
            await loadData(nextSession);
          } else {
            refreshOverviewMetrics(nextSession);
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
      if (registerPassword !== registerPasswordConfirm) {
        setError("Passwords do not match.");
        return;
      }
      await api("/auth/register", {
        method: "POST",
        body: {
          username: registerUsername,
          password: registerPassword,
        },
      });
      setRegisterPassword("");
      setRegisterPasswordConfirm("");
      setSetupRequired(false);
      const nextSession = await refreshSession();
      await loadData(nextSession);
      showNotice("Owner account created.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function doLogin(event) {
    event.preventDefault();
    try {
      clearBanners();
      const loginResult = await api("/auth/login", { method: "POST", body: { username, password } });
      setPassword("");
      const nextSession = await refreshSession();
      if (loginResult?.force_reset) {
        setForcedResetPending(true);
      } else {
        await loadData(nextSession);
        showNotice("Signed in successfully.");
      }
    } catch (exc) {
      handleError(exc);
    }
  }

  async function doLogout() {
    try {
      clearBanners();
      await api("/auth/logout", { method: "POST" });
      sessionRef.current = null;
      setSession(null);
      setRuns([]);
      setSchedules([]);
      setUsers([]);
      sessionStorage.removeItem(CACHE_KEY);
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
        filterRows: [...(cookbookDraft.filterRows || [])],
        public: Boolean(cookbookDraft.public),
        position: Number.isFinite(parsedPosition) && parsedPosition > 0 ? parsedPosition : prev.length + 1,
      },
    ]);
    setCookbookDraft((prev) => ({
      ...prev,
      name: "",
      description: "",
      queryFilterString: "",
      filterRows: [],
      public: false,
      position: nextPosition,
    }));
  }

  function updateCookbookFilterRows(index, newRows) {
    setActiveCookbookItems((prev) =>
      prev.map((item, i) =>
        i === index
          ? { ...item, filterRows: newRows, queryFilterString: buildQueryFilter(newRows) }
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

  // --- Tool card helpers ---
  function addToolEntry() {
    if (!toolDraft.name.trim()) return;
    setActiveToolItems((prev) => [...prev, { ...toolDraft, name: toolDraft.name.trim() }]);
    setToolDraft({ name: "", onHand: false });
  }
  function updateToolEntry(index, key, value) {
    setActiveToolItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [key]: value } : item))
    );
  }
  function removeToolEntry(index) {
    setActiveToolItems((prev) => prev.filter((_, i) => i !== index));
  }
  function moveToolEntry(from, to) {
    setActiveToolItems((prev) => moveArrayItem(prev, from, to));
  }

  // --- Label card helpers ---
  function addLabelEntry() {
    if (!labelDraft.name.trim()) return;
    setActiveLabelItems((prev) => [...prev, { ...labelDraft, name: labelDraft.name.trim() }]);
    setLabelDraft({ name: "", color: "#959595" });
  }
  function updateLabelEntry(index, key, value) {
    setActiveLabelItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [key]: value } : item))
    );
  }
  function removeLabelEntry(index) {
    setActiveLabelItems((prev) => prev.filter((_, i) => i !== index));
  }
  function moveLabelEntry(from, to) {
    setActiveLabelItems((prev) => moveArrayItem(prev, from, to));
  }

  // --- Unit card helpers ---
  function addUnitEntry() {
    if (!unitDraft.name.trim()) return;
    const aliases = Array.isArray(unitDraft.aliases) ? unitDraft.aliases : parseAliasInput(unitDraft.aliases);
    setActiveUnitItems((prev) => [...prev, { ...unitDraft, name: unitDraft.name.trim(), aliases }]);
    setUnitDraft({ name: "", pluralName: "", abbreviation: "", pluralAbbreviation: "", description: "", fraction: true, useAbbreviation: false, aliases: [] });
  }
  function updateUnitEntry(index, key, value) {
    if (key === "aliases") {
      const aliases = Array.isArray(value) ? value : parseAliasInput(value);
      setActiveUnitItems((prev) =>
        prev.map((item, i) => (i === index ? { ...item, aliases } : item))
      );
      return;
    }
    setActiveUnitItems((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [key]: value } : item))
    );
  }
  function removeUnitEntry(index) {
    setActiveUnitItems((prev) => prev.filter((_, i) => i !== index));
  }
  function moveUnitEntry(from, to) {
    setActiveUnitItems((prev) => moveArrayItem(prev, from, to));
  }

  async function openConfig(name) {
    const requestId = openConfigRequestRef.current + 1;
    openConfigRequestRef.current = requestId;
    try {
      clearBanners();
      const payload = await api(`/config/files/${name}`);
      if (requestId !== openConfigRequestRef.current) {
        return;
      }
      setActiveConfig(name);
      setConfigEditorState(payload.content, name);
    } catch (exc) {
      if (requestId !== openConfigRequestRef.current) {
        return;
      }
      handleError(exc);
    }
  }

  async function initializeFromMealieBaseline(includeFiles = taxonomySetupFiles) {
    try {
      clearBanners();
      if (!Array.isArray(includeFiles) || includeFiles.length === 0) {
        setError("Select at least one taxonomy file.");
        return;
      }
      setTaxonomyActionLoading("mealie");
      const payload = await api("/config/taxonomy/initialize-from-mealie", {
        method: "POST",
        body: { mode: taxonomyBootstrapMode, files: includeFiles },
      });
      await loadTaxonomyContent();
      const changedCount = Object.keys(payload?.changes || {}).length;
      const ruleNote = formatRuleSyncNotice(payload?.rule_sync);
      showNotice(
        `Managed baseline initialized from Mealie (${taxonomyBootstrapMode}). Updated ${changedCount} file(s).${ruleNote ? ` ${ruleNote}` : ""}`
      );
    } catch (exc) {
      handleError(exc);
    } finally {
      setTaxonomyActionLoading("");
    }
  }

  async function importStarterPack(includeFiles = taxonomySetupFiles) {
    try {
      clearBanners();
      if (!Array.isArray(includeFiles) || includeFiles.length === 0) {
        setError("Select at least one taxonomy file.");
        return;
      }
      setTaxonomyActionLoading("starter-pack");
      const payload = await api("/config/taxonomy/import-starter-pack", {
        method: "POST",
        body: {
          mode: starterPackMode,
          files: includeFiles,
        },
      });
      await loadTaxonomyContent();
      const changedCount = Object.keys(payload?.changes || {}).length;
      const ruleNote = formatRuleSyncNotice(payload?.rule_sync);
      showNotice(
        `Starter pack imported (${starterPackMode}). Updated ${changedCount} file(s).${ruleNote ? ` ${ruleNote}` : ""}`
      );
    } catch (exc) {
      handleError(exc);
    } finally {
      setTaxonomyActionLoading("");
    }
  }

  async function doForcedReset(event) {
    event.preventDefault();
    const newPass = forcedResetPassword.trim();
    if (!newPass) {
      setError("Enter a new password.");
      return;
    }
    try {
      clearBanners();
      await api(`/users/${encodeURIComponent(session.username)}/reset-password`, {
        method: "POST",
        body: { password: newPass, force_reset: false },
      });
      const nextSession = await refreshSession();
      setForcedResetPending(false);
      setForcedResetPassword("");
      setForcedResetShowPass(false);
      await loadData(nextSession);
      showNotice("Password changed. Welcome!");
    } catch (exc) {
      handleError(exc);
    }
  }

  function renderOverviewPage() {
    return (
      <OverviewPage
        tasks={tasks}
        runs={runs}
        schedules={schedules}
        overviewMetrics={overviewMetrics}
        qualityMetrics={qualityMetrics}
        taxonomyCounts={taxonomyCounts}
        navigateTo={navigateTo}
        onTaskHandoff={(taskId) => {
          setTaskHandoff(taskId);
          navigateTo("tasks");
        }}
      />
    );
  }

  function renderTasksPage() {
    return (
      <TasksPage
        tasks={tasks}
        runs={runs}
        schedules={schedules}
        session={session}
        taskHandoff={taskHandoff}
        onNotice={showNotice}
        onError={handleError}
        refreshRuns={refreshRuns}
        refreshSchedules={refreshSchedules}
        refreshTasks={refreshTasks}
        clearTaskHandoff={() => setTaskHandoff(null)}
        navigateTo={navigateTo}
        sidebarCollapsed={sidebarCollapsed}
      />
    );
  }


  const GROUP_ICONS = { Connection: "link", AI: "wand", "Direct DB": "database" };
  const GROUP_DESCRIPTIONS = {
    Connection: "Mealie URL and API key",
    AI: "Provider, model, and API keys for recipe categorization",
    "Direct DB": "PostgreSQL and SSH tunnel for bulk operations",
  };

  function renderSettingsPage() {
    return (
      <SettingsPage
        session={session}
        overviewMetrics={overviewMetrics}
        qualityMetrics={qualityMetrics}
        onNotice={showNotice}
        onError={handleError}
      />
    );
  }

  function renderRecipeSourcesPage() {
    return (
      <RecipeSourcesPage
        onNotice={showNotice}
        onError={handleError}
      />
    );
  }

  function renderRecipeOrganizationPage() {
    return (
      <RecipeWorkspacePage
        onNotice={showNotice}
        onError={handleError}
        onOpenTasks={(taskId) => {
          setTaskHandoff({ task_id: taskId });
          navigateTo("tasks");
        }}
        taxonomyFileNames={TAXONOMY_FILE_NAMES}
        configLabels={CONFIG_LABELS}
        taxonomySetupFiles={taxonomySetupFiles}
        setTaxonomySetupFiles={setTaxonomySetupFiles}
        taxonomyBootstrapMode={taxonomyBootstrapMode}
        setTaxonomyBootstrapMode={setTaxonomyBootstrapMode}
        starterPackMode={starterPackMode}
        setStarterPackMode={setStarterPackMode}
        taxonomyActionLoading={taxonomyActionLoading}
        onInitializeFromMealie={initializeFromMealieBaseline}
        onImportStarterPack={importStarterPack}
      />
    );
  }

  function renderUsersPage() {
    return (
      <UsersPage
        users={users}
        session={session}
        onNotice={showNotice}
        onError={handleError}
        onConfirm={setConfirmModal}
        refreshUsers={refreshUsers}
      />
    );
  }

  function renderHelpPage() {
    return <HelpPage aboutMeta={aboutMeta} />;
  }

  function renderAboutPage() {
    return <AboutPage aboutMeta={aboutMeta} healthMeta={healthMeta} lastLoadedAt={lastLoadedAt} />;
  }

  function renderPage() {
    if (activePage === "settings" && !isOwnerRole(session?.role)) return renderOverviewPage();
    if (activePage === "users" && !isOwnerRole(session?.role)) return renderOverviewPage();
    if (activePage === "tasks") return renderTasksPage();
    if (activePage === "settings") return renderSettingsPage();
    if (activePage === "recipe-sources") return renderRecipeSourcesPage();
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
            <p>One owner account unlocks the full workspace.</p>
            <p>Runtime settings are grouped with plain descriptions.</p>
            <p>No recipe data changes happen until you explicitly run tasks.</p>
          </div>
        </section>

        <section className="auth-card">
          <h2>Create Owner Account</h2>
          <p>This account can manage users, schedules, settings, and runs.</p>
          <form onSubmit={registerFirstUser}>
            <label className="field">
              <span>Owner Username</span>
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
                autoComplete="new-password"
                value={registerPassword}
                onChange={(event) => setRegisterPassword(event.target.value)}
                placeholder="At least 8 characters"
              />
            </label>
            <label className="field">
              <span>Confirm Password</span>
              <input
                type="password"
                autoComplete="new-password"
                value={registerPasswordConfirm}
                onChange={(event) => setRegisterPasswordConfirm(event.target.value)}
                placeholder="Re-enter password"
              />
            </label>
            <button type="submit" className="primary">
              <Icon name="users" />
              Create Owner Account
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
              <input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label className="field">
              <span>Password</span>
              <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
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

  const showPageHeader = activePage !== "overview";
  const showHeaderBreadcrumb = false;
  const showHeaderRefresh = false;

  return (
    <main className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <div className="mobile-header">
        <button className="icon-btn" onClick={() => setMobileSidebarOpen(true)} aria-label="Open menu">
          <Icon name="menu" />
        </button>
        <img src={wordmark} alt="CookDex" className="brand-mark" />
      </div>
      {mobileSidebarOpen && <div className="mobile-sidebar-backdrop" onClick={() => setMobileSidebarOpen(false)} />}
      <aside className={`sidebar ${sidebarCollapsed ? "collapsed" : ""} ${mobileSidebarOpen ? "mobile-open" : ""}`}>
        <div className="sidebar-top">
          <div className="brand-wrap">
            <img src={sidebarCollapsed ? emblem : wordmark} alt="CookDex" className="brand-mark" />
          </div>
          <button className="icon-btn" onClick={() => {
            if (window.innerWidth <= 760) {
              setMobileSidebarOpen((prev) => !prev);
            } else {
              setSidebarCollapsed((prev) => !prev);
            }
          }} aria-label="Toggle sidebar">
            <Icon name="menu" />
          </button>
        </div>

        <nav className="sidebar-nav">
          <p className="muted tiny">Workspace</p>
          {visibleNavItems.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${activePage === item.id ? "active" : ""}`}
              onClick={() => { navigateTo(item.id); setMobileSidebarOpen(false); }}
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
            <span className="role-badge">{userRoleLabel(session.role)}</span>
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
        {showPageHeader ? (
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
        ) : null}

        {error ? <div className="banner error" role="alert"><span>{error}</span><button className="banner-close" onClick={() => setError("")} aria-label="Dismiss error"><Icon name="x" /></button></div> : null}
        {!error && notice ? <div className="banner info" role="status"><span>{notice}</span><button className="banner-close" onClick={clearBanners} aria-label="Dismiss notice"><Icon name="x" /></button></div> : null}

        {renderPage()}
      </section>

      {confirmModal && (
        <div className="modal-backdrop" onClick={() => setConfirmModal(null)} onKeyDown={(e) => { if (e.key === "Escape") setConfirmModal(null); }}>
          <div className="modal-card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <p>{confirmModal.message}</p>
            <div className="modal-actions">
              <button className="ghost" onClick={() => setConfirmModal(null)}>Cancel</button>
              <button
                className={`primary${confirmModal.danger === false ? "" : " danger"}`}
                onClick={() => { setConfirmModal(null); confirmModal.action(); }}
              >
                {confirmModal.confirmLabel || "Remove"}
              </button>
            </div>
          </div>
        </div>
      )}

      {forcedResetPending && (
        <div className="modal-backdrop">
          <div className="modal-card forced-reset-card" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <h3>Password Reset Required</h3>
            <p className="muted">Your password was set by an administrator. Choose a new password before continuing.</p>
            <form className="run-form" onSubmit={doForcedReset}>
              <label className="field">
                <span>New Password</span>
                <div className="password-row">
                  <input
                    type={forcedResetShowPass ? "text" : "password"}
                    autoComplete="new-password"
                    value={forcedResetPassword}
                    onChange={(e) => setForcedResetPassword(e.target.value)}
                    placeholder="At least 8 characters"
                    autoFocus
                  />
                  <button type="button" className="ghost icon-btn" onClick={() => setForcedResetShowPass((v) => !v)} aria-label={forcedResetShowPass ? "Hide password" : "Show password"}>
                    <Icon name={forcedResetShowPass ? "eye-off" : "eye"} />
                  </button>
                </div>
              </label>
              <button type="submit" className="primary">
                <Icon name="lock" />
                Set New Password
              </button>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
