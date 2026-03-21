import React, { useEffect, useMemo, useRef, useState } from "react";
import Icon from "../../components/Icon";
import {
  api,
  buildDefaultOptionValues,
  fieldFromOption,
  formatDateTime,
  formatDateTimeShort,
  formatRunTime,
  formatRelativeTime,
  formatCountdown,
  normalizeErrorMessage,
  normalizeTaskOptions,
  parseIso,
  runTypeLabel,
  statusClass,
} from "../../utils.jsx";
import {
  DATA_MAINTENANCE_STAGE_LABELS,
  SUMMARY_PIPELINE_KEYS,
  SCHEDULE_UNIT_SECONDS,
  splitIntervalSeconds,
  toDateTimeLocalValue,
  localDatetimeToUTC,
  buildTaskOptionSeed,
  isTaskOptionVisible,
  parseLogEvents,
  groupLogEvents,
  getSummaryEntries,
  formatSummaryValue,
  isDataMaintenancePipelineSummary,
  summarizeExecutionEvents,
  buildStageResultSummary,
  buildPipelineExecutionSummary,
  renderSummaryTable,
  renderGroupedLogEvents,
  stageDisplayName,
  buildDataMaintenanceView,
} from "./taskLogUtils.jsx";

const TASK_GROUP_ORDER = ["Data Pipeline", "Actions", "Organizers", "Audits"];

const TASK_ICONS = {
  "data-maintenance": "settings",
  "clean-recipes": "trash",
  "ingredient-parse": "folder",
  "yield-normalize": "zap",
  "cleanup-duplicates": "layers",
  "tag-categorize": "tag",
  "taxonomy-refresh": "refresh",
  "cookbook-sync": "book-open",
  "reimport-recipes": "download",
  "health-check": "check-circle",
};

const TASK_GROUP_COLORS = {
  "Data Pipeline": "pipeline",
  Actions: "actions",
  Organizers: "organizers",
  Audits: "audits",
};

const STATUS_ICONS = {
  queued: { icon: "clock", label: "Queued" },
  running: { icon: "loader", label: "Running" },
  succeeded: { icon: "check-circle", label: "Done" },
  failed: { icon: "x-circle", label: "Failed" },
  canceled: { icon: "x", label: "Canceled" },
};

const TASK_SUMMARIES = {
  "data-maintenance": (o) => {
    const stages = Array.isArray(o.stages) && o.stages.length > 0 ? o.stages.length : "all";
    return `Run ${stages} maintenance stage${stages === 1 ? "" : "s"} ${o.dry_run !== false ? "in preview" : "with live changes"}`;
  },
  "clean-recipes": (o) => `${o.dry_run !== false ? "Preview" : "Remove"} duplicate and junk recipes`,
  "slug-repair": (o) => `${o.dry_run !== false ? "Detect" : "Fix"} recipe slug mismatches`,
  "ingredient-parse": (o) => `Parse ingredients with NLP ${o.dry_run !== false ? "(preview)" : "(live)"}`,
  "yield-normalize": (o) => `${o.dry_run !== false ? "Preview" : "Normalize"} missing yield and servings data`,
  "cleanup-duplicates": (o) => `Find and ${o.dry_run !== false ? "preview" : "merge"} duplicate ${o.target || "food & unit"} entries`,
  "reimport-recipes": (o) => `${o.dry_run !== false ? "Preview" : "Re-scrape"} recipes from their original URLs`,
  "tag-categorize": (o) => `Auto-categorize recipes using ${o.method === "rules" ? "rules only" : o.method === "ai" ? "AI only" : "rules + AI"}`,
  "taxonomy-refresh": (o) => `Sync taxonomy from config files ${o.dry_run !== false ? "(preview)" : "(live)"}`,
  "cookbook-sync": (o) => `${o.dry_run !== false ? "Preview" : "Sync"} cookbooks to match config`,
  "health-check": () => "Run diagnostic audits on your recipe library",
};

export default function TasksPage({
  tasks, runs, schedules, session, taskHandoff,
  onNotice, onError, refreshRuns, refreshSchedules, refreshTasks, clearTaskHandoff, navigateTo,
  sidebarCollapsed,
}) {
  // ─── State ──────────────────────────────────────────────────────────────────
  const [selectedTask, setSelectedTask] = useState("");
  const [taskValues, setTaskValues] = useState({});
  const [showAdvancedTaskOptions, setShowAdvancedTaskOptions] = useState(false);
  const [runSearch, setRunSearch] = useState("");
  const [runTypeFilter, setRunTypeFilter] = useState("all");
  const [logBuffer, setLogBuffer] = useState("");
  const [logMaximized, setLogMaximized] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState("");

  const [scheduleMode, setScheduleMode] = useState(false);
  const [scheduleForm, setScheduleForm] = useState({
    name: "",
    kind: "interval",
    intervalValue: 6,
    intervalUnit: "hours",
    start_at: "",
    end_at: "",
    run_at: "",
    enabled: true,
    run_if_missed: false,
  });
  const [editingScheduleId, setEditingScheduleId] = useState("");
  const [scheduleEditForm, setScheduleEditForm] = useState(null);
  const [showAdvancedScheduleOptions, setShowAdvancedScheduleOptions] = useState(false);

  // ─── Refs ───────────────────────────────────────────────────────────────────
  const logOffsetRef = useRef(0);
  const logPollRef = useRef(null);
  const openConfigRequestRef = useRef(0);
  const selectedRunStatusRef = useRef(null);

  // ─── Memos ──────────────────────────────────────────────────────────────────
  const selectedTaskDef = useMemo(
    () => tasks.find((item) => item.task_id === selectedTask) || null,
    [tasks, selectedTask]
  );

  const taskTitleById = useMemo(() => {
    const map = new Map();
    for (const task of tasks) {
      map.set(task.task_id, task.title || task.task_id);
    }
    return map;
  }, [tasks]);

  const taskGroups = useMemo(() => {
    const grouped = new Map();
    for (const task of tasks) {
      const g = task.group || "Other";
      if (!grouped.has(g)) grouped.set(g, []);
      grouped.get(g).push(task);
    }
    return [...grouped.entries()].sort(
      (a, b) => (TASK_GROUP_ORDER.indexOf(a[0]) + 1 || 99) - (TASK_GROUP_ORDER.indexOf(b[0]) + 1 || 99)
    );
  }, [tasks]);

  const flatTasks = useMemo(
    () => taskGroups.flatMap(([, groupTasks]) => groupTasks),
    [taskGroups]
  );

  const lastRunByTask = useMemo(() => {
    const map = new Map();
    for (const run of runs) {
      const ts = run.finished_at || run.started_at || run.created_at;
      const existing = map.get(run.task_id);
      if (!existing || (ts && ts > existing.ts)) {
        map.set(run.task_id, { status: run.status, ts });
      }
    }
    return map;
  }, [runs]);

  const last24hStats = useMemo(() => {
    const cutoff = Date.now() - 86400000;
    const stats = { total: 0, succeeded: 0, failed: 0, running: 0 };
    for (const run of runs) {
      const ts = new Date(run.created_at || 0).getTime();
      if (ts < cutoff) continue;
      stats.total++;
      if (run.status === "succeeded") stats.succeeded++;
      else if (run.status === "failed") stats.failed++;
      else if (run.status === "running") stats.running++;
    }
    return stats;
  }, [runs]);

  const scheduleRunStats = useMemo(() => {
    const map = new Map();
    for (const run of runs) {
      if (!run.schedule_id) continue;
      const sid = String(run.schedule_id);
      if (!map.has(sid)) map.set(sid, { total: 0, succeeded: 0 });
      const s = map.get(sid);
      s.total++;
      if (run.status === "succeeded") s.succeeded++;
    }
    return map;
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

  const selectedRunStatus = useMemo(() => {
    const run = runs.find(r => r.run_id === selectedRunId);
    return run ? run.status : null;
  }, [runs, selectedRunId]);

  // ─── Effects ────────────────────────────────────────────────────────────────

  // Consume taskHandoff
  useEffect(() => {
    if (!taskHandoff?.task_id) return;
    setSelectedTask(taskHandoff.task_id);
    clearTaskHandoff();
  }, [taskHandoff]);

  // Reset task option values when selected task changes
  useEffect(() => {
    setTaskValues(buildDefaultOptionValues(selectedTaskDef));
    setShowAdvancedTaskOptions(false);
  }, [selectedTaskDef]);

  // Sync schedule edit form with schedules list
  useEffect(() => {
    if (!editingScheduleId) return;
    const stillExists = schedules.some((item) => String(item.schedule_id) === String(editingScheduleId));
    if (!stillExists) {
      setEditingScheduleId("");
      setScheduleEditForm(null);
      setShowAdvancedScheduleOptions(false);
    }
  }, [editingScheduleId, schedules]);

  // Live runs polling
  const liveRunsTimer = React.useRef(null);

  useEffect(() => {
    if (!session) {
      clearInterval(liveRunsTimer.current);
      return;
    }
    // Fetch fresh task definitions (including dynamic options like provider choices)
    // every time the user opens the Tasks page, so cached data never goes stale.
    refreshTasks();
    // Poll at 5s when there are active/queued runs, 30s when all idle.
    function scheduleNext() {
      const hasActive = runs.some(r => r.status === "running" || r.status === "queued");
      const interval = hasActive ? 5000 : 30000;
      liveRunsTimer.current = setTimeout(async () => {
        await refreshRuns();
        if (session) scheduleNext();
      }, interval);
    }
    scheduleNext();
    return () => clearTimeout(liveRunsTimer.current);
  }, [session, runs.some(r => r.status === "running" || r.status === "queued")]);

  // Keep ref in sync for any remaining external readers.
  useEffect(() => { selectedRunStatusRef.current = selectedRunStatus; }, [selectedRunStatus]);

  // Log fetch + live tail polling.
  useEffect(() => {
    if (logPollRef.current) { clearInterval(logPollRef.current); logPollRef.current = null; }

    if (!selectedRunId) {
      setLogBuffer("");
      logOffsetRef.current = 0;
      return;
    }

    setLogBuffer("");
    logOffsetRef.current = 0;

    async function doTail(append) {
      try {
        const data = await api(`/runs/${selectedRunId}/log/tail?offset=${logOffsetRef.current}`);
        if (data.content) setLogBuffer(prev => append ? prev + data.content : data.content);
        logOffsetRef.current = data.size;
      } catch (e) {
        console.warn("API request failed:", e);
      }
    }

    doTail(false);

    const isLive = selectedRunStatus === "running" || selectedRunStatus === "queued";
    if (isLive) {
      logPollRef.current = setInterval(() => { doTail(true); }, 3000);
    }

    return () => { if (logPollRef.current) { clearInterval(logPollRef.current); logPollRef.current = null; } };
  }, [selectedRunId, selectedRunStatus]);

  // ─── Handlers ───────────────────────────────────────────────────────────────

  async function triggerRun() {
    if (!selectedTaskDef) return;
    try {
      const options = normalizeTaskOptions(selectedTaskDef, taskValues);
      const isDangerous = options.dry_run === false;
      if (isDangerous) {
        await togglePolicy(selectedTaskDef.task_id, true);
      }
      await api("/runs", {
        method: "POST",
        body: { task_id: selectedTaskDef.task_id, options },
      });
      await refreshRuns();
      onNotice("Run queued.");
    } catch (exc) {
      onError(exc);
    }
  }

  async function cancelRun(runId) {
    try {
      await api(`/runs/${runId}/cancel`, { method: "POST" });
      await refreshRuns();
      onNotice("Run canceled.");
    } catch (exc) {
      onError(exc);
    }
  }

  async function togglePolicy(taskId, value) {
    try {
      await api("/policies", {
        method: "PUT",
        body: { policies: { [taskId]: { allow_dangerous: value } } },
      });
      await refreshTasks();
      onNotice("Task policy updated.");
    } catch (exc) {
      onError(exc);
    }
  }

  async function createSchedule() {
    if (!selectedTaskDef) {
      onError({ message: "Select a task before saving a schedule." });
      return;
    }
    if (!scheduleForm.name.trim()) {
      onError({ message: "Please enter a name for this schedule." });
      return;
    }
    if (scheduleForm.kind === "once" && !scheduleForm.run_at) {
      onError({ message: "Please choose a date and time for this schedule." });
      return;
    }
    if (scheduleForm.kind === "interval" && !scheduleForm.start_at) {
      onError({ message: "Please choose a start date for this schedule." });
      return;
    }

    try {
      const options = normalizeTaskOptions(selectedTaskDef, taskValues);
      if (options.dry_run === false) {
        await togglePolicy(selectedTask, true);
      }
      const intervalSeconds = Number(scheduleForm.intervalValue) * (SCHEDULE_UNIT_SECONDS[scheduleForm.intervalUnit] || 1);
      await api("/schedules", {
        method: "POST",
        body: {
          name: scheduleForm.name,
          task_id: selectedTask,
          kind: scheduleForm.kind,
          seconds: scheduleForm.kind === "interval" ? intervalSeconds : undefined,
          start_at: scheduleForm.kind === "interval" ? localDatetimeToUTC(scheduleForm.start_at) : undefined,
          end_at: (scheduleForm.kind === "interval" && scheduleForm.end_at) ? localDatetimeToUTC(scheduleForm.end_at) : undefined,
          run_at: scheduleForm.kind === "once" ? localDatetimeToUTC(scheduleForm.run_at) : undefined,
          options,
          enabled: Boolean(scheduleForm.enabled),
          run_if_missed: Boolean(scheduleForm.run_if_missed),
        },
      });
      await refreshSchedules();
      setScheduleMode(false);
      onNotice("Schedule saved.");
    } catch (exc) {
      onError(exc);
    }
  }

  function startScheduleEdit(schedule) {
    const scheduleData = schedule.schedule_data || {};
    const scheduleKind = schedule.schedule_kind === "once" ? "once" : "interval";
    const interval = splitIntervalSeconds(scheduleData.seconds);
    const taskId = String(schedule.task_id || "");
    const taskDef = tasks.find((item) => item.task_id === taskId) || null;
    setEditingScheduleId(String(schedule.schedule_id || ""));
    setShowAdvancedScheduleOptions(false);
    setScheduleEditForm({
      name: String(schedule.name || ""),
      task_id: taskId,
      kind: scheduleKind,
      intervalValue: interval.intervalValue,
      intervalUnit: interval.intervalUnit,
      start_at: toDateTimeLocalValue(scheduleData.start_at),
      end_at: toDateTimeLocalValue(scheduleData.end_at),
      run_at: toDateTimeLocalValue(scheduleData.run_at),
      enabled: schedule.enabled !== false,
      run_if_missed: Boolean(scheduleData.run_if_missed),
      optionValues: buildTaskOptionSeed(taskDef, schedule.options || {}),
    });
  }

  function cancelScheduleEdit() {
    setEditingScheduleId("");
    setScheduleEditForm(null);
    setShowAdvancedScheduleOptions(false);
  }

  async function saveScheduleEdit(scheduleId) {
    if (!scheduleEditForm) return;
    const selectedEditTaskDef = tasks.find((item) => item.task_id === scheduleEditForm.task_id) || null;
    if (!selectedEditTaskDef) {
      onError({ message: "Select a valid task before saving this schedule." });
      return;
    }
    if (!scheduleEditForm.name.trim()) {
      onError({ message: "Please enter a name for this schedule." });
      return;
    }
    if (scheduleEditForm.kind === "once" && !scheduleEditForm.run_at) {
      onError({ message: "Please choose a date and time for this schedule." });
      return;
    }
    if (scheduleEditForm.kind === "interval" && !scheduleEditForm.start_at) {
      onError({ message: "Please choose a start date for this schedule." });
      return;
    }
    if (scheduleEditForm.kind === "interval" && Number(scheduleEditForm.intervalValue) <= 0) {
      onError({ message: "Interval schedules require a positive interval value." });
      return;
    }

    try {
      const options = normalizeTaskOptions(selectedEditTaskDef, scheduleEditForm.optionValues || {});
      if (options.dry_run === false) {
        await togglePolicy(selectedEditTaskDef.task_id, true);
      }
      const intervalSeconds =
        Number(scheduleEditForm.intervalValue) * (SCHEDULE_UNIT_SECONDS[scheduleEditForm.intervalUnit] || 1);
      await api(`/schedules/${scheduleId}`, {
        method: "PATCH",
        body: {
          name: scheduleEditForm.name,
          task_id: scheduleEditForm.task_id,
          kind: scheduleEditForm.kind,
          seconds: scheduleEditForm.kind === "interval" ? intervalSeconds : undefined,
          start_at: scheduleEditForm.kind === "interval" ? localDatetimeToUTC(scheduleEditForm.start_at) : undefined,
          end_at:
            scheduleEditForm.kind === "interval" && scheduleEditForm.end_at
              ? localDatetimeToUTC(scheduleEditForm.end_at)
              : undefined,
          run_at: scheduleEditForm.kind === "once" ? localDatetimeToUTC(scheduleEditForm.run_at) : undefined,
          options,
          enabled: Boolean(scheduleEditForm.enabled),
          run_if_missed: Boolean(scheduleEditForm.run_if_missed),
        },
      });
      await refreshSchedules();
      cancelScheduleEdit();
      onNotice("Schedule updated.");
    } catch (exc) {
      onError(exc);
    }
  }

  async function deleteSchedule(scheduleId) {
    try {
      await api(`/schedules/${scheduleId}`, { method: "DELETE" });
      await refreshSchedules();
      onNotice("Schedule removed.");
    } catch (exc) {
      onError(exc);
    }
  }

  async function toggleScheduleEnabled(schedule) {
    try {
      await api(`/schedules/${schedule.schedule_id}`, {
        method: "PATCH",
        body: { enabled: !schedule.enabled },
      });
      await refreshSchedules();
    } catch (exc) {
      onError(exc);
    }
  }

  // ─── Render ─────────────────────────────────────────────────────────────────

  const selectedRun = runs.find((item) => item.run_id === selectedRunId) || null;
  const visibleTaskGroups = taskGroups;
  const selectedTaskGroup = selectedTaskDef
    ? taskGroups.find(([, groupTasks]) => groupTasks.some((task) => task.task_id === selectedTaskDef.task_id))?.[0] || ""
    : "";
  const selectedTaskOptionCount = Array.isArray(selectedTaskDef?.options) ? selectedTaskDef.options.length : 0;
  const selectedTaskAdvancedCount = Array.isArray(selectedTaskDef?.options)
    ? selectedTaskDef.options.filter((option) => option.advanced).length
    : 0;

  function formatScheduleTiming(schedule) {
    const kind = schedule.schedule_kind;
    const data = schedule.schedule_data || {};
    if (kind === "once") {
      if (!data.run_at) return "Once";
      return `Once \u00b7 ${new Date(data.run_at).toLocaleString()}`;
    }
    const secs = Number(data.seconds || 0);
    if (secs >= 86400) return `Every ${Math.round(secs / 86400)}d`;
    if (secs >= 3600) return `Every ${Math.round(secs / 3600)}h`;
    if (secs >= 60) return `Every ${Math.round(secs / 60)}m`;
    return `Every ${secs}s`;
  }

  return (
    <section className="page-grid tasks-grid">
      <div className="stacked-cards tasks-start-column">
        <article className="card">
          <h3>Start a Run</h3>
          <p className="muted">Pick a task, adjust options, then run.</p>

          <div className="run-form">
            <div className="start-run-layout">
              <div className="task-pill-picker">
                  <div className="task-pill-groups">
                    {visibleTaskGroups.map(([groupName, groupTasks]) => (
                      <section key={groupName} className="task-pill-group" data-group={TASK_GROUP_COLORS[groupName] || "default"}>
                        <div className="task-pill-group-head">
                          <h4>{groupName}</h4>
                          <span className="status-pill neutral tiny-pill">{groupTasks.length}</span>
                        </div>
                        <div className="task-pill-grid">
                          {groupTasks.map((task) => {
                            const lastRun = lastRunByTask.get(task.task_id);
                            const dotClass = lastRun
                              ? lastRun.status === "succeeded" ? "dot-success"
                                : lastRun.status === "failed" ? "dot-danger"
                                : lastRun.status === "running" ? "dot-running"
                                : "dot-neutral"
                              : null;
                            return (
                              <button
                                key={task.task_id}
                                type="button"
                                className={`task-pill${selectedTask === task.task_id ? " active" : ""}`}
                                onClick={() => setSelectedTask(task.task_id)}
                              >
                                <span className="task-pill-icon-wrap">
                                  <Icon name={TASK_ICONS[task.task_id] || "zap"} className="task-pill-icon" />
                                </span>
                                <span className="task-pill-text">
                                  <span className="task-pill-title">
                                    {task.title}
                                    {task.badges?.length > 0 && (
                                      <span className="task-badges">
                                        {task.badges.includes("ai") && <span className="task-badge badge-ai" role="img" aria-label="Uses AI"><Icon name="wand" /></span>}
                                        {task.badges.includes("db") && <span className="task-badge badge-db" role="img" aria-label="Requires DB access"><Icon name="database" /></span>}
                                      </span>
                                    )}
                                  </span>
                                  {task.description ? <span className="task-pill-desc">{task.description}</span> : null}
                                </span>
                                {lastRun ? (
                                  <span className={`task-pill-last-run ${dotClass}`} title={`Last: ${lastRun.status}`}>
                                    <span className="task-pill-last-dot" />
                                    <span>{formatRelativeTime(lastRun.ts)}</span>
                                  </span>
                                ) : null}
                              </button>
                            );
                          })}
                        </div>
                      </section>
                    ))}
                  </div>
              </div>

              <div className="start-run-main">
                {!selectedTaskDef ? (
                  <p className="muted tiny">Select a task to configure and run it.</p>
                ) : (
                  <>
                    <div className="start-run-task-hero">
                      <span className="task-hero-icon">
                        <Icon name={TASK_ICONS[selectedTaskDef.task_id] || "zap"} />
                      </span>
                      <div className="start-run-task-head">
                        <h4>{selectedTaskDef.title}</h4>
                        <p className="muted tiny">{selectedTaskDef.description}</p>
                      </div>
                      <div className="start-run-task-badges">
                        {selectedTaskGroup ? <span className="status-pill neutral">{selectedTaskGroup}</span> : null}
                        <span className="status-pill neutral">{selectedTaskOptionCount} option{selectedTaskOptionCount === 1 ? "" : "s"}</span>
                        {selectedTaskAdvancedCount > 0 ? (
                          <span className="status-pill warning">{selectedTaskAdvancedCount} advanced</span>
                        ) : null}
                        {selectedTaskDef.badges?.includes("ai") && <span className="status-pill badge-ai-pill"><Icon name="wand" /> AI</span>}
                        {selectedTaskDef.badges?.includes("db") && <span className="status-pill badge-db-pill"><Icon name="database" /> DB</span>}
                      </div>
                    </div>

                    {(() => {
                      const visibleOptions = (selectedTaskDef.options || []).filter((option) =>
                        isTaskOptionVisible(option, taskValues, true)
                      );
                      const hasDryRun = visibleOptions.some((o) => o.key === "dry_run");
                      const filteredBasic = visibleOptions.filter((o) => !o.advanced && o.key !== "dry_run");
                      const advancedOptions = visibleOptions.filter((option) => option.advanced);
                      const renderOptionFields = (options) =>
                        options.map((option) =>
                          fieldFromOption(option, taskValues[option.key], (key, optionValue) =>
                            setTaskValues((prev) => ({ ...prev, [key]: optionValue })),
                            taskValues
                          )
                        );

                      return (
                        <>
                          {hasDryRun && (
                            <div className="mode-toggle-bar">
                              <button
                                type="button"
                                className={`mode-toggle-btn safe-mode${taskValues.dry_run !== false ? " active" : ""}`}
                                onClick={() => setTaskValues((prev) => ({ ...prev, dry_run: true }))}
                              >
                                <Icon name="shield" />
                                <span className="mode-toggle-label">Safe Mode</span>
                                <span className="mode-toggle-hint">Preview only, no changes</span>
                              </button>
                              <button
                                type="button"
                                className={`mode-toggle-btn live-mode${taskValues.dry_run === false ? " active" : ""}`}
                                onClick={() => setTaskValues((prev) => ({ ...prev, dry_run: false }))}
                              >
                                <Icon name="zap" />
                                <span className="mode-toggle-label">Live</span>
                                <span className="mode-toggle-hint">Apply real changes</span>
                              </button>
                            </div>
                          )}

                          {selectedTaskDef.task_id === "reimport-recipes" && (
                            <div className="task-warning-banner">
                              <Icon name="alertTriangle" />
                              <div>
                                <strong>Overwrites recipe content</strong>
                                <p>Name, ingredients, instructions, nutrition, and times will be replaced with freshly scraped data. User edits will be lost. Parsed ingredient links are stripped for re-parsing. Tags, categories, and favorites are preserved.</p>
                              </div>
                            </div>
                          )}

                          {filteredBasic.length > 0 ? (
                            <div className="option-grid">{renderOptionFields(filteredBasic)}</div>
                          ) : !hasDryRun && visibleOptions.length === 0 ? (
                            <p className="muted tiny">This task has no additional options.</p>
                          ) : null}

                          {advancedOptions.length > 0 ? (
                            <div className={`advanced-options-panel${showAdvancedTaskOptions ? " open" : ""}`}>
                              <div className="advanced-options-head">
                                <button
                                  type="button"
                                  className={`chip-btn advanced-toggle-btn ${showAdvancedTaskOptions ? "active" : ""}`}
                                  onClick={() => setShowAdvancedTaskOptions((prev) => !prev)}
                                >
                                  <Icon name="wand" />
                                  {showAdvancedTaskOptions ? "Hide Advanced" : "Show Advanced"}
                                </button>
                                <span className="muted tiny">{advancedOptions.length} advanced option(s)</span>
                              </div>
                              {showAdvancedTaskOptions ? (() => {
                                const groups = [];
                                const ungrouped = [];
                                const seen = new Set();
                                for (const opt of advancedOptions) {
                                  const g = opt.option_group || "";
                                  if (!g) { ungrouped.push(opt); continue; }
                                  if (!seen.has(g)) { seen.add(g); groups.push([g, []]); }
                                  groups.find(([name]) => name === g)[1].push(opt);
                                }
                                if (groups.length === 0) {
                                  return <div className="option-grid option-grid-advanced">{renderOptionFields(ungrouped)}</div>;
                                }
                                return (
                                  <div className="advanced-groups">
                                    {groups.map(([groupName, groupOpts]) => (
                                      <div key={groupName} className="advanced-group">
                                        <span className="advanced-group-label">{groupName}</span>
                                        <div className="option-grid option-grid-advanced">{renderOptionFields(groupOpts)}</div>
                                      </div>
                                    ))}
                                    {ungrouped.length > 0 && (
                                      <div className="advanced-group">
                                        <span className="advanced-group-label">Other</span>
                                        <div className="option-grid option-grid-advanced">{renderOptionFields(ungrouped)}</div>
                                      </div>
                                    )}
                                  </div>
                                );
                              })() : (
                                <p className="muted tiny">Advanced options are hidden.</p>
                              )}
                            </div>
                          ) : null}
                        </>
                      );
                    })()}

                    <div className="schedule-mode-switch" role="tablist" aria-label="Run mode">
                      <button
                        type="button"
                        className={`ghost small ${!scheduleMode ? "active" : ""}`}
                        onClick={() => setScheduleMode(false)}
                        aria-pressed={!scheduleMode}
                      >
                        <Icon name="play" />
                        Run Now
                      </button>
                      <button
                        type="button"
                        className={`ghost small ${scheduleMode ? "active" : ""}`}
                        onClick={() => setScheduleMode(true)}
                        aria-pressed={scheduleMode}
                      >
                        <Icon name="calendar" />
                        Schedule
                      </button>
                    </div>

                    {scheduleMode && (
                      <div className="schedule-inline">
                        <label className="field">
                          <span>Schedule Name</span>
                          <input
                            value={scheduleForm.name}
                            onChange={(event) => setScheduleForm((prev) => ({ ...prev, name: event.target.value }))}
                            placeholder="e.g. Morning cleanup"
                          />
                        </label>

                        <label className="field">
                          <span>Type</span>
                          <select
                            value={scheduleForm.kind}
                            onChange={(event) => setScheduleForm((prev) => ({ ...prev, kind: event.target.value }))}
                          >
                            <option value="interval">Interval</option>
                            <option value="once">Once</option>
                          </select>
                        </label>

                        {scheduleForm.kind === "interval" ? (
                          <>
                            <div className="interval-row">
                              <label className="field">
                                <span>Every</span>
                                <input
                                  type="number"
                                  min="1"
                                  value={scheduleForm.intervalValue}
                                  onChange={(event) => setScheduleForm((prev) => ({ ...prev, intervalValue: event.target.value }))}
                                />
                              </label>
                              <label className="field">
                                <span>&nbsp;</span>
                                <select
                                  value={scheduleForm.intervalUnit}
                                  onChange={(event) => setScheduleForm((prev) => ({ ...prev, intervalUnit: event.target.value }))}
                                >
                                  <option value="seconds">Seconds</option>
                                  <option value="minutes">Minutes</option>
                                  <option value="hours">Hours</option>
                                  <option value="days">Days</option>
                                </select>
                              </label>
                            </div>
                            <label className="field">
                              <span>Start date</span>
                              <input
                                type="datetime-local"
                                value={scheduleForm.start_at}
                                min={new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)}
                                onChange={(event) => setScheduleForm((prev) => ({ ...prev, start_at: event.target.value }))}
                              />
                            </label>
                            <label className="field">
                              <span>End date <span className="muted">(optional)</span></span>
                              <input
                                type="datetime-local"
                                value={scheduleForm.end_at}
                                min={scheduleForm.start_at || new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)}
                                onChange={(event) => setScheduleForm((prev) => ({ ...prev, end_at: event.target.value }))}
                              />
                            </label>
                          </>
                        ) : (
                          <label className="field">
                            <span>Run at</span>
                            <input
                              type="datetime-local"
                              value={scheduleForm.run_at}
                              min={new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)}
                              onChange={(event) => setScheduleForm((prev) => ({ ...prev, run_at: event.target.value }))}
                            />
                          </label>
                        )}

                        <label className="field field-inline">
                          <span>Enabled</span>
                          <input
                            type="checkbox"
                            checked={Boolean(scheduleForm.enabled)}
                            onChange={(event) => setScheduleForm((prev) => ({ ...prev, enabled: event.target.checked }))}
                          />
                        </label>

                        <label className="field field-inline">
                          <span>Run if schedule is missed</span>
                          <input
                            type="checkbox"
                            checked={Boolean(scheduleForm.run_if_missed)}
                            onChange={(event) =>
                              setScheduleForm((prev) => ({ ...prev, run_if_missed: event.target.checked }))
                            }
                          />
                        </label>
                      </div>
                    )}

                    {TASK_SUMMARIES[selectedTaskDef.task_id] && (
                      <p className="task-action-summary muted tiny">
                        <Icon name="info" />
                        {TASK_SUMMARIES[selectedTaskDef.task_id](taskValues)}
                      </p>
                    )}

                    {scheduleMode ? (
                      <button type="button" className="primary action-hero-btn" onClick={createSchedule}>
                        <Icon name="save" />
                        Save Schedule
                      </button>
                    ) : (
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <button
                          type="button"
                          className={`primary action-hero-btn ${taskValues.dry_run === false ? "live-action" : "safe-action"}`}
                          onClick={triggerRun}
                        >
                          <Icon name={taskValues.dry_run === false ? "zap" : "play"} />
                          {taskValues.dry_run === false ? "Run Live" : "Preview Run"}
                        </button>
                        {(() => {
                          const required = (selectedTaskDef.options || []).filter(
                            (o) => o.required && !o.hidden
                          );
                          if (required.length === 0) return null;
                          const filled = required.filter((o) => {
                            const v = taskValues[o.key];
                            return v !== undefined && v !== "" && v !== null;
                          });
                          const pct = Math.round((filled.length / required.length) * 100);
                          if (pct >= 100) return null;
                          const dashLen = pct * 0.628;
                          return (
                            <span
                              className="readiness-ring"
                              title={`${filled.length}/${required.length} required options set`}
                            >
                              <svg viewBox="0 0 24 24" className="readiness-svg">
                                <circle
                                  cx="12" cy="12" r="10" fill="none"
                                  stroke="var(--line)" strokeWidth="2.5"
                                />
                                <circle
                                  cx="12" cy="12" r="10" fill="none"
                                  stroke="var(--accent)" strokeWidth="2.5"
                                  strokeDasharray={`${dashLen} 62.8`}
                                  strokeLinecap="round"
                                  transform="rotate(-90 12 12)"
                                />
                              </svg>
                            </span>
                          );
                        })()}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        </article>
      </div>

      <div className="stacked-cards tasks-schedule-column">
        {schedules.length === 0 ? (
          <article className="card schedule-empty-state">
            <div className="schedule-empty-icon">
              <Icon name="calendar" />
            </div>
            <h4>No Schedules Yet</h4>
            <p className="muted tiny">Automate your workflows by scheduling tasks to run on a timer.</p>
            <p className="muted tiny">Select a task, switch to <strong>Schedule</strong> mode, and save.</p>
          </article>
        ) : (
          <article className="card">
            <h3>Saved Schedules</h3>
            <p className="muted">{schedules.length} schedule{schedules.length !== 1 ? "s" : ""} configured.</p>
            <ul className="schedule-list">
              {schedules.map((schedule) => {
                const scheduleId = String(schedule.schedule_id || "");
                const isEditing = scheduleId === String(editingScheduleId || "");
                const editor = isEditing ? scheduleEditForm : null;
                const editTaskDef = editor ? tasks.find((item) => item.task_id === editor.task_id) || null : null;
                const visibleEditOptions = (editTaskDef?.options || []).filter((option) =>
                  isTaskOptionVisible(option, editor?.optionValues || {}, true)
                );
                const basicEditOptions = visibleEditOptions.filter((option) => !option.advanced);
                const advancedEditOptions = visibleEditOptions.filter((option) => option.advanced);
                const shownEditOptions = showAdvancedScheduleOptions ? visibleEditOptions : basicEditOptions;
                return (
                  <li key={scheduleId} className={`schedule-item${isEditing ? " is-editing" : ""}`}>
                    <div className="schedule-item-main">
                      <div>
                        <div className="schedule-name-row">
                          <span className={`schedule-status-dot ${schedule.enabled !== false ? "dot-active" : "dot-inactive"}`} />
                          <strong>{schedule.name || schedule.schedule_id}</strong>
                        </div>
                        <p className="tiny muted">
                          {taskTitleById.get(schedule.task_id) || schedule.task_id}
                          {" \u00b7 "}
                          {formatScheduleTiming(schedule)}
                          {" \u00b7 "}
                          {schedule.schedule_data?.run_if_missed ? "Run if missed" : "Skip if missed"}
                          {schedule.enabled !== false && schedule.next_run_at ? (
                            <>
                              {" "}
                              <span className="schedule-countdown">
                                <Icon name="play" />
                                {formatCountdown(schedule.next_run_at)}
                              </span>
                            </>
                          ) : null}
                        </p>
                        {(() => {
                          const stats = scheduleRunStats.get(scheduleId);
                          if (!stats || stats.total === 0) return null;
                          const pct = Math.round((stats.succeeded / stats.total) * 100);
                          return (
                            <span className="schedule-streak">
                              {stats.total} run{stats.total !== 1 ? "s" : ""} \u00b7 {pct}% success
                            </span>
                          );
                        })()}
                      </div>
                      <div className="schedule-item-actions">
                        <button
                          className={`ghost small${isEditing ? " active-edit" : ""}`}
                          aria-label={isEditing ? "Close editor" : "Edit schedule"}
                          onClick={() => (isEditing ? cancelScheduleEdit() : startScheduleEdit(schedule))}
                        >
                          <Icon name="pencil" />
                        </button>
                        <button
                          className={`ghost small ${schedule.enabled !== false ? "enabled-toggle" : "disabled-toggle"}`}
                          aria-label={schedule.enabled !== false ? "Disable schedule" : "Enable schedule"}
                          onClick={() => toggleScheduleEnabled(schedule)}
                        >
                          <Icon name={schedule.enabled !== false ? "check-circle" : "x-circle"} />
                        </button>
                        <button className="ghost small danger" aria-label="Delete schedule" onClick={() => deleteSchedule(scheduleId)}>
                          <Icon name="trash" />
                        </button>
                      </div>
                    </div>

                    {isEditing && editor ? (
                      <div className="schedule-edit-panel">
                        <div className="schedule-edit-grid">
                          <label className="field">
                            <span>Schedule Name</span>
                            <input
                              value={editor.name}
                              onChange={(event) =>
                                setScheduleEditForm((prev) => (prev ? { ...prev, name: event.target.value } : prev))
                              }
                            />
                          </label>

                          <label className="field">
                            <span>Task</span>
                            <select
                              value={editor.task_id}
                              onChange={(event) => {
                                const nextTaskId = event.target.value;
                                const nextTaskDef = tasks.find((item) => item.task_id === nextTaskId) || null;
                                setShowAdvancedScheduleOptions(false);
                                setScheduleEditForm((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        task_id: nextTaskId,
                                        optionValues: buildTaskOptionSeed(nextTaskDef, {}),
                                      }
                                    : prev
                                );
                              }}
                            >
                              {tasks.map((task) => (
                                <option key={task.task_id} value={task.task_id}>
                                  {task.title || task.task_id}
                                </option>
                              ))}
                            </select>
                          </label>

                          <label className="field">
                            <span>Type</span>
                            <select
                              value={editor.kind}
                              onChange={(event) =>
                                setScheduleEditForm((prev) => (prev ? { ...prev, kind: event.target.value } : prev))
                              }
                            >
                              <option value="interval">Interval</option>
                              <option value="once">Once</option>
                            </select>
                          </label>

                          {editor.kind === "interval" ? (
                            <>
                              <div className="interval-row">
                                <label className="field">
                                  <span>Every</span>
                                  <input
                                    type="number"
                                    min="1"
                                    value={editor.intervalValue}
                                    onChange={(event) =>
                                      setScheduleEditForm((prev) =>
                                        prev ? { ...prev, intervalValue: event.target.value } : prev
                                      )
                                    }
                                  />
                                </label>
                                <label className="field">
                                  <span>&nbsp;</span>
                                  <select
                                    value={editor.intervalUnit}
                                    onChange={(event) =>
                                      setScheduleEditForm((prev) =>
                                        prev ? { ...prev, intervalUnit: event.target.value } : prev
                                      )
                                    }
                                  >
                                    <option value="seconds">Seconds</option>
                                    <option value="minutes">Minutes</option>
                                    <option value="hours">Hours</option>
                                    <option value="days">Days</option>
                                  </select>
                                </label>
                              </div>
                              <label className="field">
                                <span>Start date</span>
                                <input
                                  type="datetime-local"
                                  value={editor.start_at}
                                  onChange={(event) =>
                                    setScheduleEditForm((prev) => (prev ? { ...prev, start_at: event.target.value } : prev))
                                  }
                                />
                              </label>
                              <label className="field">
                                <span>End date <span className="muted">(optional)</span></span>
                                <input
                                  type="datetime-local"
                                  value={editor.end_at}
                                  onChange={(event) =>
                                    setScheduleEditForm((prev) => (prev ? { ...prev, end_at: event.target.value } : prev))
                                  }
                                />
                              </label>
                            </>
                          ) : (
                            <label className="field">
                              <span>Run at</span>
                              <input
                                type="datetime-local"
                                value={editor.run_at}
                                onChange={(event) =>
                                  setScheduleEditForm((prev) => (prev ? { ...prev, run_at: event.target.value } : prev))
                                }
                              />
                            </label>
                          )}

                          <label className="field field-inline">
                            <span>Enabled</span>
                            <input
                              type="checkbox"
                              checked={Boolean(editor.enabled)}
                              onChange={(event) =>
                                setScheduleEditForm((prev) => (prev ? { ...prev, enabled: event.target.checked } : prev))
                              }
                            />
                          </label>

                          <label className="field field-inline">
                            <span>Run if schedule is missed</span>
                            <input
                              type="checkbox"
                              checked={Boolean(editor.run_if_missed)}
                              onChange={(event) =>
                                setScheduleEditForm((prev) =>
                                  prev ? { ...prev, run_if_missed: event.target.checked } : prev
                                )
                              }
                            />
                          </label>
                        </div>

                        {visibleEditOptions.length > 0 ? (
                          <>
                            {advancedEditOptions.length > 0 && (
                              <>
                                <label className="field field-inline">
                                  <span>Show advanced options</span>
                                  <input
                                    type="checkbox"
                                    checked={showAdvancedScheduleOptions}
                                    onChange={(event) => setShowAdvancedScheduleOptions(event.target.checked)}
                                  />
                                </label>
                                {!showAdvancedScheduleOptions && (
                                  <p className="muted tiny">{advancedEditOptions.length} advanced option(s) hidden.</p>
                                )}
                              </>
                            )}
                            {shownEditOptions.length > 0 ? (
                              <div className="option-grid schedule-edit-options">
                                {shownEditOptions.map((option) =>
                                  fieldFromOption(
                                    option,
                                    (editor.optionValues || {})[option.key],
                                    (key, value) =>
                                      setScheduleEditForm((prev) =>
                                        prev
                                          ? {
                                              ...prev,
                                              optionValues: { ...(prev.optionValues || {}), [key]: value },
                                            }
                                          : prev
                                      ),
                                    editor.optionValues || {}
                                  )
                                )}
                              </div>
                            ) : (
                              <p className="muted tiny">No basic options for this task. Enable advanced options to customize it.</p>
                            )}
                          </>
                        ) : (
                          <p className="muted tiny">This task has no additional options.</p>
                        )}

                        <div className="schedule-edit-actions">
                          <button type="button" className="primary small" onClick={() => saveScheduleEdit(scheduleId)}>
                            <Icon name="save" />
                            Save Changes
                          </button>
                          <button type="button" className="ghost small" onClick={cancelScheduleEdit}>
                            <Icon name="x" />
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </article>
        )}

        {runs.some((r) => r.status === "running") && (
          <div className="running-banner">
            <span className="running-banner-dot" />
            <Icon name="loader" className="spin" />
            <span>
              {(() => {
                const active = runs.filter((r) => r.status === "running");
                return `${active.length} task${active.length !== 1 ? "s" : ""} running`;
              })()}
            </span>
            <button
              type="button"
              className="ghost small"
              onClick={() => {
                const r = runs.find((r) => r.status === "running");
                if (r) setSelectedRunId(r.run_id);
              }}
            >
              View Log
            </button>
          </div>
        )}
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
              aria-label="Search runs"
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

        {last24hStats.total > 0 && (
          <div className="activity-stats-bar">
            <span className="activity-stat">
              <Icon name="check-circle" />
              <strong>{last24hStats.succeeded}</strong> passed
            </span>
            <span className="activity-stat stat-danger">
              <Icon name="x-circle" />
              <strong>{last24hStats.failed}</strong> failed
            </span>
            {last24hStats.running > 0 && (
              <span className="activity-stat stat-running">
                <Icon name="loader" />
                <strong>{last24hStats.running}</strong> active
              </span>
            )}
            <span className="activity-stat stat-total">
              {last24hStats.total} total in 24h
            </span>
          </div>
        )}

        <div className="table-wrap">
          <table className="runs-table">
            <thead>
              <tr>
                <th scope="col">Task</th>
                <th scope="col">Status</th>
                <th scope="col" className="hide-mobile">Run Time</th>
                <th scope="col" className="hide-mobile">Started</th>
                <th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {filteredRuns.length === 0 ? (
                <tr>
                  <td colSpan={5} className="activity-empty">
                    <div className="activity-empty-content">
                      <Icon name="play" />
                      <span>No activity yet. Queue a task to see results here.</span>
                    </div>
                  </td>
                </tr>
              ) : (
                filteredRuns.map((run) => {
                  const cancelable = run.status === "queued" || run.status === "running";
                  const isDryRun = run.options?.dry_run !== false;
                  return (
                    <tr
                      key={run.run_id}
                      className={selectedRunId === run.run_id ? "selected-row" : ""}
                      onClick={() => { if (selectedRunId !== run.run_id) setSelectedRunId(run.run_id); }}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (selectedRunId !== run.run_id) setSelectedRunId(run.run_id); } }}
                      tabIndex={0}
                      role="button"
                      aria-selected={selectedRunId === run.run_id}
                    >
                      <td>{taskTitleById.get(run.task_id) || run.task_id}</td>
                      <td className="run-status-cell">
                        <span className={`status-indicator ${statusClass(run.status)}`}>
                          <Icon name={STATUS_ICONS[run.status]?.icon || "info"} />
                          {STATUS_ICONS[run.status]?.label || run.status}
                        </span>
                        <span className={`run-mode-label ${isDryRun ? "mode-safe" : "mode-live"}`}>
                          {isDryRun ? "Safe mode" : "Live"}
                        </span>
                        {run.status === "running" && (
                          <div className="run-progress-bar">
                            <div className="run-progress-fill" />
                          </div>
                        )}
                      </td>
                      <td className="muted hide-mobile">{formatRunTime(run)}</td>
                      <td className="muted hide-mobile">{formatDateTimeShort(run.started_at || run.created_at)}</td>
                      <td className="run-actions-cell">
                        {cancelable && (
                          <button
                            className="ghost small danger"
                            aria-label="Cancel run"
                            onClick={(event) => { event.stopPropagation(); cancelRun(run.run_id); }}
                          >
                            <Icon name="x" />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </article>

      <article
        className={`card log-output-card${logMaximized ? " log-card-maximized" : ""}`}
        style={logMaximized ? { "--sidebar-offset": sidebarCollapsed ? "72px" : "280px" } : undefined}
      >
        <div className="log-section">
          <div className="log-head">
            <div className="log-head-left">
              <h4>Run Output</h4>
              {selectedRun && (
                <span className="muted tiny">
                  {taskTitleById.get(selectedRun.task_id) || selectedRun.task_id} | {runTypeLabel(selectedRun)} | {formatRunTime(selectedRun)}
                </span>
              )}
            </div>
            <div className="log-head-actions">
              {selectedRun && logBuffer && (
                <>
                  <button
                    className="ghost small"
                    title="Copy log to clipboard"
                    onClick={() => {
                      navigator.clipboard.writeText(logBuffer).catch(() => {});
                      onNotice("Log copied to clipboard.");
                    }}
                  >
                    <Icon name="copy" />
                  </button>
                  <button
                    className="ghost small"
                    title="Download log file"
                    onClick={() => {
                      const name = (taskTitleById.get(selectedRun.task_id) || selectedRun.task_id)
                        .replace(/\s+/g, "-").toLowerCase();
                      const blob = new Blob([logBuffer], { type: "text/plain" });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement("a");
                      a.href = url;
                      a.download = `cookdex-run-${name}.log`;
                      a.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    <Icon name="download" />
                  </button>
                </>
              )}
              <button
                className="ghost small"
                aria-label={logMaximized ? "Restore" : "Maximize"}
                onClick={() => setLogMaximized(prev => !prev)}
              >
                <Icon name={logMaximized ? "minimize" : "maximize"} />
              </button>
            </div>
          </div>
          <div className="log-box" role="log" aria-live="polite">
            {!selectedRunId ? (
              <span className="log-empty">Select a run above to inspect its output.</span>
            ) : !logBuffer ? (
              <span className="log-empty">
                {selectedRun?.status === "queued" ? "Waiting to start\u2026" : "Loading\u2026"}
              </span>
            ) : (() => {
              const isLive = selectedRun && (selectedRun.status === "running" || selectedRun.status === "queued");
              const rawEvents = parseLogEvents(logBuffer);
              // Mark the last [start] as spinning if run is still active
              const events = isLive
                ? rawEvents.map((e, i) =>
                    e.type === "start" && rawEvents.slice(i + 1).every(x => x.type !== "start")
                      ? { ...e, type: "start-live" }
                      : e
                  )
                : rawEvents;
              const grouped = groupLogEvents(events);
              const dataMaintenanceView = buildDataMaintenanceView(events, Boolean(isLive));
              const stageStatusMeta = {
                succeeded: { label: "Completed", icon: "check-circle", cls: "log-stage-status-done" },
                failed: { label: "Failed", icon: "x-circle", cls: "log-stage-status-failed" },
                running: { label: "Running", icon: "loader", cls: "log-stage-status-running" },
                pending: { label: "Pending", icon: "info", cls: "log-stage-status-pending" },
                unknown: { label: "Unknown", icon: "alertTriangle", cls: "log-stage-status-unknown" },
              };
              return (
                <>
                  {dataMaintenanceView ? (
                    <>
                      {renderGroupedLogEvents(groupLogEvents(dataMaintenanceView.prelude), {
                        isLive: Boolean(isLive),
                        keyPrefix: "dm-prelude",
                      })}
                      <div className="log-stage-list">
                        {dataMaintenanceView.stages.map((stage, idx) => {
                          const meta = stageStatusMeta[stage.status] || stageStatusMeta.unknown;
                          const stageEvents = groupLogEvents(stage.events);
                          const stageKey = `dm-stage-${stage.stage}-${idx}`;
                          const stageIsLive = Boolean(isLive) && stage.status === "running";
                          const summaryTitle = `${stageDisplayName(stage.stage)} Summary`;
                          const stageResultSummary = buildStageResultSummary(stage, meta.label);
                          const showStageResults = stage.started || stage.events.length > 0 || Boolean(stage.summary);
                          return (
                            <details
                              key={stageKey}
                              className={`log-stage-card ${meta.cls}`}
                              defaultOpen={stage.started || stage.status === "running" || stage.status === "failed"}
                            >
                              <summary className="log-stage-summary">
                                <span className="log-stage-summary-left">
                                  <Icon name={meta.icon} />
                                  <span className="log-stage-name">{stageDisplayName(stage.stage)}</span>
                                  <span className="log-stage-id">{stage.stage}</span>
                                </span>
                                <span className="log-stage-summary-right">
                                  <span className="log-stage-state">{meta.label}</span>
                                  {stage.elapsed && <span className="log-stage-elapsed">{stage.elapsed}</span>}
                                  {stage.exitCode != null && <span className="log-stage-exit">exit {stage.exitCode}</span>}
                                  <span className="log-stage-chevron">&#x25b6;</span>
                                </span>
                              </summary>
                              <div className="log-stage-body">
                                {stage.events.length === 0 && !stage.summary ? (
                                  <div className="log-verbose">No stage output captured.</div>
                                ) : (
                                  <>
                                    {renderGroupedLogEvents(stageEvents, {
                                      isLive: stageIsLive,
                                      keyPrefix: `${stageKey}-events`,
                                      expandProgressDetails: true,
                                    })}
                                    {stage.summary && renderSummaryTable(stage.summary, {
                                      title: summaryTitle,
                                      iconName: stage.status === "failed" ? "alertTriangle" : "check-circle",
                                      keyPrefix: `${stageKey}-summary`,
                                    })}
                                  </>
                                )}
                                {showStageResults
                                  ? renderSummaryTable(stageResultSummary, {
                                      title: `${stageDisplayName(stage.stage)} Results`,
                                      iconName: stage.status === "failed" ? "alertTriangle" : "check-circle",
                                      keyPrefix: `${stageKey}-result`,
                                    })
                                  : null}
                              </div>
                            </details>
                          );
                        })}
                      </div>
                      {renderGroupedLogEvents(groupLogEvents(dataMaintenanceView.trailer), {
                        isLive: Boolean(isLive),
                        keyPrefix: "dm-trailer",
                      })}
                      {renderSummaryTable(buildPipelineExecutionSummary(dataMaintenanceView.stages), {
                        title: "Pipeline Results",
                        iconName: "check-circle",
                        keyPrefix: "dm-pipeline-summary",
                      })}
                    </>
                  ) : (
                    renderGroupedLogEvents(grouped, { isLive: Boolean(isLive), keyPrefix: "log" })
                  )}
                  {isLive && (
                    <div className="log-live-tail">
                      <span className="log-live-dot" /> live
                    </div>
                  )}
                </>
              );
            })()}
          </div>
        </div>
      </article>
      </div>
    </section>
  );
}
