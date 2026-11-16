"""One-time byte-level M7 portability audit, no account replay."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "3df2391dc646ab98122ac6b029d0ef7a5cef2b32"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def run():
    path = "reports/m7_cohort/SOURCE_PLAN.json"
    old = subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT)
    expected = old.replace(b"\n", b"\r\n")
    working = (ROOT / path).read_bytes()
    clean = (ROOT / "work/m8_clean_checkout" / path).read_bytes()
    assert b"\r" not in old and len(old) == 4024
    assert working == clean == expected and len(clean) == 4132
    assert sha(clean) == "e1790dad608c0b1f081a9595305e1d2c4980c6dc32d4b6eb48e4894da9ffc48c"
    manifest = json.loads((ROOT / "reports/m7_cohort/source_manifest.json").read_text(encoding="utf-8"))
    rows = []
    for source in manifest["sources"]:
        local = ROOT / source["repository_path"]
        actual = sha(local.read_bytes()) if local.exists() else None
        rows.append(dict(path=source["repository_path"], expected_sha256=source["sha256"],
            observed_sha256=actual, status="MATCH" if actual == source["sha256"] else "MISSING" if actual is None else "MISMATCH"))
    result = dict(status="PASS" if all(r["status"] == "MATCH" for r in rows) else "PARTIAL",
        baseline=BASE, old_lf_sha256=sha(old), old_lf_bytes=len(old),
        clean_checkout_sha256=sha(clean), clean_checkout_bytes=len(clean),
        exact_lf_to_crlf=True, semantic_change=False, old_accounts_rerun=False,
        source_counts={status: sum(r["status"] == status for r in rows) for status in ("MATCH", "MISSING", "MISMATCH")},
        source_hash_verification=rows,
        limitations=["Byte presence and hash matching do not constitute new semantic admission or a complete account replay.",
            "M7 all-cash TR/action waiver does not authorize M8 holdings."])
    (ROOT / "reports/m8_review/independent_m7_reproducibility.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "source_hash_verification"}))


if __name__ == "__main__":
    run()
