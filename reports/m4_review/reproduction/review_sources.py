"""Independent read-only documentary/coverage checks, without importing D builder."""
import bisect
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess

import fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "work/m4_data_review"
POPPLER = Path(r"C:\Users\Elessar Apocalypse\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe")


def read(p):
    return json.loads(Path(p).read_bytes())


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def compact(text):
    return re.sub(r"[\s,，]", "", text).replace("−", "-")


def run():
    cases_file = ROOT / "reports/m4_data/financial_vintage_cases.json"
    cases = read(cases_file)
    calendar = sorted(set(read(ROOT/"data/admitted_r1/phase2_v1/development/calendar.json") + read(ROOT/"data/admitted_r1/phase2_v1/validation/calendar.json") + ["2025-01-02","2025-01-03"]))
    result = {"financial_source_json_sha256":sha(cases_file),"case_checks":[],"page_text_files":[],"source_hashes":{},"failures":[]}
    jobs = []
    for idx, case in enumerate(cases["cases"]):
        findings = {"case_id":case["case_id"],"case_status":case["case_status"],"sides":{},"conflicts":case.get("conflicts",[])}
        assert case["independent_human_reviews"] == 0 and not case["counts_toward_human_admission_gate"]
        for side in ("original","revision"):
            version = case[side]
            doc = version["document"]
            raw = Path(doc["raw_path"])
            assert sha(raw) == doc["sha256"]
            result["source_hashes"][str(raw)] = sha(raw)
            pdf = fitz.open(raw)
            pages = version["pages"]
            texts = {p:pdf[p-1].get_text() for p in pages}
            page_hits = {}
            values = version.get("as_reported_values",version["values"])
            for field,value in values.items():
                if value is None:
                    continue
                hits = [p for p,text in texts.items() if compact(value) in compact(text)]
                page_hits[field] = hits
                if not hits:
                    result["failures"].append({"case":case["case_id"],"side":side,"field":field,"value":value,"reason":"VALUE_NOT_IN_DECLARED_PAGES"})
            target = bisect.bisect_right(calendar,version["published_date"])
            expected_available = calendar[target] + "T21:00:00+08:00"
            expected_execution = calendar[target+1]
            assert version["available_at"] == expected_available,(case["case_id"],side)
            assert version["earliest_execution"] == expected_execution
            for page,text in texts.items():
                textpath = OUT/f"case{idx}_{side}_page{page}.txt"
                textpath.write_text(text,encoding="utf-8")
                result["page_text_files"].append(str(textpath))
            # Render the complete source pages carrying the maximum field evidence.
            best = max(pages,key=lambda p:sum(p in hit for hit in page_hits.values()))
            prefix = OUT/f"case{idx}_{side}_page{best}"
            jobs.append((raw,best,prefix))
            findings["sides"][side] = {"document_sha256":sha(raw),"pdf_pages":len(pdf),"declared_pages":pages,
                "value_page_hits":page_hits,"date_only_clock_pass":True,"available_at":expected_available,
                "earliest_execution":expected_execution,"rendered_review_page":best,"render_path":str(prefix)+".png"}
            supplement = version.get("supporting_correction_document")
            if supplement:
                raw2 = Path(supplement["raw_path"])
                assert sha(raw2)==supplement["sha256"]
                result["source_hashes"][str(raw2)] = sha(raw2)
                pdf2 = fitz.open(raw2)
                texts2 = {p+1:page.get_text() for p,page in enumerate(pdf2)}
                supplemental_hits = {}
                for conflict in case.get("conflicts",[]):
                    for key,value in conflict.items():
                        if key.endswith("value") and isinstance(value,str):
                            supplemental_hits[key] = [p for p,t in texts2.items() if compact(value) in compact(t)]
                findings["sides"][side]["supplement_conflict_value_pages"] = supplemental_hits
                if supplemental_hits:
                    implicated = sorted({p for hits in supplemental_hits.values() for p in hits})
                    for p in implicated:
                        (OUT/f"case{idx}_supplement_page{p}.txt").write_text(texts2[p],encoding="utf-8")
                    if implicated:
                        p=implicated[0]
                        jobs.append((raw2,p,OUT/f"case{idx}_supplement_page{p}"))
                if idx==5:
                    findings["unchanged_fields_correction_evidence_pages"] = [p for p,t in texts2.items() if "31,568,345.38" in t]
        assert case["revision"]["supersedes_id"] == case["original"]["revision_id"]
        for conflict in case.get("conflicts",[]):
            assert case["revision"]["values"][conflict["field"]] is None
        result["case_checks"].append(findings)
    def render(job):
        raw,page,prefix=job
        subprocess.run([str(POPPLER),"-f",str(page),"-l",str(page),"-r","110","-singlefile","-png",str(raw),str(prefix)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        return str(prefix)+".png"
    with ThreadPoolExecutor(max_workers=4) as pool:
        result["rendered_pages"] = list(pool.map(render,jobs))
    # Pair original/revision full pages, with labels, for visual inspection.
    for idx,case in enumerate(result["case_checks"]):
        pics=[Image.open(case["sides"][side]["render_path"]).convert("RGB") for side in ("original","revision")]
        width=sum(im.width for im in pics)
        sheet=Image.new("RGB",(width,max(im.height for im in pics)+35),"white")
        draw=ImageDraw.Draw(sheet)
        x=0
        for side,im in zip(("original","revision"),pics):
            draw.text((x+10,10),f"{case['case_id']} / {side}",fill="black")
            sheet.paste(im,(x,35));x+=im.width
        sheet.save(OUT/f"case{idx}_pair.png")
    raw_dir=ROOT/"data/raw_m4_equity/baostock"
    raw=read(raw_dir/"full_universe_20200731.json")
    universe=[dict(zip(raw["fields"],r)) for r in raw["rows"]]
    assert raw["error_code"]=="0" and len({r["code"] for r in universe})==len(universe)
    allowed=lambda s:s.startswith(("sh.600","sh.601","sh.603","sh.605","sz.000","sz.001","sz.002","sz.003","sz.300","sz.301"))
    expected_ids={r["code"] for r in universe if allowed(r["code"])}
    pool_file=ROOT/"reports/m4_data/full_pool_2020-07-31.json"
    published=read(pool_file)["rows"]
    actual_ids={r["instrument_id"] for r in published}
    assert expected_ids==actual_ids and len(published)==len(actual_ids)==3779
    summary=read(ROOT/"reports/m4_data/coverage_summary.json")
    st=Counter(r["isST_vendor_history"] for r in published)
    state=Counter(r["trade_status"] for r in published)
    assert dict(st)==summary["vendor_st_counts"] and dict(state)==summary["trade_status_counts"]
    assert summary["nonST_size_percentile_denominator"] is None
    for key in ("historical_total_shares","market_cap_same_share_scope","listing_age_252_sessions","median_amount_60_sessions","corporate_actions_complete","financial_vintage_complete","r2_qualified","r3_qualified"):
        assert all(row[key] is None for row in published),key
    result["full_pool"]={"source_sha256":sha(raw_dir/"full_universe_20200731.json"),"published_sha256":sha(pool_file),"raw_security_rows":len(universe),"unfiltered_main_chinext_denominator":len(expected_ids),"id_set_equal":True,"st_counts":dict(st),"trade_status_counts":dict(state),"missing_critical_coverage_retained":True,"size_denominator_not_fabricated":True}
    result["counts"]={"cases":len(cases["cases"]),"complete":sum(c["case_status"]=="COMPLETE_DOCUMENTARY_PAIR" for c in cases["cases"]),"quarantined":sum(c["case_status"].startswith("QUARANTINED") for c in cases["cases"]),"independent_human_reviews":0}
    result["status"]="PENDING_VISUAL_AND_SCOPE_REVIEW"
    (OUT/"checks.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"counts":result["counts"],"failures":result["failures"],"rendered_pages":len(result["rendered_pages"]),"full_pool":result["full_pool"]},ensure_ascii=False))


if __name__=="__main__":
    run()
