import React from "react";

const ICON_PATHS = {
  home: (
    <>
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5 10.5V20h14v-9.5" />
      <path d="M10 20v-5h4v5" />
    </>
  ),
  play: <path d="M8 6v12l10-6-10-6Z" />,
  calendar: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 10h18" />
      <path d="M8 3v4M16 3v4" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 2.5v3M12 18.5v3M4.5 4.5l2.1 2.1M17.4 17.4l2.1 2.1M2.5 12h3M18.5 12h3M4.5 19.5l2.1-2.1M17.4 6.6l2.1-2.1" />
    </>
  ),
  layers: (
    <>
      <path d="m12 4 8 4-8 4-8-4 8-4Z" />
      <path d="m4 12 8 4 8-4" />
      <path d="m4 16 8 4 8-4" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3" />
      <circle cx="17" cy="9" r="2.2" />
      <path d="M3 19c0-2.8 2.7-5 6-5s6 2.2 6 5" />
      <path d="M14 19c.2-1.9 1.8-3.3 4-3.3 1 0 1.9.2 2.7.8" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.7 9.2a2.7 2.7 0 1 1 4.6 2c-.8.8-1.8 1.3-1.8 2.5" />
      <circle cx="12" cy="16.9" r=".8" fill="currentColor" stroke="none" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 10.5v6" />
      <circle cx="12" cy="7.5" r=".8" fill="currentColor" stroke="none" />
    </>
  ),
  refresh: <path d="M20 4v5h-5M4 20v-5h5M20 9a8 8 0 0 0-13.6-4M4 15a8 8 0 0 0 13.6 4" />,
  logout: (
    <>
      <path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" />
      <path d="M14 16l5-4-5-4" />
      <path d="M9 12h10" />
    </>
  ),
  chevron: <path d="m9 6 6 6-6 6" />,
  menu: (
    <>
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6" />
      <path d="m20 20-4.2-4.2" />
    </>
  ),
  save: (
    <>
      <path d="M5 4h12l2 2v14H5z" />
      <path d="M8 4v5h8V4" />
      <path d="M8 20v-6h8v6" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V6" />
      <path d="m8.5 9.5 3.5-3.5 3.5 3.5" />
      <path d="M5 18h14" />
    </>
  ),
  external: (
    <>
      <path d="M14 5h5v5" />
      <path d="M19 5 10 14" />
      <path d="M18 14v5H5V6h5" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 5 6v6c0 4.5 2.8 7.6 7 9 4.2-1.4 7-4.5 7-9V6z" />
      <path d="m9.5 12 1.8 1.8 3.2-3.2" />
    </>
  ),
};

export default function Icon({ name, className = "" }) {
  return (
    <svg className={`ui-icon ${className}`.trim()} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      {ICON_PATHS[name] || <circle cx="12" cy="12" r="8" />}
    </svg>
  );
}
