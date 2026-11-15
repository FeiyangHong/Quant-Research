# Strategy optimization equivalence

Decision-only engineering comparison; no account backtests or return inspection.

Frozen oracle: `1096a7f`. Optimized strategy SHA256: `cd59afc451bd791fb68543422893fbe90c66ecfd54a4389e777cc6c8622ce2ae`.

All 16 synthetic rule/delay combinations match every TargetDecision field exactly. All 352 completed v1 run decision artifacts match every persisted field exactly across 25 period/rule/delay keys.

Direct frozen-oracle real-data comparisons additionally cover ranks and every warmup decision. The v1 account results remain invalidated; matching decisions does not rehabilitate execution results.

| Period | Frozen oracle seconds | Optimized seconds | Speedup | Full dataclass match |
|---|---:|---:|---:|---|
| development | 28.826 | 13.425 | 2.15x | Exact |
| validation | 72.820 | 33.055 | 2.20x | Exact |

Changes: project only strategy-used bar columns; parse TR availability once while preserving errors only when malformed rows become visible; pivot only requested dates while retaining the historical column union/order. Non-float64 values and categorical instrument IDs use the original pivot path to preserve dtype promotion and category order.

No strategy formula, candidate eligibility, chronology, parameter, rank rule, execution configuration, or account ledger is changed. Wall timings are observational and machine-load dependent.

The two direct real-data oracle calls use R1, risk_scaling=True, execution_delay=2 and signal_release_delay=1. All persisted v1 fields are compared for all 25 available period/rule/delay keys; ranks and pre-account decisions are additionally checked by those direct oracle calls and all 16 synthetic calls. The interrupted v1 attempt has no completed decision artifact and is not represented as a passing completed run.

Strategy unit tests: 24 passed in 11.55 seconds. The JSON embeds the complete decision-only comparison program and its SHA256 for reproduction; all four admitted input files are hash-checked against their dataset manifest before comparison.
