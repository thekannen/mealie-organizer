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
  const [selectedCookbookIndex, setSelectedCookbookIndex] = useState(0);

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

  useEffect(() => {
    loadWorkspace({ quiet: true });
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
  const filteredCookbookIndexes = useMemo(() => {
    const query = cookbookSearch.trim().toLowerCase();
    return cookbooks
      .map((_, index) => index)
      .filter((index) => {
        const item = cookbooks[index] || {};
        return !query || `${item.name || ""} ${item.description || ""} ${item.queryFilterString || ""}`.toLowerCase().includes(query);
      });
  }, [cookbooks, cookbookSearch]);
  const activeCookbook = cookbooks[selectedCookbookIndex] || null;
  const activeRules = useMemo(() => parseQueryFilter(activeCookbook?.queryFilterString || ""), [activeCookbook]);

  useEffect(() => {
    if (selectedCookbookIndex < cookbooks.length) return;
    setSelectedCookbookIndex(Math.max(0, cookbooks.length - 1));
  }, [cookbooks.length, selectedCookbookIndex]);

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
                          <Icon name="menu" />
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
            <div className="cookbooks-split">
              <aside className="cookbook-list-panel">
                <div className="cookbook-list-head">
                  <input
                    value={cookbookSearch}
                    onChange={(event) => setCookbookSearch(event.target.value)}
                    placeholder="Search cookbooks"
                  />
                  <button
                    className="ghost"
                    onClick={() => {
                      updateDraft((next) => {
                        next.cookbooks.push({
                          name: "",
                          description: "",
                          queryFilterString: "",
                          public: false,
                          position: next.cookbooks.length + 1,
                        });
                      });
                      setSelectedCookbookIndex(cookbooks.length);
                    }}
                  >
                    <Icon name="plus" /> Add
                  </button>
                </div>
                <ul className="cookbook-list">
                  {filteredCookbookIndexes.map((index) => {
                    const item = cookbooks[index] || {};
                    const changed = !equalJson(item, serverDraft.cookbooks?.[index] || null);
                    return (
                      <li key={`cookbook-${index}`}>
                        <button
                          className={`cookbook-list-item ${selectedCookbookIndex === index ? "active" : ""}`}
                          onClick={() => setSelectedCookbookIndex(index)}
                        >
                          <span>{item.name || `Cookbook ${index + 1}`}</span>
                          {changed ? <span className="status-pill warning">Draft</span> : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </aside>

              <div className="cookbook-editor-panel">
                {!activeCookbook ? (
                  <p className="muted">Select a cookbook to edit its rules.</p>
                ) : (
                  <>
                    <div className="cookbook-editor-grid">
                      <label className="field">
                        <span>Name</span>
                        <input
                          value={String(activeCookbook.name || "")}
                          onChange={(event) => {
                            const value = event.target.value;
                            updateDraft((next) => {
                              next.cookbooks[selectedCookbookIndex] = { ...(next.cookbooks[selectedCookbookIndex] || {}), name: value };
                            });
                          }}
                        />
                      </label>
                      <label className="field">
                        <span>Description</span>
                        <input
                          value={String(activeCookbook.description || "")}
                          onChange={(event) => {
                            const value = event.target.value;
                            updateDraft((next) => {
                              next.cookbooks[selectedCookbookIndex] = { ...(next.cookbooks[selectedCookbookIndex] || {}), description: value };
                            });
                          }}
                        />
                      </label>
                    </div>

                    <div className="cookbook-rules">
                      <div className="cookbook-rules-head">
                        <h4>Rule Builder</h4>
                        <button
                          className="ghost small"
                          onClick={() => {
                            const usedFields = new Set(activeRules.map((row) => row.field));
                            const nextField = FILTER_FIELDS.find((field) => !usedFields.has(field.key))?.key || "categories";
                            const nextRows = [...activeRules, { field: nextField, operator: "IN", values: [] }];
                            updateDraft((next) => {
                              next.cookbooks[selectedCookbookIndex] = {
                                ...(next.cookbooks[selectedCookbookIndex] || {}),
                                queryFilterString: buildQueryFilter(nextRows),
                              };
                            });
                          }}
                        >
                          Add Rule
                        </button>
                      </div>
                      {activeRules.map((row, rowIndex) => (
                        <div key={`rule-${rowIndex}`} className="cookbook-rule-row">
                          <select
                            value={row.field}
                            onChange={(event) => {
                              const nextRows = activeRules.map((item, index) => (
                                index === rowIndex ? { ...item, field: event.target.value, values: [] } : item
                              ));
                              updateDraft((next) => {
                                next.cookbooks[selectedCookbookIndex] = {
                                  ...(next.cookbooks[selectedCookbookIndex] || {}),
                                  queryFilterString: buildQueryFilter(nextRows),
                                };
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
                              const nextRows = activeRules.map((item, index) => (
                                index === rowIndex ? { ...item, operator: event.target.value } : item
                              ));
                              updateDraft((next) => {
                                next.cookbooks[selectedCookbookIndex] = {
                                  ...(next.cookbooks[selectedCookbookIndex] || {}),
                                  queryFilterString: buildQueryFilter(nextRows),
                                };
                              });
                            }}
                          >
                            {FILTER_OPERATORS.map((operator) => (
                              <option key={operator.value} value={operator.value}>{operator.label}</option>
                            ))}
                          </select>
                          <input
                            value={(row.values || []).join(", ")}
                            onChange={(event) => {
                              const values = parseAliasInput(event.target.value);
                              const nextRows = activeRules.map((item, index) => (
                                index === rowIndex ? { ...item, values } : item
                              ));
                              updateDraft((next) => {
                                next.cookbooks[selectedCookbookIndex] = {
                                  ...(next.cookbooks[selectedCookbookIndex] || {}),
                                  queryFilterString: buildQueryFilter(nextRows),
                                };
                              });
                            }}
                            placeholder="value1, value2"
                          />
                          <button
                            className="ghost small"
                            onClick={() => {
                              const nextRows = activeRules.filter((_, index) => index !== rowIndex);
                              updateDraft((next) => {
                                next.cookbooks[selectedCookbookIndex] = {
                                  ...(next.cookbooks[selectedCookbookIndex] || {}),
                                  queryFilterString: buildQueryFilter(nextRows),
                                };
                              });
                            }}
                          >
                            Remove
                          </button>
                        </div>
                      ))}
                    </div>

                    <label className="field">
                      <span>Live Query Preview</span>
                      <textarea rows={3} value={activeCookbook.queryFilterString || ""} readOnly />
                    </label>

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
                  </>
                )}
              </div>
            </div>
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
