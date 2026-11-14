"""Historical ETF discovery and conservative R1B candidate classification.

Snapshots and current names discover candidates; neither establishes a complete
lifespan universe or a historical classification without official documents.
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import copy
import importlib.metadata
import io
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quant_research.providers.baostock import canonical, write_immutable, HISTORY_END, SDK_VERSION


def quarter_sessions(sessions):
    grouped = {}
    for day in sorted(set(sessions)):
        parsed = date.fromisoformat(day)
        if day > HISTORY_END:
            raise ValueError("Final holdout is locked")
        grouped[(parsed.year, (parsed.month - 1) // 3)] = day
    return list(grouped.values())


def classify_name(name):
    """Name screening only; exact benchmark confirmation remains required."""
    normalized = re.sub(r"[\s\-·]", "", name).upper()
    # These are issuer names, not thematic/style words in the tracked index.
    # Preserve original names as evidence; strip only for heuristic screening.
    for issuer in ("中银证券", "红土创新"):
        normalized = normalized.replace(issuer, "")
    # The legal fund-type suffix contains 证券; it is not a securities-sector
    # index. Official disclosure titles use this suffix unlike short names.
    normalized = normalized.split("交易型", 1)[0]
    excluded = ["增强", "ESG", "红利", "价值", "质量", "成长", "低波", "等权", "行业", "联接", "期权", "指数优化", "医药", "消费", "信息", "金融", "地产", "科技", "材料", "工业", "能源", "精选", "智能", "债", "互联", "人工", "创新", "芯片", "半导体", "非银", "证券", "保险", "银行", "央企", "民企", "国企", "盈利", "有色", "汽车", "农业", "军工", "环保", "医疗", "通信", "电力", "装备", "光伏"]
    # 科创50 itself is the named broad benchmark; 科创50增强 is not its
    # passive replica. Retain exclusions as visible inventory records.
    base = None
    if "沪深300" in normalized:
        base = "CSI300"
    elif "中证500" in normalized:
        base = "CSI500"
    elif "中证1000" in normalized:
        base = "CSI1000"
    elif "科创创业50" in normalized or "双创50" in normalized:
        base = "STAR_CHINEXT50"
    elif "创业板" in normalized or "创业50" in normalized:
        base = ("CHINEXT50" if "50" in normalized else ("CHINEXT200" if "200" in normalized else
                ("CHINEXT300" if "300" in normalized else ("CHINEXT_LARGE_CAP" if "大盘" in normalized else
                ("CHINEXT_COMPOSITE" if "综" in normalized else "CHINEXT")))))
    elif "科创50" in normalized or "科创板50" in normalized:
        base = "STAR50"
    elif "科创" in normalized:
        base = "STAR100" if "100" in normalized else ("STAR200" if "200" in normalized else "STAR_OTHER")
    elif "北证" in normalized or "北交" in normalized:
        base = "BSE"
    if base is None:
        return {"category": None, "classification_status": "OUTSIDE_NAMED_R1B_GROUPS", "reason": "No named broad benchmark match"}
    matches = [word for word in excluded if word in normalized]
    if matches:
        return {"category": base, "classification_status": "RELATED_EXCLUDED_OR_REVIEW", "reason": "Nonplain benchmark/structure marker: " + ",".join(matches)}
    if base in {"STAR_OTHER", "BSE"}:
        return {"category": base, "classification_status": "RELATED_EXCLUDED_OR_REVIEW", "reason": "Additional benchmark requires explicit protocol classification"}
    return {"category": base, "classification_status": "NAME_CANDIDATE_REQUIRES_OFFICIAL_BENCHMARK", "reason": "Broad-name screen, not verified PIT benchmark"}


EXACT_BENCHMARKS = {
    "沪深300指数": "CSI300",
    "中证500指数": "CSI500",
    "中证1000指数": "CSI1000",
    "创业板指数": "CHINEXT",
    "创业板50指数": "CHINEXT50",
    "创业板中盘200指数": "CHINEXT200",
    "创业板300指数": "CHINEXT300",
    "创业板综合指数": "CHINEXT_COMPOSITE",
    "创业板大盘指数": "CHINEXT_LARGE_CAP",
    "上证科创板50成份指数": "STAR50",
    "上证科创板100指数": "STAR100",
    "上证科创板200指数": "STAR200",
    "中证科创创业50指数": "STAR_CHINEXT50",
    "北证50成份指数": "BSE50",
}


def documented_benchmarks(text):
    """Exact disclosed index names, without merging regional/style subindices.

    PDF table extraction can insert the repeated column heading within an index
    name. Remove that known heading, preserving the original evidence elsewhere.
    Matching is retrospective evidence; it does not backdate publication.
    """
    text = re.sub(r"\s+", "", text or "").replace("业绩比较基准", "")
    return sorted({category for name, category in EXACT_BENCHMARKS.items() if name in text})


def reconcile_inventory(inventory, evidence_records):
    """Attach official disclosures; keep unresolved or contradictory identities.

    evidence_records use collector by_instrument JSON objects with candidate,
    identity_evidence and annual_evidence fields. Classification never supplies
    a historical effective date: the original publication date remains explicit.
    """
    result = {row["code"]: copy.deepcopy(row) for row in inventory}
    for evidence in evidence_records:
        code = evidence["candidate"]["code"]
        if code not in result:
            continue
        item = result[code]
        identity = evidence.get("identity_evidence") or {}
        item.setdefault("official_identity_evidence", [])
        if identity and identity not in item["official_identity_evidence"]:
            item["official_identity_evidence"].append(copy.deepcopy(identity))
        item.setdefault("official_annual_evidence", [])
        for annual in evidence.get("annual_evidence", []):
            if annual not in item["official_annual_evidence"]:
                item["official_annual_evidence"].append(copy.deepcopy(annual))
        item.setdefault("official_listing_evidence", [])
        for listing in evidence.get("listing_evidence", []):
            if listing not in item["official_listing_evidence"]:
                item["official_listing_evidence"].append(copy.deepcopy(listing))
    for item in result.values():
        identities = item.get("official_identity_evidence", [])
        annuals = item.get("official_annual_evidence", [])
        listings = item.get("official_listing_evidence", [])
        names = [x.get("name", "") for x in identities if x.get("name")]
        texts = [x.get("benchmark_text") for x in annuals] + [x.get("benchmark") for x in identities]
        indices = sorted({i for text in texts for i in documented_benchmarks(text)})
        item["documented_index_categories"] = indices
        item["benchmark_evidence_is_historical_effective_interval"] = False
        # Preserve erroneous preliminary notices, but final/correction notice
        # evidence takes precedence. Never choose the minimum reported date.
        definitive = [x for x in listings if x.get("is_final_version") or x.get("is_correction")]
        preferred = definitive or listings
        original_dates = {x["listed_on"] for x in preferred if x.get("listed_on")}
        item["documented_listing_dates"] = sorted(original_dates or {x["listed_on_evidence"] for x in annuals + identities if x.get("listed_on_evidence")})
        item["original_notice_index_ids"] = sorted({x["benchmark_id"] for x in preferred if x.get("benchmark_id")})
        item["original_notice_has_unresolved_index"] = any(not x.get("benchmark_id") for x in preferred)
        item["original_notice_conflicts_with_later_index"] = bool(indices and item["original_notice_index_ids"] and set(indices) != set(item["original_notice_index_ids"]))
        item["original_notice_requires_timeline_review"] = item["original_notice_has_unresolved_index"] or item["original_notice_conflicts_with_later_index"]
        named = [classify_name(name) for name in names]
        candidate_names = [x for x in named if x["classification_status"] == "NAME_CANDIDATE_REQUIRES_OFFICIAL_BENCHMARK"]
        originally_candidate = item["classification_status"] == "NAME_CANDIDATE_REQUIRES_OFFICIAL_BENCHMARK"
        ambiguous_broad = item.get("category") in {"STAR_OTHER", "BSE"} and item.get("reason", "").startswith("Additional benchmark")
        if len(indices) == 1:
            item["category"] = indices[0]
            item["documentary_status"] = "EXACT_INDEX_DISCLOSED_EFFECTIVE_INTERVAL_UNVERIFIED"
            # An enhanced/style title cannot become passive merely because its
            # performance comparator is a broad index. Preserve review status.
            item["candidate_for_history_collection"] = originally_candidate or bool(candidate_names) or ambiguous_broad or item["classification_status"] == "UNRESOLVED_NAME"
        elif len(indices) > 1:
            item["documentary_status"] = "MULTIPLE_EXACT_INDICES_REQUIRE_TIMELINE"
            item["candidate_for_history_collection"] = True
        elif any(texts):
            item["documentary_status"] = "DISCLOSED_BENCHMARK_OUTSIDE_EXACT_SCOPE_OR_REQUIRES_REVIEW"
            item["candidate_for_history_collection"] = originally_candidate or ambiguous_broad
        else:
            item["documentary_status"] = "NO_EXTRACTED_OFFICIAL_BENCHMARK"
            item["candidate_for_history_collection"] = originally_candidate or bool(candidate_names) or ambiguous_broad
            if candidate_names:
                item["category"] = candidate_names[0]["category"]
        item["official_name_recovered"] = bool(names)
    return sorted(result.values(), key=lambda x: x["code"])


def provisional_amount_representatives(calendar, candidates, histories, master_records=None):
    """Independent decimal ADV60 cross-check; never a historical PIT approval.

    Candidates with missing official dates/index evidence stay in competition
    using their explicitly marked discovery metadata. The resulting schedule is
    provisional until those dependencies are closed. Listing age is a monthly
    entry rule, not a quarterly-representative rule, so no 252-day filter here.
    """
    days = sorted(set(calendar))
    if days != calendar or any(day > HISTORY_END for day in days):
        raise ValueError("Unique ordered historical exchange calendar required")
    missing = sorted({row["code"] for row in candidates} - set(histories))
    if missing:
        raise ValueError("Cannot select over partial histories: " + ",".join(missing))
    if master_records is not None:
        missing_master = sorted({row["code"] for row in candidates} - {row["instrument_id"] for row in master_records})
        if missing_master:
            raise ValueError("Incomplete original master chronology: " + ",".join(missing_master))
    by_code = {}
    metadata_gaps = []
    for candidate in candidates:
        code = candidate["code"]
        records = histories[code]
        if not records:
            raise ValueError("Empty history for historically observed candidate: " + code)
        indexed = {row["date"]: row for row in records}
        if len(indexed) != len(records):
            raise ValueError("Duplicate raw historical dates: " + code)
        listed = candidate.get("documented_listing_dates", [])
        if len(listed) == 1:
            listed_on, basis = listed[0], "OFFICIAL_DOCUMENT_EXTRACT"
        else:
            listed_on = candidate.get("listing_date_from_current_master") or min(indexed, default="9999-12-31")
            basis = "UNVERIFIED_CURRENT_MASTER_OR_FIRST_RAW_BAR"
        if basis != "OFFICIAL_DOCUMENT_EXTRACT" or not candidate.get("documented_index_categories") or candidate.get("original_notice_requires_timeline_review"):
            metadata_gaps.append({"code": code, "listing_basis": basis, "category": candidate.get("category"),
                                  "original_notice_requires_timeline_review": candidate.get("original_notice_requires_timeline_review", False)})
        by_code[code] = (candidate, indexed, listed_on)
    schedule, required, conflicts = [], set(), []
    for position, day in enumerate(days):
        quarter = (day[:4], (int(day[5:7]) - 1) // 3)
        if position:
            previous_day = days[position - 1]
            previous_quarter = (previous_day[:4], (int(previous_day[5:7]) - 1) // 3)
            if quarter == previous_quarter:
                continue
        if position < 60:
            schedule.append({"quarter_start": day, "cutoff": days[position - 1] if position else None,
                             "representatives": [], "reason": "INSUFFICIENT_60_SESSION_HISTORY"})
            continue
        previous = days[position - 1]
        window = days[position - 60:position]
        ranked = {}
        for code, (candidate, indexed, listed_on) in by_code.items():
            category = candidate.get("category")
            if master_records is not None:
                at = datetime.fromisoformat(previous + "T21:00:00+08:00")
                versions = []
                for row in master_records:
                    if row["instrument_id"] != code:
                        continue
                    known = datetime.fromisoformat(row["available_at"])
                    benchmark_known = datetime.fromisoformat(row.get("benchmark_source_available_at") or row["available_at"])
                    if known.tzinfo is None or benchmark_known.tzinfo is None:
                        raise ValueError("Original metadata availability requires timezone")
                    if known > at or benchmark_known > at or (row.get("effective_from") and row["effective_from"] > previous) or (row.get("effective_to") and row["effective_to"] <= previous):
                        continue
                    versions.append((known, row))
                if not versions:
                    continue
                if len({known for known, _ in versions}) != len(versions):
                    raise ValueError("Ambiguous master revisions at equal availability: " + code)
                _, master = max(versions, key=lambda pair: pair[0])
                if master.get("strategy_universe") != "R1B" or (master.get("delisted_on") and master["delisted_on"] <= previous):
                    continue
                listed_on, category = master["listed_on"], master["benchmark_id"]
            if listed_on > previous or not category:
                continue
            bar = indexed.get(previous)
            if not bar or bar.get("suspended") is not False:
                continue
            if previous not in candidate.get("snapshot_dates", []):
                conflicts.append({"code": code, "date": previous, "reason": "NORMAL_RAW_BAR_ABSENT_ENDPOINT_MEMBERSHIP"})
            try:
                amounts = [Decimal(indexed[d]["amount"]) for d in window]
            except (KeyError, TypeError, InvalidOperation):
                continue
            if any(not a.is_finite() or a < 0 for a in amounts):
                continue
            ranked.setdefault(category, []).append((-sum(amounts), listed_on, code))
        winners = {}
        for benchmark, competitors in sorted(ranked.items()):
            total, _, code = min(competitors)
            winners[benchmark] = {"code": code, "adv60": str(-total / Decimal(60)),
                                  "valid_competitor_count": len(competitors)}
            required.add(code)
        schedule.append({"quarter_start": day, "cutoff": previous, "representatives": sorted(x["code"] for x in winners.values()),
                         "by_exact_index": winners})
    return {"status": "PROVISIONAL_AMOUNT_ONLY_NOT_PIT_OR_ACCOUNT_GATE", "depends_on_returns": False,
            "method": "60_EXCHANGE_SESSION_DECIMAL_MEAN_PRIOR_QUARTER_LAST_SESSION_NORMAL_STATUS",
            "minimum_monthly_listing_age_not_applied_to_representative_selection": True,
            "original_master_chronology_applied": master_records is not None,
            "account_permission_filter_applied": False,
            "required_full_history_instruments": sorted(required), "metadata_gaps": metadata_gaps,
            "endpoint_membership_conflicts": conflicts, "schedule": schedule}


def metadata_worker(config):
    kind, day = config["kind"], config.get("date")
    if kind not in {"master_all", "names_asof"}:
        raise ValueError("Unsupported metadata query")
    if kind == "names_asof":
        if not day or date.fromisoformat(day).isoformat() != day or day > HISTORY_END:
            raise ValueError("Explicit historical snapshot <=2024 required")
    elif day is not None:
        raise ValueError("Current master has no historical asof claim")
    logs = io.StringIO()
    payload = {"status": "FAILED", "fields": [], "rows": [], "kind": kind, "date": day,
               "historical_pit_verified": False, "ingested_at": datetime.now(timezone.utc).isoformat()}
    sdk = None
    logged = False
    with redirect_stdout(logs), redirect_stderr(logs):
        try:
            if config.get("sdk_path"):
                sys.path.insert(0, config["sdk_path"])
            version = importlib.metadata.version("baostock")
            if version != SDK_VERSION:
                raise ValueError("Pinned optional baostock==0.9.4 required")
            import baostock as sdk
            payload["sdk_version"] = version
            socket.setdefaulttimeout(12)
            login = sdk.login()
            payload["login_error_code"] = login.error_code
            if login.error_code != "0":
                raise RuntimeError(login.error_msg)
            logged = True
            time.sleep(1)
            result = sdk.query_stock_basic() if kind == "master_all" else sdk.query_all_stock(day=day)
            payload.update(error_code=result.error_code, error_msg=result.error_msg, fields=result.fields)
            if result.error_code != "0":
                return payload
            while True:
                old_page = result.cur_page_num
                boundary = len(result.data) == int(result.per_page_count) and result.cur_row_num >= len(result.data)
                more = result.next()
                if not more:
                    if boundary and old_page == result.cur_page_num and result.error_code == "0":
                        raise RuntimeError("Ambiguous metadata pagination termination")
                    break
                payload["rows"].append(result.get_row_data())
                if len(payload["rows"]) > 30000:
                    raise RuntimeError("Metadata row cap exceeded")
            payload.update(error_code=result.error_code, error_msg=result.error_msg,
                           status="SUCCESS" if result.error_code == "0" else "FAILED")
        except Exception as exc:
            payload.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        finally:
            if sdk is not None and logged:
                try:
                    time.sleep(1)
                    logout = sdk.logout()
                    payload["logout_error_code"] = logout.error_code
                except Exception as exc:
                    payload["logout_error"] = str(exc)
            payload["sdk_diagnostics"] = logs.getvalue()[-8000:]
    return payload


def collect_metadata(output, kind, sdk_path, day=None, timeout=30):
    output = Path(output)
    if kind not in {"master_all", "names_asof"} or (kind == "names_asof" and (not day or date.fromisoformat(day).isoformat() != day or day > HISTORY_END)) or (kind == "master_all" and day is not None):
        raise ValueError("Invalid metadata query/locked holdout")
    if not 0 < timeout <= 60:
        raise ValueError("Metadata wall timeout must be in (0,60]")
    label = kind + ("_" + day if day else "")
    cache = output / "metadata" / (label + ".json")
    if cache.exists():
        cached = json.loads(cache.read_bytes())
        raw = (output / cached["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != cached["raw_sha256"]:
            raise ValueError("Metadata cache hash mismatch")
        return cached, json.loads(raw)
    config = {"kind": kind, "date": day, "sdk_path": str(Path(sdk_path).resolve()) if sdk_path else None}
    # Validate before launching any process/network, including supplied date.
    kwargs = {"input": canonical(config), "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
              "timeout": timeout, "check": False}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--metadata-worker"], **kwargs)
        payload = json.loads(process.stdout)
    except subprocess.TimeoutExpired:
        payload = {"status": "TIMEOUT", "error": "Metadata worker killed at wall deadline", "kind": kind, "date": day, "fields": [], "rows": []}
    except Exception as exc:
        payload = {"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc), "kind": kind, "date": day, "fields": [], "rows": []}
    digest = hashlib.sha256(canonical(payload)).hexdigest()
    path = Path("raw_metadata") / (label + "_" + digest + ".json")
    write_immutable(output / path, payload)
    entry = {"kind": kind, "date": day, "status": payload["status"], "row_count": len(payload["rows"]),
             "raw_path": path.as_posix(), "raw_sha256": digest}
    write_immutable(cache, entry)
    return entry, payload


def build_inventory(universe_payloads, metadata_payloads):
    inventory = {}
    for payload in universe_payloads:
        if payload["status"] != "SUCCESS":
            continue
        for row in payload["rows"]:
            record = dict(zip(payload["fields"], row))
            item = inventory.setdefault(record["code"], {"code": record["code"], "symbol": record["code"].split(".")[-1],
                                                         "snapshot_dates": [], "names": [], "current_master": None})
            item["snapshot_dates"].append(record["date"])
    for payload in metadata_payloads:
        if payload["status"] != "SUCCESS":
            continue
        for row in payload["rows"]:
            record = dict(zip(payload["fields"], row))
            code = record.get("code")
            # Historical ETF observations are the primary identity set. A
            # currently listed fund alone cannot fabricate historical presence.
            if code not in inventory:
                continue
            item = inventory[code]
            if payload["kind"] == "master_all":
                item["current_master"] = record
            name = record.get("code_name", "")
            if name:
                item["names"].append({"name": name, "observed_for_date": payload.get("date"),
                                      "kind": payload["kind"], "historical_pit_verified": False})
    for item in inventory.values():
        item["snapshot_dates"] = sorted(set(item["snapshot_dates"]))
        item["first_snapshot_seen"], item["last_snapshot_seen"] = item["snapshot_dates"][0], item["snapshot_dates"][-1]
        screened = [dict(classify_name(n["name"]), name=n["name"]) for n in item["names"]]
        candidates = [x for x in screened if x["classification_status"] == "NAME_CANDIDATE_REQUIRES_OFFICIAL_BENCHMARK"]
        related = [x for x in screened if x["category"]]
        selected = (candidates or related or screened or [{"category": None, "classification_status": "UNRESOLVED_NAME", "reason": "No metadata name returned"}])[0]
        item.update({key: selected[key] for key in ("category", "classification_status", "reason")})
        item["name_classifications"] = screened
        item["classification_conflict"] = len({r["category"] for r in screened if r["category"]}) > 1
        item["name_changed_between_observations"] = len({r["name"] for r in item["names"]}) > 1
        item["listing_date_from_current_master"] = (item["current_master"] or {}).get("ipoDate") or None
        item["delisting_date_from_current_master"] = (item["current_master"] or {}).get("outDate") or None
        item["official_lifecycle_verified"] = False
        item["account_verified"] = False
    return sorted(inventory.values(), key=lambda x: x["code"])


if __name__ == "__main__" and "--metadata-worker" in sys.argv:
    try:
        answer = metadata_worker(json.loads(sys.stdin.buffer.read()))
    except Exception as exc:
        answer = {"status": "FAILED", "fields": [], "rows": [], "error_type": type(exc).__name__, "error": str(exc)}
    sys.stdout.buffer.write(canonical(answer))
