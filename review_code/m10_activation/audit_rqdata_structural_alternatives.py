"""Offline installed-SDK contract audit; no SDK import, credential or network.

AST-extracted functions use synthetic transports. These checks establish client
behavior only, never entitlement, real returned values or source admission.
"""
import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


TARGETS = {
    "services/stock_status.py": ["get_shares", "get_allotment", "get_incentive_plan",
        "get_announcement", "get_restricted_shares", "get_special_treatment_info",
        "get_symbol_change_info"],
    "services/basic.py": ["get_private_placement", "get_share_transformation", "jy_instrument_industry"],
    "services/market_data.py": ["get_buy_back"],
    "services/financial.py": ["get_pit_financials_ex", "current_performance"],
    "services/shenwan.py": ["get_industry", "get_instrument_industry", "get_industry_change",
        "get_industry_mapping", "shenwan_industry", "shenwan_instrument_industry",
        "zx_industry", "zx_instrument_industry"],
    "services/convertible.py": ["get_conversion_info"],
    "services/factor.py": ["get_factor", "get_all_factor_names"],
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compiled_function(source, name, namespace):
    tree = ast.parse(source)
    node = copy.deepcopy(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name))
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "<installed-sdk-function-offline>", "exec"), namespace)
    return namespace[name]


def client_behavior(sdk):
    # Only the extracted function bodies run, with synthetic rows and a fake
    # client. No rqdatac module, real transport, license, or raw data is loaded.
    rows = []
    calls = []
    def execute(*args, **kwargs):
        calls.append((args[0], len(args)))
        return copy.deepcopy(rows)
    env = {"pd": pd, "get_client": lambda: SimpleNamespace(execute=execute),
           "ensure_order_book_ids": lambda x, **kw: x,
           "ensure_string": lambda x, *a: x,
           "ensure_string_in": lambda x, *a: x,
           "ensure_date_or_today_int": lambda x: x,
           "ensure_date_int": lambda x: x,
           "ensure_int": lambda x, *a: x,
           "ensure_list_of_string": lambda x, *a: x,
           "ensure_date_range": lambda a, b: (a, b),
           "check_items_in_container": lambda *a: None,
           "A_SHARE_SOURCES": ["citics"], "HK_SOURCES": [],
           "BUY_BACK_FIELDS": ["complete_info_date"]}
    source = (sdk / "services/shenwan.py").read_text(encoding="utf-8")
    instrument = compiled_function(source, "get_instrument_industry", env)
    rows[:] = [dict(order_book_id="SYNTHETIC", first_industry_code="SYNTHETIC",
                   first_industry_name="SYNTHETIC", published_at="2020-07-01")]
    result = instrument(["SYNTHETIC"], source="citics", date=20200731)
    retained_instrument = "published_at" in result.columns
    change = compiled_function(source, "get_industry_change", env)
    rows[:] = [dict(order_book_id="SYNTHETIC", start_date="2020-07-01",
                   cancel_date="2200-12-31", published_at="2020-06-30")]
    result = change("SYNTHETIC", source="citics", level=1)
    retained_change = "published_at" in result.columns
    env["OTHER_COLUMNS"] = ["first_industry_code", "first_industry_name",
        "second_industry_code", "second_industry_name", "third_industry_code", "third_industry_name"]
    mapping = compiled_function(source, "get_industry_mapping", env)
    rows[:] = [dict(**{k: "SYNTHETIC" for k in env["OTHER_COLUMNS"]}, published_at="2020-06-30")]
    result = mapping(source="citics", date=20200731)
    mapping_projects = "published_at" not in result.columns
    buyback = compiled_function((sdk / "services/market_data.py").read_text(encoding="utf-8"), "get_buy_back", env)
    rows[:] = [dict(order_book_id="SYNTHETIC", date="2020-07-01",
                   complete_info_date="2020-09-01", rice_create_tm=0)]
    result = buyback(["SYNTHETIC"], start_date=20200701, end_date=20200731,
                     fields=["complete_info_date"])
    future_not_filtered = result.iloc[0]["complete_info_date"] == "2020-09-01"
    return {"synthetic_not_actual_source": True, "network_calls": 0,
            "fake_transport_calls": len(calls),
            "instrument_industry_preserves_additional_server_columns": retained_instrument,
            "industry_change_preserves_additional_server_columns": retained_change,
            "industry_mapping_projects_only_codes_names": mapping_projects,
            "buyback_client_does_not_asof_filter_later_completion_field": future_not_filtered}


def inspect_sdk(sdk):
    evidence = []
    for relative, names in TARGETS.items():
        path = sdk / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in names:
            node = functions.get(name)
            if node is None:
                evidence.append(dict(file=relative, api=name, found=False))
                continue
            doc = ast.get_docstring(node) or ""
            args = [a.arg for a in node.args.args]
            clocks = [s for s in ["info_date", "initial_info_date", "first_info_date",
                "effective_date", "declaration_announcement_date", "complete_info_date",
                "write_off_date", "procedure_change_date", "start_date", "cancel_date",
                "公告", "发布日期", "入库"] if s in doc]
            evidence.append(dict(file=relative, file_sha256=sha(path), api=name,
                line=node.lineno, end_line=node.end_lineno, parameters=args,
                documented_clock_tokens=clocks,
                has_explicit_date_parameter=any(a in args for a in ["date", "info_date", "start_date", "end_date"]),
                note="Client/docstring evidence only; returned server schema, permission and vintage not inferred."))
    fields_file = sdk / "services/orm/pit_financials_ex.py"
    tree = ast.parse(fields_file.read_text(encoding="utf-8"))
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    field_check = {n: n in strings for n in ["total_shares", "total_a_shares", "paid_in_capital", "equity_preferred_stock", "treasury_stock"]}
    return evidence, dict(file=str(fields_file.relative_to(sdk)), sha256=sha(fields_file), fields=field_check)


def original_availability(root):
    sources = []
    coverage = json.loads((root / "reports/m5_market_cap/coverage_summary.json").read_text())
    for case in coverage["cases"]:
        source = case["document_source"]
        sources.append(dict(role="PRIOR_M5_SHARE_DOCUMENT", security=case["instrument_id"],
            path=source["raw_path"], sha256=source["sha256"], url=source["url"],
            published=case["original_document_fact"]["published"],
            limited_to="Prior registered documentary fact, not full chain or all five campus share identities"))
    m4 = json.loads((root / "reports/m4_data/source_manifest.json").read_text())
    for source in m4["raw_objects"]:
        if "csrc_industry_2020q2" in source["path"] or "shijia_industry_change" in source["path"]:
            sources.append(dict(role="PRIOR_CSRC_INDUSTRY_NOT_CITICS", path=source["path"],
                sha256=source["sha256"], url=source["source_url"],
                limited_to="CSRC2012 snapshot/publication page or single-issuer change; cannot silently replace CITICS"))
    for row in sources:
        normalized = row["path"].replace("\\", "/")
        rel = normalized[normalized.index("data/"):]
        local = root / rel
        row.update(local_path=str(local), exists=local.is_file(),
                   local_hash_match=(sha(local) == row["sha256"]) if local.is_file() else None)
    return sources


def audit(root, sdk):
    inventory, fields = inspect_sdk(sdk)
    behavior = client_behavior(sdk)
    assert all(behavior[k] for k in ["instrument_industry_preserves_additional_server_columns",
        "industry_change_preserves_additional_server_columns", "industry_mapping_projects_only_codes_names",
        "buyback_client_does_not_asof_filter_later_completion_field"])
    originals = original_availability(root)
    return dict(task="M10_SOURCE_ACTIVATION_V1", observed_at=datetime.now(timezone.utc).isoformat(),
        scope="OFFLINE_ALTERNATIVE_PATH_REVIEW_NOT_SOURCE_ADMISSION", source_requests=0,
        credentials_read=False, sdk_imported=False, actual_vendor_payload_read=False,
        api_inventory=inventory, pit_share_fields=fields, synthetic_client_behavior=behavior,
        previous_originals_availability=originals,
        previous_originals_present=sum(r["exists"] for r in originals),
        conclusion="SOURCE_CAPABILITY_UNRESOLVED_WITH_CONCRETE_ALTERNATIVES_NOT_PROVIDER_WIDE_FAILURE",
        full_sample_passed=False, complete_cards=0, human_acceptances=0, actual_r2_accounts=0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sdk-path", required=True, help="rqdatac package directory")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(Path(args.root).resolve(), Path(args.sdk_path).resolve())
    with Path(args.output).open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(dict(apis=len(result["api_inventory"]),
        offline_client_checks=4, source_requests=0,
        old_originals_present=result["previous_originals_present"])))
