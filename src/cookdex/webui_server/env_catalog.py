from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvVarSpec:
    key: str
    label: str
    group: str
    default: str
    secret: bool
    description: str
    choices: tuple[str, ...] = ()


ENV_VAR_SPECS: tuple[EnvVarSpec, ...] = (
    EnvVarSpec(
        key="MEALIE_URL",
        label="Mealie Server URL",
        group="Connection",
        default="",
        secret=False,
        description="Base Mealie API URL, e.g. http://host:9000/api.",
    ),
    EnvVarSpec(
        key="MEALIE_API_KEY",
        label="Mealie API Key",
        group="Connection",
        default="",
        secret=True,
        description="Mealie API key used for organizer task execution.",
    ),
    EnvVarSpec(
        key="CATEGORIZER_PROVIDER",
        label="AI Provider",
        group="AI",
        default="chatgpt",
        secret=False,
        description="Default AI provider for categorization tasks: chatgpt or ollama.",
    ),
    EnvVarSpec(
        key="OPENAI_MODEL",
        label="OpenAI Model",
        group="AI",
        default="gpt-4o-mini",
        secret=False,
        description="OpenAI model used when provider is chatgpt.",
    ),
    EnvVarSpec(
        key="OPENAI_API_KEY",
        label="OpenAI API Key",
        group="AI",
        default="",
        secret=True,
        description="OpenAI API key used for chatgpt provider requests.",
    ),
    EnvVarSpec(
        key="OLLAMA_URL",
        label="Ollama URL",
        group="AI",
        default="http://host.docker.internal:11434/api",
        secret=False,
        description="Ollama API URL used when provider is ollama.",
    ),
    EnvVarSpec(
        key="OLLAMA_MODEL",
        label="Ollama Model",
        group="AI",
        default="mistral:7b",
        secret=False,
        description="Ollama model name for categorizer and parser flows.",
    ),
    EnvVarSpec(
        key="TAXONOMY_REFRESH_MODE",
        label="Taxonomy Refresh Mode",
        group="Behavior",
        default="merge",
        secret=False,
        description="Default taxonomy refresh mode (merge or replace).",
    ),
    EnvVarSpec(
        key="WEB_BIND_PORT",
        label="Web UI Port",
        group="Web UI",
        default="4820",
        secret=False,
        description="Web UI bind port inside container runtime.",
    ),
    EnvVarSpec(
        key="WEB_BASE_PATH",
        label="Web UI Path",
        group="Web UI",
        default="/cookdex",
        secret=False,
        description="Web UI route prefix.",
    ),
    EnvVarSpec(
        key="WEB_SESSION_TTL_SECONDS",
        label="Session Timeout (seconds)",
        group="Web UI",
        default="43200",
        secret=False,
        description="Session TTL in seconds for Web UI login cookies.",
    ),
    # ------------------------------------------------------------------
    # Direct DB access (optional — enables use_db on relevant tasks)
    # ------------------------------------------------------------------
    EnvVarSpec(
        key="MEALIE_DB_TYPE",
        label="DB Type",
        group="Direct DB",
        default="",
        secret=False,
        description="Set to 'postgres' or 'sqlite' to enable direct DB access. Leave blank to use API-only mode.",
        choices=("", "postgres", "sqlite"),
    ),
    EnvVarSpec(
        key="MEALIE_PG_HOST",
        label="Postgres Host",
        group="Direct DB",
        default="localhost",
        secret=False,
        description="Postgres server hostname or IP. Used when MEALIE_DB_TYPE=postgres.",
    ),
    EnvVarSpec(
        key="MEALIE_PG_PORT",
        label="Postgres Port",
        group="Direct DB",
        default="5432",
        secret=False,
        description="Postgres server port.",
    ),
    EnvVarSpec(
        key="MEALIE_PG_DB",
        label="Postgres Database",
        group="Direct DB",
        default="mealie_db",
        secret=False,
        description="Postgres database name.",
    ),
    EnvVarSpec(
        key="MEALIE_PG_USER",
        label="Postgres User",
        group="Direct DB",
        default="mealie__user",
        secret=False,
        description="Postgres user name.",
    ),
    EnvVarSpec(
        key="MEALIE_PG_PASS",
        label="Postgres Password",
        group="Direct DB",
        default="",
        secret=True,
        description="Postgres password (stored encrypted).",
    ),
    EnvVarSpec(
        key="MEALIE_DB_SSH_HOST",
        label="SSH Tunnel Host",
        group="Direct DB",
        default="",
        secret=False,
        description="SSH host for auto-tunnel to Postgres. Leave blank if Postgres is directly reachable.",
    ),
    EnvVarSpec(
        key="MEALIE_DB_SSH_USER",
        label="SSH Tunnel User",
        group="Direct DB",
        default="root",
        secret=False,
        description="SSH user for the tunnel host.",
    ),
    EnvVarSpec(
        key="MEALIE_DB_SSH_KEY",
        label="SSH Key Path",
        group="Direct DB",
        default="~/.ssh/cookdex_mealie",
        secret=False,
        description="Path to SSH private key file for the tunnel.",
    ),
)

ENV_SPEC_BY_KEY: dict[str, EnvVarSpec] = {item.key: item for item in ENV_VAR_SPECS}
