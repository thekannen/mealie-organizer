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
    subtitle: "Define your managed taxonomy baseline, then sync it to Mealie with tasks.",
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

export const HELP_SETUP_GUIDES = [
  {
    id: "mealie-connection",
    title: "Find your Mealie URL and API Key",
    icon: "link",
    what: "CookDex needs two values to connect to your Mealie server: the API base URL and an API key with write access.",
    steps: [
      "Your Mealie URL is the address you use to open Mealie in a browser, followed by /api. For example: http://192.168.1.50:9925/api or http://mealie:9000/api (if CookDex and Mealie share a Docker network).",
      "Log into Mealie and click your user icon in the top-right corner.",
      "Open your user profile or account settings page.",
      "Scroll to API Tokens and click Create.",
      "Give the token a name (e.g. 'cookdex') and click Generate.",
      "Copy the token immediately \u2014 Mealie only shows it once.",
      "Paste both values into CookDex Settings under the Connection group, then click Test Mealie to verify.",
    ],
    tip: "If CookDex runs in Docker alongside Mealie, use the Docker service name (e.g. http://mealie:9000/api) instead of localhost.",
  },
  {
    id: "openai-api-key",
    title: "Get an OpenAI API Key",
    icon: "wand",
    what: "An OpenAI API key is required if you want to use the AI provider for recipe categorization. This is optional \u2014 rule-based categorization works without it.",
    steps: [
      "Go to platform.openai.com and sign in (or create an account).",
      "Open the API Keys page from the left sidebar.",
      "Click Create new secret key, give it a name, and click Create.",
      "Copy the key immediately \u2014 OpenAI only shows it once.",
      "In CookDex Settings, paste the key into the OpenAI API Key field under the AI group.",
      "Click Test OpenAI to verify it works.",
    ],
    tip: "OpenAI charges per API call. The default model (gpt-4o-mini) is inexpensive \u2014 categorizing 1,000 recipes typically costs under $0.50.",
  },
  {
    id: "mealie-db-credentials",
    title: "Find your Mealie Database Credentials",
    icon: "database",
    what: "Direct DB access is optional but dramatically faster for bulk tasks. You need the database credentials from your Mealie deployment.",
    steps: [
      "Open the docker-compose.yml (or .env file) used to run your Mealie server.",
      "Look for Postgres environment variables: POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB (Mealie defaults to mealie for the database name).",
      "In CookDex Settings under the Direct DB group, set DB Type to postgres.",
      "Enter the host (the server IP or Docker service name), port (default 5432), database name, username, and password.",
      "If Postgres is only reachable via SSH (e.g. a remote server), also fill in SSH Tunnel Host, SSH User, and SSH Key Path.",
      "Click Test DB to verify the connection.",
    ],
    tip: "For Mealie Docker installs using SQLite instead of Postgres, set DB Type to sqlite and provide the path to mealie.db (usually /app/data/mealie.db inside the Mealie container).",
  },
  {
    id: "ssh-tunnel-setup",
    title: "Set Up an SSH Tunnel for Database Access",
    icon: "lock",
    what: "If your Mealie Postgres database only listens on localhost (the default Docker setup), CookDex can open an SSH tunnel automatically. You just need an SSH key that can reach the server.",
    steps: [
      "On the Docker host (not inside the container), generate a dedicated SSH key: ssh-keygen -t ed25519 -f ~/.ssh/cookdex_mealie -N \"\"",
      "Copy the public key to the Mealie server: ssh-copy-id -i ~/.ssh/cookdex_mealie.pub your_user@192.168.1.100",
      "Verify SSH access works from the Docker host: ssh -i ~/.ssh/cookdex_mealie your_user@192.168.1.100 echo OK",
      "Mount the private key into the CookDex container by adding a volume to your compose.yaml: - ~/.ssh/cookdex_mealie:/app/.ssh/cookdex_mealie \u2014 then recreate the container with docker compose up -d.",
      "In CookDex Settings under Direct DB, set SSH Tunnel Host to your Mealie server\u2019s IP or hostname.",
      "Set SSH Tunnel User to the SSH user on that host.",
      "Set SSH Key Path to the container path: /app/.ssh/cookdex_mealie (not ~/.ssh \u2014 the host path doesn\u2019t exist inside the container).",
      "Leave Postgres Host as localhost and Postgres Port as 5432 \u2014 these refer to the remote server\u2019s local address after tunneling.",
      "Click Test DB to verify the full tunnel + database connection.",
    ],
    tip: "CookDex opens and closes the tunnel automatically for each task run \u2014 no background ssh process needed. The key must be mounted into the container; host paths like ~/.ssh/ are not visible inside Docker.",
  },
];

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
      "Yes. The tag-categorize task (rule-based method) assigns tags and kitchen tools using configurable regex rules — no LLM required. Edit configs/taxonomy/tag_rules.json to define ingredient, text, and instruction patterns. Enable Use Direct DB to unlock ingredient and tool-detection matching in addition to basic text rules.",
  },
  {
    question: "What does 'Use Direct DB' do?",
    icon: "database",
    answer:
      "Tasks with a Use Direct DB option bypass the Mealie HTTP API and read or write the database directly. This is much faster for large libraries and unlocks ingredient-level matching for tag-categorize (rule-based method). Configure MEALIE_DB_TYPE and credentials in Settings under the Direct DB group. An SSH tunnel is available if Postgres is not directly reachable.",
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
      "Run health-check with Use Direct DB enabled as a smoke test \u2014 it only reads data and reports results without making changes.",
    ],
  },
];

export const HELP_TASK_GUIDES = [
  {
    id: "data-maintenance",
    title: "Data Maintenance Pipeline",
    icon: "database",
    group: "Data Pipeline",
    what: "Runs the full cleanup pipeline end-to-end in a fixed stage order: dedup \u2192 junk filter \u2192 name normalize \u2192 ingredient parse \u2192 foods and units cleanup \u2192 labels and tools sync \u2192 taxonomy refresh \u2192 AI categorize \u2192 cookbook sync \u2192 yield normalize \u2192 quality audit \u2192 taxonomy audit. Select specific stages to run a targeted subset.",
    steps: [
      "Run with Dry Run enabled (the default) and review the log \u2014 no data is changed.",
      "Set the AI Provider dropdown if you want to force ChatGPT or Ollama for this run.",
      "Enable Apply Cleanup Writes to allow deduplication and cleanup stages to write changes, then re-run.",
      "Use Continue on Error to keep remaining stages running even if one fails.",
    ],
    tip: "Schedule data-maintenance monthly with Dry Run on to get an automatic status report with no risk.",
  },
  {
    id: "clean-recipes",
    title: "Clean Recipe Library",
    icon: "trash",
    group: "Actions",
    what: "Three targeted operations in one: URL-based deduplication (removes imported copies of the same recipe, keeping the most complete version), junk filter (removes non-recipe content such as listicles, how-to articles, digest posts, and placeholder instructions), and name normalizer (converts slug-derived names like 'how-to-make-chicken-pasta-recipe' into proper title case).",
    steps: [
      "Toggle off any operation you do not need \u2014 e.g. disable Normalize Names to run only dedup and junk filter.",
      "Run with Dry Run on to preview which recipes would be removed or renamed.",
      "Use the Junk Filter Category dropdown to scan for only one category of junk at a time.",
      "Disable Dry Run and confirm the policy unlock to write changes.",
    ],
    tip: "Run this first after a bulk import. The junk filter is fast and catches most non-recipe content automatically.",
  },
  {
    id: "ingredient-parse",
    title: "Ingredient Parser",
    icon: "list",
    group: "Actions",
    what: "Parses raw ingredient text (e.g. '2 cups all-purpose flour, sifted') into structured food, unit, and quantity fields in Mealie. Uses an NLP model first; falls back to AI parsing when confidence is below the threshold. Must run before foods and units cleanup stages can operate on structured data.",
    steps: [
      "Run with Dry Run on to see how many ingredients would be parsed.",
      "Lower the Confidence Threshold to accept more NLP results; raise it to push more to the AI fallback.",
      "Disable Dry Run to write results (requires policy unlock).",
      "Run cleanup-duplicates after parsing to merge any new near-duplicate food entries created during parsing.",
    ],
    tip: "Parsing is incremental \u2014 already-parsed ingredients are skipped. Re-run freely after importing new recipes.",
  },
  {
    id: "yield-normalize",
    title: "Yield Normalizer",
    icon: "refresh",
    group: "Actions",
    what: "Repairs missing or inconsistent yield data. If a recipe has a servings count but no yield text it generates one (e.g. '4 servings'). If a recipe has yield text like '8 cookies' it parses out the number and writes it to the numeric servings field.",
    steps: [
      "Run with Dry Run on to see how many recipes would be updated.",
      "Enable Use Direct DB to write all changes in a single database transaction \u2014 dramatically faster for large libraries.",
      "Disable Dry Run to apply changes (requires policy unlock; DB credentials required if using Direct DB).",
    ],
    tip: "Safe to run after every import. It only changes recipes where yield data is missing or inconsistent.",
  },
  {
    id: "cleanup-duplicates",
    title: "Clean Up Duplicates",
    icon: "copy",
    group: "Actions",
    what: "Merges duplicate food and unit entries that accumulate over time \u2014 for example 'Butter', 'butter', and 'Unsalted Butter' auto-created by Mealie's recipe scraper. Normalized duplicates are merged into the most-referenced canonical entry.",
    steps: [
      "Run with Dry Run on to preview what would be merged.",
      "Use Target to run only Foods or only Units if you do not need both.",
      "Disable Dry Run to apply merges (requires policy unlock).",
      "Re-run after ingredient-parse to resolve new duplicates created during parsing.",
    ],
    tip: "A large food library with many variants is normal after bulk importing. Run this after any parsing job.",
  },
  {
    id: "tag-categorize",
    title: "Tag and Categorize Recipes",
    icon: "tag",
    group: "Organizers",
    what: "Assigns categories, tags, and kitchen tools to recipes. AI method uses your configured LLM provider to classify recipes based on their full content. Rule-based method applies regex patterns from tag_rules.json \u2014 fast, free, and fully deterministic with no API cost.",
    steps: [
      "Select Method = Rule-Based and run with Dry Run on to see what your current rules match.",
      "Edit configs/taxonomy/tag_rules.json to add or refine patterns, then dry-run again.",
      "Enable Use Direct DB (rule-based only) to unlock ingredient and tool-detection matching in addition to text rules.",
      "Switch to Method = AI for semantic classification and optionally pick AI Provider for this run.",
    ],
    tip: "Start with rule-based to cover obvious patterns for free, then use AI mode for recipes that fall through.",
  },
  {
    id: "taxonomy-refresh",
    title: "Refresh Taxonomy",
    icon: "book-open",
    group: "Organizers",
    what: "Syncs categories, tags, labels, and tools from your local config files (configs/taxonomy/) into Mealie. Run this after editing taxonomy JSON files in the Recipe Organization page to push changes live.",
    steps: [
      "Edit taxonomy files in the Recipe Organization page or directly in configs/taxonomy/.",
      "Run with Dry Run on to preview what would change in Mealie.",
      "Use Refresh Mode = Merge (default) to add new entries without removing existing ones.",
      "Use Refresh Mode = Replace to make Mealie exactly match your source files.",
      "Enable Delete Unused Entries only when you are sure \u2014 it permanently removes categories and tags from Mealie.",
    ],
    tip: "Always preview with Dry Run before enabling Delete Unused Entries.",
  },
  {
    id: "cookbook-sync",
    title: "Cookbook Sync",
    icon: "book-open",
    group: "Organizers",
    what: "Creates and updates Mealie cookbooks to match the rules defined in your cookbook config. Cookbooks are filter-based collections \u2014 each rule defines which recipes belong based on categories, tags, or other criteria.",
    steps: [
      "Edit configs/cookbooks.json via the Recipe Organization page to define cookbook rules.",
      "Run with Dry Run on to preview what cookbooks would be created or updated.",
      "Disable Dry Run to apply changes.",
    ],
    tip: "Cookbooks update dynamically in Mealie as recipes are tagged \u2014 you only need to re-run sync when the rules themselves change.",
  },
  {
    id: "health-check",
    title: "Health Check",
    icon: "shield",
    group: "Audits",
    what: "Two read-only audits in one. Recipe Quality scores each recipe on completeness: categories, tags, tools, description, cook time, yield, and nutrition coverage. Taxonomy Audit finds unused taxonomy entries, near-duplicate names, and recipes missing categories or tags.",
    steps: [
      "Run with both scopes enabled to get a full library health report \u2014 no changes are ever made.",
      "Enable Use Direct DB for fast, exact nutrition coverage instead of a sample estimate.",
      "Review the summary card in the log output for pass/fail counts and top issues.",
      "Use the report as a prioritized action list: fix missing categories and untagged recipes first.",
    ],
    tip: "Schedule health-check monthly as a read-only report. It never writes any data.",
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
