"""Independent raw-wire Decimal formation calculations and source binding."""
from pathlib import Path
from collections import Counter, defaultdict
from decimal import Decimal
from bisect import bisect_left
import hashlib
import json
import re
import fitz

ROOT = Path(__file__).resolve().parents[2]
D = Decimal


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def checked(path, expected):
    raw = Path(path).read_bytes()
    assert sha(raw) == expected, path
    return raw


def run():
    author_path = ROOT / "reports/m8_rotation/FORMATION_REVIEW_DRAFT.json"
    author = read(author_path)
    calendar_path = ROOT / "data/normalized_csi/h00300_2010_2024_v1/calendar_evidence/raw/6c53baad9d880219_fba4a743f5_a1_00ea4bd4d692d85808180cd9884c9ab9b85777cbae6ae197bfd08873cec626fe.json"
    calendar_raw = checked(calendar_path, "00ea4bd4d692d85808180cd9884c9ab9b85777cbae6ae197bfd08873cec626fe")
    calendar = [r[0] for r in json.loads(calendar_raw)["rows"] if r[1] == "1"]
    observation = [d for d in calendar if d <= "2019-12-31"][-60:]
    assert observation == author["formation_window"] and observation[0] == "2019-10-09"
    assert observation[-1] == "2019-12-31"
    first_month = max(d for d in calendar if "2020-01-01" <= d <= "2020-01-31")
    i = calendar.index(first_month)
    assert first_month == "2020-01-23" and calendar[i+1:i+3] == ["2020-02-03", "2020-02-04"]
    budget = read(ROOT / "data/raw_m8/budget.json")
    evidence, qualified, source_hashes, pending = [], [], {}, []
    source_date_checks = []
    for candidate in author["ETF_candidate_rows"]:
        sid = candidate["instrument_id"]
        product = candidate["product_evidence"]
        original = product["original"]["receipt"]
        raw = checked(original["raw_path"], original["sha256"])
        source_hashes[original["raw_path"]] = original["sha256"]
        doc = fitz.open(stream=raw, filetype="pdf")
        pages = [re.sub(r"\s+", "", page.get_text()) for page in doc]
        y,m,d = map(int, candidate["listed_on"].split("-"))
        date_regex = re.compile(fr"{y}年0?{m}月0?{d}日")
        dates = [(p+1, match.start()) for p, text in enumerate(pages[:8]) for match in date_regex.finditer(text)]
        if not dates:
            pending.append(dict(instrument_id=sid, issue="Listing date requires visual/manual confirmation", declared=candidate["listed_on"]))
        else:
            p,pos = dates[0]
            source_date_checks.append(dict(instrument_id=sid, declared=candidate["listed_on"], page=p,
                quote=pages[p-1][max(0,pos-35):pos+45]))
        age = sum(candidate["listed_on"] <= d <= "2019-12-31" for d in calendar)
        if age != candidate["listed_sessions"]:
            pending.append(dict(instrument_id=sid, issue="Listed age differs from nonnegative direct session count",
                expected=age, observed=candidate["listed_sessions"]))
        result = dict(instrument_id=sid, listed_on=candidate["listed_on"], independently_counted_sessions=age)
        if candidate["status"] == "EXCLUDED_LISTED_LESS_THAN_60":
            assert age < 60
            result["status"] = candidate["status"]
        elif candidate["status"] == "EXCLUDED_EXITED_BEFORE_FORMATION":
            exit_ev = candidate["exit_evidence"]
            event = exit_ev["document"]
            rec = event["receipt"]
            raw_exit = checked(rec["raw_path"], rec["sha256"])
            source_hashes[rec["raw_path"]] = rec["sha256"]
            text = re.sub(r"\s+", "", "".join(page.get_text() for page in fitz.open(stream=raw_exit,filetype="pdf")))
            ey,em,ed = map(int,exit_ev["date"].split("-"))
            assert exit_ev["date"] <= "2019-12-31" and "终止上市" in text
            assert re.search(fr"{ey}年0?{em}月0?{ed}日",text), sid
            result.update(status=candidate["status"], exit_date=exit_ev["date"], exit_raw_hash=rec["sha256"])
        else:
            records = []
            captures = [r for r in budget["attempts"] if r["kind"] == "baostock_wire_attempts" and r["label"] == "formation_" + sid]
            assert captures, sid
            for rec in captures:
                wire = checked(rec["raw_path"], rec["sha256"])
                assert len(wire) == rec["byte_count"]
                source_hashes[rec["raw_path"]] = rec["sha256"]
                text = wire.decode("utf-8")
                payload, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
                records.extend(payload["record"])
            assert all(r[1] == sid and r[9] == "3" and r[0] <= "2019-12-31" for r in records)
            assert len({r[0] for r in records}) == len(records)
            decoded = read(candidate["raw_path"])
            assert sha(Path(candidate["raw_path"]).read_bytes()) == candidate["raw_sha256"]
            assert decoded["rows"] == records
            by_date = {r[0]: r for r in records}
            assert set(observation).issubset(by_date), sid
            window = [by_date[d] for d in observation]
            amounts = [D(r[8]) for r in window]
            assert all(a.is_finite() and a >= 0 for a in amounts)
            for r in window:
                assert r[11] in ("0","1")
                if r[11] == "0":
                    assert D(r[7]) == D(r[8]) == 0
                if D(r[7]) > 0:
                    assert D(r[7])*D(r[4])-1 <= D(r[8]) <= D(r[7])*D(r[3])+1, (sid,r[0],"units")
            ordered = sorted(amounts)
            median = (ordered[29]+ordered[30])/2
            assert median == D(candidate["median_amount60"]), sid
            result.update(median_amount60=str(median), window_count=60)
            if median < 20000000:
                assert candidate["status"] == "EXCLUDED_MEDIAN_LT_20M"
                result["status"] = "EXCLUDED_MEDIAN_LT_20M"
            else:
                assert candidate["status"] == "QUALIFIED_INDEX_CANDIDATE" and age >= 60
                assert window[-1][11] == "1"
                name = candidate["exact_index_id"].removeprefix("NAME:")
                index_pages = pages
                index_source = original
                if product.get("index_contract_document"):
                    contract = product["index_contract_document"]
                    assert contract["publication_date"] <= "2019-12-31"
                    index_source = contract["receipt"]
                    index_raw = checked(index_source["raw_path"], index_source["sha256"])
                    source_hashes[index_source["raw_path"]] = index_source["sha256"]
                    index_pages = [re.sub(r"\s+", "",page.get_text()) for page in fitz.open(stream=index_raw,filetype="pdf")]
                found = [(p+1, text.index(name)) for p,text in enumerate(index_pages) if name in text]
                if found:
                    p,pos = found[0]
                    # Prefer explicit definition clauses over generic risk mentions.
                    clause = [(p+1,m.start()) for p,text in enumerate(index_pages)
                        for m in re.finditer(r"标的指数.{0,80}"+re.escape(name),text)]
                    if clause:
                        p,pos = clause[0]
                    result.update(index_original_page=p,index_original_quote=index_pages[p-1][max(0,pos-30):pos+len(name)+180],
                        index_source_sha256=index_source["sha256"])
                    if sid == "sh.515000":
                        theme = next((text for text in index_pages if "电子、计算机、通信、生物科技" in text),None)
                        assert theme is not None
                        result["sector_scope_quote"] = theme[theme.index("中证科技龙头指数由"):][:180]
                        result["style_qualifier"] = "Sector-restricted technology leaders with size/market-share/growth/R&D filters; overlapping technology exposures, not industry neutrality"
                else:
                    pending.append(dict(instrument_id=sid, issue="Exact declared index name requires original alias confirmation", declared=name))
                result.update(status="QUALIFIED_INDEX_CANDIDATE", exact_index_id=candidate["exact_index_id"])
                qualified.append((median, sid, candidate["exact_index_id"]))
        evidence.append(result)
    by_index = defaultdict(list)
    for median,sid,index in qualified:
        by_index[index].append((median,sid))
    representatives = [(sorted(rows,key=lambda row:(-row[0],row[1]))[0][0], index,
        sorted(rows,key=lambda row:(-row[0],row[1]))[0][1]) for index,rows in by_index.items()]
    ranked = sorted(representatives,key=lambda row:(-row[0],row[1],row[2]))
    selected = [row[2] for row in ranked[:10]]
    assert selected == author["selected_instruments"]
    assert len(by_index) == 15 and len(qualified) == 17
    assert [r[2] for r in ranked] == [r["instrument_id"] for r in author["representative_ranking"]]
    result = dict(status="PASS_RAW_FORMATION_ARITHMETIC_PENDING_DOCUMENT_REVIEW" if pending else "PASS_RAW_FORMATION_ARITHMETIC",
        author_draft_sha256=sha(author_path.read_bytes()), observation_window=observation,
        candidate_count=69, qualified_products=17, unique_indices=15, selected_instruments=selected,
        counts=dict(Counter(r["status"] for r in evidence)), candidates=evidence,
        listing_date_original_checks=source_date_checks, source_hashes=source_hashes,
        document_followups=pending, first_anchor=first_month, first_release=calendar[i+1], first_execution=calendar[i+2],
        independent_raw_market_rows=sum(r.get("window_count",0) for r in evidence),
        limitations=["Arithmetic is independently recomputed from raw SDK response bytes, not author medians.",
            "Contract amendment/history and date-only clocks are reviewed separately in independent_lifecycle_review.json; this arithmetic receipt alone is not holding-source admission."])
    (ROOT / "reports/m8_review/independent_formation_arithmetic.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("candidates","source_hashes","listing_date_original_checks","observation_window")},ensure_ascii=True,indent=2))


if __name__ == "__main__":
    run()
