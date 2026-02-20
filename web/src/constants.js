export const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: "home" },
  { id: "runs", label: "Runs", icon: "play" },
  { id: "schedules", label: "Schedules", icon: "calendar" },
  { id: "settings", label: "Settings", icon: "settings" },
  { id: "recipe-organization", label: "Recipe Organization", icon: "layers" },
  { id: "users", label: "Users", icon: "users" },
  { id: "help", label: "Help", icon: "help" },
  { id: "about", label: "About", icon: "info" },
];

export const PAGE_META = {
  overview: {
    title: "System Overview",
    subtitle: "Live summary of recipe organization coverage, run health, and Mealie metrics.",
  },
  runs: {
    title: "Runs",
    subtitle: "Run one-off tasks and review output from manual and scheduled executions.",
  },
  schedules: {
    title: "Schedules",
    subtitle: "Set recurring runs with interval or cron schedules and monitor schedule activity.",
  },
  settings: {
    title: "Settings",
    subtitle: "Configure Mealie, AI provider, and runtime behavior from one place.",
  },
  "recipe-organization": {
    title: "Recipe Organization",
    subtitle: "Manage categories, cookbooks, labels, tags, tools, and units from taxonomy files.",
  },
  users: {
    title: "Users and Access",
    subtitle: "Manage accounts, reset passwords, and keep access secure.",
  },
  help: {
    title: "Help Center",
    subtitle: "Self-contained setup and troubleshooting guidance embedded from project docs.",
  },
  about: {
    title: "About CookDex",
    subtitle: "Version, project links, and operational metrics for this deployment.",
  },
};

export const CONFIG_LABELS = {
  config: "Advanced Config",
  categories: "Categories",
  tags: "Tags",
  cookbooks: "Cookbooks",
  labels: "Labels",
  tools: "Tools",
  units_aliases: "Units",
};

export const TAXONOMY_FILE_NAMES = ["categories", "cookbooks", "labels", "tags", "tools", "units_aliases"];

export const HELP_FAQ = [
  {
    question: "Why do I need to keep the API key secret?",
    answer:
      "The key has write access to your Mealie data. Store it in Settings and avoid sharing screenshots that include connection details.",
  },
  {
    question: "Can I dry-run before applying changes?",
    answer:
      "Yes. Most tasks default to dry run. Keep Dry Run enabled when validating new taxonomy updates or parser changes.",
  },
  {
    question: "How do permissions work for team members?",
    answer:
      "Create separate user accounts for each person. Use temporary passwords and reset after onboarding for better access hygiene.",
  },
  {
    question: "What does JSON import do on Recipe Organization?",
    answer:
      "Import replaces the selected taxonomy file content with your JSON payload. Validate your JSON first and keep backups in git.",
  },
];

function inferBasePath() {
  const known = "/cookdex";
  if (window.location.pathname.startsWith(known)) {
    return known;
  }
  return "";
}

export const BASE_PATH = inferBasePath();
export const API = `${BASE_PATH}/api/v1`;
