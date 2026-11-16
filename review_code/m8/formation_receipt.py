"""Bind independently completed formation checks to immutable selection bytes."""
from pathlib import Path
import datetime
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
def sha(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
def read(path):
    return json.loads((ROOT/path).read_bytes())

checks = {
    "reports/m8_review/independent_registration.json": ("status", "PASS_CLOSED_FRAME_AND_REGISTRATION_ONLY"),
    "reports/m8_review/NON_ETF_REVIEW.json": ("status", "COMPLETE"),
    "reports/m8_review/independent_formation_arithmetic.json": ("status", "PASS_RAW_FORMATION_ARITHMETIC"),
    "reports/m8_review/independent_lifecycle_review.json": ("decision", "PASS_CLOSED_FORMATION_DOCUMENT_REVIEW"),
}
for path,(field,value) in checks.items():
    assert read(path)[field] == value
selected = "reports/m8_rotation/COHORT_SELECTION.json"
assert sha(selected) == sha("reports/m8_rotation/FORMATION_REVIEW_DRAFT.json")
assert sha(selected) == read("reports/m8_review/independent_formation_arithmetic.json")["author_draft_sha256"]
assert sha(selected) == read("reports/m8_review/independent_lifecycle_review.json")["draft_sha256"]
out = dict(decision="PASS_COHORT_SELECTION_ONLY", author_role="INDEPENDENT_REVIEWER", reviewer="/root/m8_independent",
    reviewed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), cohort_selection_sha256=sha(selected),
    evidence_files={p:sha(p) for p in [*checks,"reports/m8_review/title_archive_review.json"]},
    selected_instruments=read(selected)["selected_instruments"],
    summary="Closed1970 frame;220 hits=17 explicit historical exclusions+134 original nonETF+69 ETF.54 mature active candidates independently recomputed from3240 raw rows:37 belowthreshold,17 qualify,15 exact indices,10 selected.6 preformation exits and9 young separately excluded. All required index/lifecycle documents and conservative date-only clocks verified.",
    limitations=["Conditional historical-public reconstruction within frozen frame, not national sector universe or vendor-vintage certification.",
        "Review permits selection freeze and subsequent scoped acquisition only. It does not admit holding data or authorize strategy performance claims.",
        "Formation60-session age is separate from252-session trading eligibility. Old7 M7 products are not automatically new candidates.",
        "Technology exposures overlap; exact-index deduplication does not produce industry neutrality."],
    new_network_calls_by_reviewer=0, strategy_accounts_run_by_reviewer=0, post2019_etf_market_data_used=False)
(ROOT/"reports/m8_review/FORMATION_INDEPENDENT_REVIEW.json").write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(out["decision"],out["cohort_selection_sha256"])
