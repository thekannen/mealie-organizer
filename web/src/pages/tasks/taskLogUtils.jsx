import React from "react";
import Icon from "../../components/Icon";
import { buildDefaultOptionValues } from "../../utils.jsx";

// ─── Structured log parser ────────────────────────────────────────────────────
export const DATA_MAINTENANCE_STAGE_LABELS = {
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

export const SUMMARY_PIPELINE_KEYS = new Set(["Stages Run", "Passed", "Failed", "All Stages"]);
export const SCHEDULE_UNIT_SECONDS = { seconds: 1, minutes: 60, hours: 3600, days: 86400 };

export function splitIntervalSeconds(rawSeconds) {
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

export function toDateTimeLocalValue(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(raw)) return raw;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw.slice(0, 16);
  const localValue = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return localValue.toISOString().slice(0, 16);
}

export function localDatetimeToUTC(value) {
  const raw = String(value || "").trim();
  if (!raw) return undefined;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toISOString();
}

export function buildTaskOptionSeed(taskDefinition, existingOptions = {}) {
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

export function isTaskOptionVisible(option, values = {}, includeAdvanced = true) {
  if (!option || option.hidden) return false;
  if (!includeAdvanced && option.advanced) return false;
  if (!option.hidden_when) return true;
  const conds = Array.isArray(option.hidden_when) ? option.hidden_when : [option.hidden_when];
  return !conds.some(({ key, value: trigger }) => values[key] === trigger);
}

export function parseLogEvents(text) {
  const lines = text.split(/\r?\n/);
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

export function groupLogEvents(events) {
  const out = [];
  let i = 0;
  while (i < events.length) {
    if (events[i].type === "plan" || events[i].type === "ok") {
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

export function getSummaryEntries(data) {
  if (!data || typeof data !== "object") return [];
  return Object.entries(data).filter(([key, value]) => (
    key !== "__title__"
    && value !== null
    && value !== undefined
    && typeof value !== "object"
  ));
}

export function formatSummaryValue(value) {
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function isDataMaintenancePipelineSummary(data) {
  if (!data || typeof data !== "object") return false;
  return "Stages Run" in data;
}

export function summarizeExecutionEvents(events) {
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

export function buildStageResultSummary(stage, statusLabel) {
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

export function buildPipelineExecutionSummary(stages = []) {
  const summary = {
    stages_total: stages.length,
    stages_completed: stages.filter((item) => item.status === "succeeded").length,
    stages_failed: stages.filter((item) => item.status === "failed").length,
    stages_pending: stages.filter((item) => item.status === "pending").length,
    stages_running: stages.filter((item) => item.status === "running").length,
  };
  return summary;
}

export function renderSummaryTable(data, { title = "Run Summary", iconName = "check-circle", keyPrefix = "summary" } = {}) {
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

export function renderGroupedLogEvents(grouped, { isLive = false, keyPrefix = "evt", expandProgressDetails = false } = {}) {
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
      const summaryTitle = (evt.data && evt.data.__title__) || "Run Summary";
      return renderSummaryTable(evt.data, { title: summaryTitle, iconName: "check-circle", keyPrefix: `${eventKey}-summary` });
    }
    if (evt.type === "progress-batch") {
      const okItems = evt.items.filter((e) => e.type === "ok");
      const lastOk = okItems[okItems.length - 1];
      const total = lastOk ? lastOk.total : 0;
      const current = lastOk ? lastOk.current : 0;
      const pct = total > 0 ? Math.round((current / total) * 100) : 0;
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

export function stageDisplayName(stage) {
  return DATA_MAINTENANCE_STAGE_LABELS[stage] || stage;
}

export function buildDataMaintenanceView(events, isLive) {
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
