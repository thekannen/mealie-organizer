from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvVarSpec:
    key: str
    default: str
    secret: bool
    description: str


ENV_VAR_SPECS: tuple[EnvVarSpec, ...] = (
    EnvVarSpec(
        key="MEALIE_URL",
        default="",
        secret=False,
        description="Base Mealie API URL, e.g. http://host:9000/api.",
    ),
    EnvVarSpec(
        key="MEALIE_API_KEY",
        default="",
        secret=True,
        description="Mealie API key used for organizer task execution.",
    ),
    EnvVarSpec(
        key="CATEGORIZER_PROVIDER",
        default="chatgpt",
        secret=False,
        description="Default provider for categorization tasks: chatgpt or ollama.",
    ),
    EnvVarSpec(
        key="OPENAI_MODEL",
        default="gpt-4o-mini",
        secret=False,
        description="OpenAI model used when provider is chatgpt.",
    ),
    EnvVarSpec(
        key="OPENAI_API_KEY",
        default="",
        secret=True,
        description="OpenAI API key used for chatgpt provider requests.",
    ),
    EnvVarSpec(
        key="OLLAMA_URL",
        default="http://host.docker.internal:11434/api",
        secret=False,
        description="Ollama API URL used when provider is ollama.",
    ),
    EnvVarSpec(
        key="OLLAMA_MODEL",
        default="mistral:7b",
        secret=False,
        description="Ollama model name for categorizer and parser flows.",
    ),
    EnvVarSpec(
        key="TAXONOMY_REFRESH_MODE",
        default="merge",
        secret=False,
        description="Default taxonomy refresh mode (merge or replace).",
    ),
    EnvVarSpec(
        key="WEB_BIND_PORT",
        default="4820",
        secret=False,
        description="Web UI bind port inside container runtime.",
    ),
    EnvVarSpec(
        key="WEB_BASE_PATH",
        default="/organizer",
        secret=False,
        description="Web UI route prefix.",
    ),
    EnvVarSpec(
        key="WEB_SESSION_TTL_SECONDS",
        default="43200",
        secret=False,
        description="Session TTL in seconds for Web UI login cookies.",
    ),
)

ENV_SPEC_BY_KEY: dict[str, EnvVarSpec] = {item.key: item for item in ENV_VAR_SPECS}
