"""Read saved original action pages, not parsed action values, as the oracle."""
from pathlib import Path
import hashlib
import json
import re
import fitz
from independent_raw_bars import ROOT, read, checked


EXPECTED = [
    dict(instrument_id="sh.512760",action_type="SPLIT",announcement_date="2020-08-31",record_date="2020-09-08",ex_date="2020-09-09",effective_phase="BOD",share_factor="2"),
    dict(instrument_id="sh.512710",action_type="SPLIT",announcement_date="2021-03-10",record_date="2021-03-18",ex_date="2021-03-19",effective_phase="BOD",share_factor="2"),
    dict(instrument_id="sz.159939",action_type="SPLIT",announcement_date="2023-02-10",record_date="2023-02-15",ex_date="2023-02-15",market_ex_date="2023-02-16",effective_phase="EOD",share_factor="2"),
    dict(instrument_id="sh.512720",action_type="CASH_DIVIDEND",announcement_date="2023-09-21",record_date="2023-09-22",ex_date="2023-09-25",pay_date="2023-09-28",cash_per_share="0.048"),
    dict(instrument_id="sh.512720",action_type="CASH_DIVIDEND",announcement_date="2023-12-21",record_date="2023-12-22",ex_date="2023-12-25",pay_date="2023-12-28",cash_per_share="0.048"),
]


def compact(text): return re.sub(r"\s+","",text)
def chinese(day):
    y,m,d = map(int,day.split("-"))
    return f"{y}年{m}月{d}日"


def run():
    docs = read(ROOT/"reports/m8_rotation/holding_documents.json")
    author = read(ROOT/"reports/m8_rotation/ANNUAL_ACTION_EVIDENCE.json")["records"]
    annual_reviews = []
    for row in author:
        entry = row["document"]
        raw = checked(entry["receipt"])
        pdf = fitz.open(stream=raw,filetype="pdf")
        sid,year = row["instrument_id"],row["year"]
        # Locator metadata is permitted, but no author-derived values establish
        # the expected facts. Read original PDF pages directly and re-extract.
        div_pages = {x["pdf_page"] for x in row["dividend_none_evidence"]+row["dividend_totals"]}
        split_pages = {x["pdf_page"] for x in row["split_evidence"]}
        if (sid,year) == ("sh.512880",2019): div_pages |= {10,45}
        if (sid,year) == ("sh.512710",2019): split_pages.add(53)
        assert div_pages and split_pages, (sid,year)
        division = [(p,compact(pdf[p-1].get_text())) for p in sorted(div_pages)]
        splits = [(p,compact(pdf[p-1].get_text())) for p in sorted(split_pages)]
        none = [(p,m.group()) for p,t in division for m in re.finditer(r"(?:本基金)?(?:本报告期(?:内)?|过去三年)(?:未进行|未实施|未发生|无)利润分配(?:事项)?",t)]
        if (sid,year) == ("sh.512720",2023):
            # Displayed annual table is CNY per10 shares:0.960 =>0.096.
            assert any("2023年0.960" in t or "20230.960" in t for p,t in division)
            dividend = "0.096"
        else:
            assert none, (sid,year,"no explicit zero dividend proof")
            dividend = "0"
        split_values = []
        for p,t in splits:
            for match in re.finditer(r"基金拆分变动份额(?:（[^）]*）|\([^)]*\))?([\d,]+\.\d+|[-－—])",t):
                split_values.append((p,match.group(1),t[max(0,match.start()-65):match.end()+70]))
        assert len(split_values) == 1, (sid,year,split_values)
        p,value,quote = split_values[0]
        expected_nonzero = {("sh.512760",2020):"5,656,661,386.00",("sh.512710",2021):"4,048,329,199.00",("sz.159939",2023):"2,504,828,053.00"}
        assert value == expected_nonzero[sid,year] if (sid,year) in expected_nonzero else value in ("-","－","—")
        if year == 2024:
            assert entry["publication_date"] >= "2025-01-01"
            assert entry["documentary_only"] is True and entry["not_signal_input"] is True and entry["historical_fact_end"] == "2024-12-31"
        annual_reviews.append(dict(instrument_id=sid,year=year,source_sha256=entry["receipt"]["sha256"],publication_date=entry["publication_date"],
            dividend_per_share=dividend,dividend_none_original_quotes=none,dividend_physical_pages=sorted(div_pages),split_physical_page=p,split_original_quote=quote,
            documentary_only=year==2024))
    assert len(annual_reviews) == 60 and len({(r["instrument_id"],r["year"]) for r in annual_reviews}) == 60
    event_reviews = []
    for expected in EXPECTED:
        hits = [r for r in docs if r["instrument_id"] == expected["instrument_id"] and r["publication_date"] == expected["announcement_date"] and ("实施基金份额拆分" in r["title"] or "基金份额拆分并调整" in r["title"] or "分红公告" in r["title"])]
        assert len(hits) == 1
        entry = hits[0]
        pdf = fitz.open(stream=checked(entry["receipt"]),filetype="pdf")
        text = compact(pdf[0].get_text())
        assert expected["instrument_id"][3:] in text
        for key in ("record_date","ex_date","pay_date"):
            if key in expected: assert chinese(expected[key]) in text
        if expected["action_type"] == "SPLIT":
            assert "1:2" in text or "1：2" in text
            if expected["effective_phase"] == "EOD": assert "权益登记日日终" in text and chinese(expected["market_ex_date"]) in text
        else:
            assert "元/10份基金份额" in text and "0.480" in text
        event_reviews.append(dict(expected,raw_sha256=entry["receipt"]["sha256"],source_url=entry["source_url"],physical_pdf_page=1,original_quote=text[:2100]))
    output = dict(decision="PASS_ORIGINAL_ACTION_TERMS_AND_ANNUAL_COMPLETENESS",author_role="INDEPENDENT_REVIEWER",
        annual_reviews=annual_reviews,expected_actions=event_reviews,
        scope="60 original annual fund-years2019–24 and5 contemporaneous event plans.2024 annuals published2025 read only identified historic profit-distribution/share-change pages; never used as signal clocks.",
        limits=["ETF cash credits remain announced-date rule-based simulation, not observed broker account credits.","Full title archive/lifecycle review and normalized TR equality are separate gates."])
    (ROOT/"reports/m8_review/independent_action_documents.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(output["decision"],len(annual_reviews),len(event_reviews))


if __name__ == "__main__": run()
