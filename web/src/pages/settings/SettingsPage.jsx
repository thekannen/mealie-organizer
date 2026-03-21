import React, { useState, useMemo, useRef, useEffect } from "react";
import Icon from "../../components/Icon";
import { api, normalizeErrorMessage } from "../../utils.jsx";
import { CONFIG_LABELS } from "../../constants";

const GROUP_ICONS = { Connection: "link", AI: "wand", "Direct DB": "database" };
const GROUP_DESCRIPTIONS = {
  Connection: "Mealie URL and API key",
  AI: "Provider, model, and API keys for recipe categorization",
  "Direct DB": "PostgreSQL and SSH tunnel for bulk operations",
};

export default function SettingsPage({ session, overviewMetrics, qualityMetrics, onNotice, onError }) {
  const [envSpecs, setEnvSpecs] = useState({});
  const [envDraft, setEnvDraft] = useState({});
  const [envClear, setEnvClear] = useState({});
  const [connectionChecks, setConnectionChecks] = useState({
    mealie: { loading: false, ok: null, detail: "" },
    openai: { loading: false, ok: null, detail: "" },
    anthropic: { loading: false, ok: null, detail: "" },
    ollama: { loading: false, ok: null, detail: "" },
    db: { loading: false, ok: null, detail: "" },
    dbDetect: { loading: false, ok: null, detail: "" },
  });
  const [availableModels, setAvailableModels] = useState({ openai: [], ollama: [], anthropic: [] });
  const settingsGroupRefs = useRef({});
  const [collapsedSettingsGroups, setCollapsedSettingsGroups] = useState(new Set());

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

  useEffect(() => {
    setCollapsedSettingsGroups((prev) => {
      if (prev.size > 0 || visibleEnvGroups.length === 0) return prev;
      const defaults = new Set(
        visibleEnvGroups
          .map(([group]) => group)
          .filter((group) => group !== "Connection")
      );
      return defaults;
    });
  }, [visibleEnvGroups]);

  useEffect(() => {
    loadSettings();
  }, []);

  async function loadSettings() {
    try {
      const settingsPayload = await api("/settings");
      const nextSpecs = settingsPayload?.env || {};
      setEnvSpecs(nextSpecs);
      const nextDraft = {};
      for (const [key, item] of Object.entries(nextSpecs)) {
        nextDraft[key] = item.secret ? "" : String(item.value ?? "");
      }
      setEnvDraft(nextDraft);
      setEnvClear({});
    } catch (exc) {
      onError(exc);
    }
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
      anthropic_api_key: envClear.ANTHROPIC_API_KEY ? "" : draftOverrideValue("ANTHROPIC_API_KEY"),
      ollama_url: draftOverrideValue("OLLAMA_URL"),
    };
    try {
      const result = await api(`/settings/models/${kind}`, { method: "POST", body });
      if (Array.isArray(result.models)) {
        setAvailableModels((prev) => ({ ...prev, [kind]: result.models }));

        // Auto-correct draft if current value isn't in the fetched list.
        // Prevents controlled <select> from showing one value while state
        // holds a stale one (e.g. catalog default "mistral:7b" when only
        // "llama3.1:8b" is available).
        const modelKey = kind === "openai" ? "OPENAI_MODEL" : kind === "anthropic" ? "ANTHROPIC_MODEL" : kind === "ollama" ? "OLLAMA_MODEL" : null;
        if (modelKey && result.models.length > 0) {
          setEnvDraft((prev) => {
            const current = String(prev[modelKey] ?? "").trim();
            if (!current || !result.models.includes(current)) {
              return { ...prev, [modelKey]: result.models[0] };
            }
            return prev;
          });
        }
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
          anthropic_api_key: envClear.ANTHROPIC_API_KEY ? "" : draftOverrideValue("ANTHROPIC_API_KEY"),
          anthropic_model: draftOverrideValue("ANTHROPIC_MODEL"),
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

      if (result.ok && (kind === "openai" || kind === "ollama" || kind === "anthropic")) {
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

  async function saveEnvironment() {
    try {
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
        onNotice("No setting changes to save.");
        return;
      }

      await api("/settings", {
        method: "PUT",
        body: { env },
      });

      // Only refresh settings — no need to reload tasks/runs/metrics.
      const settingsPayload = await api("/settings");
      const nextSpecs = settingsPayload?.env || {};
      setEnvSpecs(nextSpecs);
      const nextDraft = {};
      for (const [key, item] of Object.entries(nextSpecs)) {
        nextDraft[key] = item.secret ? "" : String(item.value ?? "");
      }
      setEnvDraft(nextDraft);
      setEnvClear({});
      onNotice("Settings updated.");
    } catch (exc) {
      onError(exc);
    }
  }

  function toggleSettingsGroup(name) {
    setCollapsedSettingsGroups((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function scrollToSettingsGroup(name) {
    const target = settingsGroupRefs.current[name];
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  const configuredProvider = String(envDraft["CATEGORIZER_PROVIDER"] || "").trim().toLowerCase();
  const provider = configuredProvider === "ollama" ? "ollama" : configuredProvider === "chatgpt" ? "chatgpt" : "anthropic";
  return (
    <section className="page-grid settings-grid">
      <article className="card">
        <div className="card-head split">
          <div>
            <h3><Icon name="settings" /> Environment Settings</h3>
            <p>Manage connection and AI settings used by background tasks.</p>
          </div>
          <button className="ghost" onClick={loadSettings}>
            <Icon name="refresh" />
            Reload
          </button>
        </div>

        <div className="settings-jump-nav" role="navigation" aria-label="Jump to settings section">
          {visibleEnvGroups.map(([group, items]) => (
            <button
              key={`jump-${group}`}
              type="button"
              className="chip-btn"
              onClick={() => scrollToSettingsGroup(group)}
            >
              <span>{group}</span>
              <span className="chip-count">{items.length}</span>
            </button>
          ))}
        </div>

        <div className="settings-groups">
          {visibleEnvGroups.map(([group, items]) => {
            const isCollapsed = collapsedSettingsGroups.has(group);
            return (
              <section
                key={group}
                className={`settings-group ${isCollapsed ? "collapsed" : ""}`}
                ref={(node) => {
                  if (node) settingsGroupRefs.current[group] = node;
                }}
              >
                <button
                  type="button"
                  className="settings-group-toggle"
                  onClick={() => toggleSettingsGroup(group)}
                  aria-expanded={!isCollapsed}
                >
                  <h4><Icon name={GROUP_ICONS[group] || "settings"} /> {group}</h4>
                  <span className="tiny muted">{isCollapsed && GROUP_DESCRIPTIONS[group] ? GROUP_DESCRIPTIONS[group] : `${items.length} setting${items.length === 1 ? "" : "s"}`}</span>
                  <Icon name="chevron" />
                </button>
                {!isCollapsed ? (
                  <div className="settings-rows">
                {items.map((item) => {
                  const key = String(item.key);
                  if (provider !== "chatgpt" && key.startsWith("OPENAI_")) return null;
                  if (provider !== "anthropic" && key.startsWith("ANTHROPIC_")) return null;
                  if (provider !== "ollama" && key.startsWith("OLLAMA_")) return null;
                  const hasValue = Boolean(item.has_value);
                  const source = String(item.source || "unset");
                  const draftValue = envDraft[key] ?? "";
                  const onChangeDraft = (next) => {
                    setEnvDraft((prev) => ({ ...prev, [key]: next }));
                    if (item.secret && envClear[key]) {
                      setEnvClear((prev) => ({ ...prev, [key]: false }));
                    }
                  };

                  const modelKind = key === "OPENAI_MODEL" ? "openai" : key === "ANTHROPIC_MODEL" ? "anthropic" : key === "OLLAMA_MODEL" ? "ollama" : null;
                  const modelList = modelKind ? availableModels[modelKind] || [] : [];

                  let inputElement;
                  if (key === "CATEGORIZER_PROVIDER") {
                    inputElement = (
                      <select value={provider} onChange={(e) => onChangeDraft(e.target.value)}>
                        <option value="chatgpt">ChatGPT (OpenAI)</option>
                        <option value="anthropic">Anthropic (Claude)</option>
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
                        autoComplete={item.secret ? "off" : undefined}
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
                ) : null}
              </section>
            );
          })}
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
              { id: "anthropic", label: "Test Anthropic", hint: "Validate Anthropic key and selected model.", provider: "anthropic" },
              { id: "ollama", label: "Test Ollama", hint: "Validate Ollama endpoint reachability.", provider: "ollama" },
              { id: "dbDetect", label: "Auto-detect DB", hint: "SSH into Mealie host to discover DB credentials.", requiresSsh: true },
              { id: "db", label: "Test DB", hint: "Verify direct database connection.", requiresDb: true },
            ].filter((test) => {
              if (test.provider && provider !== test.provider) return false;
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
