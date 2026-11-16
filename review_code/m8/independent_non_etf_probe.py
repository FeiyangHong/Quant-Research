"""Direct original-PDF scope exclusion proof, never code-prefix exclusion."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import fitz

ROOT = Path(__file__).resolve().parents[2]


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def main():
    candidates = json.loads((ROOT / "reports/m8_rotation/CANDIDATE_REVIEW.json").read_text(encoding="utf-8"))
    sources = json.loads((ROOT / "reports/m8_rotation/listing_documents.json").read_text(encoding="utf-8"))
    # Prefix chooses review division only. Every exclusion below requires content.
    candidates = [r for r in candidates["records"] if r["status"] == "PENDING_ORIGINAL_PRODUCT_REVIEW"
        and not r["instrument_id"].startswith(("sh.51", "sh.56", "sh.58", "sz.159"))]
    by_id = {r["instrument_id"]: r for r in sources}
    records = []
    for candidate in candidates:
        sid = candidate["instrument_id"]
        row = dict(instrument_id=sid, status="PENDING_ORIGINAL_REVIEW", reason="Original not yet available")
        source = by_id.get(sid)
        if not source or not source.get("receipt", {}).get("raw_path"):
            records.append(row)
            continue
        receipt = source["receipt"]
        raw = Path(receipt["raw_path"]).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        assert digest == receipt["sha256"], sid
        doc = fitz.open(stream=raw, filetype="pdf")
        pages = [page.get_text() for page in doc]
        compact = [re.sub(r"\s+", "", text) for text in pages]
        code = sid.split(".")[1]
        code_pages = [n for n, text in enumerate(compact) if code in text]
        row.update(source_url=source["listing"]["source_url"], published_at=source["listing"]["publication_date"],
            raw_path=receipt["raw_path"], raw_sha256=digest, page_count=len(pages))
        # Avoid finding an unrelated fund in manager biographies or comparison tables:
        # scope proof must be in the document's title, before the listing heading.
        title = compact[0].split("基金管理人")[0]
        title = title[:500]
        reason = None
        if "分级" in title:
            reason = "Original listing title explicitly identifies a structured/split-share fund (分级), not an ordinary ETF"
        elif "LOF" in title.upper() or "上市开放式" in title:
            reason = "Original listing title explicitly identifies LOF/listed open-ended structure, not ETF"
        official_association = None
        if reason and not code_pages:
            capture_hash = source["listing"]["capture_sha256"]
            capture_path = ROOT / "data/raw_m6/objects" / (capture_hash + ".bin")
            capture_bytes = capture_path.read_bytes()
            assert hashlib.sha256(capture_bytes).hexdigest() == capture_hash
            associations = [node for node in walk(json.loads(capture_bytes))
                if code in node.get("secCode", []) and node.get("attachPath")
                and source["listing"]["source_url"].endswith(node["attachPath"])]
            assert len(associations) == 1, sid
            official_association = dict(capture_sha256=capture_hash,
                secCode=associations[0]["secCode"], secName=associations[0]["secName"],
                title=associations[0]["title"], attachPath=associations[0]["attachPath"])
        if sid == "sz.161029":
            # Manual visual review of original pp1/3/5: declassified fund
            # remains contractual ordinary open-ended, not a conversion to ETF.
            assert digest == "ccc7012c93a2844266a2d382714dc773ccd183a00a8df63e39576edabccaf16d"
            assert "契约型开放式" in compact[2] and "161029" in compact[2]
            assert "终止分级运作并变更而来" in compact[4]
            row.update(status="EXCLUDED_ORIGINAL_NON_ETF",
                reason="Original pp3-5 establish ordinary contractual open-ended fund and terminated split-share structure; not ETF",
                product_type_physical_page=3, product_type_quote=compact[2][compact[2].index("基金概览"):][-650:],
                identity_physical_page=3, identity_quote="场内简称：银行FG；交易代码：161029",
                additional_physical_page=5, additional_quote="富国中证银行指数型证券投资基金由富国中证银行指数分级证券投资基金终止分级运作并变更而来",
                visual_review_pages=[1,3,5])
            records.append(row)
            continue
        if reason and code_pages:
            n = code_pages[0]
            start = max(0, compact[n].index(code) - 85)
            row.update(status="EXCLUDED_ORIGINAL_NON_ETF", reason=reason,
                product_type_physical_page=1, product_type_quote=title,
                identity_physical_page=n + 1, identity_quote=compact[n][start:start + 190])
        elif reason and official_association:
            row.update(status="EXCLUDED_ORIGINAL_NON_ETF", reason=reason,
                product_type_physical_page=1, product_type_quote=title,
                identity_basis="Hash-verified original exchange disclosure response links this code directly to the PDF URL; code need not be printed in the correction/short notice body",
                official_identity_association=official_association,
                visual_review_pages=[1])
        else:
            row.update(reason="Original available but title/type or same-document code identity requires manual review",
                first_page_excerpt=compact[0][:900], code_found=bool(code_pages))
        records.append(row)
    result = dict(status="COMPLETE" if all(r["status"] == "EXCLUDED_ORIGINAL_NON_ETF" for r in records) else "PARTIAL_PENDING_ORIGINALS_OR_MANUAL_REVIEW",
        reviewer="independent agent /root/m8_independent", method="Direct PyMuPDF extraction of hash-verified originals; no author text-cache or classification used",
        counts=dict(Counter(r["status"] for r in records)), records=records,
        limitations=["This proof classifies original listing product structure; it does not certify an ETF's formation eligibility.",
            "A code prefix controls review division only and never serves as an exclusion reason."])
    (ROOT / "reports/m8_review/NON_ETF_REVIEW.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(status=result["status"], counts=result["counts"])))


if __name__ == "__main__":
    main()
