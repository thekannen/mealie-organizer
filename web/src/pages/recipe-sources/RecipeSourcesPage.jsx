import React, { useState, useMemo, useEffect } from "react";
import Icon from "../../components/Icon";
import { api } from "../../utils.jsx";

export default function RecipeSourcesPage({ onNotice, onError }) {
  const [dredgerSites, setDredgerSites] = useState([]);
  const [dredgerSitesDraft, setDredgerSitesDraft] = useState({ url: "", label: "", group: "" });
  const [dredgerSitesLoading, setDredgerSitesLoading] = useState(false);
  const [dredgerValidating, setDredgerValidating] = useState(false);
  const [dredgerValidationResults, setDredgerValidationResults] = useState({});
  const [dredgerSitesFilter, setDredgerSitesFilter] = useState("");
  const [dredgerEditId, setDredgerEditId] = useState(null);
  const [dredgerSelected, setDredgerSelected] = useState(new Set());
  const [dredgerAdding, setDredgerAdding] = useState(false);

  async function loadDredgerSites() {
    setDredgerSitesLoading(true);
    try {
      const data = await api("/settings/dredger-sites");
      setDredgerSites(data.sites || []);
    } catch (exc) {
      onError(exc);
    } finally {
      setDredgerSitesLoading(false);
    }
  }

  useEffect(() => {
    loadDredgerSites();
  }, []);

  async function addDredgerSite() {
    const url = dredgerSitesDraft.url.trim();
    if (!url) return;
    setDredgerAdding(true);
    try {
      await api("/settings/dredger-sites", {
        method: "POST",
        body: { url, label: dredgerSitesDraft.label, group: dredgerSitesDraft.group },
        timeout: 30000,
      });
      setDredgerSitesDraft({ url: "", label: "", group: "" });
      await loadDredgerSites();
      onNotice("Site added.");
    } catch (exc) {
      onError(exc);
    } finally {
      setDredgerAdding(false);
    }
  }

  async function toggleDredgerSite(id, enabled) {
    try {
      await api(`/settings/dredger-sites/${id}`, { method: "PUT", body: { enabled } });
      setDredgerSites((prev) => prev.map((s) => (s.id === id ? { ...s, enabled: enabled ? 1 : 0 } : s)));
    } catch (exc) {
      onError(exc);
    }
  }

  async function deleteDredgerSite(id) {
    try {
      await api(`/settings/dredger-sites/${id}`, { method: "DELETE" });
      setDredgerSites((prev) => prev.filter((s) => s.id !== id));
      onNotice("Site removed.");
    } catch (exc) {
      onError(exc);
    }
  }

  async function saveDredgerSiteEdit(id, updates) {
    try {
      await api(`/settings/dredger-sites/${id}`, { method: "PUT", body: updates });
      setDredgerEditId(null);
      await loadDredgerSites();
      onNotice("Site updated.");
    } catch (exc) {
      onError(exc);
    }
  }

  async function seedDredgerSites({ force = false, merge = false } = {}) {
    try {
      const data = await api("/settings/dredger-sites/seed", { method: "POST", body: { force, merge } });
      await loadDredgerSites();
      if (data.inserted > 0) {
        onNotice(`${merge ? "Merged" : "Seeded"} ${data.inserted} default site${data.inserted !== 1 ? "s" : ""}.`);
      } else {
        onNotice("No new sites to add — your list already includes all defaults.");
      }
    } catch (exc) {
      onError(exc);
    }
  }

  async function validateDredgerSites() {
    setDredgerValidating(true);
    setDredgerValidationResults({});
    try {
      const data = await api("/settings/dredger-sites/validate", { method: "POST", body: {} });
      const results = {};
      for (const r of data.results || []) {
        results[r.id] = r;
      }
      setDredgerValidationResults(results);
    } catch (exc) {
      onError(exc);
    } finally {
      setDredgerValidating(false);
    }
  }

  function toggleDredgerSelect(id) {
    setDredgerSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function selectDredgerGroup(sites) {
    setDredgerSelected((prev) => {
      const next = new Set(prev);
      const allSelected = sites.every((s) => prev.has(s.id));
      for (const s of sites) {
        if (allSelected) next.delete(s.id); else next.add(s.id);
      }
      return next;
    });
  }

  async function bulkDeleteDredgerSites() {
    if (dredgerSelected.size === 0) return;
    try {
      for (const id of dredgerSelected) {
        await api(`/settings/dredger-sites/${id}`, { method: "DELETE" });
      }
      setDredgerSelected(new Set());
      await loadDredgerSites();
      onNotice(`Removed ${dredgerSelected.size} site(s).`);
    } catch (exc) {
      onError(exc);
    }
  }

  async function bulkToggleDredgerSites(enabled) {
    if (dredgerSelected.size === 0) return;
    try {
      for (const id of dredgerSelected) {
        await api(`/settings/dredger-sites/${id}`, { method: "PUT", body: { enabled } });
      }
      setDredgerSelected(new Set());
      await loadDredgerSites();
      onNotice(`${enabled ? "Enabled" : "Disabled"} ${dredgerSelected.size} site(s).`);
    } catch (exc) {
      onError(exc);
    }
  }

  async function deleteGroupDredgerSites(groupSites) {
    try {
      for (const s of groupSites) {
        await api(`/settings/dredger-sites/${s.id}`, { method: "DELETE" });
      }
      await loadDredgerSites();
      onNotice(`Removed ${groupSites.length} site(s).`);
    } catch (exc) {
      onError(exc);
    }
  }

  const filter = dredgerSitesFilter.toLowerCase();
  const grouped = {};
  for (const site of dredgerSites) {
    if (filter && !site.url.toLowerCase().includes(filter) && !(site.group || "").toLowerCase().includes(filter)) continue;
    const group = site.group || "Uncategorized";
    if (!grouped[group]) grouped[group] = [];
    grouped[group].push(site);
  }
  const groupEntries = Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b));
  const enabledCount = dredgerSites.filter((s) => s.enabled).length;
  const groups = [...new Set(dredgerSites.map((s) => s.group).filter(Boolean))].sort();
  const hasSelection = dredgerSelected.size > 0;
  const hasValidation = Object.keys(dredgerValidationResults).length > 0;
  const deadLinks = hasValidation ? dredgerSites.filter((s) => dredgerValidationResults[s.id] && !dredgerValidationResults[s.id].reachable) : [];

  return (
    <section className="page-content">
      <article className="card">
        <div className="card-head split">
          <div>
            <h3><Icon name="globe" /> Recipe Sources</h3>
            <p>Sites the Recipe Dredger crawls for new recipes. <span className="muted tiny">Based on work by <a href="https://github.com/D0rk4ce/mealie-recipe-dredger" target="_blank" rel="noopener noreferrer">D0rk4ce</a></span></p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <button className="ghost" onClick={validateDredgerSites} disabled={dredgerValidating}>
              <Icon name={dredgerValidating ? "refresh" : "check-circle"} />
              {dredgerValidating ? "Validating\u2026" : "Validate All"}
            </button>
            <button className="ghost" onClick={loadDredgerSites} disabled={dredgerSitesLoading}>
              <Icon name="refresh" />
            </button>
          </div>
        </div>

        {dredgerSites.length === 0 && !dredgerSitesLoading ? (
          <div style={{ textAlign: "center", padding: "3rem 1rem" }}>
            <p className="muted" style={{ marginBottom: "1rem" }}>No recipe sources configured yet.</p>
            <button className="primary" onClick={() => seedDredgerSites()}>
              <Icon name="plus" /> Load Default Sites
            </button>
            <p className="tiny muted" style={{ marginTop: "0.5rem" }}>Seeds ~85 curated recipe blogs organized by group.</p>
          </div>
        ) : (
          <>
            <div className="dredger-sites-toolbar">
              <div className="dredger-add-form">
                <input
                  type="text"
                  placeholder="https://example.com"
                  aria-label="Site URL"
                  value={dredgerSitesDraft.url}
                  onChange={(e) => setDredgerSitesDraft((d) => ({ ...d, url: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && addDredgerSite()}
                />
                <input
                  type="text"
                  list="dredger-group-list"
                  placeholder="Group"
                  aria-label="Group"
                  value={dredgerSitesDraft.group}
                  onChange={(e) => setDredgerSitesDraft((d) => ({ ...d, group: e.target.value }))}
                  style={{ maxWidth: "10rem" }}
                />
                <datalist id="dredger-group-list">
                  {groups.map((g) => (
                    <option key={g} value={g} />
                  ))}
                </datalist>
                <button className="primary compact" onClick={addDredgerSite} disabled={!dredgerSitesDraft.url.trim() || dredgerAdding}>
                  <Icon name={dredgerAdding ? "refresh" : "plus"} /> {dredgerAdding ? "Validating\u2026" : "Add"}
                </button>
              </div>
              <div className="dredger-filter">
                <input
                  type="text"
                  placeholder="Search..."
                  aria-label="Search recipe sources"
                  value={dredgerSitesFilter}
                  onChange={(e) => setDredgerSitesFilter(e.target.value)}
                />
                <span className="chip-count">{enabledCount}/{dredgerSites.length}</span>
              </div>
            </div>

            {hasSelection ? (
              <div className="dredger-bulk-bar">
                <span>{dredgerSelected.size} selected</span>
                <button className="ghost compact" onClick={() => bulkToggleDredgerSites(true)}><Icon name="check-circle" /> Enable</button>
                <button className="ghost compact" onClick={() => bulkToggleDredgerSites(false)}><Icon name="x" /> Disable</button>
                <button className="ghost compact danger" onClick={bulkDeleteDredgerSites}><Icon name="trash" /> Delete</button>
                <button className="ghost compact" onClick={() => setDredgerSelected(new Set())}>Clear</button>
              </div>
            ) : null}

            {hasValidation && deadLinks.length > 0 ? (
              <div className="dredger-dead-bar">
                <Icon name="alertTriangle" />
                <span>{deadLinks.length} unreachable site{deadLinks.length !== 1 ? "s" : ""} found</span>
                <button className="ghost compact" onClick={() => {
                  setDredgerSelected(new Set(deadLinks.map((s) => s.id)));
                }}>Select</button>
                <button className="ghost compact" onClick={async () => {
                  for (const s of deadLinks) {
                    await api(`/settings/dredger-sites/${s.id}`, { method: "PUT", body: { enabled: false } });
                  }
                  setDredgerValidationResults({});
                  await loadDredgerSites();
                  onNotice(`Disabled ${deadLinks.length} dead link(s).`);
                }}>
                  <Icon name="x" /> Disable
                </button>
                <button className="ghost compact danger" onClick={async () => {
                  for (const s of deadLinks) {
                    await api(`/settings/dredger-sites/${s.id}`, { method: "DELETE" });
                  }
                  setDredgerValidationResults({});
                  await loadDredgerSites();
                  onNotice(`Removed ${deadLinks.length} dead link(s).`);
                }}>
                  <Icon name="trash" /> Delete
                </button>
                <button className="ghost compact" onClick={() => setDredgerValidationResults({})}>Dismiss</button>
              </div>
            ) : hasValidation && deadLinks.length === 0 ? (
              <div className="dredger-ok-bar">
                <Icon name="check-circle" />
                <span>All sites reachable</span>
                <button className="ghost compact" onClick={() => setDredgerValidationResults({})}>Dismiss</button>
              </div>
            ) : null}

            <div className="dredger-sites-list">
              {groupEntries.map(([group, sites]) => {
                const allGroupSelected = sites.every((s) => dredgerSelected.has(s.id));
                const someGroupSelected = sites.some((s) => dredgerSelected.has(s.id));
                return (
                  <div key={group} className="dredger-group">
                    <div className="dredger-region-header">
                      <label className="dredger-region-select">
                        <input
                          type="checkbox"
                          checked={allGroupSelected}
                          ref={(el) => { if (el) el.indeterminate = someGroupSelected && !allGroupSelected; }}
                          onChange={() => selectDredgerGroup(sites)}
                        />
                        <h4 className="dredger-region-label">{group} <span className="chip-count">{sites.length}</span></h4>
                      </label>
                    </div>
                    {sites.map((site) => {
                      const vr = dredgerValidationResults[site.id];
                      const isEditing = dredgerEditId === site.id;
                      const isSelected = dredgerSelected.has(site.id);
                      return (
                        <div key={site.id} className={`dredger-site-row${site.enabled ? "" : " disabled"}${vr && !vr.reachable ? " unreachable" : ""}${isSelected ? " selected" : ""}`}>
                          {isEditing ? (
                            <form className="dredger-edit-form" onSubmit={(e) => {
                              e.preventDefault();
                              const fd = new FormData(e.target);
                              saveDredgerSiteEdit(site.id, { url: fd.get("url"), group: fd.get("group") });
                            }}>
                              <input name="url" defaultValue={site.url} aria-label="Edit site URL" autoFocus />
                              <input name="group" defaultValue={site.group} placeholder="Group" aria-label="Edit group" list="dredger-group-list" style={{ maxWidth: "10rem" }} />
                              <button type="submit" className="ghost compact" aria-label="Save"><Icon name="check" /></button>
                              <button type="button" className="ghost compact" aria-label="Cancel" onClick={() => setDredgerEditId(null)}><Icon name="x" /></button>
                            </form>
                          ) : (
                            <>
                              <div className="dredger-site-left">
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onChange={() => toggleDredgerSelect(site.id)}
                                />
                                <span className="dredger-site-url">{site.url.replace(/^https?:\/\//, "")}</span>
                              </div>
                              <div className="dredger-site-actions">
                                {vr ? (
                                  <span className={`tiny ${vr.reachable ? "success-text" : "danger-text"}`}>
                                    {vr.reachable ? (vr.sitemap_found ? "OK" : "No sitemap") : vr.error || "Unreachable"}
                                  </span>
                                ) : null}
                                <label className="toggle-switch" aria-label={site.enabled ? "Enabled" : "Disabled"}>
                                  <input
                                    type="checkbox"
                                    checked={!!site.enabled}
                                    onChange={(e) => toggleDredgerSite(site.id, e.target.checked)}
                                  />
                                  <span className="toggle-track" />
                                </label>
                                <button className="ghost compact" onClick={() => setDredgerEditId(site.id)} aria-label="Edit"><Icon name="edit" /></button>
                                <button className="ghost compact danger" onClick={() => deleteDredgerSite(site.id)} aria-label="Remove"><Icon name="trash" /></button>
                              </div>
                            </>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "1rem", gap: "0.5rem" }}>
              <button className="ghost" onClick={() => seedDredgerSites({ merge: true })}>
                <Icon name="plus" /> Merge Defaults
              </button>
              <button className="ghost" onClick={() => seedDredgerSites({ force: true })}>
                <Icon name="refresh" /> Reset to Defaults
              </button>
            </div>
          </>
        )}
      </article>
    </section>
  );
}
