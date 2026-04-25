import React from "react";
import Icon from "../../components/Icon";
import { formatDateTime } from "../../utils.jsx";

export default function AboutPage({ aboutMeta, healthMeta, lastLoadedAt }) {
  const appVersion = aboutMeta?.app_version || healthMeta?.version || "-";
  const backendStatus = healthMeta?.ok === false ? "Degraded" : "Connected";
  const lastSyncLabel = lastLoadedAt ? formatDateTime(lastLoadedAt) : "-";
  const host = String(window?.location?.hostname || "").toLowerCase();
  const environmentLabel = host === "localhost" || host === "127.0.0.1" || host === "::1" ? "Local" : "Self-hosted";

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
              <strong>{environmentLabel}</strong>
            </li>
          </ul>
        </article>

        <article className="card">
          <h3><Icon name="shield" /> Privacy &amp; Data</h3>
          <ul className="kv-list">
            <li>
              <span>Telemetry</span>
              <strong>None</strong>
            </li>
            <li>
              <span>Analytics &amp; Tracking</span>
              <strong>None</strong>
            </li>
            <li>
              <span>Credentials</span>
              <strong>Local only, encrypted at rest</strong>
            </li>
            <li>
              <span>Network access</span>
              <strong>Your Mealie instance only</strong>
            </li>
          </ul>
          <p className="privacy-detail">
            CookDex does not phone home, collect usage data, or send
            information to any third-party service. API keys and passwords
            are stored locally in an encrypted database and never leave
            your server.
          </p>
          <p className="privacy-detail">
            If AI-powered categorization is enabled, recipe names and
            ingredient lists are sent to your configured provider
            (OpenAI, Anthropic, or Ollama). No other recipe data is transmitted.
          </p>
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

    </section>
  );
}
