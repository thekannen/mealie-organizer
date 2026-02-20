export const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: "home" },
  { id: "runs", label: "Runs", icon: "folder" },
  { id: "schedules", label: "Schedules", icon: "calendar" },
  { id: "settings", label: "Settings", icon: "settings" },
  { id: "recipe-organization", label: "Recipe Organization", icon: "book-open" },
  { id: "users", label: "Users", icon: "user" },
  { id: "help", label: "Help", icon: "life-buoy" },
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
    subtitle: "Answers to common questions, troubleshooting tips, and reference guides you can read without leaving the app.",
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
    question: "Can I dry-run before applying changes?",
    icon: "shield",
    answer:
      "Yes. Most tasks default to dry run. Keep Dry Run enabled when validating new taxonomy updates or parser changes. Only disable it when you are ready to write changes to Mealie.",
  },
  {
    question: "Why did my JSON import skip values?",
    icon: "upload",
    answer:
      "Import replaces the selected taxonomy file with your JSON payload. If entries are malformed or duplicated the server will silently drop them. Validate your JSON and check the run log for details.",
  },
  {
    question: "How do permissions work for team members?",
    icon: "users",
    answer:
      "Create separate user accounts on the Users page. Assign the Viewer role for read-only access or Editor for full task execution. Use temporary passwords and rotate after onboarding.",
  },
  {
    question: "How do I schedule recurring tasks?",
    icon: "calendar",
    answer:
      "Open the Schedules page, pick a task, choose interval or cron timing, and save. Scheduled runs appear in the activity table and their logs are accessible from the Runs page.",
  },
];

export const HELP_TROUBLESHOOTING = [
  {
    title: "Connection and Authentication Issues",
    icon: "shield",
    items: [
      "Verify MEALIE_URL and MEALIE_API_KEY are correct in Settings.",
      "Use the Test Connection button to confirm the backend can reach Mealie.",
      "If login fails, check that WEB_COOKIE_SECURE matches your protocol (false for HTTP).",
    ],
  },
  {
    title: "Import and Taxonomy Validation",
    icon: "upload",
    items: [
      "JSON imports fully replace the target taxonomy file \u2014 back up first.",
      "Entries must be valid JSON arrays. Objects need at least a \"name\" field.",
      "After import, run taxonomy-refresh with dry run to preview what changed.",
    ],
  },
  {
    title: "Runs, Scheduling, and Logs",
    icon: "play",
    items: [
      "Click any row in the run history table to load its log output.",
      "Cancelled runs stop at the next safe checkpoint, not immediately.",
      "Scheduled runs use the server clock \u2014 cron expressions follow UTC unless configured otherwise.",
    ],
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
