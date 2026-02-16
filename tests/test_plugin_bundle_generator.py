from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_generator_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "install" / "generate_plugin_bundle.py"
    spec = importlib.util.spec_from_file_location("generate_plugin_bundle", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_discover_port_from_inline_mapping(tmp_path):
    mod = _load_generator_module()
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(
        """
services:
  mealie:
    ports:
      - "9925:9000"
""".strip(),
        encoding="utf-8",
    )
    discovered = mod.discover_port_from_compose(compose_path)
    assert discovered is not None
    assert discovered.port == 9925


def test_discover_port_from_long_syntax(tmp_path):
    mod = _load_generator_module()
    compose_path = tmp_path / "compose.yaml"
    compose_path.write_text(
        """
services:
  mealie:
    ports:
      - target: 9000
        published: 8822
""".strip(),
        encoding="utf-8",
    )
    discovered = mod.discover_port_from_compose(compose_path)
    assert discovered is not None
    assert discovered.port == 8822


def test_discover_public_port_prefers_explicit_value(tmp_path):
    mod = _load_generator_module()
    discovered = mod.discover_public_port(tmp_path, 7777)
    assert discovered.port == 7777
    assert discovered.source == "--public-port"
