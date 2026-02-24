import React, { useEffect, useMemo, useRef, useState } from "react";
import wordmark from "./assets/CookDex_wordmark.png";
import emblem from "./assets/CookDex_light.png";

import { NAV_ITEMS, PAGE_META, CONFIG_LABELS, TAXONOMY_FILE_NAMES, HELP_FAQ, HELP_TROUBLESHOOTING, HELP_TASK_GUIDES, HELP_SETUP_GUIDES } from "./constants";
import {
  api,
  buildDefaultOptionValues,
  fieldFromOption,
  formatDateTime,
  formatDateTimeShort,
  formatRunTime,
  moveArrayItem,
  normalizeCookbookEntries,
  normalizeErrorMessage,
  normalizeLabelEntries,
  normalizeTaskOptions,
  normalizeToolEntries,
  normalizeUnitEntries,
  parseAliasInput,
  parseQueryFilter,
  buildQueryFilter,
  FILTER_FIELDS,
  FILTER_OPERATORS,
  parseIso,
  parseLineEditorContent,
  renderMarkdownDocument,
  runTypeLabel,
  statusClass,
  userRoleLabel,
} from "./utils.jsx";
import Icon from "./components/Icon";
import CoverageRing from "./components/CoverageRing";

// ─── Structured log parser ────────────────────────────────────────────────────
const DATA_MAINTENANCE_STAGE_LABELS = {
  dedup: "Deduplicate Recipes",
  junk: "Filter Junk Recipes",
  names: "Normalize Recipe Names",
  parse: "Ingredient Parsing",
  foods: "Foods Cleanup",
  units: "Units Cleanup",
  labels: "Labels Sync",
  tools: "Tools Sync",
  taxonomy: "Taxonomy Refresh",
  categorize: "Recipe Categorization",
  cookbooks: "Cookbook Sync",
  yield: "Yield Normalization",
  quality: "Quality Audit",
  audit: "Taxonomy Audit",
};

const SUMMARY_PIPELINE_KEYS = new Set(["Stages Run", "Passed", "Failed", "All Stages"]);
const SCHEDULE_UNIT_SECONDS = { seconds: 1, minutes: 60, hours: 3600, days: 86400 };

function splitIntervalSeconds(rawSeconds) {
  const seconds = Number(rawSeconds || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return { intervalValue: 1, intervalUnit: "hours" };
  }
  if (seconds % 86400 === 0) {
    return { intervalValue: Math.max(1, Math.floor(seconds / 86400)), intervalUnit: "days" };
  }
  if (seconds % 3600 === 0) {
    return { intervalValue: Math.max(1, Math.floor(seconds / 3600)), intervalUnit: "hours" };
  }
  if (seconds % 60 === 0) {
    return { intervalValue: Math.max(1, Math.floor(seconds / 60)), intervalUnit: "minutes" };
  }
  return { intervalValue: Math.max(1, Math.floor(seconds)), intervalUnit: "seconds" };
}

function toDateTimeLocalValue(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(raw)) return raw;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw.slice(0, 16);
  const localValue = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return localValue.toISOString().slice(0, 16);
}

function buildTaskOptionSeed(taskDefinition, existingOptions = {}) {
  const seeded = { ...buildDefaultOptionValues(taskDefinition) };
  for (const option of taskDefinition?.options || []) {
    if (!Object.prototype.hasOwnProperty.call(existingOptions || {}, option.key)) {
      continue;
    }
    const value = existingOptions[option.key];
    if (option.multi) {
      seeded[option.key] = Array.isArray(value) ? value : value ? [value] : [];
      continue;
    }
    seeded[option.key] = value;
  }
  return seeded;
}

function isTaskOptionVisible(option, values = {}, includeAdvanced = true) {
  if (!option || option.hidden) return false;
  if (!includeAdvanced && option.advanced) return false;
  if (!option.hidden_when) return true;
  const conds = Array.isArray(option.hidden_when) ? option.hidden_when : [option.hidden_when];
  return !conds.some(({ key, value: trigger }) => values[key] === trigger);
}

function parseLogEvents(text) {
  const lines = text.split("\n");
  const events = [];
  let summaryBuf = null;
  let dataMaintenanceStageSet = new Set();
  for (const line of lines) {
    if (summaryBuf !== null) {
      summaryBuf += "\n" + line;
      try {
        const data = JSON.parse(summaryBuf.trim());
        events.push({ type: "summary", data, raw: "[summary] " + summaryBuf });
        summaryBuf = null;
      } catch {
        if (summaryBuf.split("\n").length > 50) {
          events.push({ type: "summary", data: null, raw: "[summary] " + summaryBuf });
          summaryBuf = null;
        }
      }
      continue;
    }
    if (line.startsWith("$ "))             events.push({ type: "command",  text: line.slice(2) });
    else if (line.startsWith("[start] ")) {
      const textLine = line.slice(8);
      const pipelineMatch = textLine.match(/^data-maintenance stages=([^ ]+)\s+/);
      if (pipelineMatch) {
        const stages = pipelineMatch[1]
          .split(",")
          .map((item) => item.trim().toLowerCase())
          .filter(Boolean);
        dataMaintenanceStageSet = new Set(stages);
        events.push({ type: "pipeline-start", pipeline: "data-maintenance", stages, text: textLine });
      } else {
        const stageName = textLine.trim().toLowerCase();
        if (dataMaintenanceStageSet.has(stageName) && !stageName.includes(" ")) {
          events.push({ type: "stage-start", stage: stageName, text: textLine });
        } else {
          events.push({ type: "start", text: textLine });
        }
      }
    } else if (line.startsWith("[done] ")) {
      const textLine = line.slice(7);
      const stageDoneMatch = textLine.match(/^([a-z0-9_-]+)\s+\(([^)]+)\)$/i);
      if (stageDoneMatch && dataMaintenanceStageSet.has(stageDoneMatch[1].toLowerCase())) {
        events.push({
          type: "stage-done",
          stage: stageDoneMatch[1].toLowerCase(),
          elapsed: stageDoneMatch[2],
          text: textLine,
        });
      } else if (/^\d+\s+stage\(s\)\s+run\b/i.test(textLine)) {
        events.push({ type: "pipeline-done", pipeline: "data-maintenance", text: textLine });
      } else {
        events.push({ type: "done", text: textLine });
      }
    } else if (line.startsWith("[error] ")) {
      const textLine = line.slice(8);
      const stageErrMatch = textLine.match(/^([a-z0-9_-]+): exit code (\d+)(?: \(([^)]+)\))?/i);
      if (stageErrMatch && dataMaintenanceStageSet.has(stageErrMatch[1].toLowerCase())) {
        events.push({
          type: "stage-error",
          stage: stageErrMatch[1].toLowerCase(),
          exitCode: Number(stageErrMatch[2]),
          elapsed: stageErrMatch[3] || null,
          text: textLine,
        });
      } else {
        events.push({ type: "error", text: textLine });
      }
    }
    else if (line.startsWith("[warning] "))events.push({ type: "warning",  text: line.slice(10) });
    else if (line.startsWith("[warn] "))   events.push({ type: "warning",  text: line.slice(7) });
    else if (line.startsWith("[db] "))     events.push({ type: "db",       text: line.slice(5) });
    else if (line.startsWith("[skip] "))   events.push({ type: "skip",     text: line.slice(7) });
    else if (line.startsWith("[info] "))   events.push({ type: "info",     text: line.slice(7) });
    else if (line.startsWith("[dry-run] "))events.push({ type: "dryrun",   text: line.slice(10) });
    else if (line.startsWith("[plan] ")) {
      const rest = line.slice(7);
      const colonIdx = rest.indexOf(":");
      const slug = colonIdx >= 0 ? rest.slice(0, colonIdx).trim() : rest.trim();
      const attrs = colonIdx >= 0 ? rest.slice(colonIdx + 1).trim() : "";
      events.push({ type: "plan", slug, attrs });
    } else if (line.startsWith("[ok] ")) {
      const rest = line.slice(5).trim();
      const m = rest.match(/^(\d+)\/(\d+)\s+/);
      if (m) {
        const current = parseInt(m[1], 10);
        const total = parseInt(m[2], 10);
        const after = rest.slice(m[0].length);
        const sp = after.indexOf(" ");
        const slug = sp >= 0 ? after.slice(0, sp) : after;
        const attrs = sp >= 0 ? after.slice(sp + 1) : "";
        const dm = attrs.match(/duration=([\d.]+)s/);
        const duration = dm ? parseFloat(dm[1]) : null;
        events.push({ type: "ok", current, total, slug, attrs, duration });
      } else {
        events.push({ type: "verbose", text: line });
      }
    } else if (line.startsWith("[summary] ")) {
      const rest = line.slice(10).trim();
      try { events.push({ type: "summary", data: JSON.parse(rest), raw: line }); }
      catch { summaryBuf = rest; }
    } else if (line.trim() && !/^[-=]{20,}$/.test(line.trim())) {
      events.push({ type: "verbose", text: line });
    }
  }
  if (summaryBuf !== null) events.push({ type: "summary", data: null, raw: "[summary] " + summaryBuf });
  return events;
}

function groupLogEvents(events) {
  const out = [];
  let i = 0;
  while (i < events.length) {
    if (events[i].type === "plan" || events[i].type === "ok") {
      // Collect plan/ok events into one batch, absorbing interleaved non-progress
      // events (e.g. warnings) as long as more plan/ok lines follow.
      const items = [];
      while (i < events.length) {
        if (events[i].type === "plan" || events[i].type === "ok") {
          items.push(events[i++]);
        } else {
          const hasMore = events.slice(i + 1).some(e => e.type === "plan" || e.type === "ok");
          if (hasMore) { items.push(events[i++]); } else { break; }
        }
      }
      out.push({ type: "progress-batch", items });
    } else if (events[i].type === "verbose") {
      const lines = [];
      while (i < events.length && events[i].type === "verbose") lines.push(events[i++].text);
      out.push({ type: "verbose-group", lines });
    } else {
      out.push(events[i++]);
    }
  }
  return out;
}

function getSummaryEntries(data) {
  if (!data || typeof data !== "object") return [];
  return Object.entries(data).filter(([, value]) => (
    value !== null
    && value !== undefined
    && typeof value !== "object"
  ));
}

function formatSummaryValue(value) {
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function isDataMaintenancePipelineSummary(data) {
  if (!data || typeof data !== "object") return false;
  const keys = Object.keys(data);
  return keys.some((key) => SUMMARY_PIPELINE_KEYS.has(key));
}

function summarizeExecutionEvents(events) {
  const stats = {
    planned: 0,
    completed: 0,
    warnings: 0,
    errors: 0,
    skipped: 0,
    info: 0,
    db: 0,
    verbose: 0,
    reportedTotal: null,
  };

  for (const evt of events || []) {
    if (!evt || typeof evt !== "object") continue;
    if (evt.type === "plan") {
      stats.planned += 1;
      continue;
    }
    if (evt.type === "ok") {
      stats.completed += 1;
      if (Number.isFinite(evt.total)) {
        stats.reportedTotal = Math.max(stats.reportedTotal || 0, Number(evt.total));
      }
      continue;
    }
    if (evt.type === "warning") {
      stats.warnings += 1;
      continue;
    }
    if (evt.type === "error" || evt.type === "stage-error") {
      stats.errors += 1;
      continue;
    }
    if (evt.type === "skip") {
      stats.skipped += 1;
      continue;
    }
    if (evt.type === "info") {
      stats.info += 1;
      continue;
    }
    if (evt.type === "db") {
      stats.db += 1;
      continue;
    }
    if (evt.type === "verbose") {
      stats.verbose += 1;
    }
  }
  return stats;
}

function buildStageResultSummary(stage, statusLabel) {
  const stats = summarizeExecutionEvents(stage?.events || []);
  const expected = stats.reportedTotal ?? Math.max(stats.planned, stats.completed);
  const completionText =
    expected > 0
      ? `${stats.completed.toLocaleString()} / ${expected.toLocaleString()} (${Math.round((stats.completed / expected) * 100)}%)`
      : stats.completed.toLocaleString();

  const summary = {
    status: statusLabel,
    duration: stage?.elapsed || "n/a",
    completion: completionText,
    warnings: stats.warnings,
    errors: stats.errors,
    skipped: stats.skipped,
  };

  if (stage?.exitCode != null) {
    summary.exit_code = stage.exitCode;
  }
  if (stats.info > 0) {
    summary.info_messages = stats.info;
  }
  if (stats.db > 0) {
    summary.db_messages = stats.db;
  }
  if (stats.verbose > 0) {
    summary.extra_output_lines = stats.verbose;
  }
  return summary;
}

function buildPipelineExecutionSummary(stages = []) {
  const summary = {
    stages_total: stages.length,
    stages_completed: stages.filter((item) => item.status === "succeeded").length,
    stages_failed: stages.filter((item) => item.status === "failed").length,
    stages_pending: stages.filter((item) => item.status === "pending").length,
    stages_running: stages.filter((item) => item.status === "running").length,
  };
  return summary;
}

function renderSummaryTable(data, { title = "Run Summary", iconName = "check-circle", keyPrefix = "summary" } = {}) {
  const entries = getSummaryEntries(data);
  if (entries.length === 0) return null;
  return (
    <div key={keyPrefix} className="log-summary-card">
      <div className="log-summary-head">
        <Icon name={iconName} /> {title}
      </div>
      <div className="log-summary-table-wrap">
        <table className="log-summary-table">
          <tbody>
            {entries.map(([k, v]) => (
              <tr key={`${keyPrefix}-${k}`} className="log-summary-table-row">
                <th className="log-summary-key">{k.replace(/_/g, " ")}</th>
                <td className="log-summary-val">{formatSummaryValue(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function renderGroupedLogEvents(grouped, { isLive = false, keyPrefix = "evt", expandProgressDetails = false } = {}) {
  const iconMap = {
    start: "info",
    "start-live": "loader",
    done: "check-circle",
    error: "x-circle",
    warning: "alertTriangle",
    db: "database",
    skip: "x",
    info: "info",
    dryrun: "eye",
    "pipeline-start": "settings",
    "pipeline-done": "check-circle",
  };
  const classMap = {
    start: "step-start",
    "start-live": "step-live",
    done: "step-done",
    error: "step-error",
    warning: "step-warning",
    db: "step-db",
    skip: "step-skip",
    info: "step-info",
    dryrun: "step-dryrun",
    "pipeline-start": "step-start",
    "pipeline-done": "step-done",
  };

  return grouped.map((evt, i) => {
    const eventKey = `${keyPrefix}-${i}`;
    if (evt.type === "command") {
      return <div key={eventKey} className="log-command">{evt.text}</div>;
    }
    if (evt.type === "summary") {
      if (!evt.data) return <pre key={eventKey} className="log-verbose">{evt.raw}</pre>;
      return renderSummaryTable(evt.data, { title: "Run Summary", iconName: "check-circle", keyPrefix: `${eventKey}-summary` });
    }
    if (evt.type === "progress-batch") {
      const okItems = evt.items.filter((e) => e.type === "ok");
      const lastOk = okItems[okItems.length - 1];
      const total = lastOk ? lastOk.total : 0;
      const current = lastOk ? lastOk.current : 0;
      const pct = total > 0 ? Math.round((current / total) * 100) : 0;
      // Keep the log responsive for very large batches while preserving recent details.
      const maxProgressItems = 25;
      const okIndices = evt.items.map((item, idx) => (item.type === "ok" ? idx : -1)).filter((idx) => idx >= 0);
      const startIdx = okIndices.length > maxProgressItems ? okIndices[okIndices.length - maxProgressItems] : 0;
      const displayItems = evt.items.slice(startIdx);
      const hiddenProgressItems = Math.max(0, evt.items.length - displayItems.length);
      const intIconMap = { warning: "alertTriangle", error: "x-circle", db: "database", info: "info", skip: "x" };
      const intClassMap = { warning: "step-warning", error: "step-error", db: "step-db", info: "step-info", skip: "step-skip" };
      return (
        <div key={eventKey} className="log-progress-batch">
          <div className="log-progress-sticky">
            {total > 0 && (
              <div className="log-progress-header">
                <span className="log-progress-count">{current.toLocaleString()} / {total.toLocaleString()}</span>
                <span className="log-progress-pct">{pct}%</span>
              </div>
            )}
            {total > 0 && (
              <div className="log-progress-bar">
                <div className="log-progress-fill" style={{ width: `${pct}%` }} />
              </div>
            )}
          </div>
          <div className="log-progress-items">
            {hiddenProgressItems > 0 ? (
              <div className="log-progress-truncation">
                Showing latest {displayItems.length} items ({hiddenProgressItems.toLocaleString()} earlier lines hidden)
              </div>
            ) : null}
            {displayItems.map((item, j) => {
              const itemKey = `${eventKey}-${j}`;
              if (item.type === "ok") {
                return (
                  <details key={itemKey} className="log-progress-detail" open={expandProgressDetails}>
                    <summary className="log-progress-item log-progress-item-done">
                      <Icon name="check-circle" />
                      <span className="log-progress-slug">{item.slug}</span>
                      {item.duration != null && <span className="log-progress-dur">{item.duration.toFixed(2)}s</span>}
                      <span className="log-progress-chevron">▶</span>
                    </summary>
                    {item.attrs && <div className="log-progress-raw">{item.attrs}</div>}
                  </details>
                );
              }
              if (item.type === "plan") {
                return (
                  <details key={itemKey} className="log-progress-detail" open={expandProgressDetails}>
                    <summary className={`log-progress-item log-progress-item-${isLive ? "live" : "pending"}`}>
                      <Icon name={isLive ? "loader" : "info"} />
                      <span className="log-progress-slug">{item.slug}</span>
                      <span className="log-progress-chevron">▶</span>
                    </summary>
                    {item.attrs && <div className="log-progress-raw">{item.attrs}</div>}
                  </details>
                );
              }
              return (
                <div key={itemKey} className={`log-step ${intClassMap[item.type] || ""}`}>
                  <Icon name={intIconMap[item.type] || "info"} />
                  <span>{item.text}</span>
                </div>
              );
            })}
          </div>
        </div>
      );
    }
    if (evt.type === "verbose-group") {
      if (evt.lines.length <= 3) {
        return (
          <div key={eventKey}>
            {evt.lines.map((lineText, j) => <div key={`${eventKey}-${j}`} className="log-verbose">{lineText}</div>)}
          </div>
        );
      }
      return (
        <details key={eventKey} className="log-verbose-details">
          <summary>{evt.lines.length} lines of output</summary>
          {evt.lines.map((lineText, j) => <div key={`${eventKey}-${j}`} className="log-verbose">{lineText}</div>)}
        </details>
      );
    }
    if (iconMap[evt.type]) {
      return (
        <div key={eventKey} className={`log-step ${classMap[evt.type] || ""}`}>
          <Icon name={iconMap[evt.type]} />
          <span>{evt.text}</span>
        </div>
      );
    }
    return null;
  });
}

function stageDisplayName(stage) {
  return DATA_MAINTENANCE_STAGE_LABELS[stage] || stage;
}

function buildDataMaintenanceView(events, isLive) {
  const pipelineStart = events.find((evt) => evt.type === "pipeline-start" && evt.pipeline === "data-maintenance");
  if (!pipelineStart) return null;

  const orderedStageNames = Array.isArray(pipelineStart.stages) ? [...pipelineStart.stages] : [];
  const stageMap = new Map();
  const prelude = [];
  const trailer = [];
  let currentStage = null;

  function ensureStage(name) {
    const normalized = String(name || "").trim().toLowerCase();
    if (!stageMap.has(normalized)) {
      stageMap.set(normalized, {
        stage: normalized,
        events: [],
        summary: null,
        status: "pending",
        elapsed: null,
        exitCode: null,
        started: false,
      });
    }
    return stageMap.get(normalized);
  }

  for (const evt of events) {
    if (evt.type === "command") {
      if (!currentStage) prelude.push(evt);
      else currentStage.events.push(evt);
      continue;
    }
    if (evt.type === "pipeline-start") {
      prelude.push(evt);
      continue;
    }
    if (evt.type === "stage-start") {
      const stage = ensureStage(evt.stage);
      stage.started = true;
      stage.status = "running";
      currentStage = stage;
      continue;
    }
    if (evt.type === "stage-done") {
      const stage = ensureStage(evt.stage);
      stage.started = true;
      stage.status = "succeeded";
      stage.elapsed = evt.elapsed || null;
      if (currentStage && currentStage.stage === stage.stage) currentStage = null;
      continue;
    }
    if (evt.type === "stage-error") {
      const stage = ensureStage(evt.stage);
      stage.started = true;
      stage.status = "failed";
      stage.elapsed = evt.elapsed || null;
      stage.exitCode = Number.isFinite(evt.exitCode) ? evt.exitCode : null;
      if (currentStage && currentStage.stage === stage.stage) currentStage = null;
      continue;
    }
    if (evt.type === "summary" && evt.data && isDataMaintenancePipelineSummary(evt.data)) {
      trailer.push(evt);
      continue;
    }
    if (evt.type === "pipeline-done") {
      trailer.push(evt);
      continue;
    }
    if (currentStage) {
      if (evt.type === "summary" && evt.data) {
        currentStage.summary = evt.data;
      } else {
        currentStage.events.push(evt);
      }
      continue;
    }
    trailer.push(evt);
  }

  const stageNames = [...orderedStageNames];
  for (const key of stageMap.keys()) {
    if (!stageNames.includes(key)) stageNames.push(key);
  }

  const stages = stageNames.map((name) => {
    const stage = stageMap.get(name) || {
      stage: name,
      events: [],
      summary: null,
      status: "pending",
      elapsed: null,
      exitCode: null,
      started: false,
    };
    if (stage.status === "running" && !isLive) {
      stage.status = "unknown";
    }
    return stage;
  });

  return { prelude, stages, trailer };
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
  const [showAdvancedTaskOptions, setShowAdvancedTaskOptions] = useState(false);
  const [runSearch, setRunSearch] = useState("");
  const [runTypeFilter, setRunTypeFilter] = useState("all");
  const [logBuffer, setLogBuffer] = useState("");
  const [logMaximized, setLogMaximized] = useState(false);
  const logOffsetRef = useRef(0);
  const logPollRef = useRef(null);
  const openConfigRequestRef = useRef(0);
  const selectedRunStatusRef = useRef(null);
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

  const [importTarget, setImportTarget] = useState("categories");
  const [importJsonText, setImportJsonText] = useState("");
  const [taxonomyBootstrapMode, setTaxonomyBootstrapMode] = useState("replace");
  const [starterPackMode, setStarterPackMode] = useState("merge");
  const [taxonomyActionLoading, setTaxonomyActionLoading] = useState("");

  const [envSpecs, setEnvSpecs] = useState({});
  const [envDraft, setEnvDraft] = useState({});
  const [envClear, setEnvClear] = useState({});
  const [connectionChecks, setConnectionChecks] = useState({
    mealie: { loading: false, ok: null, detail: "" },
    openai: { loading: false, ok: null, detail: "" },
    ollama: { loading: false, ok: null, detail: "" },
    db: { loading: false, ok: null, detail: "" },
    dbDetect: { loading: false, ok: null, detail: "" },
  });
  const [availableModels, setAvailableModels] = useState({ openai: [], ollama: [] });

  const [newUserUsername, setNewUserUsername] = useState("");
  const [newUserRole, setNewUserRole] = useState("Editor");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserForceReset, setNewUserForceReset] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [userSearch, setUserSearch] = useState("");
  const [resetPasswords, setResetPasswords] = useState({});
  const [resetForceResets, setResetForceResets] = useState({});
  const [expandedUser, setExpandedUser] = useState(null);
  const [confirmModal, setConfirmModal] = useState(null);
  const [forcedResetPending, setForcedResetPending] = useState(false);
  const [forcedResetPassword, setForcedResetPassword] = useState("");
  const [forcedResetShowPass, setForcedResetShowPass] = useState(false);

  const [taxonomyItemsByFile, setTaxonomyItemsByFile] = useState({});
  const [helpDocs, setHelpDocs] = useState([]);
  const [debugLog, setDebugLog] = useState(null);
  const [debugLogLoading, setDebugLogLoading] = useState(false);
  const [overviewMetrics, setOverviewMetrics] = useState(null);
  const [qualityMetrics, setQualityMetrics] = useState(null);
  const [aboutMeta, setAboutMeta] = useState(null);
  const [healthMeta, setHealthMeta] = useState(null);
  const [lastLoadedAt, setLastLoadedAt] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState(new Set(["Data Pipeline", "Actions", "Organizers", "Audits"]));

  const selectedTaskDef = useMemo(
    () => tasks.find((item) => item.task_id === selectedTask) || null,
    [tasks, selectedTask]
  );

  const activePageMeta = PAGE_META[activePage] || PAGE_META.overview;

  const taskTitleById = useMemo(() => {
    const map = new Map();
    for (const task of tasks) {
      map.set(task.task_id, task.title || task.task_id);
    }
    return map;
  }, [tasks]);

  const TASK_GROUP_ORDER = ["Data Pipeline", "Actions", "Organizers", "Audits"];

  function toggleTaskGroup(name) {
    setCollapsedGroups(prev => {
      const next = new Set(prev);
      if (next.has(name)) { next.delete(name); } else { next.add(name); }
      return next;
    });
  }

  const TASK_ICONS = {
    "data-maintenance": "settings",
    "clean-recipes": "trash",
    "ingredient-parse": "folder",
    "yield-normalize": "zap",
    "cleanup-duplicates": "layers",
    "tag-categorize": "tag",
    "taxonomy-refresh": "refresh",
    "cookbook-sync": "book-open",
    "health-check": "check-circle",
  };

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
      tools: extractNames(taxonomyItemsByFile.tools),
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
    setShowAdvancedTaskOptions(false);
  }, [selectedTaskDef]);

  useEffect(() => {
    if (!editingScheduleId) {
      return;
    }
    const stillExists = schedules.some((item) => String(item.schedule_id) === String(editingScheduleId));
    if (!stillExists) {
      setEditingScheduleId("");
      setScheduleEditForm(null);
      setShowAdvancedScheduleOptions(false);
    }
  }, [editingScheduleId, schedules]);

  const liveRunsTimer = React.useRef(null);

  useEffect(() => {
    if (activePage !== "tasks" || !session) {
      clearInterval(liveRunsTimer.current);
      return;
    }
    // Fetch fresh task definitions (including dynamic options like provider choices)
    // every time the user opens the Tasks page, so cached data never goes stale.
    refreshTasks();
    liveRunsTimer.current = setInterval(() => { refreshRuns(); }, 3000);
    return () => clearInterval(liveRunsTimer.current);
  }, [activePage, session]);

  // Keep a ref to the latest selected run status so the log poll interval
  // can detect completion without a stale closure.
  useEffect(() => {
    const run = runs.find(r => r.run_id === selectedRunId) || null;
    selectedRunStatusRef.current = run ? run.status : null;
  }, [runs, selectedRunId]);

  // Log fetch + live tail polling.
  // Re-runs when selectedRunId or activePage changes.
  useEffect(() => {
    if (logPollRef.current) { clearInterval(logPollRef.current); logPollRef.current = null; }

    if (activePage !== "tasks" || !selectedRunId) {
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
      } catch {}
    }

    doTail(false);

    const run = runs.find(r => r.run_id === selectedRunId);
    if (run && (run.status === "running" || run.status === "queued")) {
      logPollRef.current = setInterval(async () => {
        const status = selectedRunStatusRef.current;
        if (status !== "running" && status !== "queued") {
          clearInterval(logPollRef.current);
          logPollRef.current = null;
          await doTail(true);
          return;
        }
        await doTail(true);
      }, 1500);
    }

    return () => { if (logPollRef.current) { clearInterval(logPollRef.current); logPollRef.current = null; } };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId, activePage]);

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
      setSession(payload);
      setError("");
      if (payload.force_reset) setForcedResetPending(true);
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
    } catch {
      // Cache update failures should never block UI actions.
    }
  }

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
    setQualityMetrics(data.quality);
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

  }

  function scheduleAutoRefresh() {
    clearTimeout(staleTimer.current);
    staleTimer.current = setTimeout(() => { loadData(); }, CACHE_TTL);
  }

  async function fetchDebugLog() {
    setDebugLogLoading(true);
    try {
      const data = await api("/debug-log");
      setDebugLog(data);
    } catch (e) {
      setDebugLog({ error: String(e), log: "", log_available: false });
    } finally {
      setDebugLogLoading(false);
    }
  }

  function downloadDebugLog() {
    if (!debugLog) return;
    const h = debugLog.health || {};
    const db = h.db || {};
    const cfg = h.config || {};
    const conns = h.connections || {};
    const runs = h.runs || {};
    const sc = h.scheduler || {};
    const statusCounts = runs.status_counts || {};
    const connLine = (label, c) => `${label.padEnd(12)}${c?.ok ? "OK" : "FAIL"}  ${c?.detail || ""}`;

    const sections = [
      "=== CookDex Debug Report ===",
      `Version:    ${debugLog.app_version || "-"}`,
      `Python:     ${debugLog.python_version || "-"}`,
      `Platform:   ${debugLog.platform || "-"}`,
      `Log file:   ${debugLog.log_file || "-"}`,
      "",
      "=== Connection Tests ===",
      connLine("Mealie", conns.mealie),
      connLine("OpenAI", conns.openai),
      connLine("Ollama", conns.ollama),
      connLine("Direct DB", conns.direct_db),
      "",
      "=== Instance Health ===",
      `Users:      ${db.user_count ?? "-"}`,
      `Runs total: ${db.run_count ?? "-"}  (${Object.entries(statusCounts).map(([k, v]) => `${k}: ${v}`).join(", ") || "none"})`,
      `Schedules:  ${db.schedule_count ?? "-"} total, ${db.enabled_schedules ?? "-"} enabled`,
      `Scheduler:  ${sc.running ? "running" : "stopped"}`,
      "",
      "=== Configuration ===",
      `Mealie URL:       ${cfg.mealie_url || "(not set)"}`,
      `Mealie key:       ${cfg.mealie_key_set ? "set" : "NOT SET"}`,
      `OpenAI key:       ${cfg.openai_key_set ? "set" : "not set"}`,
      `OpenAI model:     ${cfg.openai_model || "(default)"}`,
      `Ollama URL:       ${cfg.ollama_url || "(not set)"}`,
      `Ollama model:     ${cfg.ollama_model || "(default)"}`,
      "",
      "=== Recent Runs ===",
      ...(runs.recent || []).map(r =>
        `${r.started_at || "-"}  ${r.status.padEnd(10)}  ${r.task_id}  (${r.triggered_by})`
      ),
      "",
      "=== Server Log ===",
      debugLog.log || "(no log content)",
    ].join("\n");

    const blob = new Blob([sections], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cookdex-debug.log";
    a.click();
    URL.revokeObjectURL(url);
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

  const prevRunsRef = React.useRef([]);

  async function refreshRuns() {
    try {
      const payload = await api("/runs");
      const nextRuns = payload?.items || [];
      const prev = prevRunsRef.current;
      const qualityJustFinished = nextRuns.some((run) => {
        if (run.task_id !== "health-check") return false;
        if (run.status !== "completed") return false;
        const old = prev.find((r) => r.run_id === run.run_id);
        return !old || old.status !== "completed";
      });
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

  async function loadData() {
    if (isLoading) return;
    setIsLoading(true);
    showNotice("Refreshing data\u2026", 30000);
    try {
      const [
        taskPayload, runPayload, schedulePayload, settingsPayload,
        configPayload, usersPayload, helpPayload,
        metricsPayload, qualityPayload, aboutPayload, healthPayload,
      ] = await Promise.all([
        api("/tasks"),
        api("/runs"),
        api("/schedules"),
        api("/settings"),
        api("/config/files"),
        api("/users"),
        api("/help/docs").catch(() => ({ items: [] })),
        api("/metrics/overview").catch(() => null),
        api("/metrics/quality").catch(() => null),
        api("/about/meta").catch(() => null),
        api("/health").catch(() => null),
      ]);

      const data = {
        tasks: taskPayload, runs: runPayload, schedules: schedulePayload,
        settings: settingsPayload, config: configPayload, users: usersPayload,
        help: helpPayload, metrics: metricsPayload, quality: qualityPayload,
        about: aboutPayload, health: healthPayload,
        timestamp: new Date().toISOString(), savedAt: Date.now(),
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
      const loginResult = await api("/auth/login", { method: "POST", body: { username, password } });
      setPassword("");
      await refreshSession();
      await loadData();
      if (loginResult?.force_reset) {
        setForcedResetPending(true);
      } else {
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
      const isDangerous = options.dry_run === false;
      if (isDangerous) {
        await togglePolicy(selectedTaskDef.task_id, true);
      }
      await api("/runs", {
        method: "POST",
        body: { task_id: selectedTaskDef.task_id, options },
      });
      await refreshRuns();
      showNotice("Run queued.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function cancelRun(runId) {
    try {
      clearBanners();
      await api(`/runs/${runId}/cancel`, { method: "POST" });
      await refreshRuns();
      showNotice("Run canceled.");
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
      await refreshTasks();
      showNotice("Task policy updated.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function createSchedule() {
    if (!selectedTaskDef) {
      setError("Select a task before saving a schedule.");
      return;
    }
    if (!scheduleForm.name.trim()) {
      setError("Please enter a name for this schedule.");
      return;
    }
    if (scheduleForm.kind === "once" && !scheduleForm.run_at) {
      setError("Please choose a date and time for this schedule.");
      return;
    }
    if (scheduleForm.kind === "interval" && !scheduleForm.start_at) {
      setError("Please choose a start date for this schedule.");
      return;
    }

    try {
      clearBanners();
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
          start_at: scheduleForm.kind === "interval" ? scheduleForm.start_at : undefined,
          end_at: (scheduleForm.kind === "interval" && scheduleForm.end_at) ? scheduleForm.end_at : undefined,
          run_at: scheduleForm.kind === "once" ? scheduleForm.run_at : undefined,
          options,
          enabled: Boolean(scheduleForm.enabled),
          run_if_missed: Boolean(scheduleForm.run_if_missed),
        },
      });
      await refreshSchedules();
      setScheduleMode(false);
      showNotice("Schedule saved.");
    } catch (exc) {
      handleError(exc);
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
    if (!scheduleEditForm) {
      return;
    }
    const selectedEditTaskDef = tasks.find((item) => item.task_id === scheduleEditForm.task_id) || null;
    if (!selectedEditTaskDef) {
      setError("Select a valid task before saving this schedule.");
      return;
    }
    if (!scheduleEditForm.name.trim()) {
      setError("Please enter a name for this schedule.");
      return;
    }
    if (scheduleEditForm.kind === "once" && !scheduleEditForm.run_at) {
      setError("Please choose a date and time for this schedule.");
      return;
    }
    if (scheduleEditForm.kind === "interval" && !scheduleEditForm.start_at) {
      setError("Please choose a start date for this schedule.");
      return;
    }
    if (scheduleEditForm.kind === "interval" && Number(scheduleEditForm.intervalValue) <= 0) {
      setError("Interval schedules require a positive interval value.");
      return;
    }

    try {
      clearBanners();
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
          start_at: scheduleEditForm.kind === "interval" ? scheduleEditForm.start_at : undefined,
          end_at:
            scheduleEditForm.kind === "interval" && scheduleEditForm.end_at
              ? scheduleEditForm.end_at
              : undefined,
          run_at: scheduleEditForm.kind === "once" ? scheduleEditForm.run_at : undefined,
          options,
          enabled: Boolean(scheduleEditForm.enabled),
          run_if_missed: Boolean(scheduleEditForm.run_if_missed),
        },
      });
      await refreshSchedules();
      cancelScheduleEdit();
      showNotice("Schedule updated.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function deleteSchedule(scheduleId) {
    try {
      clearBanners();
      await api(`/schedules/${scheduleId}`, { method: "DELETE" });
      await refreshSchedules();
      showNotice("Schedule removed.");
    } catch (exc) {
      handleError(exc);
    }
  }

  async function toggleScheduleEnabled(schedule) {
    try {
      clearBanners();
      await api(`/schedules/${schedule.schedule_id}`, {
        method: "PATCH",
        body: { enabled: !schedule.enabled },
      });
      await refreshSchedules();
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
      } else if (activeConfigMode === "tool-cards") {
        content = normalizeToolEntries(activeToolItems);
      } else if (activeConfigMode === "label-cards") {
        content = normalizeLabelEntries(activeLabelItems);
      } else if (activeConfigMode === "unit-cards") {
        content = normalizeUnitEntries(activeUnitItems);
      } else {
        const parsed = JSON.parse(activeConfigBody);
        content = parsed;
      }

      const savePayload = await api(`/config/files/${activeConfig}`, {
        method: "PUT",
        body: { content },
      });

      if (TAXONOMY_FILE_NAMES.includes(activeConfig) && Array.isArray(content)) {
        setTaxonomyItemsByFile((prev) => ({ ...prev, [activeConfig]: content }));
      }

      setConfigEditorState(content, activeConfig);
      await loadData();
      const ruleNote = formatRuleSyncNotice(savePayload?.rule_sync);
      showNotice(
        `${CONFIG_LABELS[activeConfig] || activeConfig} saved.${ruleNote ? ` ${ruleNote}` : ""}`
      );
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

      const result = await api(`/config/files/${target}`, {
        method: "PUT",
        body: { content: payload },
      });

      setImportJsonText("");
      if (activeConfig === target) {
        setConfigEditorState(payload, target);
      }
      await loadData();
      const ruleNote = formatRuleSyncNotice(result?.rule_sync);
      showNotice(`${CONFIG_LABELS[target] || target} imported from JSON.${ruleNote ? ` ${ruleNote}` : ""}`);
    } catch (exc) {
      handleError(exc);
    }
  }

  async function initializeFromMealieBaseline() {
    try {
      clearBanners();
      setTaxonomyActionLoading("mealie");
      const payload = await api("/config/taxonomy/initialize-from-mealie", {
        method: "POST",
        body: { mode: taxonomyBootstrapMode },
      });
      await loadData();
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

  async function importStarterPack() {
    try {
      clearBanners();
      setTaxonomyActionLoading("starter-pack");
      const payload = await api("/config/taxonomy/import-starter-pack", {
        method: "POST",
        body: {
          mode: starterPackMode,
        },
      });
      await loadData();
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

  function generateTemporaryPassword() {
    const upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    const lower = "abcdefghijkmnopqrstuvwxyz";
    const digits = "23456789";
    const all = upper + lower + digits + "!@#$%";
    const rng = (max) => {
      const buf = new Uint32Array(1);
      const limit = Math.floor(0x100000000 / max) * max;
      let v;
      do { crypto.getRandomValues(buf); v = buf[0]; } while (v >= limit);
      return v % max;
    };
    const pick = (s) => s[rng(s.length)];
    const required = [pick(upper), pick(lower), pick(digits)];
    for (let i = required.length; i < 14; i += 1) required.push(pick(all));
    for (let i = required.length - 1; i > 0; i -= 1) {
      const j = rng(i + 1);
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
        body: { username: newUserUsername, password: newUserPassword, force_reset: newUserForceReset },
      });
      setNewUserUsername("");
      setNewUserRole("Editor");
      setNewUserPassword("");
      setNewUserForceReset(true);
      await refreshUsers();
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
        body: { password: nextPassword, force_reset: resetForceResets[usernameValue] ?? false },
      });
      setResetPasswords((prev) => ({ ...prev, [usernameValue]: "" }));
      setResetForceResets((prev) => ({ ...prev, [usernameValue]: false }));
      await refreshUsers();
      showNotice(`Password reset for ${usernameValue}.`);
    } catch (exc) {
      handleError(exc);
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
      setForcedResetPending(false);
      setForcedResetPassword("");
      setForcedResetShowPass(false);
      showNotice("Password changed. Welcome!");
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
          await refreshUsers();
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

      const requestOptions = { method: "POST" };
      if (kind !== "db") {
        requestOptions.body = {
          mealie_url: draftOverrideValue("MEALIE_URL"),
          mealie_api_key: envClear.MEALIE_API_KEY ? "" : draftOverrideValue("MEALIE_API_KEY"),
          openai_api_key: envClear.OPENAI_API_KEY ? "" : draftOverrideValue("OPENAI_API_KEY"),
          openai_model: draftOverrideValue("OPENAI_MODEL"),
          ollama_url: draftOverrideValue("OLLAMA_URL"),
          ollama_model: draftOverrideValue("OLLAMA_MODEL"),
        };
      }

      const result = await api(`/settings/test/${kind}`, requestOptions);

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

  async function runDbDetect() {
    try {
      setConnectionChecks((prev) => ({
        ...prev,
        dbDetect: { loading: true, ok: null, detail: "Detecting database credentials\u2026" },
      }));
      const body = {
        ssh_host: draftOverrideValue("MEALIE_DB_SSH_HOST"),
        ssh_user: draftOverrideValue("MEALIE_DB_SSH_USER"),
        ssh_key: draftOverrideValue("MEALIE_DB_SSH_KEY"),
      };
      const result = await api("/settings/detect/db", { method: "POST", body });
      if (result.ok && result.detected) {
        setEnvDraft((prev) => {
          const next = { ...prev };
          for (const [key, value] of Object.entries(result.detected)) {
            if (value) next[key] = String(value);
          }
          return next;
        });
        if (result.detected.MEALIE_PG_PASS) {
          setEnvClear((prev) => ({ ...prev, MEALIE_PG_PASS: false }));
        }
      }
      setConnectionChecks((prev) => ({
        ...prev,
        dbDetect: {
          loading: false,
          ok: Boolean(result.ok),
          detail: String(result.detail || (result.ok ? "Credentials detected. Review and click Apply Changes." : "Detection failed.")),
        },
      }));
    } catch (exc) {
      setConnectionChecks((prev) => ({
        ...prev,
        dbDetect: {
          loading: false,
          ok: false,
          detail: normalizeErrorMessage(exc?.message || exc),
        },
      }));
    }
  }

  function renderOverviewPage() {
    const hour = new Date().getHours();
    const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    const hasFailed = runStats.failed > 0;
    const needsConnectionSetup = envSpecs?.MEALIE_URL?.has_value === false || envSpecs?.MEALIE_API_KEY?.has_value === false;
    const statusMsg = hasFailed
      ? `${runStats.failed} run${runStats.failed === 1 ? "" : "s"} failed recently.`
      : !overviewMetrics?.ok && overviewMetrics?.reason
      ? "Mealie is not connected."
      : "Your organizer is healthy and ready.";

    return (
      <section className="page-grid overview-grid">
        <article className="card tone-soft intro-card">
          <h3>{greeting}. {statusMsg}</h3>
          <div className="status-row">
            <span className="status-pill success">Queued {runStats.queued}</span>
            <span className="status-pill neutral">Scheduled {upcomingScheduleCount}</span>
            {runStats.failed > 0 && <span className="status-pill danger">Failed {runStats.failed}</span>}
          </div>
          {!overviewMetrics?.ok && overviewMetrics?.reason ? (
            <p className="muted tiny">{overviewMetrics.reason}</p>
          ) : null}
        </article>

        {needsConnectionSetup && (
          <p className="banner warning">
            <span>
              <strong>Mealie connection not configured.</strong>{" "}
              Go to{" "}
              <button className="link-inline" onClick={() => setActivePage("settings")}>Settings</button>
              {" "}to add your Mealie URL and API key before running tasks.
            </span>
          </p>
        )}

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

        <div className="overview-left">
          <article className="card chart-panel">
            <h3>Coverage</h3>
            <div className="coverage-grid">
              <CoverageRing label="Categories" value={overviewCoverage.categories} />
              <CoverageRing label="Tags" value={overviewCoverage.tags} />
              <CoverageRing label="Tools" value={overviewCoverage.tools} />
              {qualityMetrics?.available && <>
                <CoverageRing label="Description" value={qualityMetrics.dimension_coverage?.description?.pct_have ?? 0} />
                <CoverageRing label="Cook Time" value={qualityMetrics.dimension_coverage?.time?.pct_have ?? 0} />
                <CoverageRing label="Yield" value={qualityMetrics.dimension_coverage?.yield?.pct_have ?? 0} />
              </>}
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
        </div>

        <div className="overview-right">
          <article className="card medallion-card">
            <h3>Recipe Quality</h3>
            {qualityMetrics?.available ? (() => {
              const { total, gold, silver, bronze, gold_pct, dimension_coverage } = qualityMetrics;
              const tier = gold_pct >= 80 ? "gold" : gold_pct >= 50 ? "silver" : "bronze";
              const DIMS = ["category", "tags", "tools", "description", "time", "yield"];
              const DIM_LABELS = { category: "Category", tags: "Tags", tools: "Tools", description: "Description", time: "Cook Time", yield: "Yield" };
              return (
                <div className="medallion-body">
                  <div className={`medallion-badge medallion-${tier}`}>
                    <span className="medallion-icon">{tier === "gold" ? "🥇" : tier === "silver" ? "🥈" : "🥉"}</span>
                    <span className="medallion-tier">{tier.charAt(0).toUpperCase() + tier.slice(1)}</span>
                    <span className="medallion-pct">{gold_pct}% gold</span>
                  </div>
                  <div className="medallion-tiers">
                    <span className="medallion-tier-row gold-row"><strong>{gold}</strong> gold</span>
                    <span className="medallion-tier-row silver-row"><strong>{silver}</strong> silver</span>
                    <span className="medallion-tier-row bronze-row"><strong>{bronze}</strong> bronze</span>
                  </div>
                  <div className="medallion-dims">
                    {DIMS.map((dim) => {
                      const d = dimension_coverage?.[dim];
                      const pct = d?.pct_have ?? 0;
                      return (
                        <div key={dim} className="dim-row">
                          <span className="dim-label">{DIM_LABELS[dim]}</span>
                          <div className="dim-bar-track">
                            <div className="dim-bar-fill" style={{ width: `${pct}%` }} />
                          </div>
                          <span className="dim-pct">{pct}%</span>
                        </div>
                      );
                    })}
                  </div>
                  <p className="muted tiny">{total} recipes scored</p>
                </div>
              );
            })() : (
              <div className="medallion-empty">
                <p className="muted">No quality audit data yet.</p>
                <button
                  className="ghost small"
                  onClick={() => {
                    setActivePage("tasks");
                    setSelectedTask("health-check");
                  }}
                >
                  Run Quality Audit →
                </button>
              </div>
            )}
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
        </div>
      </section>
    );
  }

  function renderTasksPage() {
    const selectedRun = runs.find((item) => item.run_id === selectedRunId) || null;

    function formatScheduleTiming(schedule) {
      const kind = schedule.schedule_kind;
      const data = schedule.schedule_data || {};
      if (kind === "once") {
        if (!data.run_at) return "Once";
        return `Once · ${new Date(data.run_at).toLocaleString()}`;
      }
      const secs = Number(data.seconds || 0);
      if (secs >= 86400) return `Every ${Math.round(secs / 86400)}d`;
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
              <div className="task-picker">
                {taskGroups.map(([groupName, groupTasks], gi) => {
                  const collapsed = collapsedGroups.has(groupName);
                  return (
                    <div key={groupName} className="task-group">
                      <button
                        type="button"
                        className={`task-group-header${gi === 0 ? " first" : ""}`}
                        onClick={() => toggleTaskGroup(groupName)}
                      >
                        <span className="task-group-label">{groupName}</span>
                        <span className={`task-group-chevron${collapsed ? " collapsed" : ""}`}>▾</span>
                      </button>
                      {!collapsed && groupTasks.map((task) => (
                        <button
                          key={task.task_id}
                          type="button"
                          className={`task-item${selectedTask === task.task_id ? " active" : ""}`}
                          onClick={() => setSelectedTask(task.task_id)}
                        >
                          <span className="task-item-title">
                            <Icon name={TASK_ICONS[task.task_id] || "zap"} className="task-item-icon" />
                            {task.title}
                          </span>
                          <span className="task-item-desc">{task.description}</span>
                        </button>
                      ))}
                    </div>
                  );
                })}
              </div>

              {!selectedTaskDef ? (
                <p className="muted tiny">Select a task above to configure and run it.</p>
              ) : (() => {
                const visibleOptions = (selectedTaskDef.options || []).filter((option) =>
                  isTaskOptionVisible(option, taskValues, true)
                );
                const basicOptions = visibleOptions.filter((option) => !option.advanced);
                const advancedOptions = visibleOptions.filter((option) => option.advanced);
                const shownOptions = showAdvancedTaskOptions ? visibleOptions : basicOptions;

                if (visibleOptions.length === 0) {
                  return <p className="muted tiny">This task has no additional options.</p>;
                }

                return (
                  <>
                    {advancedOptions.length > 0 && (
                      <>
                        <label className="field field-inline">
                          <span>Show advanced options</span>
                          <input
                            type="checkbox"
                            checked={showAdvancedTaskOptions}
                            onChange={(event) => setShowAdvancedTaskOptions(event.target.checked)}
                          />
                        </label>
                        {!showAdvancedTaskOptions && (
                          <p className="muted tiny">{advancedOptions.length} advanced option(s) hidden.</p>
                        )}
                      </>
                    )}
                    {shownOptions.length > 0 ? (
                      <div className="option-grid">
                        {shownOptions.map((option) =>
                          fieldFromOption(option, taskValues[option.key], (key, value) =>
                            setTaskValues((prev) => ({ ...prev, [key]: value })),
                            taskValues
                          )
                        )}
                      </div>
                    ) : (
                      <p className="muted tiny">No basic options for this task. Enable advanced options to customize it.</p>
                    )}
                  </>
                );
              })()}

              <label className="field field-inline schedule-toggle" style={selectedTaskDef ? undefined : { display: "none" }}>
                <span>Schedule Run</span>
                <input
                  type="checkbox"
                  checked={scheduleMode}
                  onChange={(event) => setScheduleMode(event.target.checked)}
                />
              </label>

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

              {selectedTaskDef && (scheduleMode ? (
                <button type="button" className="primary" onClick={createSchedule}>
                  <Icon name="save" />
                  Save Schedule
                </button>
              ) : (
                <button type="button" className="primary" onClick={triggerRun}>
                  <Icon name="play" />
                  Queue Run
                </button>
              ))}
            </div>
          </article>
        </div>

        <div className="stacked-cards">
          {schedules.length > 0 ? (
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
                          <strong>{schedule.name || schedule.schedule_id}</strong>
                          <p className="tiny muted">
                            {taskTitleById.get(schedule.task_id) || schedule.task_id}
                            {" · "}
                            {formatScheduleTiming(schedule)}
                            {" · "}
                            {schedule.schedule_data?.run_if_missed ? "Run if missed" : "Skip if missed"}
                          </p>
                        </div>
                        <div className="schedule-item-actions">
                          <button
                            className={`ghost small${isEditing ? " active-edit" : ""}`}
                            title={isEditing ? "Close editor" : "Edit schedule"}
                            onClick={() => (isEditing ? cancelScheduleEdit() : startScheduleEdit(schedule))}
                          >
                            <Icon name="pencil" />
                          </button>
                          <button
                            className={`ghost small ${schedule.enabled !== false ? "enabled-toggle" : "disabled-toggle"}`}
                            title={schedule.enabled !== false ? "Disable schedule" : "Enable schedule"}
                            onClick={() => toggleScheduleEnabled(schedule)}
                          >
                            <Icon name={schedule.enabled !== false ? "check-circle" : "x-circle"} />
                          </button>
                          <button className="ghost small danger" onClick={() => deleteSchedule(scheduleId)}>
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
          ) : null}

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
                  <th>Mode</th>
                  <th>Status</th>
                  <th>Run Time</th>
                  <th>Started</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filteredRuns.length === 0 ? (
                  <tr>
                    <td colSpan={7}>No runs found.</td>
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
                      >
                        <td>{taskTitleById.get(run.task_id) || run.task_id}</td>
                        <td>{runTypeLabel(run)}</td>
                        <td>
                          <span className={`status-pill ${isDryRun ? "dry-run" : "live-run"}`}>
                            {isDryRun ? "Dry Run" : "Live"}
                          </span>
                        </td>
                        <td>
                          <span className={`status-pill ${statusClass(run.status)}`}>{run.status}</span>
                        </td>
                        <td>{formatRunTime(run)}</td>
                        <td className="muted">{formatDateTimeShort(run.started_at || run.created_at)}</td>
                        <td className="run-actions-cell">
                          {cancelable && (
                            <button
                              className="ghost small danger"
                              title="Cancel run"
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
                        showNotice("Log copied to clipboard.");
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
                  title={logMaximized ? "Restore" : "Maximize"}
                  onClick={() => setLogMaximized(prev => !prev)}
                >
                  <Icon name={logMaximized ? "minimize" : "maximize"} />
                </button>
              </div>
            </div>
            <div className="log-box">
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
                                    <span className="log-stage-chevron">▶</span>
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

  const GROUP_ICONS = { Connection: "link", AI: "wand", "Direct DB": "database" };

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
                    const configuredProvider = String(envDraft["CATEGORIZER_PROVIDER"] || "").trim().toLowerCase();
                    const provider = configuredProvider === "ollama" ? "ollama" : "chatgpt";
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
                        <select value={provider} onChange={(e) => onChangeDraft(e.target.value)}>
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
                    } else if (Array.isArray(item.choices) && item.choices.length > 0) {
                      inputElement = (
                        <select value={draftValue} onChange={(e) => onChangeDraft(e.target.value)}>
                          {item.choices.map((c) => (
                            <option key={c} value={c}>{c === "" ? "— disabled —" : c}</option>
                          ))}
                        </select>
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
                { id: "dbDetect", label: "Auto-detect DB", hint: "SSH into Mealie host to discover DB credentials.", requiresSsh: true },
                { id: "db", label: "Test DB", hint: "Verify direct database connection.", requiresDb: true },
              ].filter((test) => {
                const configuredProvider = String(envDraft["CATEGORIZER_PROVIDER"] || "").trim().toLowerCase();
                const p = configuredProvider === "ollama" ? "ollama" : "chatgpt";
                if (test.provider && p !== test.provider) return false;
                if (test.requiresSsh) {
                  return Boolean(String(envDraft["MEALIE_DB_SSH_HOST"] || "").trim());
                }
                if (test.requiresDb) {
                  const dbType = String(envDraft["MEALIE_DB_TYPE"] || "").trim();
                  return dbType === "postgres" || dbType === "sqlite";
                }
                return true;
              })
              .map((test) => {
                const state = connectionChecks[test.id] || {};
                return (
                  <div key={test.id} className="connection-test-item">
                    <button
                      className="ghost"
                      onClick={() => test.id === "dbDetect" ? runDbDetect() : runConnectionTest(test.id)}
                      disabled={state.loading}
                    >
                      <Icon name={state.loading ? "refresh" : test.id === "dbDetect" ? "search" : "zap"} />
                      {state.loading ? (test.id === "dbDetect" ? "Detecting\u2026" : "Testing\u2026") : test.label}
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
          </article>

        </aside>
      </section>
    );
  }

  function renderRecipeOrganizationPage() {
    const activeContentCount =
      activeConfigMode === "cookbook-cards"
        ? activeCookbookItems.length
        : activeConfigMode === "tool-cards"
        ? activeToolItems.length
        : activeConfigMode === "label-cards"
        ? activeLabelItems.length
        : activeConfigMode === "unit-cards"
        ? activeUnitItems.length
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

                  {(cookbookDraft.filterRows || []).map((row, rowIdx) => {
                    const fieldDef = FILTER_FIELDS.find((f) => f.key === row.field);
                    const hasDropdown = Boolean(availableFilterOptions[row.field]);
                    const valueOptions = hasDropdown
                      ? (availableFilterOptions[row.field] || []).filter((v) => !(row.values || []).includes(v))
                      : [];
                    return (
                      <div key={rowIdx} className="filter-row">
                        <select
                          value={row.field}
                          onChange={(event) => {
                            setCookbookDraft((prev) => {
                              const next = [...(prev.filterRows || [])];
                              next[rowIdx] = { ...next[rowIdx], field: event.target.value, values: [] };
                              return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                            });
                          }}
                        >
                          {FILTER_FIELDS.map((f) => (
                            <option key={f.key} value={f.key}>{f.label}</option>
                          ))}
                        </select>
                        <select
                          value={row.operator || "IN"}
                          onChange={(event) => {
                            setCookbookDraft((prev) => {
                              const next = [...(prev.filterRows || [])];
                              next[rowIdx] = { ...next[rowIdx], operator: event.target.value };
                              return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                            });
                          }}
                        >
                          {FILTER_OPERATORS.map((op) => (
                            <option key={op.value} value={op.value}>{op.label}</option>
                          ))}
                        </select>
                        <div className="filter-value-area">
                          {hasDropdown ? (
                            <select
                              value=""
                              onChange={(event) => {
                                const val = event.target.value;
                                if (!val) return;
                                setCookbookDraft((prev) => {
                                  const next = [...(prev.filterRows || [])];
                                  next[rowIdx] = { ...next[rowIdx], values: [...(next[rowIdx].values || []), val] };
                                  return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                                });
                              }}
                            >
                              <option value="">Select {fieldDef?.label.toLowerCase() || "value"}...</option>
                              {valueOptions.map((opt) => (
                                <option key={opt} value={opt}>{opt}</option>
                              ))}
                            </select>
                          ) : (
                            <input
                              type="text"
                              placeholder={`Type name, press Enter`}
                              onKeyDown={(event) => {
                                if (event.key !== "Enter") return;
                                event.preventDefault();
                                const val = event.target.value.trim();
                                if (!val || (row.values || []).includes(val)) return;
                                event.target.value = "";
                                setCookbookDraft((prev) => {
                                  const next = [...(prev.filterRows || [])];
                                  next[rowIdx] = { ...next[rowIdx], values: [...(next[rowIdx].values || []), val] };
                                  return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                                });
                              }}
                            />
                          )}
                          {(row.values || []).length > 0 && (
                            <div className="filter-chips">
                              {row.values.map((val) => (
                                <span key={val} className="filter-chip">
                                  {val}
                                  <button
                                    type="button"
                                    className="chip-remove"
                                    onClick={() => {
                                      setCookbookDraft((prev) => {
                                        const next = [...(prev.filterRows || [])];
                                        next[rowIdx] = { ...next[rowIdx], values: (next[rowIdx].values || []).filter((v) => v !== val) };
                                        return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
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
                        <button
                          type="button"
                          className="ghost filter-remove-btn"
                          onClick={() => {
                            setCookbookDraft((prev) => {
                              const next = (prev.filterRows || []).filter((_, i) => i !== rowIdx);
                              return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                            });
                          }}
                        >
                          <Icon name="x" />
                        </button>
                      </div>
                    );
                  })}
                  <button
                    type="button"
                    className="ghost filter-add-btn"
                    onClick={() => {
                      setCookbookDraft((prev) => {
                        const usedFields = (prev.filterRows || []).map((r) => r.field);
                        const nextField = FILTER_FIELDS.find((f) => !usedFields.includes(f.key))?.key || "categories";
                        const next = [...(prev.filterRows || []), { field: nextField, operator: "IN", values: [] }];
                        return { ...prev, filterRows: next };
                      });
                    }}
                  >
                    + Add Filter
                  </button>

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

                        {(item.filterRows || []).map((row, rowIdx) => {
                          const fieldDef = FILTER_FIELDS.find((f) => f.key === row.field);
                          const hasDropdown = Boolean(availableFilterOptions[row.field]);
                          const valueOptions = hasDropdown
                            ? (availableFilterOptions[row.field] || []).filter((v) => !(row.values || []).includes(v))
                            : [];
                          return (
                            <div key={rowIdx} className="filter-row">
                              <select
                                value={row.field}
                                onChange={(event) => {
                                  const next = [...(item.filterRows || [])];
                                  next[rowIdx] = { ...next[rowIdx], field: event.target.value, values: [] };
                                  updateCookbookFilterRows(index, next);
                                }}
                              >
                                {FILTER_FIELDS.map((f) => (
                                  <option key={f.key} value={f.key}>{f.label}</option>
                                ))}
                              </select>
                              <select
                                value={row.operator || "IN"}
                                onChange={(event) => {
                                  const next = [...(item.filterRows || [])];
                                  next[rowIdx] = { ...next[rowIdx], operator: event.target.value };
                                  updateCookbookFilterRows(index, next);
                                }}
                              >
                                {FILTER_OPERATORS.map((op) => (
                                  <option key={op.value} value={op.value}>{op.label}</option>
                                ))}
                              </select>
                              <div className="filter-value-area">
                                {hasDropdown ? (
                                  <select
                                    value=""
                                    onChange={(event) => {
                                      const val = event.target.value;
                                      if (!val) return;
                                      const next = [...(item.filterRows || [])];
                                      next[rowIdx] = { ...next[rowIdx], values: [...(next[rowIdx].values || []), val] };
                                      updateCookbookFilterRows(index, next);
                                    }}
                                  >
                                    <option value="">Select {fieldDef?.label.toLowerCase() || "value"}...</option>
                                    {valueOptions.map((opt) => (
                                      <option key={opt} value={opt}>{opt}</option>
                                    ))}
                                  </select>
                                ) : (
                                  <input
                                    type="text"
                                    placeholder="Type name, press Enter"
                                    onKeyDown={(event) => {
                                      if (event.key !== "Enter") return;
                                      event.preventDefault();
                                      const val = event.target.value.trim();
                                      if (!val || (row.values || []).includes(val)) return;
                                      event.target.value = "";
                                      const next = [...(item.filterRows || [])];
                                      next[rowIdx] = { ...next[rowIdx], values: [...(next[rowIdx].values || []), val] };
                                      updateCookbookFilterRows(index, next);
                                    }}
                                  />
                                )}
                                {(row.values || []).length > 0 && (
                                  <div className="filter-chips">
                                    {row.values.map((val) => (
                                      <span key={val} className="filter-chip">
                                        {val}
                                        <button
                                          type="button"
                                          className="chip-remove"
                                          onClick={() => {
                                            const next = [...(item.filterRows || [])];
                                            next[rowIdx] = { ...next[rowIdx], values: (next[rowIdx].values || []).filter((v) => v !== val) };
                                            updateCookbookFilterRows(index, next);
                                          }}
                                        >
                                          <Icon name="x" />
                                        </button>
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                              <button
                                type="button"
                                className="ghost filter-remove-btn"
                                onClick={() => {
                                  const next = (item.filterRows || []).filter((_, i) => i !== rowIdx);
                                  updateCookbookFilterRows(index, next);
                                }}
                              >
                                <Icon name="x" />
                              </button>
                            </div>
                          );
                        })}
                        <button
                          type="button"
                          className="ghost filter-add-btn"
                          onClick={() => {
                            const usedFields = (item.filterRows || []).map((r) => r.field);
                            const nextField = FILTER_FIELDS.find((f) => !usedFields.includes(f.key))?.key || "categories";
                            const next = [...(item.filterRows || []), { field: nextField, operator: "IN", values: [] }];
                            updateCookbookFilterRows(index, next);
                          }}
                        >
                          + Add Filter
                        </button>

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
          ) : activeConfigMode === "tool-cards" ? (
            <section className="structured-editor">
              <li className="structured-item">
                <div className="structured-item-grid tool-fields">
                  <label className="field">
                    <span>Name</span>
                    <input
                      value={toolDraft.name}
                      placeholder="Air Fryer"
                      onChange={(e) => setToolDraft((prev) => ({ ...prev, name: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addToolEntry(); } }}
                    />
                  </label>
                  <label className="field-inline">
                    <input
                      type="checkbox"
                      checked={toolDraft.onHand}
                      onChange={(e) => setToolDraft((prev) => ({ ...prev, onHand: e.target.checked }))}
                    />
                    <span>On Hand</span>
                  </label>
                </div>
                <div className="line-actions">
                  <button className="ghost" type="button" onClick={addToolEntry}>
                    <Icon name="plus" /> Add Tool
                  </button>
                </div>
              </li>
              <ul className="structured-list">
                {activeToolItems.map((item, index) => (
                  <li key={`tool-${index}`} className="structured-item">
                    <div className="structured-item-grid tool-fields">
                      <label className="field">
                        <span>Name</span>
                        <input
                          value={item.name}
                          onChange={(e) => updateToolEntry(index, "name", e.target.value)}
                          placeholder="Air Fryer"
                        />
                      </label>
                      <label className="field-inline">
                        <input
                          type="checkbox"
                          checked={item.onHand}
                          onChange={(e) => updateToolEntry(index, "onHand", e.target.checked)}
                        />
                        <span>On Hand</span>
                      </label>
                    </div>
                    <div className="line-actions">
                      <button type="button" className="ghost small" onClick={() => moveToolEntry(index, Math.max(index - 1, 0))} disabled={index === 0}>Up</button>
                      <button type="button" className="ghost small" onClick={() => moveToolEntry(index, Math.min(index + 1, activeToolItems.length - 1))} disabled={index === activeToolItems.length - 1}>Down</button>
                      <button type="button" className="ghost small" onClick={() => removeToolEntry(index)}>Remove</button>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="muted tiny">Define kitchen tools. Check "On Hand" for tools you own.</p>
            </section>
          ) : activeConfigMode === "label-cards" ? (
            <section className="structured-editor">
              <li className="structured-item">
                <div className="structured-item-grid label-fields">
                  <label className="field">
                    <span>Name</span>
                    <input
                      value={labelDraft.name}
                      placeholder="Meal Prep"
                      onChange={(e) => setLabelDraft((prev) => ({ ...prev, name: e.target.value }))}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLabelEntry(); } }}
                    />
                  </label>
                  <label className="field">
                    <span>Color</span>
                    <div className="color-field">
                      <input
                        type="color"
                        value={labelDraft.color}
                        onChange={(e) => setLabelDraft((prev) => ({ ...prev, color: e.target.value }))}
                      />
                      <input
                        type="text"
                        value={labelDraft.color}
                        onChange={(e) => setLabelDraft((prev) => ({ ...prev, color: e.target.value }))}
                        placeholder="#959595"
                        className="color-hex"
                      />
                    </div>
                  </label>
                </div>
                <div className="line-actions">
                  <button className="ghost" type="button" onClick={addLabelEntry}>
                    <Icon name="plus" /> Add Label
                  </button>
                </div>
              </li>
              <ul className="structured-list">
                {activeLabelItems.map((item, index) => (
                  <li key={`label-${index}`} className="structured-item">
                    <div className="structured-item-grid label-fields">
                      <label className="field">
                        <span>Name</span>
                        <input
                          value={item.name}
                          onChange={(e) => updateLabelEntry(index, "name", e.target.value)}
                          placeholder="Meal Prep"
                        />
                      </label>
                      <label className="field">
                        <span>Color</span>
                        <div className="color-field">
                          <input
                            type="color"
                            value={item.color || "#959595"}
                            onChange={(e) => updateLabelEntry(index, "color", e.target.value)}
                          />
                          <input
                            type="text"
                            value={item.color || "#959595"}
                            onChange={(e) => updateLabelEntry(index, "color", e.target.value)}
                            placeholder="#959595"
                            className="color-hex"
                          />
                        </div>
                      </label>
                    </div>
                    <div className="line-actions">
                      <button type="button" className="ghost small" onClick={() => moveLabelEntry(index, Math.max(index - 1, 0))} disabled={index === 0}>Up</button>
                      <button type="button" className="ghost small" onClick={() => moveLabelEntry(index, Math.min(index + 1, activeLabelItems.length - 1))} disabled={index === activeLabelItems.length - 1}>Down</button>
                      <button type="button" className="ghost small" onClick={() => removeLabelEntry(index)}>Remove</button>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="muted tiny">Define labels with colors for organizing recipes and shopping lists.</p>
            </section>
          ) : activeConfigMode === "unit-cards" ? (
            <section className="structured-editor">
              <li className="structured-item">
                <div className="structured-item-grid unit-fields">
                  <label className="field">
                    <span>Name</span>
                    <input value={unitDraft.name} placeholder="Teaspoon" onChange={(e) => setUnitDraft((prev) => ({ ...prev, name: e.target.value }))} />
                  </label>
                  <label className="field">
                    <span>Plural Name</span>
                    <input value={unitDraft.pluralName} placeholder="Teaspoons" onChange={(e) => setUnitDraft((prev) => ({ ...prev, pluralName: e.target.value }))} />
                  </label>
                  <label className="field">
                    <span>Abbreviation</span>
                    <input value={unitDraft.abbreviation} placeholder="tsp" onChange={(e) => setUnitDraft((prev) => ({ ...prev, abbreviation: e.target.value }))} />
                  </label>
                  <label className="field">
                    <span>Plural Abbreviation</span>
                    <input value={unitDraft.pluralAbbreviation} placeholder="tsps" onChange={(e) => setUnitDraft((prev) => ({ ...prev, pluralAbbreviation: e.target.value }))} />
                  </label>
                  <label className="field" style={{ gridColumn: "1 / -1" }}>
                    <span>Description</span>
                    <input value={unitDraft.description} placeholder="Optional description" onChange={(e) => setUnitDraft((prev) => ({ ...prev, description: e.target.value }))} />
                  </label>
                  <label className="field" style={{ gridColumn: "1 / -1" }}>
                    <span>Aliases (comma separated)</span>
                    <input value={unitDraft.aliases.join(", ")} placeholder="t, tsp, tsp." onChange={(e) => setUnitDraft((prev) => ({ ...prev, aliases: e.target.value }))} />
                  </label>
                  <label className="field-inline">
                    <input type="checkbox" checked={unitDraft.fraction} onChange={(e) => setUnitDraft((prev) => ({ ...prev, fraction: e.target.checked }))} />
                    <span>Display as Fraction</span>
                  </label>
                  <label className="field-inline">
                    <input type="checkbox" checked={unitDraft.useAbbreviation} onChange={(e) => setUnitDraft((prev) => ({ ...prev, useAbbreviation: e.target.checked }))} />
                    <span>Use Abbreviation</span>
                  </label>
                </div>
                <div className="line-actions">
                  <button className="ghost" type="button" onClick={addUnitEntry}>
                    <Icon name="plus" /> Add Unit
                  </button>
                </div>
              </li>
              <ul className="structured-list">
                {activeUnitItems.map((item, index) => (
                  <li key={`unit-${index}`} className="structured-item">
                    <div className="structured-item-grid unit-fields">
                      <label className="field">
                        <span>Name</span>
                        <input value={item.name} onChange={(e) => updateUnitEntry(index, "name", e.target.value)} placeholder="Teaspoon" />
                      </label>
                      <label className="field">
                        <span>Plural Name</span>
                        <input value={item.pluralName} onChange={(e) => updateUnitEntry(index, "pluralName", e.target.value)} placeholder="Teaspoons" />
                      </label>
                      <label className="field">
                        <span>Abbreviation</span>
                        <input value={item.abbreviation} onChange={(e) => updateUnitEntry(index, "abbreviation", e.target.value)} placeholder="tsp" />
                      </label>
                      <label className="field">
                        <span>Plural Abbreviation</span>
                        <input value={item.pluralAbbreviation} onChange={(e) => updateUnitEntry(index, "pluralAbbreviation", e.target.value)} placeholder="tsps" />
                      </label>
                      <label className="field" style={{ gridColumn: "1 / -1" }}>
                        <span>Description</span>
                        <input value={item.description} onChange={(e) => updateUnitEntry(index, "description", e.target.value)} placeholder="Optional description" />
                      </label>
                      <label className="field" style={{ gridColumn: "1 / -1" }}>
                        <span>Aliases (comma separated)</span>
                        <input
                          value={item.aliases.join(", ")}
                          onChange={(e) => updateUnitEntry(index, "aliases", e.target.value)}
                          placeholder="t, tsp, tsp."
                        />
                      </label>
                      <label className="field-inline">
                        <input type="checkbox" checked={item.fraction} onChange={(e) => updateUnitEntry(index, "fraction", e.target.checked)} />
                        <span>Display as Fraction</span>
                      </label>
                      <label className="field-inline">
                        <input type="checkbox" checked={item.useAbbreviation} onChange={(e) => updateUnitEntry(index, "useAbbreviation", e.target.checked)} />
                        <span>Use Abbreviation</span>
                      </label>
                    </div>
                    <div className="line-actions">
                      <button type="button" className="ghost small" onClick={() => moveUnitEntry(index, Math.max(index - 1, 0))} disabled={index === 0}>Up</button>
                      <button type="button" className="ghost small" onClick={() => moveUnitEntry(index, Math.min(index + 1, activeUnitItems.length - 1))} disabled={index === activeUnitItems.length - 1}>Down</button>
                      <button type="button" className="ghost small" onClick={() => removeUnitEntry(index)}>Remove</button>
                    </div>
                  </li>
                ))}
              </ul>
              <p className="muted tiny">Define ingredient units with abbreviations and aliases for recipe parsing.</p>
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
            <h3><Icon name="refresh" /> Managed Taxonomy Baseline</h3>
            <p className="muted">
              Recipe Organization edits managed taxonomy files. This does not change Mealie until you run
              <strong> taxonomy-refresh </strong>
              and
              <strong> cookbook-sync</strong>.
            </p>

            <label className="field">
              <span>Initialize from Mealie</span>
              <select value={taxonomyBootstrapMode} onChange={(event) => setTaxonomyBootstrapMode(event.target.value)}>
                <option value="replace">Replace managed files with current Mealie</option>
                <option value="merge">Merge current Mealie into managed files</option>
              </select>
            </label>
            <button
              className="primary"
              type="button"
              onClick={initializeFromMealieBaseline}
              disabled={taxonomyActionLoading === "mealie"}
            >
              <Icon name="download" />
              {taxonomyActionLoading === "mealie" ? "Initializing..." : "Initialize from Mealie"}
            </button>

            <hr />

            <label className="field">
              <span>Starter Pack Import Mode</span>
              <select value={starterPackMode} onChange={(event) => setStarterPackMode(event.target.value)}>
                <option value="merge">Merge starter pack into managed files</option>
                <option value="replace">Replace managed files with starter pack</option>
              </select>
            </label>
            <button
              className="ghost"
              type="button"
              onClick={importStarterPack}
              disabled={taxonomyActionLoading === "starter-pack"}
            >
              <Icon name="upload" />
              {taxonomyActionLoading === "starter-pack" ? "Importing..." : "Import Starter Pack"}
            </button>
            <p className="muted tiny">
              Recommended for existing Mealie libraries: initialize from Mealie first, then import starter pack in merge mode.
            </p>
          </article>

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

            <label className="field checkbox-field">
              <input
                type="checkbox"
                checked={newUserForceReset}
                onChange={(e) => setNewUserForceReset(e.target.checked)}
              />
              <span>Force password reset on first login</span>
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
                          {item.force_password_reset && <span className="status-pill warning" title="Must reset password on next login">Reset pending</span>}
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
                        <label className="field checkbox-field" style={{ marginTop: "0.5rem" }}>
                          <input
                            type="checkbox"
                            checked={resetForceResets[item.username] ?? false}
                            onChange={(e) =>
                              setResetForceResets((prev) => ({ ...prev, [item.username]: e.target.checked }))
                            }
                          />
                          <span>Force password reset on next login</span>
                        </label>
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
            <h3>Quick Guides</h3>
            <p className="muted">How to find the credentials and keys CookDex needs.</p>

            <div className="accordion-stack">
              {HELP_SETUP_GUIDES.map((guide) => (
                <details className="accordion" key={guide.id}>
                  <summary>
                    <Icon name={guide.icon || "info"} />
                    <span>{guide.title}</span>
                    <Icon name="chevron" />
                  </summary>
                  <div className="doc-preview">
                    <p style={{ fontSize: "0.82rem", marginBottom: "0.5rem" }}>{guide.what}</p>
                    <ol style={{ margin: "0 0 0.6rem", paddingLeft: "1.2rem" }}>
                      {guide.steps.map((step, i) => (
                        <li key={i} className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.25rem" }}>{step}</li>
                      ))}
                    </ol>
                    {guide.tip && (
                      <p className="muted" style={{ fontSize: "0.8rem", borderLeft: "3px solid var(--accent)", paddingLeft: "0.6rem", margin: 0 }}>
                        <strong>Tip:</strong> {guide.tip}
                      </p>
                    )}
                  </div>
                </details>
              ))}
            </div>
          </article>

          <article className="card">
            <h3>Task Guides</h3>
            <p className="muted">Step-by-step instructions for every available task.</p>

            <div className="accordion-stack">
              {(() => {
                let lastGroup = null;
                return HELP_TASK_GUIDES.flatMap((guide) => {
                  const items = [];
                  if (guide.group !== lastGroup) {
                    lastGroup = guide.group;
                    items.push(
                      <p key={`group-${guide.group}`} className="accordion-group-label">
                        {guide.group}
                      </p>
                    );
                  }
                  items.push(
                    <details className="accordion" key={guide.id}>
                      <summary>
                        <Icon name={guide.icon || "play"} />
                        <span>{guide.title}</span>
                        <Icon name="chevron" />
                      </summary>
                      <div className="doc-preview">
                        <p style={{ fontSize: "0.82rem", marginBottom: "0.5rem" }}>{guide.what}</p>
                        <ol style={{ margin: "0 0 0.6rem", paddingLeft: "1.2rem" }}>
                          {guide.steps.map((step, i) => (
                            <li key={i} className="muted" style={{ fontSize: "0.82rem", marginBottom: "0.25rem" }}>{step}</li>
                          ))}
                        </ol>
                        {guide.tip && (
                          <p className="muted" style={{ fontSize: "0.8rem", borderLeft: "3px solid var(--accent)", paddingLeft: "0.6rem", margin: 0 }}>
                            <strong>Tip:</strong> {guide.tip}
                          </p>
                        )}
                      </div>
                    </details>
                  );
                  return items;
                });
              })()}
            </div>
          </article>

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
        </div>

        <aside className="stacked-cards">
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

          <article className="card">
            <h3>Report a Bug</h3>
            <p className="muted">Collect debug logs and open a GitHub issue to help the developer reproduce and fix problems.</p>

            <div className="debug-actions">
              <a
                className="button ghost"
                href={(aboutMeta?.links?.github || "https://github.com/thekannen/cookdex") + "/issues/new"}
                target="_blank"
                rel="noreferrer"
              >
                <Icon name="external" /> Open a GitHub Issue
              </a>

              {!debugLog ? (
                <button className="ghost" type="button" onClick={fetchDebugLog} disabled={debugLogLoading}>
                  <Icon name={debugLogLoading ? "refresh" : "list"} />
                  {debugLogLoading ? "Generating…" : "Generate Debug Log"}
                </button>
              ) : (
                <>
                  {debugLog.error ? (
                    <p className="muted tiny" style={{ color: "var(--error, #c0392b)" }}>{debugLog.error}</p>
                  ) : (() => {
                    const h = debugLog.health || {};
                    const db = h.db || {};
                    const cfg = h.config || {};
                    const conns = h.connections || {};
                    const runs = h.runs || {};
                    const sc = h.scheduler || {};
                    const counts = runs.status_counts || {};
                    const ConnRow = ({ label, conn, detail }) => (
                      <div className="debug-health-row">
                        <span className="muted tiny">{label}</span>
                        <span className={`status-pill ${conn?.ok ? "success" : conn?.detail === "Not configured" ? "neutral" : "danger"}`}
                          title={conn?.detail || ""}>
                          {conn?.ok ? "OK" : conn?.detail === "Not configured" ? "Not configured" : "Failed"}
                        </span>
                      </div>
                    );
                    return (
                      <>
                        <div className="debug-health-grid">
                          <div className="debug-health-row">
                            <span className="muted tiny">Scheduler</span>
                            <span className={`status-pill ${sc.running ? "success" : "danger"}`}>{sc.running ? "Running" : "Stopped"}</span>
                          </div>
                          <ConnRow label="Mealie" conn={conns.mealie} />
                          <ConnRow label="OpenAI" conn={conns.openai} />
                          <ConnRow label="Ollama" conn={conns.ollama} />
                          <ConnRow label="Direct DB" conn={conns.direct_db} />
                          <div className="debug-health-row">
                            <span className="muted tiny">Runs</span>
                            <span className="muted tiny">
                              {db.run_count ?? 0} total
                              {counts.failed ? <span style={{ color: "var(--error, #c0392b)", marginLeft: "0.4rem" }}>{counts.failed} failed</span> : null}
                            </span>
                          </div>
                          <div className="debug-health-row">
                            <span className="muted tiny">Schedules</span>
                            <span className="muted tiny">{db.enabled_schedules ?? 0} of {db.schedule_count ?? 0} enabled</span>
                          </div>
                        </div>
                        {!debugLog.log_available ? (
                          <p className="muted tiny">No server log file found yet — logs appear after the first server restart.</p>
                        ) : (
                          <pre className="debug-log-preview">{debugLog.log}</pre>
                        )}
                      </>
                    );
                  })()}
                  <div className="debug-log-row">
                    <button className="ghost small" type="button" onClick={downloadDebugLog}>
                      <Icon name="download" /> Download Report
                    </button>
                    <button className="ghost small" type="button" onClick={() => setDebugLog(null)}>
                      <Icon name="refresh" /> Regenerate
                    </button>
                  </div>
                  {debugLog.app_version && (
                    <p className="muted tiny">v{debugLog.app_version} · {debugLog.platform}</p>
                  )}
                </>
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
                <strong>AGPL-3.0</strong>
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
              className="link-btn sponsor-btn"
              href={aboutMeta?.links?.sponsor || "https://github.com/sponsors/thekannen"}
              target="_blank"
              rel="noreferrer"
            >
              <svg className="ui-icon" viewBox="0 0 16 16" fill="#db61a2" aria-hidden="true">
                <path d="m8 14.25.345.666a.75.75 0 0 1-.69 0l-.008-.004-.018-.01a7.152 7.152 0 0 1-.31-.17 22.055 22.055 0 0 1-3.434-2.414C2.045 10.731 0 8.35 0 5.5 0 2.836 2.086 1 4.25 1 5.797 1 7.153 1.802 8 3.02 8.847 1.802 10.203 1 11.75 1 13.914 1 16 2.836 16 5.5c0 2.85-2.045 5.231-3.885 6.818a22.066 22.066 0 0 1-3.744 2.584l-.018.01-.006.003h-.002Z" />
              </svg>
              Sponsor
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
            <label className="field">
              <span>Confirm Password</span>
              <input
                type="password"
                value={registerPasswordConfirm}
                onChange={(event) => setRegisterPasswordConfirm(event.target.value)}
                placeholder="Re-enter password"
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

      {forcedResetPending && (
        <div className="modal-backdrop">
          <div className="modal-card forced-reset-card" onClick={(e) => e.stopPropagation()}>
            <h3>Password Reset Required</h3>
            <p className="muted">Your password was set by an administrator. Choose a new password before continuing.</p>
            <form className="run-form" onSubmit={doForcedReset}>
              <label className="field">
                <span>New Password</span>
                <div className="password-row">
                  <input
                    type={forcedResetShowPass ? "text" : "password"}
                    value={forcedResetPassword}
                    onChange={(e) => setForcedResetPassword(e.target.value)}
                    placeholder="At least 8 characters"
                    autoFocus
                  />
                  <button type="button" className="ghost icon-btn" onClick={() => setForcedResetShowPass((v) => !v)} title={forcedResetShowPass ? "Hide" : "Show"}>
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

