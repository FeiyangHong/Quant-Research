"""Read-only independent M8 closed-frame and preregistration audit."""
from pathlib import Path
from collections import Counter
from itertools import product
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "3df2391dc646ab98122ac6b029d0ef7a5cef2b32"
PREREG = "e30ae6157c8ee69aae439f2980bcc08b6fc5aae2"
WORDS = "能源、材料、原料、资源、有色、煤炭、钢铁、化工、工业、制造、机械、军工、国防、消费、食品、饮料、酒、农业、医药、医疗、生物、健康、金融、银行、非银、证券、保险、地产、房地产、信息、科技、TMT、通信、计算机、电子、半导体、芯片、互联网、人工智能、机器人、新能源、环保、公用事业、大宗商品股票".split("、")
GENERIC = ["证券投资基金", "上市交易公告书", "上市交易公告", "基金份额", "交易型开放式", "指数发起式", "证券投资", "指数型"]


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_bytes(ref, path):
    return subprocess.check_output(["git", "show", ref + ":" + path], cwd=ROOT)


def run():
    frame_path = "reports/m6_r1i/official_listing_inventory.json"
    raw = (ROOT / frame_path).read_bytes()
    assert digest(raw) == "55b7b554d5e785b91a743960dec5f84f45bfdac13c70f191fd5f71c308e58b7a"
    assert raw == git_bytes(BASE, frame_path)
    frame = json.loads(raw)
    candidate = read("reports/m8_rotation/CANDIDATE_REVIEW.json")
    receipt = read("reports/m8_rotation/CANDIDATE_FREEZE_RECEIPT.json")
    assert digest((ROOT / receipt["path"]).read_bytes()) == receipt["sha256"]
    assert candidate["keywords"] == WORDS and candidate["stripped_generic_phrases"] == GENERIC
    original = {r["instrument_id"]: r for r in frame["records"]}
    actual = {r["instrument_id"]: r for r in candidate["records"]}
    assert len(original) == len(actual) == 1970
    assert set(original) == set(actual)
    pre = hits = 0
    for sid, row in original.items():
        historical = sorted([r for r in row["original_listing_title_evidence"] if r["publication_date"] <= "2019-12-31"],
            key=lambda r: (r["publication_date"], r["source_url"]))
        observed = actual[sid]
        assert historical == observed["pre2020_title_evidence"], sid
        pre += bool(historical)
        expected = []
        for source in historical:
            stripped = source["title"]
            for generic in GENERIC:
                stripped = stripped.replace(generic, "")
            matches = [word for word in WORDS if word.lower() in stripped.lower()]
            if matches:
                expected.append(dict(source, stripped_title=stripped, matched_keywords=matches))
        assert expected == observed["keyword_evidence"], sid
        hits += bool(expected)
        assert (observed["status"] == "OUTSIDE_FIXED_ARCHIVAL_SAMPLE") == (not expected)
        assert observed["future_returns_used"] is False and observed["future_survival_used"] is False
    assert pre == 920 and hits == 220
    counts = Counter(row["status"] for row in actual.values())
    assert dict(counts) == candidate["counts"]
    registry_path = "reports/m8_rotation/EXPERIMENT_REGISTRY.json"
    registered = json.loads(git_bytes(PREREG, registry_path))
    expected_grid = set(product(("development", "validation"), ("E0", "R0", "E1", "R1"),
        ("base", "cost_2x", "cost_3x", "delay_1_session")))
    grid = {(r["period"], r["variant"], r["path"]) for r in registered["trials"]}
    assert len(registered["trials"]) == 32 and grid == expected_grid
    assert registered["primary"] == "validation 100000 base R0-E0"
    assert registered["periods"] == {"development": ["2020-01-01", "2021-12-31"], "validation": ["2022-01-01", "2024-12-31"]}
    for trial in registered["trials"]:
        assert trial["initial_cash"] == 100000 and trial["risk_scaling"] is False
        assert trial["annual_incremental_cost"] is None and trial["actual_run_id"] is None
        assert trial["statutory_tax_multiplier"] == 1 and trial["signal_release_delay"] == 1
        multiplier = {"base": 1, "cost_2x": 2, "cost_3x": 3, "delay_1_session": 1}[trial["path"]]
        assert trial["cost_multiplier"] == trial["slippage_multiplier"] == multiplier
        assert trial["execution_delay"] == (2 if trial["path"] == "delay_1_session" else 1)
    # Source-plan byte oracle is mathematical LF -> CRLF, with no hash substitution.
    path = "reports/m7_cohort/SOURCE_PLAN.json"
    old = git_bytes(BASE, path)
    expected_crlf = old.replace(b"\n", b"\r\n")
    assert len(old) == 4024 and b"\r" not in old
    assert digest(old) == "90db1e4dd79690f5e7352b27d673cded6700d9e89086e4eb24133d6a4fb84ca5"
    assert len(expected_crlf) == 4132
    assert digest(expected_crlf) == "e1790dad608c0b1f081a9595305e1d2c4980c6dc32d4b6eb48e4894da9ffc48c"
    assert (ROOT / path).read_bytes() == expected_crlf
    result = dict(status="PASS_CLOSED_FRAME_AND_REGISTRATION_ONLY", preregistration=PREREG,
        source_frame_sha256=digest(raw), frame_count=1970, pre2020_identity_count=pre,
        closed_keyword_hits=hits, counts=dict(counts), candidate_sha256=receipt["sha256"],
        candidate_frozen_at=receipt["frozen_at"], trials=32,
        m7_byte_oracle=dict(old_bytes=4024, restored_bytes=4132, exact_crlf_restoration=True),
        limitations=["Keyword and registration checks do not admit product identities or formation ranking.",
            "203 original-product reviews remain subject to separate original-document audit.",
            "Source collection timestamps and post2019 sequence admission require subsequent audit."])
    target = ROOT / "reports/m8_review/independent_registration.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    run()
