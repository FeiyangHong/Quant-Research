"""Direct source SDK-response audit, independent from normalized builder."""
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = Decimal


def read(path): return json.loads(Path(path).read_bytes())
def checked(receipt):
    raw = Path(receipt["raw_path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
    assert len(raw) == receipt["byte_count"]
    return raw


def build():
    selection = read(ROOT/"reports/m8_rotation/COHORT_SELECTION.json")
    listing = {r["instrument_id"]:r["listed_on"] for r in selection["ETF_candidate_rows"]}
    raw_calendar = read(ROOT/"data/normalized_csi/h00300_2010_2024_v1/calendar_evidence/raw/6c53baad9d880219_fba4a743f5_a1_00ea4bd4d692d85808180cd9884c9ab9b85777cbae6ae197bfd08873cec626fe.json")
    calendar = [r[0] for r in raw_calendar["rows"] if r[1] == "1"]
    new = read(ROOT/"data/raw_m8/budget.json")
    old = read(ROOT/"data/raw_m7/budget.json")
    output,summary,hashes = {},[],{}
    for sid in selection["selected_instruments"]:
        decoded = ROOT/"data/raw_m8/decoded"/("holding_"+sid+".json")
        source = read(decoded)
        if source.get("reused_source_path"):
            prior = Path(source["reused_source_path"])
            assert hashlib.sha256(prior.read_bytes()).hexdigest() == source["reused_source_sha256"]
            captures = [r for r in old["attempts"] if r["kind"] == "baostock_wire_attempts" and r["label"] == "history_"+sid]
        else:
            captures = [r for r in new["attempts"] if r["kind"] == "baostock_wire_attempts" and r["label"] == "holding_"+sid]
        assert captures
        wire_rows = []
        for receipt in captures:
            text = checked(receipt).decode("utf-8")
            assert "\x01success\x01query_history_k_data_plus\x01" in text
            payload,_ = json.JSONDecoder().raw_decode(text[text.index("{"):])
            wire_rows.extend(payload["record"])
            hashes[receipt["raw_path"]] = receipt["sha256"]
        rows = [r for r in wire_rows if "2019-01-01" <= r[0] <= "2024-12-31"]
        assert rows == source["rows"], sid
        assert len({r[0] for r in rows}) == len(rows)
        expected = [d for d in calendar if max("2019-01-01",listing[sid]) <= d <= "2024-12-31"]
        assert [r[0] for r in rows] == expected, (sid,"missing/extra listed session")
        suspension = 0
        for r in rows:
            assert r[1] == sid and r[9] == "3" and r[11] in ("0","1")
            values = [D(v) for v in r[2:9]]
            assert all(v.is_finite() and v>=0 for v in values)
            op,hi,lo,cl,prev,vol,amount = values
            if r[11] == "0":
                assert vol == amount == 0
                suspension += 1
            else:
                assert vol > 0 and amount > 0 and lo <= op <= hi and lo <= cl <= hi
                assert lo*vol-1 <= amount <= hi*vol+1, (sid,r[0],"amount/volume unit")
            output[r[0],sid] = dict(zip(source["fields"],r))
        summary.append(dict(instrument_id=sid,sessions=len(rows),first=rows[0][0],last=rows[-1][0],
            suspended_sessions=suspension,original_response_count=len(captures),decoded_sha256=hashlib.sha256(decoded.read_bytes()).hexdigest()))
    return output,dict(decision="PASS_PRIMARY_RAW_BARS_ONLY",rows=len(output),instruments=summary,source_hashes=hashes,
        method="Direct original SDK payload parse; exact identity/adjustflag3/date bounds/calendar coverage/decoded equality/finite OHLC and volume/amount consistency. No TR/event completeness inferred from raw prices.")


if __name__ == "__main__":
    rows,summary = build()
    (ROOT/"reports/m8_review/independent_raw_bars.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(summary["decision"],summary["rows"])
