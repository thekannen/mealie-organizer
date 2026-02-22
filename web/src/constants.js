export const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: "home" },
  { id: "tasks", label: "Tasks", icon: "folder" },
  { id: "recipe-organization", label: "Recipe Organization", icon: "book-open" },
  { id: "users", label: "Users", icon: "user" },
  { id: "settings", label: "Settings", icon: "settings" },
  { id: "help", label: "Help", icon: "life-buoy" },
  { id: "about", label: "About", icon: "info" },
];

export const PAGE_META = {
  overview: {
    title: "System Overview",
    subtitle: "",
  },
  tasks: {
    title: "Tasks",
    subtitle: "Run, schedule, and monitor automation tasks.",
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
      "Open the Tasks page, pick a task, choose interval or cron timing, and save. Scheduled runs appear in the activity table alongside manual runs.",
  },
  {
    question: "Can I tag recipes without an AI provider?",
    icon: "tag",
    answer:
      "Yes. The rule-tag task assigns tags and kitchen tools using configurable regex rules — no LLM required. Edit configs/taxonomy/tag_rules.json to define ingredient, text, and instruction patterns. Enable Use Direct DB to unlock ingredient and tool-detection matching in addition to basic text rules.",
  },
  {
    question: "What does 'Use Direct DB' do?",
    icon: "database",
    answer:
      "Tasks with a Use Direct DB option bypass the Mealie HTTP API and read or write the database directly. This is much faster for large libraries and unlocks ingredient-level matching for rule-tag. Configure MEALIE_DB_TYPE and credentials in Settings under the Direct DB group. An SSH tunnel is available if Postgres is not directly reachable.",
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
  {
    title: "Direct DB Access",
    icon: "database",
    items: [
      "Set MEALIE_DB_TYPE to 'postgres' or 'sqlite' in Settings to enable Use Direct DB options.",
      "If Postgres is only accessible via SSH, set MEALIE_DB_SSH_HOST to your server address and ensure the SSH key is present at the path in MEALIE_DB_SSH_KEY.",
      "Run recipe-quality with Use Direct DB enabled as a smoke test \u2014 it only reads data and reports results without making changes.",
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
