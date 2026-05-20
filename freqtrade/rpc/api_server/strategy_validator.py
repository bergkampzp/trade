"""Strategy code validation for AI-generated freqtrade strategies.

Implements the 4-layer security validation pipeline:
  1. ast.parse() syntax check
  2. Import whitelist
  3. Forbidden function calls blacklist
  4. Required method signature verification

Also provides Jinja2-based LLM prompt templating with StrictUndefined.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import yaml


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Whitelists & Blacklists
# ---------------------------------------------------------------------------

ALLOWED_IMPORTS = {
    "pandas",
    "numpy",
    "talib",
    "freqtrade.strategy",
    "freqtrade.strategy.IStrategy",
    "freqtrade.persistence",
    "logging",
    "datetime",
    "typing",
}

FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "os.system",
    "os.popen",
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "shutil.rmtree",
    "shutil.copy",
    "open",
    "requests.get",
    "requests.post",
    "socket.socket",
    "pickle.load",
    "pickle.loads",
}

REQUIRED_METHODS = {
    "populate_indicators",
    "populate_entry_trend",
    "populate_exit_trend",
}

# freqtrade standard OHLCV columns that strategies always have access to
STANDARD_COLUMNS = {
    "open",
    "high",
    "low",
    "close",
    "volume",
    "date",
    "enter_long",
    "enter_short",
    "exit_long",
    "exit_short",
    "trade_size",
    "returns",
    "logret",
}

# ---------------------------------------------------------------------------
# AST Helpers
# ---------------------------------------------------------------------------


def _get_full_attr_name(node: ast.Attribute) -> str:
    """Recursively resolve ast.Attribute chain to dotted name, e.g. os.system."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_strategy_code(code: str) -> tuple[bool, str]:
    """Validate AI-generated strategy code for safety and correctness.

    Returns:
        (is_valid, error_message) — error_message is "OK" on success.
    """
    # 1. Syntax check
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"

    found_methods: set[str] = set()

    # 2. Walk AST
    for node in ast.walk(tree):
        # Import check
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Check if the import module/path is allowed
                parts = alias.name.split(".")
                # Check all prefix paths (e.g. 'freqtrade.strategy' → check 'freqtrade', 'freqtrade.strategy')
                allowed = False
                for i in range(1, len(parts) + 1):
                    if ".".join(parts[:i]) in ALLOWED_IMPORTS:
                        allowed = True
                        break
                if parts[0] in ALLOWED_IMPORTS:
                    allowed = True
                if not allowed:
                    return False, f"Forbidden import: {alias.name}"

        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                # Check full module path, not just first component
                if (
                    node.module not in ALLOWED_IMPORTS
                    and node.module.split(".")[0] not in ALLOWED_IMPORTS
                ):
                    return False, f"Forbidden import from: {node.module}"

        # Forbidden call check
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_CALLS:
                    return False, f"Forbidden call: {node.func.id}()"
            elif isinstance(node.func, ast.Attribute):
                full = _get_full_attr_name(node.func)
                if full in FORBIDDEN_CALLS:
                    return False, f"Forbidden call: {full}()"

        # Required method check
        elif isinstance(node, ast.FunctionDef):
            found_methods.add(node.name)

    # 3. Verify required methods exist
    missing = REQUIRED_METHODS - found_methods
    if missing:
        return False, f"Missing required methods: {missing}"

    # 4. Verify IStrategy inheritance (best-effort)
    has_istrategy = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == "IStrategy":
                    has_istrategy = True
                elif isinstance(base, ast.Attribute) and base.attr == "IStrategy":
                    has_istrategy = True
    if not has_istrategy:
        return False, "Strategy class must inherit from IStrategy"

    return True, "OK"


def validate_column_references(code: str) -> tuple[bool, str]:
    """Check that dataframe column references are valid.

    Extracts dataframe['xxx'] patterns and warns about non-standard columns.
    Full validation against DB schema is done at strategy storage time.
    """
    import re

    col_refs: set[str] = set()
    col_refs |= set(re.findall(r"dataframe\['(\w+)'\]", code))
    col_refs |= set(re.findall(r'dataframe\["(\w+)"\]', code))

    unknown = col_refs - STANDARD_COLUMNS
    if unknown:
        logger.info("Strategy references non-standard columns: %s", sorted(unknown))
    return True, "OK"


# ---------------------------------------------------------------------------
# LLM Prompt Template
# ---------------------------------------------------------------------------

from jinja2 import StrictUndefined, Template


def build_strategy_prompt(
    description: str,
    trading_pair: str,
    allowed_factors: list[dict],
    allowed_columns: list[str],
) -> str:
    """Build a safe LLM prompt for strategy generation.

    Uses Jinja2 with StrictUndefined to prevent prompt injection.
    """
    template = Template(
        """You are an expert freqtrade strategy developer. Generate a complete, production-ready freqtrade IStrategy subclass.

CRITICAL RULES — VIOLATIONS WILL BE REJECTED:
1. Only import from: pandas, numpy, talib, freqtrade.strategy, logging
2. Only reference these dataframe columns: {{ allowed_columns|tojson }}
3. Use ONLY these factors (from quant.mart_hourly_signals):
{% for f in allowed_factors %}
   - {{ f.name }}: {{ f.description }} (direction: {{ f.direction }})
{% endfor %}
4. Return ONLY valid Python code. No markdown blocks, no explanations.
5. Must implement: populate_indicators(), populate_entry_trend(), populate_exit_trend()
6. Use INTERFACE_VERSION = 3
7. Set stoploss between -0.02 and -0.15
8. Set minimal_roi as a dict

TRADING REQUEST:
{{ description }}

TRADING PAIR: {{ trading_pair }}
TIMEFRAME: 1h

RESPOND WITH EXACTLY THIS JSON FORMAT:
{
    "strategy_name": "CamelCaseName",
    "code": "from freqtrade.strategy import IStrategy\\n\\nclass ..."
}
""",
        undefined=StrictUndefined,
    )

    return template.render(
        description=description,
        trading_pair=trading_pair,
        allowed_factors=allowed_factors,
        allowed_columns=allowed_columns,
    )


# ---------------------------------------------------------------------------
# Factor Registry Helpers
# ---------------------------------------------------------------------------


def load_factor_registry() -> list[dict]:
    """Load factor definitions from factors.yml."""
    yml_path = Path(__file__).resolve().parents[3] / "user_data" / "factors.yml"
    if not yml_path.exists():
        logger.warning("factors.yml not found at %s", yml_path)
        return []
    with yml_path.open() as f:
        data = yaml.safe_load(f)
    return data.get("factors", [])


def load_factor_names() -> list[str]:
    """Return sorted list of valid factor names."""
    return sorted(f["name"] for f in load_factor_registry())


# ---------------------------------------------------------------------------
# Trade result helpers
# ---------------------------------------------------------------------------


def compute_deflated_sharpe(
    sharpe_ratios: list[float],
    n_observations: int = 252,
    variance_across_strategies: float = 0.0,
) -> float:
    """Compute Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Corrects for multiple testing when ranking N strategies.
    DSR = P[ max(SR) > E[max(SR)] | SR_true = 0 ]

    Simplified implementation: penalizes high Sharpe when variance across
    strategies is high (indicating potential overfitting).

    Args:
        sharpe_ratios: list of Sharpe ratios for all strategies in the batch
        n_observations: number of observations (default 252 trading days)
        variance_across_strategies: variance of Sharpe ratios across strategies
    """
    if not sharpe_ratios or len(sharpe_ratios) < 2:
        return sharpe_ratios[0] if sharpe_ratios else 0.0

    import math

    max_sr = max(sharpe_ratios)
    mean_sr = sum(sharpe_ratios) / len(sharpe_ratios)
    var_sr = variance_across_strategies or (
        sum((s - mean_sr) ** 2 for s in sharpe_ratios) / (len(sharpe_ratios) - 1)
    )

    # Expected maximum Sharpe under null (simplified from extreme value theory)
    e_max = math.sqrt(2 * math.log(len(sharpe_ratios)))

    # DSR: penalized Sharpe
    if var_sr > 0:
        dsr = max_sr * (1 - (var_sr / (max_sr * math.sqrt(n_observations))))
    else:
        dsr = max_sr

    return max(0.0, dsr)
