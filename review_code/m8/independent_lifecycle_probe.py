"""Bounded documentary formation review; no collection or production writes."""
from pathlib import Path
import bisect
import hashlib
import json
import re
import fitz

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pages(entry):
    receipt = entry["receipt"]
    raw = Path(receipt["raw_path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
    assert len(raw) == receipt["byte_count"]
    return [re.sub(r"\s+", "", p.get_text()) for p in fitz.open(stream=raw, filetype="pdf")]


def run():
    draft = read("reports/m8_rotation/FORMATION_REVIEW_DRAFT.json")
    documents = read("reports/m8_rotation/formation_documents.json")
    calendar = [r[0] for r in read("data/normalized_csi/h00300_2010_2024_v1/calendar_evidence/raw/6c53baad9d880219_fba4a743f5_a1_00ea4bd4d692d85808180cd9884c9ab9b85777cbae6ae197bfd08873cec626fe.json")["rows"] if r[1] == "1"]
    def available(day):
        return calendar[bisect.bisect_right(calendar, day)] + "T21:00:00+08:00"
    categories = {
        0:"information disclosure", 1:"related-party index replication restriction", 2:"termination", 3:"related-party index replication restriction",
        4:"termination", 5:"related-party index replication restriction", 6:"information disclosure", 7:"liquidity risk", 8:"manager/fund name prefix",
        9:"information disclosure", 10:"liquidity risk", 11:"termination", 12:"off-exchange share precision", 13:"termination", 14:"termination",
        15:"information disclosure", 16:"information disclosure", 17:"information disclosure", 18:"information disclosure", 19:"liquidity risk", 20:"manager/fund name prefix",
        21:"information disclosure", 22:"information disclosure", 23:"technology index prospectus", 24:"technology index prospectus summary", 25:"information disclosure",
        26:"information disclosure", 27:"creation/redemption and information disclosure", 28:"liquidity risk", 29:"off-exchange cash creation/redemption",
        30:"on-exchange creation/redemption", 31:"liquidity risk", 32:"termination", 33:"liquidity risk", 34:"off-exchange creation/redemption"}
    assert len(documents) == len(categories) == 35
    reviews = []
    for i, entry in enumerate(documents):
        text = pages(entry)
        assert entry["publication_date"] <= "2019-12-31"
        reviews.append(dict(instrument_id=entry["instrument_id"], publication_date=entry["publication_date"], title=entry["title"],
            raw_sha256=entry["receipt"]["sha256"], classification=categories[i], first_page_quote=text[0][:1100],
            index_related_clauses=[dict(page=k+1,quote=t[max(0,m.start()-35):m.start()+160]) for k,t in enumerate(text)
                for m in re.finditer("变更标的指数|标的指数发生变更|关联交易|关联方",t)][:8]))
    clock_checks = []
    for row in draft["ETF_candidate_rows"]:
        p = row["product_evidence"]
        assert p["available_at"] == available(p["published_at"]), row["instrument_id"]
        if p.get("index_contract_document"):
            day = p["index_contract_document"]["publication_date"]
            assert p["index_contract_available_at"] == available(day)
            assert p["index_contract_available_at"] <= draft["cohort_available_at"]
        if row["status"] == "QUALIFIED_INDEX_CANDIDATE":
            assert p["available_at"] <= draft["cohort_available_at"]
        clock_checks.append(dict(instrument_id=row["instrument_id"], listing_available_at=p["available_at"],
            index_available_at=p.get("index_contract_available_at")))
    assert draft["cohort_available_at"] == available("2019-12-31")
    bad = read("reports/m8_rotation/METADATA_TITLE_CONFLICT_EVIDENCE.json")[0]
    badpages = pages(bad)
    assert bad["instrument_id"] == "sh.512000" and "华宝中证银行" in badpages[0]
    assert "基金主代码512800交易代码512800" in badpages[5]
    assert all(row["product_evidence"].get("raw_object_hash") != bad["receipt"]["sha256"]
               and row["product_evidence"].get("index_contract_document",{}).get("receipt",{}).get("sha256") != bad["receipt"]["sha256"]
               for row in draft["ETF_candidate_rows"])
    out = dict(decision="PASS_CLOSED_FORMATION_DOCUMENT_REVIEW", author_role="INDEPENDENT_REVIEWER",
        draft_sha256=digest(ROOT/"reports/m8_rotation/FORMATION_REVIEW_DRAFT.json"), documentary_reviews=reviews,
        publication_clock_checks=clock_checks, metadata_conflict=dict(raw_sha256=bad["receipt"]["sha256"],
            physical_pdf_page=6,actual_identity_quote=badpages[5][:600],resolution="Excluded from 512000 identity; correct latest 2019-11-30 contract establishes securities-company index"),
        title_archive_review_sha256=digest(ROOT/"reports/m8_review/title_archive_review.json"),
        conclusion="35 saved lifecycle/amendment originals reviewed; captured amendments concern disclosure, liquidity, name prefixes, creation/redemption or accounting precision. No captured amendment changes an eligible candidate's target index. Exact formation index clauses independently checked in independent_formation_arithmetic.json.",
        limits=["Bounded to the frozen historical exchange archive and saved originals; not a claim about every possible disclosure anywhere.",
            "Selected overlapping technology/industry exposures are not industry-neutral. Formation age60 does not grant trading permission before252 sessions.",
            "No post2019 ETF market observations or strategy returns read in this review."])
    (ROOT/"reports/m8_review/independent_lifecycle_review.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(out["decision"])


if __name__ == "__main__":
    run()
