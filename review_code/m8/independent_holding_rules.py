"""Independent preserved-original rule, fee and private-source-use review."""
import hashlib
import html
import json
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET
import fitz
from independent_raw_bars import ROOT, read, checked


def text(path):
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix == ".pdf": return "".join(p.get_text() for p in fitz.open(stream=raw,filetype="pdf"))
    if path.suffix == ".docx": return "".join(ET.fromstring(zipfile.ZipFile(path).read("word/document.xml")).itertext())
    return html.unescape(re.sub(r"<[^>]+>"," ",raw.decode("utf-8")))


def compact(s): return re.sub(r"\s+","",s)


def run():
    policy_path = ROOT/"reports/m8_rotation/HOLDING_RULE_POLICY.json"
    policy = read(policy_path)
    hashes = dict(policy["source_evidence_files"])
    for path,digest in hashes.items(): assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest, path
    rules = {key:compact(text(ROOT/value["local_path"])) for key,value in policy["rule_sources"].items()}
    for key in ("sse_rules_2014","sse_rules_2020","sse_rules_2023_full"):
        assert "10%" in rules[key] and "0.001元" in rules[key]
        assert "交收前不得卖出" in rules[key]
    assert "基金资产比例不低于80%的上证LOF" in rules["sse_20pct_2020"]
    assert "跟踪指数成份股仅为科创板股票" in rules["sse_20pct_2020"]
    assert "159939" not in rules["szse_20pct_list_20200824"]
    # SZ2016 encoding is visually verified on original physicalpages9/10;
    # SZ2020 clause2.9 p4 and SZ2023 p12 visually confirm the special20% limb.
    portfolio_reviews = []
    for product in policy["product_applicability"]:
        sid = product["instrument_id"]
        proof = product["original_portfolio_example"]
        candidates = [p for p,d in hashes.items() if d == product["identity_source_sha256"] and p.endswith(".bin")]
        assert len(candidates) == 1
        pdf = fitz.open(ROOT/candidates[0],filetype="pdf")
        content = compact(pdf[proof["physical_pdf_page"]-1].get_text())
        assert proof["stock_code"] in content and proof["stock_name"] in content
        portfolio_reviews.append(dict(instrument_id=sid,original_page=proof["physical_pdf_page"],
            historic_mainboard_example=proof["stock_code"],identity_sha256=product["identity_source_sha256"]))
    costs = policy["cost_scenario"]
    fee_text = compact(checked(costs["direct_etf_source"]).decode("utf-8"))
    assert "2009-02-13" in fee_text and "买卖深市ETF份额免征交易印花税" in fee_text
    assert "只需要向其经纪证券公司交纳相应的买卖佣金" in fee_text
    statutory = {r["label"]:compact(html.unescape(re.sub(r"<[^>]+>"," ",checked(r).decode("utf-8")))) for r in costs["stock_only_statutory_scope_sources"]}
    assert "Ａ股、Ｂ股股权转让书据" in statutory["mof_2008_stamp"]
    assert "股票和以股票为基础的存托凭证" in statutory["guangdong_2023_stamp_law"]
    assert "A股交易过户费" in statutory["sse_2015_joint_fees"]
    assert "股票交易过户费" in statutory["shanghai_official_fee_republication"]
    licenses = {
        "data/raw_policy/baostock_help_home_650853bc35ac.bin":"650853bc35ac9d3a4f51a3944b2a57bbce5262a8cb520b178879d5f463d275f5",
        "data/raw_policy/csi_disclaimer_script_4d7a21d98f56.html":"4d7a21d98f56252270903c5ea9488b7715db1bbbc83ba364484798cf43ca2786"}
    for path,digest in licenses.items(): assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest
    bao = text(ROOT/next(iter(licenses)))
    csi = text(ROOT/list(licenses)[1])
    assert "免费" in bao and "本地后进行分析" in bao
    assert "可基于非商业目的浏览、下载本网站的内容" in csi
    settlement_reviews=[]
    docs=read(ROOT/"reports/m8_rotation/holding_documents.json")
    for doc in docs:
        if "分红公告" not in doc["title"]: continue
        pdf=fitz.open(stream=checked(doc["receipt"]),filetype="pdf")
        page=compact(pdf[1].get_text())
        phrase="投资者可在红利发放日领取现金红利"
        assert phrase in page and "指定交易" in page
        at=page.index(phrase)
        settlement_reviews.append(dict(source_sha256=doc["receipt"]["sha256"],physical_page=2,quote=page[max(0,at-180):at+70]))
    assert len(settlement_reviews)==2
    output=dict(decision="PASS_CONDITIONAL_HISTORICAL_RULES_AND_PRIVATE_SOURCE_USE",author_role="INDEPENDENT_REVIEWER",
        policy_sha256=hashlib.sha256(policy_path.read_bytes()).hexdigest(),source_hashes_checked=len(hashes),license_source_hashes=licenses,
        independent_visual_pages=["SZ2016 physical9/10:100units,0.001CNY,10%,HALF_UP","SZ2020 physical4:20%index-exclusive exception,80%limbLOF only","SZ2023 physical12:ordinary10%,same exception"],
        historic_product_corroboration=portfolio_reviews,dividend_cash_rule_originals=settlement_reviews,
        fees=dict(commission="Counterfactual3bp/min5 research assumption, no broker invoice",stamp="SZ direct2009 ETF-secondary exemption; SSE nonapplication inferred from national stock-only tax scope plus same ETF legal form, not direct SSE exemption",transfer="Stock-only statutory transfer fee not charged to ETF shares; no double-count of handling charges within modeled commission"),
        rule_scope="Ordinary domestic equity ETF,100-share lot,0.001CNY tick,T+1,ordinary10%limit; special20%requires index exclusively20%-limit stocks. Original sector index definitions and historic main-board examples support ordinary class, subject to lifecycle conflicts.",
        limitations=["No complete daily historical constituent matrix or exchange per-product limit feed certified. No conflicting conversion/product limit announcement found in separately audited closed title archive.",
            "Public-source private local noncommercial research only; no raw redistribution, commercial service or live-trading permission inferred.",
            "Tencent raw OHLC is corroboration only, not admitted as primary price/signal series; no broad Tencent license is claimed.",
            "Hypothetical ordinary account eligibility and announced-date cash settlement are scenarios, not actual user broker permissions or observed credit timestamps."])
    (ROOT/"reports/m8_review/independent_holding_rules.json").write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(output["decision"])


if __name__=="__main__":run()
