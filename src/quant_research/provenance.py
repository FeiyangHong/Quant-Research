"""Content-addressed provenance and append-only local trial events."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_provenance(root):
    root = Path(root)
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], text=True, encoding="utf-8").strip()
    files = {}
    for directory in ("src", "configs", "tests", "scripts"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("requirements.lock", "pyproject.toml"):
        files[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    for name in ("STRATEGY_SPEC.md", "EXPERIMENT_PLAN.md", "RISK_POLICY.md", "DATA_CONTRACT.md"):
        files["docs/" + name] = hashlib.sha256((root / "docs" / name).read_bytes()).hexdigest()
    return {"git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain")),
            "source_hash": digest(files), "source_files": files,
            "python": platform.python_version(), "platform": platform.platform(),
            "dependencies": {p: importlib.metadata.version(p) for p in ("numpy", "pandas", "scipy")}}


def append_event(path, event):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    record = dict(event, recorded_at=datetime.now(timezone.utc).isoformat())
    # Exclusive process-level runner below prevents concurrent writers.
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(canonical_bytes(record).decode("utf-8") + "\n")


def validate_run_config(config):
    allowed = {"protocol_version", "live_enabled", "sample", "universe", "variant", "initial_cash",
               "primary_capital_confirmed", "annual_incremental_cost", "risk_scaling", "execution_delay",
               "cost_multiplier", "slippage_multiplier", "seed", "claim_type", "cash_delay_sessions", "signal_release_delay"}
    if set(config) - allowed:
        raise ValueError("Unknown configuration keys: " + str(sorted(set(config) - allowed)))
    for key in ("risk_scaling", "primary_capital_confirmed"):
        if key in config and type(config[key]) is not bool:
            raise ValueError(key + " must be a boolean")
    for key in ("initial_cash", "execution_delay", "cost_multiplier", "slippage_multiplier", "seed", "cash_delay_sessions", "signal_release_delay"):
        if key in config and type(config[key]) is not int:
            raise ValueError(key + " must be an integer, not a boolean or string")
    if config.get("protocol_version", "phase2-mvp-0.1") != "phase2-mvp-0.1":
        raise ValueError("Unknown protocol version")
    if config.get("claim_type", "economic_increment") != "economic_increment":
        raise ValueError("Only registered economic_increment is supported")
    if config.get("live_enabled") is not False:
        raise ValueError("Only explicit live_enabled=false is supported")
    if config.get("sample") not in ("development", "validation", "synthetic"):
        raise ValueError("Final holdout is locked; milestone review and frozen protocol required")
    if config.get("universe") != "R1B":
        raise ValueError("R1I remains BLOCKED_DATA pending audited historical industry mapping")
    if config.get("variant") not in ("E0", "R0", "E1", "R1"):
        raise ValueError("Unregistered strategy variant")
    if config.get("initial_cash") not in (10000, 100000, 500000, 1000000):
        raise ValueError("Unregistered capital scenario")
    if config.get("execution_delay", 1) not in (1, 2):
        raise ValueError("Unregistered execution delay")
    if config.get("cash_delay_sessions", 0) not in (0, 1, 3):
        raise ValueError("Unregistered cash settlement delay")
    if config.get("signal_release_delay", 0) not in (0, 1):
        raise ValueError("Unregistered signal release delay")
    if config.get("cost_multiplier", 1) not in (1, 2, 3) or config.get("slippage_multiplier", 1) not in (0, 1, 2, 3):
        raise ValueError("Unregistered cost stress")
    if config.get("annual_incremental_cost") is not None:
        cost = config["annual_incremental_cost"]
        if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
            raise ValueError("Fixed cost must be finite and nonnegative")
