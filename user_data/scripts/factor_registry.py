"""Load and validate factors.yml registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "factors.yml"


def load_factors(path: Path = DEFAULT_REGISTRY) -> list[dict[str, Any]]:
    """Return list of factor dicts from factors.yml."""
    with path.open() as f:
        data = yaml.safe_load(f)
    return data.get("factors", [])


def load_factor_names(path: Path = DEFAULT_REGISTRY) -> list[str]:
    """Return sorted list of factor names."""
    return sorted(f["name"] for f in load_factors(path))


def load_zscore_map(path: Path = DEFAULT_REGISTRY) -> dict[str, str]:
    """Return {factor_name: zscore_column} mapping."""
    return {f["name"]: f["zscore_column"] for f in load_factors(path)}
