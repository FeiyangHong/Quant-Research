"""Dated identity continuity from pre2025 originals and captured amendments."""
from pathlib import Path
import hashlib
import json
import re
import fitz
from independent_raw_bars import ROOT, read, checked


def compact(s): return re.sub(r"\s+","",s)


def run():
    selection=read(ROOT/"reports/m8_rotation/COHORT_SELECTION.json")
    expected={r["instrument_id"]:r["exact_index_id"].removeprefix("NAME:") for r in selection["ETF_candidate_rows"]}
    annual=read(ROOT/"reports/m8_rotation/ANNUAL_ACTION_EVIDENCE.json")["records"]
    identities=[]
    for item in annual:
        if item["year"]==2024: continue  # Late2025 report exception is action-only.
        doc=item["document"];pdf=fitz.open(stream=checked(doc["receipt"]),filetype="pdf")
        sid=item["instrument_id"]
        pages=[compact(p.get_text()) for p in list(pdf)[:12]]
        assert any(sid[3:] in t for t in pages)
        name=expected[sid]
        if sid=="sh.512760" and item["year"]>=2020: name="中华交易服务半导体芯片行业指数"
        matches=[(i+1,t.find(name)) for i,t in enumerate(pages) if name in t]
        assert matches,(sid,item["year"],name)
        p,at=matches[0]
        identities.append(dict(instrument_id=sid,year=item["year"],index_display_name=name,physical_page=p,
            source_sha256=doc["receipt"]["sha256"],quote=pages[p-1][max(0,at-25):at+100]))
    supplementary=read(ROOT/"reports/m8_rotation/HOLDING_SUPPLEMENTAL_DOCUMENTS.json")
    rename=next(r for r in supplementary if r["instrument_id"]=="sh.512760" and r["publication_date"]=="2020-06-11")
    text=compact(fitz.open(stream=checked(rename["receipt"]),filetype="pdf")[0].get_text())
    assert "自2020年6月15日起将“中华交易服务半导体行业指数”名称变更为“中华交易服务半导体芯片行业指数”" in text
    assert "自2020年6月16日起" in text and "基金代码保持不变" in text
    docs=read(ROOT/"reports/m8_rotation/holding_documents.json")
    originals={r["receipt"]["sha256"]:r for r in docs if r["kind"]!="ANNUAL" and not any(w in r["title"] for w in ("拆分","分红公告"))}
    reviews=[]
    for digest,doc in originals.items():
        pdf=fitz.open(stream=checked(doc["receipt"]),filetype="pdf")
        first=compact(pdf[0].get_text())
        labels=[]
        for keyword,label in [("指数基金指引","regulatory index-risk and contingent future transition clauses"),("存托凭证","depositary receipt investment eligibility"),
            ("指数许可使用费","fund-level index-license cost"),("信息披露","disclosure rules"),("分红方式变更","distribution election procedure"),("场内申购赎回","creation/redemption mechanism")]:
            if keyword in first: labels.append(label)
        assert labels,(doc["title"],first[:100])
        reviews.append(dict(source_sha256=digest,title=doc["title"],publication_date=doc["publication_date"],
            classification=labels,first_page_quote=first[:1500]))
    archive=ROOT/"reports/m8_review/holding_title_archive_review.json"
    output=dict(decision="PASS_BOUNDED_HOLDING_LIFECYCLE",author_role="INDEPENDENT_REVIEWER",annual_identity_original_checks=identities,
        distinct_generic_amendment_originals=reviews,rename=dict(source_sha256=rename["receipt"]["sha256"],publication_date="2020-06-11",
            index_name_effective="2020-06-15",fund_name_effective="2020-06-16",physical_page=1,quote=text[:1850],
            conclusion="Issuer explicitly identifies name change of same index; preserve frozen2019 exact index identity with dated display-name revision."),
        holding_title_archive_review_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        limits=["50 annual identities published before2025 independently checked.2024 annuals published2025 are used only for separate historical action completeness, not index selection.",
            "Captured contract amendments change disclosure, CDR eligibility, risk/contingency rules, fund-level index fees, or dealing procedures; no captured economic index substitution or retirement of selected10.",
            "Title audit has82 broad routine manager/abbreviation attention notices without standalone originals; all narrowly material lifecycle/contract/index/fund-name notices covered. This is bounded archive reconstruction, not universal disclosure certification."])
    (ROOT/"reports/m8_review/independent_holding_lifecycle.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(output["decision"],len(identities),len(reviews))


if __name__=="__main__":run()
