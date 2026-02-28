import React from "react";

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

export function renderInlineMarkdown(text, keyPrefix) {
  const source = String(text || "");
  if (!source) {
    return "";
  }

  const tokenPattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  const nodes = [];
  let lastIndex = 0;
  let matchIndex = 0;
  let match = tokenPattern.exec(source);

  while (match) {
    const token = String(match[0] || "");
    if (match.index > lastIndex) {
      nodes.push(source.slice(lastIndex, match.index));
    }

    if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(
        <code key={`${keyPrefix}-code-${matchIndex}`} className="md-inline-code">
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(<strong key={`${keyPrefix}-strong-${matchIndex}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*") && token.endsWith("*")) {
      nodes.push(<em key={`${keyPrefix}-em-${matchIndex}`}>{token.slice(1, -1)}</em>);
    } else if (token.startsWith("[") && token.includes("](") && token.endsWith(")")) {
      const splitIndex = token.indexOf("](");
      const label = token.slice(1, splitIndex);
      const href = token.slice(splitIndex + 2, -1);
      nodes.push(
        <a
          key={`${keyPrefix}-link-${matchIndex}`}
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          className="md-link"
        >
          {label}
        </a>
      );
    } else {
      nodes.push(token);
    }

    lastIndex = match.index + token.length;
    matchIndex += 1;
    match = tokenPattern.exec(source);
  }

  if (lastIndex < source.length) {
    nodes.push(source.slice(lastIndex));
  }

  return nodes;
}

function parseMarkdownBlocks(markdown) {
  const lines = String(markdown || "")
    .replace(/\uFEFF/g, "")
    .replace(/\r/g, "")
    .split("\n");
  const blocks = [];
  let index = 0;

  const isListItem = (line) => /^\s*[-*]\s+/.test(line);
  const isOrderedItem = (line) => /^\s*\d+\.\s+/.test(line);
  const isHeading = (line) => /^\s*#{1,6}\s+/.test(line);
  const isFence = (line) => /^\s*```/.test(line);
  const isTableRow = (line) => /^\s*\|.*\|\s*$/.test(line);
  const isTableDivider = (line) => {
    const trimmed = String(line || "").trim();
    if (!trimmed.includes("|")) return false;
    const cells = trimmed
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());
    if (cells.length < 2) return false;
    return cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  };
  const parseTableCells = (line) =>
    String(line || "")
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((cell) => cell.trim());

  while (index < lines.length) {
    const line = lines[index];

    if (isFence(line)) {
      const language = line.replace(/^\s*```/, "").trim();
      index += 1;
      const codeLines = [];
      while (index < lines.length && !isFence(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length && isFence(lines[index])) {
        index += 1;
      }
      blocks.push({ type: "code", language, text: codeLines.join("\n") });
      continue;
    }

    if (isHeading(line)) {
      const match = line.match(/^(\s*#{1,6})\s+(.+)$/);
      const rawLevel = match ? match[1].replace(/\s/g, "").length : 2;
      const level = Math.min(4, Math.max(2, rawLevel));
      blocks.push({ type: "heading", level, text: String(match ? match[2] : line).trim() });
      index += 1;
      continue;
    }

    if (isTableRow(line) && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const headers = parseTableCells(line);
      index += 2;
      const rows = [];
      while (index < lines.length && isTableRow(lines[index])) {
        const row = parseTableCells(lines[index]);
        if (row.some((cell) => cell.length > 0)) {
          rows.push(row);
        }
        index += 1;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    if (isListItem(line)) {
      const items = [];
      while (index < lines.length && isListItem(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, "").trim());
        index += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (isOrderedItem(line)) {
      const items = [];
      while (index < lines.length && isOrderedItem(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, "").trim());
        index += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    if (!line.trim()) {
      index += 1;
      continue;
    }

    const paragraph = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isFence(lines[index]) &&
      !isHeading(lines[index]) &&
      !isListItem(lines[index]) &&
      !isOrderedItem(lines[index]) &&
      !(isTableRow(lines[index]) && index + 1 < lines.length && isTableDivider(lines[index + 1]))
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join(" ") });
  }

  return blocks;
}

export function renderMarkdownDocument(markdown) {
  const blocks = parseMarkdownBlocks(markdown);
  if (blocks.length === 0) {
    return <p className="muted tiny">No content available.</p>;
  }
  return blocks.map((block, index) => {
    if (block.type === "heading") {
      if (block.level <= 2) {
        return <h4 key={`md-${index}`}>{renderInlineMarkdown(block.text, `md-${index}`)}</h4>;
      }
      return <h5 key={`md-${index}`}>{renderInlineMarkdown(block.text, `md-${index}`)}</h5>;
    }
    if (block.type === "code") {
      return (
        <pre key={`md-${index}`} className="doc-code">
          <code>{block.text}</code>
        </pre>
      );
    }
    if (block.type === "ul") {
      return (
        <ul key={`md-${index}`}>
          {block.items.map((item, itemIndex) => (
            <li key={`md-${index}-${itemIndex}`}>{renderInlineMarkdown(item, `md-${index}-${itemIndex}`)}</li>
          ))}
        </ul>
      );
    }
    if (block.type === "ol") {
      return (
        <ol key={`md-${index}`}>
          {block.items.map((item, itemIndex) => (
            <li key={`md-${index}-${itemIndex}`}>{renderInlineMarkdown(item, `md-${index}-${itemIndex}`)}</li>
          ))}
        </ol>
      );
    }
    if (block.type === "table") {
      const columnCount = Math.max(
        block.headers.length,
        ...block.rows.map((row) => (Array.isArray(row) ? row.length : 0))
      );
      const headerCells = Array.from({ length: columnCount }, (_, colIndex) => block.headers[colIndex] || "");
      return (
        <div key={`md-${index}`} className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>
                {headerCells.map((header, colIndex) => (
                  <th key={`md-${index}-h-${colIndex}`}>{renderInlineMarkdown(header, `md-${index}-h-${colIndex}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={`md-${index}-r-${rowIndex}`}>
                  {headerCells.map((_, colIndex) => (
                    <td key={`md-${index}-r-${rowIndex}-c-${colIndex}`}>
                      {renderInlineMarkdown(row[colIndex] || "", `md-${index}-r-${rowIndex}-c-${colIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return <p key={`md-${index}`}>{renderInlineMarkdown(block.text, `md-${index}`)}</p>;
  });
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
  if (!value) {
    return null;
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return date;
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
  const isToday =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  const timePart = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (isToday) return timePart;
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
      return formatDurationMs(Date.now() - started.getTime());
    }
    return "--:--:--";
  }
  return formatDurationMs(finished.getTime() - started.getTime());
}

export function runTypeLabel(run) {
  return run.schedule_id ? "Scheduled" : "Manual";
}

export function userRoleLabel(username, currentUsername) {
  return String(username || "") === String(currentUsername || "") ? "Owner" : "Editor";
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

export async function api(path, options = {}) {
  const headers = { "X-Requested-With": "XMLHttpRequest", ...(options.headers || {}) };
  let body = options.body;

  if (body && typeof body !== "string") {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
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
  { key: "categories", label: "Categories", pattern: /^\s*(?:recipe_?[Cc]ategory|recipeCategory)\.name\s+/i, attr: "recipeCategory.name" },
  { key: "tags", label: "Tags", pattern: /^\s*tags\.name\s+/i, attr: "tags.name" },
  { key: "tools", label: "Tools", pattern: /^\s*tools\.name\s+/i, attr: "tools.name" },
  { key: "foods", label: "Foods", pattern: /^\s*(?:recipe_?[Ii]ngredient|recipeIngredient)\.food\.name\s+/i, attr: "recipeIngredient.food.name" },
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
      if (!pattern.test(clause)) continue;
      const opMatch = clause.match(/\b(NOT\s+IN|CONTAINS\s+ALL|IN)\s*\[([^\]]*)\]/i);
      if (opMatch) {
        rows.push({
          field: key,
          operator: normalizeOperator(opMatch[1]),
          values: parseFilterValueList(opMatch[2]),
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
    const list = row.values.map((v) => `"${v}"`).join(", ");
    clauses.push(`${fieldDef.attr} ${row.operator || "IN"} [${list}]`);
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
