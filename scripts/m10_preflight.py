"""Selected offline draft guards only; no exhaustive review, run or admission mode."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path


def inspect_draft(registry, repo):
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    require(registry.get("status") == "DRAFT_NOT_AUTHORIZED", "DRAFT_STATUS_REQUIRED")
    require(registry.get("scope") == "M10_R2_DATA_AND_FIRST_SCREEN_V1", "WRONG_SCOPE")
    require(registry.get("periods") == {
        "development": ["2016-01-01", "2021-12-31"],
        "validation": ["2022-01-01", "2024-12-31"]}, "PERIODS_CHANGED")
    for key in ("real_experiments_registered", "real_experiments_run"):
        require(type(registry.get(key)) is int and registry[key] == 0, key.upper() + "_MUST_BE_ZERO")
    require(registry.get("performance_metrics") is None, "PERFORMANCE_MUST_BE_NULL")
    authorization = registry.get("authorization", {})
    for key in ("strategy_runs_permitted", "data_admission", "execution_admission", "whole_pool_period_version_chain_verified"):
        require(authorization.get(key) is False, key.upper() + "_MUST_REMAIN_FALSE")
    require(authorization.get("minimum_complete_nonduplicate_human_cases") == 20, "HUMAN_MINIMUM_CHANGED")
    require(type(authorization.get("human_approvals_verified")) is int and authorization["human_approvals_verified"] == 0,
            "NO_HUMAN_APPROVALS_IN_THIS_DRAFT")
    for key in ("actual_run_registration", "actual_code_hash", "actual_data_hash", "actual_rules_hash"):
        require(authorization.get(key) is None, "NO_ACTUAL_REGISTRATION_IN_DRAFT:" + key)
    expected_paths = {
        "base": (1, 1, 1, 0), "cost_2x": (2, 2, 2, 0),
        "cost_3x": (3, 3, 3, 0), "delay_1_session": (1, 1, 1, 1)}
    columns = ("nonstatutory_commission_multiplier", "minimum_commission_multiplier",
               "slippage_multiplier", "additional_execution_delay_sessions")
    expected_path_definitions = {p: dict(zip(columns, values)) for p, values in expected_paths.items()}
    require(registry.get("paths") == expected_path_definitions, "COST_DELAY_PATHS_CHANGED")
    expected = set(itertools.product(("development", "validation"), ("VALUE", "QUALITY", "COMBINED"), expected_paths))
    slots = registry.get("experiments", [])
    actual = [(s.get("period"), s.get("arm"), s.get("path")) for s in slots]
    require(len(slots) == 24 and len(set(actual)) == 24 and set(actual) == expected, "EXACT_24_GRID_REQUIRED")
    require(len({s.get("experiment_id") for s in slots}) == 24, "UNIQUE_SLOT_IDS_REQUIRED")
    for slot in slots:
        require(slot.get("status") == "DRAFT_NOT_AUTHORIZED" and slot.get("actual_run_id") is None
                and "performance_metrics" in slot and slot["performance_metrics"] is None
                and type(slot.get("initial_cash_cny")) is int and slot["initial_cash_cny"] == 100000,
                "SLOT_IS_NOT_UNEXECUTED_100K_DRAFT:" + str(slot.get("experiment_id")))
    require(registry.get("arms") == {"VALUE": "Z1", "QUALITY": "(Z2+Z3)/2", "COMBINED": "0.50*Z1+0.25*Z2+0.25*Z3"}, "ARMS_CHANGED")
    primary = registry.get("primary", {})
    require(all(primary.get(k) == v for k, v in {
        "period": "validation", "path": "base", "candidate": "COMBINED", "baseline": "VALUE",
        "measure": "mean_net_daily_return_difference", "M9_quadratic_utility": False}.items()), "PRIMARY_ENDPOINT_CHANGED")
    bootstrap = registry.get("bootstrap", {})
    require(all(bootstrap.get(k) == v for k, v in {
        "main_block": 60, "sensitivity_blocks": [20, 120], "repetitions": 5000,
        "seed": 20261114, "predefined_interval_count": 6, "stress_CI": False, "QUALITY_CI": False}.items()), "FIXED_SIX_INTERVALS_CHANGED")
    execution = registry.get("execution", {})
    require(all(execution.get(k) == v for k, v in {
        "stock_slippage_bp_each_side": 10, "commission_bp_each_side": 3,
        "minimum_commission_cny": 5, "statutory_rate_stress_multiplier": 1}.items()), "STOCK_COSTS_CHANGED")
    require(registry.get("valuation", {}).get("name") == "A_PRICE_ALL_ISSUED_ORDINARY_SHARES_V1", "VALUATION_CONVENTION_CHANGED")
    portfolio = registry.get("portfolio", {})
    require(all(portfolio.get(k) == v for k, v in {
        "target_count": 30, "target_weight": "1/30", "single_stock_target_cap": 0.05,
        "original_PIT_first_level_industry_max_stocks": 6, "retention_rank_at_most": 45,
        "held_rank_over_45_cannot_reenter_as_new": True}.items()), "PORTFOLIO_RULES_CHANGED")
    normalization = registry.get("normalization", {})
    require(normalization.get("neutralization_passes") == 1
            and normalization.get("common_sample_for_three_factors") is True, "NORMALIZATION_OR_COMMON_POOL_CHANGED")
    limits = registry.get("scope_limits", {})
    require(limits.get("final_holdout_start") == "2025-01-01" and limits.get("final_holdout") == "LOCKED"
            and limits.get("live_enabled") is False and limits.get("paper_enabled") is False, "HOLDOUT_OR_DEPLOYMENT_OPENED")
    bindings = dict(registry.get("definition_sources", {}))
    require(set(bindings) == {"docs/EQUITY_RESEARCH_PROTOCOL.md", "docs/STRATEGY_SPEC.md"}, "DEFINITION_BINDINGS_REQUIRED")
    task = registry.get("governing_task", {})
    if task.get("path"):
        bindings[task["path"]] = task.get("sha256")
    else:
        errors.append("GOVERNING_TASK_BINDING_MISSING")
    for relative, digest in bindings.items():
        try:
            path = (Path(repo) / relative).resolve()
            path.relative_to(Path(repo).resolve())
            require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, "DEFINITION_HASH_CHANGED:" + relative)
        except (OSError, ValueError):
            errors.append("DEFINITION_UNAVAILABLE:" + relative)
    return {
        "purpose": "OFFLINE_DRAFT_INSPECTION_NOT_ADMISSION",
        "status": "NOT_RUN_BLOCKED_ADMISSION",
        "draft_valid": not errors,
        "strategy_runs_permitted": False,
        "real_accounts_run": 0,
        "performance_metrics": None,
        "errors": errors,
        "unresolved_before_actual_registration": registry.get("unresolved_before_actual_registration", []),
        "limitation": "Selected draft guards only, not exhaustive specification validation. Draft consistency does not establish data, license, human approval, execution or runner readiness. This tool cannot authorize a run.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    registry = args.repo / "reports/m10_r2/EXPERIMENT_REGISTRY.json"
    result = inspect_draft(json.loads(registry.read_text(encoding="utf-8")), args.repo)
    result["registry_sha256"] = hashlib.sha256(registry.read_bytes()).hexdigest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["draft_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
