import React from "react";
import {
  differenceInHours,
  differenceInMilliseconds,
  differenceInMinutes,
  isSameDay,
  isValid,
  parseISO,
} from "date-fns";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { API } from "./constants";

export function safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

export function normalizeErrorMessage(raw) {
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

export function buildDefaultOptionValues(taskDefinition) {
  const values = {};
  for (const option of taskDefinition?.options || []) {
    if (option.multi) {
      values[option.key] = [];
    } else if (option.default !== undefined && option.default !== null) {
      values[option.key] = option.default;
    }
  }
  return values;
}

export function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function parseAliasInput(raw) {
  return String(raw || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function normalizeCookbookEntries(content) {
  if (!Array.isArray(content)) {
    return [];
  }
  return content
    .filter((item) => isPlainObject(item) && typeof item.name === "string")
    .map((item, index) => {
      const parsedPosition = Number.parseInt(String(item.position ?? index + 1), 10);
      return {
        name: String(item.name || "").trim(),
        description: String(item.description || "").trim(),
        queryFilterString: String(item.queryFilterString || "").trim(),
        public: Boolean(item.public),
        position: Number.isFinite(parsedPosition) && parsedPosition > 0 ? parsedPosition : index + 1,
      };
    })
    .filter((item) => item.name);
}

export function normalizeUnitEntries(content) {
  if (!Array.isArray(content)) return [];
  return content
    .filter((item) => isPlainObject(item) && (typeof item.name === "string" || typeof item.canonical === "string"))
    .map((item) => {
      const aliases = Array.isArray(item.aliases)
        ? item.aliases.map((a) => String(a).trim()).filter(Boolean)
        : parseAliasInput(item.aliases);
      return {
        name: String(item.name || item.canonical || "").trim(),
        pluralName: String(item.pluralName || "").trim(),
        abbreviation: String(item.abbreviation || "").trim(),
        pluralAbbreviation: String(item.pluralAbbreviation || "").trim(),
        description: String(item.description || "").trim(),
        fraction: item.fraction !== undefined ? Boolean(item.fraction) : true,
        useAbbreviation: Boolean(item.useAbbreviation),
        aliases,
      };
    })
    .filter((item) => item.name);
}

export function normalizeToolEntries(content) {
  if (!Array.isArray(content)) return [];
  return content
    .map((item) => {
      if (typeof item === "string") return { name: item.trim(), onHand: false };
      if (isPlainObject(item) && typeof item.name === "string")
        return { name: String(item.name).trim(), onHand: Boolean(item.onHand) };
      return null;
    })
    .filter((item) => item && item.name);
}

export function normalizeLabelEntries(content) {
  if (!Array.isArray(content)) return [];
  return content
    .map((item) => {
      if (typeof item === "string") return { name: item.trim(), color: "#959595" };
      if (isPlainObject(item) && typeof item.name === "string")
        return { name: String(item.name).trim(), color: String(item.color || "#959595").trim() };
      return null;
    })
    .filter((item) => item && item.name);
}

export function parseLineEditorContent(content, configName = "") {
  if (!Array.isArray(content)) {
    return { mode: "json", listKind: "", items: [] };
  }

  const normalizedConfigName = String(configName || "").trim();

  // Tools: objects with onHand, or plain strings for tools config
  const isToolConfig = normalizedConfigName === "tools";
  if (isToolConfig) {
    return { mode: "tool-cards", listKind: "tool_object", items: normalizeToolEntries(content) };
  }

  // Labels: objects with color, or plain strings for labels config
  const isLabelConfig = normalizedConfigName === "labels";
  if (isLabelConfig) {
    return { mode: "label-cards", listKind: "label_object", items: normalizeLabelEntries(content) };
  }

  // Units: objects with name/pluralName/abbreviation/aliases
  const isUnitConfig = normalizedConfigName === "units_aliases";
  const hasUnitShape = content.some(
    (item) =>
      isPlainObject(item) &&
      (Object.prototype.hasOwnProperty.call(item, "aliases") ||
        Object.prototype.hasOwnProperty.call(item, "canonical") ||
        Object.prototype.hasOwnProperty.call(item, "abbreviation"))
  );
  if (hasUnitShape || isUnitConfig) {
    return { mode: "unit-cards", listKind: "unit_object", items: normalizeUnitEntries(content) };
  }

  // Cookbooks
  const allCookbookObjects = content.every((item) => isPlainObject(item) && typeof item.name === "string");
  const hasCookbookShape = content.some(
    (item) =>
      isPlainObject(item) &&
      (Object.prototype.hasOwnProperty.call(item, "queryFilterString") ||
        Object.prototype.hasOwnProperty.call(item, "public") ||
        Object.prototype.hasOwnProperty.call(item, "position"))
  );
  if (allCookbookObjects && (hasCookbookShape || normalizedConfigName === "cookbooks")) {
    return { mode: "cookbook-cards", listKind: "cookbook_object", items: normalizeCookbookEntries(content) };
  }

  // Plain strings
  const allStrings = content.every((item) => typeof item === "string");
  if (allStrings) {
    return { mode: "line-pills", listKind: "string", items: content.map((item) => String(item)) };
  }

  // Name-only objects
  const allNameObjects = content.every(
    (item) => isPlainObject(item) && typeof item.name === "string" && Object.keys(item).length === 1
  );
  if (allNameObjects) {
    return { mode: "line-pills", listKind: "name_object", items: content.map((item) => String(item.name)) };
  }

  return { mode: "json", listKind: "", items: [] };
}

const MARKDOWN_REMARK_PLUGINS = [remarkGfm];

function mergeClassNames(...classNames) {
  return classNames.filter(Boolean).join(" ") || undefined;
}

function MarkdownLink({ node, className, href, children, ...props }) {
  const linkProps = {
    ...props,
    href,
    target: "_blank",
    rel: "noreferrer noopener",
    className: mergeClassNames(className, "md-link"),
  };
  return <a {...linkProps}>{children}</a>;
}

function MarkdownCode({ node, className, children, ...props }) {
  const codeText = String(children ?? "");
  const isCodeBlock = Boolean(className) || codeText.endsWith("\n");
  return (
    <code {...props} className={mergeClassNames(className, isCodeBlock ? "" : "md-inline-code")}>
      {children}
    </code>
  );
}

function MarkdownPre({ node, className, children, ...props }) {
  return (
    <pre {...props} className={mergeClassNames(className, "doc-code")}>
      {children}
    </pre>
  );
}

function MarkdownTable({ node, className, children, ...props }) {
  return (
    <div className="md-table-wrap">
      <table {...props} className={mergeClassNames(className, "md-table")}>
        {children}
      </table>
    </div>
  );
}

function MarkdownImage({ node, src, alt }) {
  if (!src) return null;
  return (
    <a href={src} target="_blank" rel="noreferrer noopener" className="md-link">
      {alt || src}
    </a>
  );
}

function MarkdownH4({ node, children, ...props }) {
  return <h4 {...props}>{children}</h4>;
}

function MarkdownH5({ node, children, ...props }) {
  return <h5 {...props}>{children}</h5>;
}

const MARKDOWN_COMPONENTS = {
  a: MarkdownLink,
  code: MarkdownCode,
  pre: MarkdownPre,
  table: MarkdownTable,
  img: MarkdownImage,
  h1: MarkdownH4,
  h2: MarkdownH4,
  h3: MarkdownH5,
  h4: MarkdownH5,
  h5: MarkdownH5,
  h6: MarkdownH5,
};

export function renderMarkdownDocument(markdown) {
  const source = String(markdown || "")
    .replace(/\uFEFF/g, "")
    .replace(/\r/g, "")
    .trim();
  if (!source) {
    return <p className="muted tiny">No content available.</p>;
  }
  return (
    <ReactMarkdown remarkPlugins={MARKDOWN_REMARK_PLUGINS} components={MARKDOWN_COMPONENTS}>
      {source}
    </ReactMarkdown>
  );
}

export function moveArrayItem(items, fromIndex, toIndex) {
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

export function parseIso(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return null;
  }
  const parsed = parseISO(raw);
  if (isValid(parsed)) return parsed;
  const fallback = new Date(raw);
  return isValid(fallback) ? fallback : null;
}

export function formatDateTime(value) {
  const date = parseIso(value);
  if (!date) {
    return "-";
  }
  return date.toLocaleString();
}

export function formatDateTimeShort(value) {
  const date = parseIso(value);
  if (!date) return "-";
  const now = new Date();
  const timePart = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (isSameDay(date, now)) return timePart;
  return date.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + timePart;
}

export function formatDurationMs(ms) {
  const safe = Math.max(0, Math.floor(ms));
  const totalSeconds = Math.floor(safe / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(
    2,
    "0"
  )}`;
}

export function formatRunTime(run) {
  const started = parseIso(run.started_at);
  if (!started) {
    return "--:--:--";
  }
  const finished = parseIso(run.finished_at);
  if (!finished) {
    if (String(run.status || "").toLowerCase() === "running") {
      return formatDurationMs(differenceInMilliseconds(Date.now(), started));
    }
    return "--:--:--";
  }
  return formatDurationMs(differenceInMilliseconds(finished, started));
}

export function formatRelativeTime(isoString) {
  const date = parseIso(isoString);
  if (!date) return "";
  const now = Date.now();
  const diff = differenceInMilliseconds(now, date);
  if (diff < 0) return "just now";
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${differenceInMinutes(now, date)}m ago`;
  if (diff < 86400000) return `${differenceInHours(now, date)}h ago`;
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
  return `${Math.floor(diff / 604800000)}w ago`;
}

export function formatCountdown(isoString) {
  const date = parseIso(isoString);
  if (!date) return null;
  const diff = differenceInMilliseconds(date, Date.now());
  if (diff < 0) return "overdue";
  if (diff < 60000) return "< 1m";
  if (diff < 3600000) return `in ${Math.round(diff / 60000)}m`;
  if (diff < 86400000) {
    const h = Math.floor(diff / 3600000);
    const m = Math.round((diff % 3600000) / 60000);
    return `in ${h}h ${m}m`;
  }
  return `in ${Math.round(diff / 86400000)}d`;
}

export function runTypeLabel(run) {
  return run.schedule_id ? "Scheduled" : "Manual";
}

export function isOwnerRole(role) {
  return String(role || "").trim().toLowerCase() === "owner";
}

export function userRoleLabel(role) {
  return isOwnerRole(role) ? "Owner" : "Editor";
}

export function statusClass(status) {
  const value = String(status || "").toLowerCase();
  if (value === "succeeded") {
    return "success";
  }
  if (value === "running") {
    return "running";
  }
  if (value === "failed" || value === "canceled") {
    return "danger";
  }
  return "neutral";
}

function errorMessageFromPayload(payload, status) {
  if (payload && typeof payload === "object") {
    const detail = payload.detail ?? payload.message ?? payload.error;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      return detail.map((e) => e.msg || JSON.stringify(e)).join("; ");
    }
    return `Request failed (${status})`;
  }
  return `Request failed (${status})`;
}

// ETag cache: stores { etag, data } per GET path for 304 handling.
const _etagCache = new Map();

export async function api(path, options = {}) {
  const headers = { "X-Requested-With": "XMLHttpRequest", ...(options.headers || {}) };
  let body = options.body;
  const method = (options.method || "GET").toUpperCase();

  if (body && typeof body !== "string") {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }

  // Send If-None-Match for GET requests that have a cached ETag.
  if (method === "GET" && _etagCache.has(path)) {
    headers["If-None-Match"] = _etagCache.get(path).etag;
  }

  const externalSignal = options.signal;
  const timeoutMs = options.timeout ?? 30000;
  const controller = new AbortController();
  const timeoutId = timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", () => controller.abort(), { once: true });
    }
  }

  try {
    const response = await fetch(`${API}${path}`, {
      ...options,
      headers,
      body,
      credentials: "include",
      signal: controller.signal,
    });

    // 304 Not Modified — return cached data without parsing.
    if (response.status === 304 && _etagCache.has(path)) {
      return _etagCache.get(path).data;
    }

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

    // Cache ETag for future conditional requests.
    const etag = response.headers.get("etag");
    if (method === "GET" && etag) {
      const data = jsonPayload !== null ? jsonPayload : textPayload;
      _etagCache.set(path, { etag, data });
    }

    if (jsonPayload !== null) {
      return jsonPayload;
    }
    return textPayload;
  } finally {
    if (timeoutId !== null) clearTimeout(timeoutId);
  }
}

export function fieldFromOption(option, value, onChange, allValues = {}) {
  if (option.hidden) return null;
  if (option.hidden_when) {
    const conditions = Array.isArray(option.hidden_when) ? option.hidden_when : [option.hidden_when];
    if (conditions.some(({ key, value: trigger }) => allValues[key] === trigger)) return null;
  }

  const labelClass = option.dangerous ? "danger-text" : "";
  const hint = option.help_text ? (
    <p className="muted tiny" style={{ margin: 0 }}>{option.help_text}</p>
  ) : null;

  if (Array.isArray(option.choices) && option.choices.length > 0) {
    if (option.multi) {
      const selected = Array.isArray(value) ? value : [];
      const remove = (v) => onChange(option.key, selected.filter((x) => x !== v));
      const add = (v) => { if (v) onChange(option.key, [...selected, v]); };
      const remaining = option.choices.filter((c) => !selected.includes(c.value));
      return (
        <div key={option.key} className="chip-select tag-selector">
          <span className={labelClass} style={{ fontSize: "0.82rem", fontWeight: 600 }}>{option.label}</span>
          <div className="tag-selector-body">
            {selected.map((v) => {
              const choice = option.choices.find((c) => c.value === v);
              return (
                <span key={v} className="tag-item">
                  {choice?.label ?? v}
                  <button type="button" onClick={() => remove(v)} title={`Remove ${choice?.label ?? v}`}>×</button>
                </span>
              );
            })}
            {remaining.length > 0 && (
              <select className="tag-add" value="" onChange={(e) => add(e.target.value)}>
                <option value="">{selected.length === 0 ? "Add stages to limit pipeline…" : "Add stage…"}</option>
                {remaining.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            )}
          </div>
          {selected.length === 0 && (
            <p className="muted tiny" style={{ margin: 0 }}>All stages will run. Select stages above to run a subset.</p>
          )}
          {selected.length > 0 && hint}
        </div>
      );
    }
    return (
      <label key={option.key} className="field">
        <span className={labelClass}>{option.label}</span>
        <select
          value={value ?? ""}
          onChange={(event) => onChange(option.key, event.target.value)}
        >
          {option.choices.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
        {hint}
      </label>
    );
  }

  if (option.type === "boolean") {
    return (
      <div key={option.key} style={{ display: "grid", gap: "0.2rem" }}>
        <label className="field field-inline">
          <span className={labelClass}>{option.label}</span>
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => onChange(option.key, event.target.checked)}
          />
        </label>
        {hint}
      </div>
    );
  }

  if (option.type === "number") {
    return (
      <label key={option.key} className="field">
        <span className={labelClass}>{option.label}</span>
        <input
          type="number"
          value={value ?? ""}
          onChange={(event) => onChange(option.key, event.target.value)}
        />
        {hint}
      </label>
    );
  }

  if (option.type === "integer") {
    return (
      <label key={option.key} className="field">
        <span className={labelClass}>{option.label}</span>
        <input
          type="number"
          step="1"
          value={value ?? ""}
          onChange={(event) => onChange(option.key, event.target.value)}
        />
        {hint}
      </label>
    );
  }

  return (
    <label key={option.key} className="field">
      <span className={labelClass}>{option.label}</span>
      <input
        type="text"
        value={value ?? ""}
        onChange={(event) => onChange(option.key, event.target.value)}
      />
      {hint}
    </label>
  );
}

function parseFilterValueList(raw) {
  try {
    const parsed = JSON.parse(`[${raw}]`);
    return parsed.filter((v) => typeof v === "string" && v.trim()).map((v) => v.trim());
  } catch {
    return raw
      .split(",")
      .map((s) => s.trim().replace(/^["']|["']$/g, ""))
      .filter(Boolean);
  }
}

export const FILTER_FIELDS = [
  {
    key: "categories",
    label: "Categories",
    pattern: /^\s*(?:recipe_?[Cc]ategory|recipeCategory)\.(name|id)\s+/i,
    attrName: "recipeCategory.name",
    attrId: "recipeCategory.id",
  },
  {
    key: "tags",
    label: "Tags",
    pattern: /^\s*tags\.(name|id)\s+/i,
    attrName: "tags.name",
    attrId: "tags.id",
  },
  {
    key: "tools",
    label: "Tools",
    pattern: /^\s*tools\.(name|id)\s+/i,
    attrName: "tools.name",
    attrId: "tools.id",
  },
  {
    key: "foods",
    label: "Foods",
    pattern: /^\s*(?:recipe_?[Ii]ngredient|recipeIngredient)\.food\.(name|id)\s+/i,
    attrName: "recipeIngredient.food.name",
    attrId: "recipeIngredient.food.id",
  },
];

export const FILTER_OPERATORS = [
  { value: "IN", label: "is one of" },
  { value: "NOT IN", label: "is not one of" },
  { value: "CONTAINS ALL", label: "contains all of" },
];

function normalizeOperator(raw) {
  const upper = String(raw || "").trim().toUpperCase().replace(/\s+/g, " ");
  if (upper === "NOT IN") return "NOT IN";
  if (upper === "CONTAINS ALL") return "CONTAINS ALL";
  return "IN";
}

export function parseQueryFilter(queryFilterString) {
  const rows = [];
  const raw = String(queryFilterString || "").trim();
  if (!raw) return rows;

  const clauses = raw.split(/\s+AND\s+/i);
  for (const clause of clauses) {
    for (const { key, pattern } of FILTER_FIELDS) {
      const fieldMatch = clause.match(pattern);
      if (!fieldMatch) continue;
      const opMatch = clause.match(/\b(NOT\s+IN|CONTAINS\s+ALL|IN)\s*\[([^\]]*)\]/i);
      if (opMatch) {
        const identifier = String(fieldMatch[1] || "").trim().toLowerCase() === "id" ? "id" : "name";
        rows.push({
          field: key,
          operator: normalizeOperator(opMatch[1]),
          values: parseFilterValueList(opMatch[2]),
          identifier,
        });
      }
      break;
    }
  }
  return rows;
}

export function buildQueryFilter(filterRows) {
  if (!Array.isArray(filterRows)) return "";
  const clauses = [];
  for (const row of filterRows) {
    if (!row.values || row.values.length === 0) continue;
    const fieldDef = FILTER_FIELDS.find((f) => f.key === row.field);
    if (!fieldDef) continue;
    const identifier = String(row.identifier || "").trim().toLowerCase() === "id" ? "id" : "name";
    const attr = identifier === "id" ? fieldDef.attrId : fieldDef.attrName;
    if (!attr) continue;
    const list = row.values.map((v) => `"${v}"`).join(", ");
    clauses.push(`${attr} ${row.operator || "IN"} [${list}]`);
  }
  return clauses.join(" AND ");
}

export function normalizeTaskOptions(task, values) {
  const payload = {};
  for (const option of task?.options || []) {
    const raw = values[option.key];
    if (raw === undefined || raw === null || raw === "") {
      continue;
    }
    if (option.multi) {
      if (Array.isArray(raw) && raw.length > 0) {
        payload[option.key] = raw;
      }
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
