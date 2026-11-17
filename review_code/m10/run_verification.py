"""Capture final independent narrow checks and the exact content reviewed."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
inputs = [
    "src/quant_research/equity_features.py", "scripts/m10_preflight.py",
    "reports/m10_r2/EXPERIMENT_REGISTRY.json", "reports/m10_r2/case_inventory.json",
    "reports/m10_review/archive_hash_review.json", "review_code/m10/test_independent_m10.py",
    "docs/EQUITY_RESEARCH_PROTOCOL.md", "docs/STRATEGY_SPEC.md",
    "docs/M9_INDEPENDENT_REVIEW_AND_M10_HANDOFF_2026-11-16.md",
]


def hashes():
    return {p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in inputs}


started = datetime.now(timezone.utc).isoformat()
before = hashes()
commands = [[sys.executable, "-m", "pytest", "review_code/m10/test_independent_m10.py", "-q"],
            [sys.executable, "scripts/m10_preflight.py"]]
runs = []
for cmd in commands:
    result = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, encoding="utf-8")
    runs.append({"argv": cmd, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
after = hashes()
receipt = {"reviewer": "independent AI agent; not human acceptance", "started_at": started,
           "finished_at": datetime.now(timezone.utc).isoformat(), "content_sha256": after,
           "inputs_unchanged_during_checks": before == after, "runs": runs,
           "strategy_accounts_run": 0, "performance_metrics": None,
           "human_acceptances": 0, "source_requests": 0}
path = repo / "reports/m10_review/verification_receipt.json"
path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"inputs_unchanged": before == after, "checks": [{"exit_code": r["exit_code"], "summary": r["stdout"][:240]} for r in runs]}, indent=2))
raise SystemExit(0 if before == after and all(r["exit_code"] == 0 for r in runs) else 1)
