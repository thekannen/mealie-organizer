import React, { useEffect, useMemo, useState } from "react";

import Icon from "../../components/Icon";
import {
  api,
  buildQueryFilter,
  FILTER_FIELDS,
  FILTER_OPERATORS,
  moveArrayItem,
  normalizeErrorMessage,
  parseAliasInput,
  parseQueryFilter,
} from "../../utils.jsx";

const TAXONOMY_RESOURCES = ["categories", "tags", "labels", "tools", "units_aliases"];
const ALL_RESOURCES = [...TAXONOMY_RESOURCES, "cookbooks"];
const RESOURCE_LABELS = {
  categories: "Categories",
  tags: "Tags",
  labels: "Labels",
  tools: "Tools",
  units_aliases: "Units",
  cookbooks: "Cookbooks",
};
const TAB_ORDER = ["plan", "taxonomy", "cookbooks"];

function ensureDraftShape(rawDraft) {
  const source = rawDraft && typeof rawDraft === "object" ? rawDraft : {};
  const out = {};
  for (const name of ALL_RESOURCES) {
    out[name] = Array.isArray(source[name]) ? source[name] : [];
  }
  return out;
}

function equalJson(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

function defaultRow(resource) {
  if (resource === "labels") return { name: "", color: "#959595" };
  if (resource === "tools") return { name: "", onHand: false };
  if (resource === "units_aliases") return { name: "", aliases: [], fraction: true, useAbbreviation: false, abbreviation: "" };
  return { name: "" };
}

function defaultCookbookDraft() {
  return {
    name: "",
    description: "",
    queryFilterString: "",
    filterRows: [],
    public: false,
  };
}

function extractNameValue(item) {
  if (typeof item === "string") return item.trim();
  if (item && typeof item === "object") return String(item.name || "").trim();
  return "";
}

function parseCookbookPosition(value, fallback = 1) {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  const safeFallback = Number.parseInt(String(fallback ?? "").trim(), 10);
  return Number.isFinite(safeFallback) && safeFallback > 0 ? safeFallback : 1;
}

function getOrderedCookbookIndexes(cookbooks) {
  return cookbooks
    .map((_, index) => index)
    .sort((leftIndex, rightIndex) => {
      const left = cookbooks[leftIndex] || {};
      const right = cookbooks[rightIndex] || {};
      const leftPosition = parseCookbookPosition(left.position, leftIndex + 1);
      const rightPosition = parseCookbookPosition(right.position, rightIndex + 1);
      if (leftPosition !== rightPosition) return leftPosition - rightPosition;
      const leftName = String(left.name || "").trim();
      const rightName = String(right.name || "").trim();
      if (leftName !== rightName) return leftName.localeCompare(rightName);
      return leftIndex - rightIndex;
    });
}

function applyCookbookPositions(cookbooks, orderedIndexes) {
  for (const [position, cookbookIndex] of orderedIndexes.entries()) {
    const current = cookbooks[cookbookIndex] || {};
    cookbooks[cookbookIndex] = { ...current, position: position + 1 };
  }
}

function getNextCookbookPosition(cookbooks) {
  let maxPosition = 0;
  for (const [index, cookbook] of cookbooks.entries()) {
    const parsed = parseCookbookPosition(cookbook?.position, index + 1);
    if (parsed > maxPosition) maxPosition = parsed;
  }
  return maxPosition + 1;
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

export default function RecipeWorkspacePage({ onNotice, onError, onOpenTasks }) {
  const [tab, setTab] = useState("plan");
  const [resource, setResource] = useState("categories");
  const [snapshot, setSnapshot] = useState(null);
  const [draft, setDraft] = useState(ensureDraftShape({}));
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedRows, setSelectedRows] = useState(new Set());
  const [dragIndex, setDragIndex] = useState(null);
  const [validation, setValidation] = useState(null);
  const [publishResult, setPublishResult] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerResource, setDrawerResource] = useState("categories");
  const [drawerText, setDrawerText] = useState("[]\n");
  const [drawerError, setDrawerError] = useState("");
  const [cookbookSearch, setCookbookSearch] = useState("");
  const [cookbookDraft, setCookbookDraft] = useState(defaultCookbookDraft());
  const [dragCookbookIndex, setDragCookbookIndex] = useState(null);
  const [dragOverCookbookIndex, setDragOverCookbookIndex] = useState(null);
  const [expandedCookbooks, setExpandedCookbooks] = useState(() => new Set());
  const [lookupIdMaps, setLookupIdMaps] = useState({
    categories: {},
    tags: {},
    tools: {},
    foods: {},
  });

  const loadWorkspace = async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true);
    try {
      const payload = await api("/config/workspace/draft");
      setSnapshot(payload);
      setDraft(ensureDraftShape(payload?.draft));
      setSelectedRows(new Set());
      return payload;
    } catch (exc) {
      onError?.(exc);
      return null;
    } finally {
      if (!quiet) setLoading(false);
    }
  };

  const loadLookups = async () => {
    try {
      const payload = await api("/config/workspace/lookups", { timeout: 45000 });
      const toMap = (items) => {
        const out = {};
        for (const item of Array.isArray(items) ? items : []) {
          const id = String(item?.id || "").trim();
          const name = String(item?.name || "").trim();
          if (!id || !name) continue;
          out[id] = name;
        }
        return out;
      };
      setLookupIdMaps({
        categories: toMap(payload?.categories),
        tags: toMap(payload?.tags),
        tools: toMap(payload?.tools),
        foods: toMap(payload?.foods),
      });
    } catch {
      setLookupIdMaps({
        categories: {},
        tags: {},
        tools: {},
        foods: {},
      });
    }
  };

  useEffect(() => {
    loadWorkspace({ quiet: true });
    loadLookups();
  }, []);

  useEffect(() => {
    setSearch("");
    setSelectedRows(new Set());
  }, [resource]);

  const serverDraft = useMemo(() => ensureDraftShape(snapshot?.draft), [snapshot]);
  const dirtyResources = useMemo(() => {
    return ALL_RESOURCES.filter((name) => !equalJson(draft[name], serverDraft[name]));
  }, [draft, serverDraft]);
  const hasUnsavedChanges = dirtyResources.length > 0;

  const resourceItems = useMemo(() => Array.isArray(draft[resource]) ? draft[resource] : [], [draft, resource]);
  const filteredResourceIndexes = useMemo(() => {
    const query = search.trim().toLowerCase();
    return resourceItems
      .map((_, index) => index)
      .filter((index) => !query || JSON.stringify(resourceItems[index] || {}).toLowerCase().includes(query));
  }, [resourceItems, search]);
  const filteredSelectedCount = useMemo(
    () => filteredResourceIndexes.filter((index) => selectedRows.has(index)).length,
    [filteredResourceIndexes, selectedRows]
  );
  const allFilteredSelected = filteredResourceIndexes.length > 0 && filteredSelectedCount === filteredResourceIndexes.length;
  const taxonomyNameStats = useMemo(() => {
    const names = new Map();
    const duplicateNames = new Set();
    let missingNameCount = 0;
    for (const item of resourceItems) {
      const normalized = String(item?.name || "").trim().toLowerCase();
      if (!normalized) {
        missingNameCount += 1;
        continue;
      }
      const seen = names.get(normalized) || 0;
      names.set(normalized, seen + 1);
      if (seen >= 1) duplicateNames.add(normalized);
    }
    return { missingNameCount, duplicateNames };
  }, [resourceItems]);

  const cookbooks = useMemo(() => Array.isArray(draft.cookbooks) ? draft.cookbooks : [], [draft.cookbooks]);
  const orderedCookbookIndexes = useMemo(() => {
    return getOrderedCookbookIndexes(cookbooks);
  }, [cookbooks]);
  const cookbookOrderMap = useMemo(() => {
    const map = new Map();
    for (const [order, index] of orderedCookbookIndexes.entries()) map.set(index, order);
    return map;
  }, [orderedCookbookIndexes]);
  const filteredCookbookIndexes = useMemo(() => {
    const query = cookbookSearch.trim().toLowerCase();
    return orderedCookbookIndexes.filter((index) => {
      const item = cookbooks[index] || {};
      return !query || `${item.name || ""} ${item.description || ""} ${item.queryFilterString || ""}`.toLowerCase().includes(query);
    });
  }, [orderedCookbookIndexes, cookbooks, cookbookSearch]);
  const availableFilterOptions = useMemo(() => {
    const toOptions = (values) => (
      [...new Set(values)]
        .filter(Boolean)
        .map((value) => ({ value, label: value }))
    );
    const fromLookup = (field) => {
      const map = lookupIdMaps[field] || {};
      return Object.entries(map)
        .map(([value, label]) => ({ value, label: String(label) }))
        .sort((a, b) => a.label.localeCompare(b.label));
    };
    const pick = (field, fallbackValues) => {
      const lookup = fromLookup(field);
      return lookup.length > 0 ? lookup : toOptions(fallbackValues);
    };
    return {
      categories: pick("categories", (draft.categories || []).map(extractNameValue)),
      tags: pick("tags", (draft.tags || []).map(extractNameValue)),
      tools: pick("tools", (draft.tools || []).map(extractNameValue)),
    };
  }, [draft.categories, draft.tags, draft.tools, lookupIdMaps]);
  const nameFilterOptions = useMemo(() => {
    const toOptions = (values) => (
      [...new Set(values)]
        .filter(Boolean)
        .map((value) => ({ value, label: value }))
    );
    return {
      categories: toOptions((draft.categories || []).map(extractNameValue)),
      tags: toOptions((draft.tags || []).map(extractNameValue)),
      tools: toOptions((draft.tools || []).map(extractNameValue)),
    };
  }, [draft.categories, draft.tags, draft.tools]);

  const defaultFilterIdentifier = (field) => {
    if (!field) return "name";
    const map = lookupIdMaps[field] || {};
    return Object.keys(map).length > 0 ? "id" : "name";
  };

  const resolveFilterValue = (field, value) => {
    const text = String(value || "").trim();
    if (!text) return text;
    return lookupIdMaps[field]?.[text] || text;
  };

  const updateDraft = (mutate) => {
    setDraft((prev) => {
      const next = JSON.parse(JSON.stringify(ensureDraftShape(prev)));
      mutate(next);
      return next;
    });
    setValidation(null);
    setPublishResult(null);
  };

  const saveDraft = async (resources = dirtyResources) => {
    if (!snapshot) return null;
    const names = [...new Set(resources)].filter((name) => ALL_RESOURCES.includes(name));
    if (names.length === 0) return snapshot;
    const payload = {};
    for (const name of names) payload[name] = draft[name];
    setSaving(true);
    try {
      const updated = await api("/config/workspace/draft", {
        method: "PUT",
        body: { version: snapshot.version, draft: payload },
      });
      setSnapshot(updated);
      setDraft(ensureDraftShape(updated?.draft));
      setValidation(null);
      setPublishResult(null);
      onNotice?.(`Draft saved for ${names.length} resource${names.length === 1 ? "" : "s"}.`);
      return updated;
    } catch (exc) {
      onError?.(exc);
      if (String(exc?.message || "").includes("409")) {
        await loadWorkspace({ quiet: true });
      }
      return null;
    } finally {
      setSaving(false);
    }
  };

  const runValidation = async (versionOverride) => {
    const version = versionOverride || snapshot?.version;
    if (!version) return null;
    setValidating(true);
    try {
      const result = await api("/config/workspace/validate", { method: "POST", body: { version } });
      setValidation(result);
      return result;
    } catch (exc) {
      onError?.(exc);
      return null;
    } finally {
      setValidating(false);
    }
  };

  const saveAndValidate = async () => {
    const updated = await saveDraft(dirtyResources);
    if (!updated) return;
    await runValidation(updated.version);
  };

  const runValidationAction = async () => {
    if (hasUnsavedChanges) {
      await saveAndValidate();
      return;
    }
    await runValidation();
  };

  const publishDraft = async () => {
    if (!snapshot) return;
    setPublishing(true);
    try {
      const result = await api("/config/workspace/publish", {
        method: "POST",
        body: { version: snapshot.version },
      });
      setPublishResult(result);
      setValidation(null);
      await loadWorkspace({ quiet: true });
      onNotice?.(`Published ${result.changed_resources?.length || 0} resource(s).`);
    } catch (exc) {
      onError?.(exc);
    } finally {
      setPublishing(false);
    }
  };

  const openAdvancedDrawer = (name) => {
    setDrawerResource(name);
    setDrawerText(`${JSON.stringify(draft[name] || [], null, 2)}\n`);
    setDrawerError("");
    setDrawerOpen(true);
  };

  const applyAdvancedJson = () => {
    try {
      const parsed = JSON.parse(drawerText);
      if (!Array.isArray(parsed)) {
        setDrawerError("JSON payload must be an array.");
        return;
      }
      updateDraft((next) => {
        next[drawerResource] = parsed;
      });
      setDrawerOpen(false);
      onNotice?.(`Applied advanced JSON for ${RESOURCE_LABELS[drawerResource]}.`);
    } catch (exc) {
      setDrawerError(normalizeErrorMessage(exc?.message || exc));
    }
  };

  const validationCurrent = Boolean(validation && snapshot && validation.version === snapshot.version);
  const canPublish = Boolean(validationCurrent && validation.can_publish && !hasUnsavedChanges);
  const validationState = useMemo(() => {
    if (hasUnsavedChanges) {
      return {
        tone: "warning",
        label: "Save draft changes before validation.",
      };
    }
    if (!validation) {
      return {
        tone: "neutral",
        label: "No validation has been run for this draft version.",
      };
    }
    if (!validationCurrent) {
      return {
        tone: "warning",
        label: "Validation results are stale. Re-run validation for the latest draft.",
      };
    }
    if (validation.can_publish) {
      return {
        tone: "success",
        label: "Draft passed validation and is ready to publish.",
      };
    }
    return {
      tone: "danger",
      label: "Blocking errors detected. Fix them before publish.",
    };
  }, [hasUnsavedChanges, validation, validationCurrent]);

  const resourceRows = useMemo(() => {
    return ALL_RESOURCES.map((name) => ({
      name,
      label: RESOURCE_LABELS[name],
      draftCount: snapshot?.meta?.draft_counts?.[name] ?? serverDraft[name]?.length ?? 0,
      managedCount: snapshot?.meta?.managed_counts?.[name] ?? snapshot?.managed?.[name]?.length ?? 0,
      changedCount: snapshot?.meta?.changed_counts?.[name] ?? 0,
      unsaved: dirtyResources.includes(name),
    }));
  }, [dirtyResources, serverDraft, snapshot]);

  const updateCookbookEntry = (index, key, value) => {
    updateDraft((next) => {
      const current = next.cookbooks[index] || {};
      const nextValue = key === "position" ? parseCookbookPosition(value, index + 1) : value;
      next.cookbooks[index] = { ...current, [key]: nextValue };
    });
  };

  const updateCookbookFilterRows = (index, newRows) => {
    updateDraft((next) => {
      const current = next.cookbooks[index] || {};
      const rows = Array.isArray(newRows) ? newRows : [];
      next.cookbooks[index] = {
        ...current,
        filterRows: rows,
        queryFilterString: buildQueryFilter(rows),
      };
    });
  };

  const removeCookbookEntry = (index) => {
    updateDraft((next) => {
      next.cookbooks = next.cookbooks.filter((_, rowIndex) => rowIndex !== index);
    });
  };

  const moveCookbookPosition = (index, direction) => {
    updateDraft((next) => {
      const currentOrder = getOrderedCookbookIndexes(next.cookbooks);
      const currentOrderIndex = currentOrder.indexOf(index);
      const targetOrderIndex = currentOrderIndex + direction;
      if (currentOrderIndex < 0 || targetOrderIndex < 0 || targetOrderIndex >= currentOrder.length) return;
      const reordered = moveArrayItem(currentOrder, currentOrderIndex, targetOrderIndex);
      applyCookbookPositions(next.cookbooks, reordered);
    });
  };

  const reorderCookbookPosition = (fromIndex, toIndex) => {
    if (fromIndex === null || fromIndex === undefined || fromIndex === toIndex) return;
    updateDraft((next) => {
      const currentOrder = getOrderedCookbookIndexes(next.cookbooks);
      const fromOrderIndex = currentOrder.indexOf(fromIndex);
      const toOrderIndex = currentOrder.indexOf(toIndex);
      if (fromOrderIndex < 0 || toOrderIndex < 0 || fromOrderIndex === toOrderIndex) return;
      const reordered = moveArrayItem(currentOrder, fromOrderIndex, toOrderIndex);
      applyCookbookPositions(next.cookbooks, reordered);
    });
  };

  const toggleCookbookExpanded = (index) => {
    setExpandedCookbooks((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const addCookbookEntry = () => {
    const name = String(cookbookDraft.name || "").trim();
    if (!name) {
      onError?.(new Error("Cookbook name is required."));
      return;
    }

    const position = getNextCookbookPosition(cookbooks);
    const filterRows = Array.isArray(cookbookDraft.filterRows) ? cookbookDraft.filterRows : [];
    const queryFilterString = buildQueryFilter(filterRows);

    updateDraft((next) => {
      next.cookbooks.push({
        name,
        description: String(cookbookDraft.description || "").trim(),
        queryFilterString,
        public: Boolean(cookbookDraft.public),
        position,
      });
    });

    setCookbookDraft(defaultCookbookDraft());
  };

  if (loading && !snapshot) {
    return (
      <section className="page-grid recipe-workspace-grid">
        <article className="card"><p className="muted">Loading taxonomy workspace...</p></article>
      </section>
    );
  }

  return (
    <section className="page-grid recipe-workspace-grid">
      <article className="card recipe-workspace-shell">
        <div className="recipe-workspace-tabs">
          {TAB_ORDER.map((key) => (
            <button key={key} className={`pill-btn ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
              <span>{key.charAt(0).toUpperCase() + key.slice(1)}</span>
            </button>
          ))}
          <div className="recipe-workspace-meta">
            <span className={`status-pill ${hasUnsavedChanges ? "warning" : "success"}`}>
              {hasUnsavedChanges ? `${dirtyResources.length} unsaved` : "Draft synced"}
            </span>
          </div>
        </div>

        {tab === "plan" ? (
          <div className="workspace-tab-content">
            <p className="muted">
              Draft edits are stored server-side. Publish updates managed taxonomy files only after validation passes.
            </p>
            <div className="workspace-status-grid">
              {resourceRows.map((row) => (
                <article key={row.name} className="workspace-status-card">
                  <h4>{row.label}</h4>
                  <p className="muted tiny">Draft {row.draftCount} · Managed {row.managedCount}</p>
                  <p className="muted tiny">
                    Diff {row.changedCount}
                    {row.unsaved ? " · unsaved local edits" : ""}
                  </p>
                  <button
                    className="ghost small"
                    onClick={() => {
                      setTab(row.name === "cookbooks" ? "cookbooks" : "taxonomy");
                      if (row.name !== "cookbooks") setResource(row.name);
                    }}
                  >
                    Continue Editing
                  </button>
                </article>
              ))}
            </div>
            <div className="workspace-plan-footer">
              <p className="muted tiny">
                Last published: {formatTime(snapshot?.meta?.last_published_at)} by {snapshot?.meta?.last_published_by || "-"}
              </p>
              <button className="ghost" onClick={runValidationAction} disabled={saving || validating}>
                <Icon name="check-circle" /> {validating ? "Validating..." : "Run Validation"}
              </button>
            </div>
          </div>
        ) : null}

        {tab === "taxonomy" ? (
          <div className="workspace-tab-content">
            <div className="taxonomy-header workspace-sticky-top">
              <div className="taxonomy-resource-tabs">
                {TAXONOMY_RESOURCES.map((name) => (
                  <button
                    key={name}
                    className={`pill-btn ${resource === name ? "active" : ""}`}
                    onClick={() => setResource(name)}
                  >
                    {RESOURCE_LABELS[name]}
                  </button>
                ))}
              </div>
              <div className="taxonomy-controls">
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={`Search ${RESOURCE_LABELS[resource].toLowerCase()}`}
                />
                <button
                  className="ghost"
                  onClick={() => {
                    updateDraft((next) => {
                      next[resource].push(defaultRow(resource));
                    });
                  }}
                >
                  <Icon name="plus" /> Add Row
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    if (!selectedRows.size) return;
                    updateDraft((next) => {
                      next[resource] = next[resource].filter((_, index) => !selectedRows.has(index));
                    });
                    setSelectedRows(new Set());
                  }}
                  disabled={!selectedRows.size}
                >
                  <Icon name="trash" /> Delete Selected
                </button>
              </div>
            </div>

            <div className="taxonomy-summary-bar">
              <span className="status-pill">{RESOURCE_LABELS[resource]}</span>
              <span className="tiny muted">
                Rows {resourceItems.length} - Showing {filteredResourceIndexes.length}
              </span>
              <span className="tiny muted">Selected {selectedRows.size}</span>
              {taxonomyNameStats.missingNameCount > 0 ? (
                <span className="status-pill danger">
                  Missing names {taxonomyNameStats.missingNameCount}
                </span>
              ) : null}
              {taxonomyNameStats.duplicateNames.size > 0 ? (
                <span className="status-pill warning">
                  Duplicate names {taxonomyNameStats.duplicateNames.size}
                </span>
              ) : null}
            </div>

            <div className="workspace-table-wrap">
              <table className="workspace-table">
                <thead>
                  <tr>
                    <th className="table-col-select">
                      <input
                        type="checkbox"
                        checked={allFilteredSelected}
                        disabled={filteredResourceIndexes.length === 0}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setSelectedRows((prev) => {
                            const next = new Set(prev);
                            for (const index of filteredResourceIndexes) {
                              if (checked) next.add(index);
                              else next.delete(index);
                            }
                            return next;
                          });
                        }}
                        aria-label="Select all rows"
                      />
                    </th>
                    <th className="table-col-drag" />
                    <th className="workspace-row-index-head">#</th>
                    <th>Name</th>
                    {resource === "labels" ? <th>Color</th> : null}
                    {resource === "tools" ? <th>On Hand</th> : null}
                    {resource === "units_aliases" ? <th>Abbreviation</th> : null}
                    {resource === "units_aliases" ? <th>Aliases</th> : null}
                    <th className="table-col-action" />
                  </tr>
                </thead>
                <tbody>
                  {filteredResourceIndexes.map((index) => {
                    const item = resourceItems[index] || {};
                    const normalizedName = String(item.name || "").trim().toLowerCase();
                    const rowMissingName = !normalizedName;
                    const rowDuplicateName = Boolean(normalizedName && taxonomyNameStats.duplicateNames.has(normalizedName));
                    const rowInvalid = rowMissingName || rowDuplicateName;
                    return (
                      <tr
                        key={`${resource}-${index}`}
                        className={rowInvalid ? "workspace-row invalid" : "workspace-row"}
                        draggable
                        onDragStart={() => setDragIndex(index)}
                        onDragOver={(event) => event.preventDefault()}
                        onDrop={() => {
                          if (dragIndex === null) return;
                          updateDraft((next) => {
                            next[resource] = moveArrayItem(next[resource], dragIndex, index);
                          });
                          setDragIndex(null);
                        }}
                      >
                        <td className="table-col-select">
                          <input
                            type="checkbox"
                            checked={selectedRows.has(index)}
                            onChange={() => {
                              setSelectedRows((prev) => {
                                const next = new Set(prev);
                                if (next.has(index)) next.delete(index);
                                else next.add(index);
                                return next;
                              });
                            }}
                          />
                        </td>
                        <td className="drag-handle table-col-drag">
                          <span className="drag-handle-glyph" aria-hidden="true">
                            <Icon name="menu" />
                          </span>
                        </td>
                        <td className="workspace-row-index">{index + 1}</td>
                        <td>
                          <div className="workspace-name-cell">
                            <input
                              value={String(item.name || "")}
                              onChange={(event) => {
                                const value = event.target.value;
                                updateDraft((next) => {
                                  next[resource][index] = { ...(next[resource][index] || {}), name: value };
                                });
                              }}
                            />
                            {rowMissingName ? <span className="tiny danger-text">Name is required.</span> : null}
                            {!rowMissingName && rowDuplicateName ? <span className="tiny danger-text">Duplicate name.</span> : null}
                          </div>
                        </td>
                        {resource === "labels" ? (
                          <td>
                            <div className="color-field">
                              <input
                                type="color"
                                value={String(item.color || "#959595")}
                                onChange={(event) => {
                                  const value = event.target.value;
                                  updateDraft((next) => {
                                    next[resource][index] = { ...(next[resource][index] || {}), color: value };
                                  });
                                }}
                              />
                              <input
                                value={String(item.color || "#959595")}
                                onChange={(event) => {
                                  const value = event.target.value;
                                  updateDraft((next) => {
                                    next[resource][index] = { ...(next[resource][index] || {}), color: value };
                                  });
                                }}
                              />
                            </div>
                          </td>
                        ) : null}
                        {resource === "tools" ? (
                          <td>
                            <input
                              type="checkbox"
                              checked={Boolean(item.onHand)}
                              onChange={(event) => {
                                const value = event.target.checked;
                                updateDraft((next) => {
                                  next[resource][index] = { ...(next[resource][index] || {}), onHand: value };
                                });
                              }}
                            />
                          </td>
                        ) : null}
                        {resource === "units_aliases" ? (
                          <td>
                            <input
                              value={String(item.abbreviation || "")}
                              onChange={(event) => {
                                const value = event.target.value;
                                updateDraft((next) => {
                                  next[resource][index] = { ...(next[resource][index] || {}), abbreviation: value };
                                });
                              }}
                            />
                          </td>
                        ) : null}
                        {resource === "units_aliases" ? (
                          <td>
                            <input
                              value={Array.isArray(item.aliases) ? item.aliases.join(", ") : ""}
                              onChange={(event) => {
                                const value = parseAliasInput(event.target.value);
                                updateDraft((next) => {
                                  next[resource][index] = { ...(next[resource][index] || {}), aliases: value };
                                });
                              }}
                            />
                          </td>
                        ) : null}
                        <td className="table-col-action">
                          <button
                            className="ghost small"
                            onClick={() => {
                              updateDraft((next) => {
                                next[resource] = next[resource].filter((_, row) => row !== index);
                              });
                            }}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {!filteredResourceIndexes.length ? (
                    <tr>
                      <td colSpan={resource === "units_aliases" ? 8 : resource === "labels" || resource === "tools" ? 7 : 6}>
                        <p className="muted tiny workspace-empty-row">
                          No rows match this filter. Clear search or add a new row.
                        </p>
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>

            <div className="workspace-sticky-actions">
              <button className="primary" onClick={() => saveDraft([resource])} disabled={saving}>
                <Icon name="save" /> {saving ? "Saving..." : "Save Draft"}
              </button>
              <button
                className="ghost"
                onClick={() => {
                  updateDraft((next) => {
                    next[resource] = JSON.parse(JSON.stringify(serverDraft[resource] || []));
                  });
                }}
                disabled={!dirtyResources.includes(resource)}
              >
                Discard Resource Changes
              </button>
              <button className="ghost" onClick={() => openAdvancedDrawer(resource)}>
                Open Advanced JSON
              </button>
            </div>
          </div>
        ) : null}

        {tab === "cookbooks" ? (
          <div className="workspace-tab-content">
            <section className="structured-editor">
              <article className="workspace-cookbook-card workspace-cookbook-add-card">
                <div className="card-head split">
                  <div>
                    <h4><Icon name="book-open" /> Add Cookbook</h4>
                    <p>Create a new entry, define filters, then save draft to include it in publish.</p>
                  </div>
                </div>
                <div className="cookbook-add-form">
                  <div className="cookbook-add-fields">
                    <label className="field">
                      <span>Name</span>
                      <input
                        value={cookbookDraft.name}
                        onChange={(event) => setCookbookDraft((prev) => ({ ...prev, name: event.target.value }))}
                        placeholder="Weeknight Dinners"
                      />
                    </label>
                    <label className="field">
                      <span>Description</span>
                      <input
                        value={cookbookDraft.description}
                        onChange={(event) => setCookbookDraft((prev) => ({ ...prev, description: event.target.value }))}
                        placeholder="Quick and reliable meals for busy days."
                      />
                    </label>
                  </div>

                  {(cookbookDraft.filterRows || []).map((row, rowIndex) => {
                    const fieldDef = FILTER_FIELDS.find((f) => f.key === row.field);
                    const optionsForField = row.identifier === "name"
                      ? (nameFilterOptions[row.field] || [])
                      : (availableFilterOptions[row.field] || []);
                    const hasDropdown = optionsForField.length > 0;
                    const valueOptions = hasDropdown
                      ? optionsForField.filter((option) => !(row.values || []).includes(option.value))
                      : [];
                    return (
                      <div key={`draft-rule-${rowIndex}`} className="filter-row">
                        <select
                          value={row.field}
                          onChange={(event) => {
                            setCookbookDraft((prev) => {
                              const next = [...(prev.filterRows || [])];
                              next[rowIndex] = {
                                ...next[rowIndex],
                                field: event.target.value,
                                values: [],
                                identifier: defaultFilterIdentifier(event.target.value),
                              };
                              return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                            });
                          }}
                        >
                          {FILTER_FIELDS.map((field) => (
                            <option key={field.key} value={field.key}>{field.label}</option>
                          ))}
                        </select>
                        <select
                          value={row.operator || "IN"}
                          onChange={(event) => {
                            setCookbookDraft((prev) => {
                              const next = [...(prev.filterRows || [])];
                              next[rowIndex] = { ...next[rowIndex], operator: event.target.value };
                              return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                            });
                          }}
                        >
                          {FILTER_OPERATORS.map((operator) => (
                            <option key={operator.value} value={operator.value}>{operator.label}</option>
                          ))}
                        </select>
                        <div className="filter-value-area">
                          {hasDropdown ? (
                            <select
                              value=""
                              onChange={(event) => {
                                const value = event.target.value;
                                if (!value) return;
                                setCookbookDraft((prev) => {
                                  const next = [...(prev.filterRows || [])];
                                  next[rowIndex] = { ...next[rowIndex], values: [...(next[rowIndex].values || []), value] };
                                  return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                                });
                              }}
                            >
                              <option value="">Select {fieldDef?.label.toLowerCase() || "value"}...</option>
                              {valueOptions.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                              ))}
                            </select>
                          ) : (
                            <input
                              type="text"
                              placeholder="Type name, press Enter"
                              onKeyDown={(event) => {
                                if (event.key !== "Enter") return;
                                event.preventDefault();
                                const value = event.target.value.trim();
                                if (!value || (row.values || []).includes(value)) return;
                                event.target.value = "";
                                setCookbookDraft((prev) => {
                                  const next = [...(prev.filterRows || [])];
                                  next[rowIndex] = { ...next[rowIndex], values: [...(next[rowIndex].values || []), value] };
                                  return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                                });
                              }}
                            />
                          )}
                          {(row.values || []).length > 0 ? (
                            <div className="filter-chips">
                              {row.values.map((value) => (
                                <span key={value} className="filter-chip">
                                  {resolveFilterValue(row.field, value)}
                                  <button
                                    type="button"
                                    className="chip-remove"
                                    onClick={() => {
                                      setCookbookDraft((prev) => {
                                        const next = [...(prev.filterRows || [])];
                                        next[rowIndex] = {
                                          ...next[rowIndex],
                                          values: (next[rowIndex].values || []).filter((entry) => entry !== value),
                                        };
                                        return { ...prev, filterRows: next, queryFilterString: buildQueryFilter(next) };
                                      });
                                    }}
                                  >
                                    <Icon name="x" />
                                  </button>
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </div>
                        <button
                          type="button"
                          className="ghost filter-remove-btn"
                          onClick={() => {
                            setCookbookDraft((prev) => {
                              const next = (prev.filterRows || []).filter((_, index) => index !== rowIndex);
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
                        const used = new Set((prev.filterRows || []).map((row) => row.field));
                        const nextField = FILTER_FIELDS.find((field) => !used.has(field.key))?.key || "categories";
                        const nextRows = [
                          ...(prev.filterRows || []),
                          { field: nextField, operator: "IN", values: [], identifier: defaultFilterIdentifier(nextField) },
                        ];
                        return { ...prev, filterRows: nextRows, queryFilterString: buildQueryFilter(nextRows) };
                      });
                    }}
                  >
                    + Add Filter
                  </button>

                  <div className="cookbook-add-actions">
                    <label className="field field-inline">
                      <span>Public</span>
                      <input
                        type="checkbox"
                        checked={Boolean(cookbookDraft.public)}
                        onChange={(event) => setCookbookDraft((prev) => ({ ...prev, public: event.target.checked }))}
                      />
                    </label>
                    <button className="ghost" type="button" onClick={addCookbookEntry}>
                      <Icon name="plus" /> Add Cookbook
                    </button>
                  </div>
                </div>
              </article>

              <article className="workspace-cookbook-card">
                <div className="card-head split">
                  <div>
                    <h4><Icon name="list" /> Cookbook Entries</h4>
                    <p>{cookbooks.length} total cookbook{cookbooks.length === 1 ? "" : "s"}.</p>
                    <p className="muted tiny">
                      {cookbookSearch.trim() ? "Clear search to drag-reorder entries." : "Drag the handle to reorder. Positions update automatically."}
                    </p>
                  </div>
                  <div className="split-actions cookbook-entry-tools">
                    <label className="field cookbook-search-field">
                      <span>Search Existing</span>
                      <input
                        value={cookbookSearch}
                        onChange={(event) => setCookbookSearch(event.target.value)}
                        placeholder="Search cookbooks"
                      />
                    </label>
                    <span className="status-pill">{filteredCookbookIndexes.length} shown</span>
                  </div>
                </div>
                {filteredCookbookIndexes.length ? (
                  <ul className="structured-list">
                    {filteredCookbookIndexes.map((index) => {
                      const item = cookbooks[index] || {};
                      const changed = !equalJson(item, serverDraft.cookbooks?.[index] || null);
                      const filterRows = Array.isArray(item.filterRows)
                        ? item.filterRows
                        : parseQueryFilter(item.queryFilterString || "");
                      const sortedOrderIndex = cookbookOrderMap.get(index) ?? 0;
                      const isFirstByPosition = sortedOrderIndex <= 0;
                      const isLastByPosition = sortedOrderIndex >= (orderedCookbookIndexes.length - 1);
                      const reorderLocked = Boolean(cookbookSearch.trim());
                      const isExpanded = expandedCookbooks.has(index);
                      return (
                        <li
                          key={`cookbook-${index}`}
                          className={`structured-item cookbook-entry-item ${dragOverCookbookIndex === index ? "drag-over" : ""}`}
                          onDragOver={(event) => {
                            if (reorderLocked || dragCookbookIndex === null) return;
                            event.preventDefault();
                          }}
                          onDragEnter={() => {
                            if (reorderLocked || dragCookbookIndex === null) return;
                            setDragOverCookbookIndex(index);
                          }}
                          onDrop={(event) => {
                            if (reorderLocked || dragCookbookIndex === null) return;
                            event.preventDefault();
                            reorderCookbookPosition(dragCookbookIndex, index);
                            setDragCookbookIndex(null);
                            setDragOverCookbookIndex(null);
                          }}
                        >
                          <div className="card-head split cookbook-entry-head">
                            <div>
                              <div className="cookbook-entry-title-row">
                                <span
                                  className={`cookbook-drag-handle ${reorderLocked ? "disabled" : ""}`}
                                  draggable={!reorderLocked}
                                  title={reorderLocked ? "Clear search to reorder" : "Drag to reorder"}
                                  onDragStart={() => {
                                    if (reorderLocked) return;
                                    setDragCookbookIndex(index);
                                  }}
                                  onDragEnd={() => {
                                    setDragCookbookIndex(null);
                                    setDragOverCookbookIndex(null);
                                  }}
                                >
                                  <Icon name="menu" />
                                </span>
                                <h4>{item.name || `Cookbook ${index + 1}`}</h4>
                              </div>
                              <p className="muted tiny">
                                Filters {filterRows.length}{isExpanded ? "" : " · collapsed"}
                              </p>
                            </div>
                            <div className="cookbook-entry-badges">
                              <span className="status-pill">Pos {parseCookbookPosition(item.position, index + 1)}</span>
                              {item.public ? <span className="status-pill">Public</span> : null}
                              {changed ? <span className="status-pill warning">Draft</span> : null}
                              <button
                                type="button"
                                className={`ghost small cookbook-collapse-btn ${isExpanded ? "expanded" : ""}`}
                                aria-expanded={isExpanded}
                                onClick={() => toggleCookbookExpanded(index)}
                              >
                                <Icon name="chevron" />
                                {isExpanded ? "Collapse" : "Expand"}
                              </button>
                            </div>
                          </div>
                          {isExpanded ? (
                            <>
                              <div className="structured-item-grid cookbook-fields">
                                <label className="field">
                                  <span>Name</span>
                                  <input
                                    value={String(item.name || "")}
                                    onChange={(event) => updateCookbookEntry(index, "name", event.target.value)}
                                  />
                                </label>
                                <label className="field">
                                  <span>Description</span>
                                  <input
                                    value={String(item.description || "")}
                                    onChange={(event) => updateCookbookEntry(index, "description", event.target.value)}
                                  />
                                </label>
                              </div>
                              {filterRows.map((row, rowIndex) => {
                                const fieldDef = FILTER_FIELDS.find((f) => f.key === row.field);
                                const optionsForField = row.identifier === "name"
                                  ? (nameFilterOptions[row.field] || [])
                                  : (availableFilterOptions[row.field] || []);
                                const hasDropdown = optionsForField.length > 0;
                                const valueOptions = hasDropdown
                                  ? optionsForField.filter((option) => !(row.values || []).includes(option.value))
                                  : [];
                                return (
                                  <div key={`cookbook-rule-${index}-${rowIndex}`} className="filter-row">
                                    <select
                                      value={row.field}
                                      onChange={(event) => {
                                        const nextRows = [...filterRows];
                                        nextRows[rowIndex] = {
                                          ...nextRows[rowIndex],
                                          field: event.target.value,
                                          values: [],
                                          identifier: defaultFilterIdentifier(event.target.value),
                                        };
                                        updateCookbookFilterRows(index, nextRows);
                                      }}
                                    >
                                      {FILTER_FIELDS.map((field) => (
                                        <option key={field.key} value={field.key}>{field.label}</option>
                                      ))}
                                    </select>
                                    <select
                                      value={row.operator || "IN"}
                                      onChange={(event) => {
                                        const nextRows = [...filterRows];
                                        nextRows[rowIndex] = { ...nextRows[rowIndex], operator: event.target.value };
                                        updateCookbookFilterRows(index, nextRows);
                                      }}
                                    >
                                      {FILTER_OPERATORS.map((operator) => (
                                        <option key={operator.value} value={operator.value}>{operator.label}</option>
                                      ))}
                                    </select>
                                    <div className="filter-value-area">
                                      {hasDropdown ? (
                                        <select
                                          value=""
                                          onChange={(event) => {
                                            const value = event.target.value;
                                            if (!value) return;
                                            const nextRows = [...filterRows];
                                            nextRows[rowIndex] = { ...nextRows[rowIndex], values: [...(nextRows[rowIndex].values || []), value] };
                                            updateCookbookFilterRows(index, nextRows);
                                          }}
                                        >
                                          <option value="">Select {fieldDef?.label.toLowerCase() || "value"}...</option>
                                          {valueOptions.map((option) => (
                                            <option key={option.value} value={option.value}>{option.label}</option>
                                          ))}
                                        </select>
                                      ) : (
                                        <input
                                          type="text"
                                          placeholder="Type name, press Enter"
                                          onKeyDown={(event) => {
                                            if (event.key !== "Enter") return;
                                            event.preventDefault();
                                            const value = event.target.value.trim();
                                            if (!value || (row.values || []).includes(value)) return;
                                            event.target.value = "";
                                            const nextRows = [...filterRows];
                                            nextRows[rowIndex] = { ...nextRows[rowIndex], values: [...(nextRows[rowIndex].values || []), value] };
                                            updateCookbookFilterRows(index, nextRows);
                                          }}
                                        />
                                      )}
                                      {(row.values || []).length > 0 ? (
                                        <div className="filter-chips">
                                          {row.values.map((value) => (
                                            <span key={value} className="filter-chip">
                                              {resolveFilterValue(row.field, value)}
                                              <button
                                                type="button"
                                                className="chip-remove"
                                                onClick={() => {
                                                  const nextRows = [...filterRows];
                                                  nextRows[rowIndex] = {
                                                    ...nextRows[rowIndex],
                                                    values: (nextRows[rowIndex].values || []).filter((entry) => entry !== value),
                                                  };
                                                  updateCookbookFilterRows(index, nextRows);
                                                }}
                                              >
                                                <Icon name="x" />
                                              </button>
                                            </span>
                                          ))}
                                        </div>
                                      ) : null}
                                    </div>
                                    <button
                                      type="button"
                                      className="ghost filter-remove-btn"
                                      onClick={() => {
                                        const nextRows = filterRows.filter((_, valueIndex) => valueIndex !== rowIndex);
                                        updateCookbookFilterRows(index, nextRows);
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
                                  const used = new Set(filterRows.map((row) => row.field));
                                  const nextField = FILTER_FIELDS.find((field) => !used.has(field.key))?.key || "categories";
                                  const nextRows = [
                                    ...filterRows,
                                    { field: nextField, operator: "IN", values: [], identifier: defaultFilterIdentifier(nextField) },
                                  ];
                                  updateCookbookFilterRows(index, nextRows);
                                }}
                              >
                                + Add Filter
                              </button>
                              <div className="cookbook-item-footer">
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
                                    onClick={() => moveCookbookPosition(index, -1)}
                                    disabled={isFirstByPosition}
                                  >
                                    Up
                                  </button>
                                  <button
                                    type="button"
                                    className="ghost small"
                                    onClick={() => moveCookbookPosition(index, 1)}
                                    disabled={isLastByPosition}
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
                            </>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="muted tiny">No cookbooks match the current search.</p>
                )}
              </article>
              <div className="workspace-sticky-actions">
                <button className="primary" onClick={() => saveDraft(["cookbooks"])} disabled={saving}>
                  <Icon name="save" /> {saving ? "Saving..." : "Save Draft"}
                </button>
                <button
                  className="ghost"
                  onClick={() => {
                    updateDraft((next) => {
                      next.cookbooks = JSON.parse(JSON.stringify(serverDraft.cookbooks || []));
                    });
                  }}
                  disabled={!dirtyResources.includes("cookbooks")}
                >
                  Discard Cookbook Changes
                </button>
                <button className="ghost" onClick={() => openAdvancedDrawer("cookbooks")}>
                  Open Advanced JSON
                </button>
              </div>
            </section>
          </div>
        ) : null}

      </article>

      <aside className="recipe-workspace-side">
        <article className="card workspace-side-card">
          <h3><Icon name="check-circle" /> Validate Draft</h3>
          <p className="muted tiny">Validation is required before publish.</p>
          <article className={`workspace-validation-state ${validationState.tone}`}>
            <h4>Validation Status</h4>
            <p className="tiny">{validationState.label}</p>
            <ul className="workspace-checklist">
              <li className={!hasUnsavedChanges ? "ok" : "pending"}>
                <Icon name={!hasUnsavedChanges ? "check-circle" : "x-circle"} />
                <span>Draft saved</span>
              </li>
              <li className={validationCurrent ? "ok" : "pending"}>
                <Icon name={validationCurrent ? "check-circle" : "x-circle"} />
                <span>Validation run on current version</span>
              </li>
              <li className={validationCurrent && validation?.can_publish ? "ok" : "pending"}>
                <Icon name={validationCurrent && validation?.can_publish ? "check-circle" : "x-circle"} />
                <span>No blocking errors</span>
              </li>
            </ul>
          </article>
          <div className="workspace-side-actions">
            <button className="primary" onClick={saveAndValidate} disabled={saving || validating}>
              <Icon name="save" /> {saving ? "Saving..." : validating ? "Validating..." : "Save Draft + Validate"}
            </button>
            <button className="ghost" onClick={() => runValidation()} disabled={hasUnsavedChanges || validating}>
              <Icon name="check-circle" /> {validating ? "Validating..." : "Validate Current Draft"}
            </button>
          </div>
          {validation ? (
            <div className="validation-results">
              <span className={`status-pill ${validation.can_publish ? "success" : "danger"}`}>
                {validation.can_publish ? "Publishable" : "Blocking errors present"}
              </span>
              {(validation.errors || []).length > 0 ? (
                <article className="validation-panel error">
                  <h4>Blocking Errors</h4>
                  <ul>
                    {(validation.errors || []).map((issue, index) => (
                      <li key={`err-${index}`}>{issue.message}</li>
                    ))}
                  </ul>
                </article>
              ) : null}
              {(validation.warnings || []).length > 0 ? (
                <article className="validation-panel warning">
                  <h4>Warnings</h4>
                  <ul>
                    {(validation.warnings || []).map((issue, index) => (
                      <li key={`warn-${index}`}>{issue.message}</li>
                    ))}
                  </ul>
                </article>
              ) : null}
            </div>
          ) : (
            <article className="validation-panel">
              <h4>What validation checks</h4>
              <ul>
                <li>Schema and type checks across all draft resources.</li>
                <li>Duplicate and normalization checks for taxonomy values.</li>
                <li>Cookbook rule integrity and query filter checks.</li>
              </ul>
            </article>
          )}
        </article>

        <article className="card workspace-side-card">
          <h3><Icon name="upload" /> Publish Draft</h3>
          <p className="muted tiny">Publish writes managed files and then hands off to tasks.</p>
          <ul className="workspace-publish-list">
            {resourceRows.map((row) => (
              <li key={`publish-${row.name}`}>
                <strong>{row.label}</strong>
                <span className="tiny muted">Draft {row.draftCount} | Managed {row.managedCount} | Diff {row.changedCount}</span>
              </li>
            ))}
          </ul>
          {!validationCurrent ? (
            <p className="banner warning"><span>Run validation on the current draft version before publish.</span></p>
          ) : null}
          {hasUnsavedChanges ? (
            <p className="banner warning"><span>You have unsaved local edits.</span></p>
          ) : null}
          <div className="workspace-side-actions">
            <button className="primary" onClick={publishDraft} disabled={!canPublish || publishing}>
              <Icon name="upload" /> {publishing ? "Publishing..." : "Publish Draft to Managed Files"}
            </button>
          </div>
          {publishResult ? (
            <article className="publish-result-panel">
              <h4>Publish Complete</h4>
              <p className="muted tiny">Published at {formatTime(publishResult.published_at)}</p>
              <div className="publish-next-actions">
                <button className="ghost" onClick={() => onOpenTasks?.("taxonomy-refresh")}>
                  Open Tasks with taxonomy-refresh preselected
                </button>
                <button className="ghost" onClick={() => onOpenTasks?.("cookbook-sync")}>
                  Open Tasks with cookbook-sync preselected
                </button>
              </div>
            </article>
          ) : null}
        </article>

        {drawerOpen ? (
          <aside className="card workspace-json-drawer">
            <div className="drawer-head">
              <h3>Advanced JSON - {RESOURCE_LABELS[drawerResource]}</h3>
              <button className="ghost small" onClick={() => setDrawerOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <textarea rows={20} value={drawerText} onChange={(event) => setDrawerText(event.target.value)} />
            {drawerError ? <p className="danger-text tiny">{drawerError}</p> : null}
            <div className="split-actions">
              <button className="primary" onClick={applyAdvancedJson}>Apply JSON</button>
              <button className="ghost" onClick={() => setDrawerError("")}>Clear Error</button>
            </div>
          </aside>
        ) : null}
      </aside>
    </section>
  );
}
