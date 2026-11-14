# Independent review code archive

These are exact-byte copies of the independent admission reviewer's scratch programs and pre-results method records. `independent_review_code_manifest.json` records every original path, archived path and SHA256. The archive is outside the frozen strategy-source inventory; creating it did not change any strategy, admitted data or run.

Restore the original `work/` paths before execution. The scripts locate the repository and sibling imports relative to those paths; running directly from this archive would resolve the wrong repository root. Run the following from the repository root in PowerShell. Existing matching files are retained, and a different existing file causes refusal rather than overwrite.

```powershell
@'
from pathlib import Path
import hashlib, json

manifest = json.loads(Path('reports/real_data_phase3/review_code/independent_review_code_manifest.json').read_bytes())
for item in manifest['files']:
    payload = Path(item['archived_path']).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == item['sha256']
    destination = Path(item['original_path'])
    if destination.exists():
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == item['sha256'], str(destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
print('Exact review files restored or verified')
'@ | .venv/Scripts/python.exe -
```

The repository's locked Python environment, registered plan, admitted data snapshots and original run artifacts are required. Completed result summaries contain absolute matrix paths from `F:\QuantTrade\Quant-Research`; replay must make those paths available. Changing a bound summary to relocate paths creates a different reviewed artifact and must be disclosed.

Invented-data checks open no actual runs:

```powershell
.venv/Scripts/python.exe work/independent_inventory_review.py --selfcheck
.venv/Scripts/python.exe work/run_independent_inventory_matrix_v2.py --selfcheck
```

The development-only accounting review requires its complete 224-run registry and matrix manifest. It does not evaluate returns or open validation runs:

```powershell
.venv/Scripts/python.exe work/run_independent_inventory_development.py --output work/replayed_inventory_development_review.json
```

After both matrices and the main evaluator's `results_summary.json` are complete, replay the full accounting review and the descriptive supplement:

```powershell
.venv/Scripts/python.exe work/run_independent_inventory_matrix_v2.py --summary reports/real_data_phase3/results_summary.json --output work/replayed_inventory_matrix_review.json
.venv/Scripts/python.exe work/independent_statistical_diagnostics.py --summary reports/real_data_phase3/results_summary.json --output work/replayed_statistical_diagnostics.json
```

Use new output filenames. Inventory wrappers refuse to overwrite an existing review. The statistical supplement records its execution timestamp, so its full output hash will change on replay even when all deterministic checks and diagnostics agree.

`run_independent_inventory_matrix.py` is retained as the original pre-results wrapper. Use **v2** for the full matrix: it fixes the review wrapper's handling of omitted `cash_delay_sessions` (the registered default is zero) and adds an invented omitted-default check. It does not modify strategy results. The core inventory reviewer is unchanged.

Inventory review verifies exact funded exchange sessions, aggregate unit flows and share rounding, closing quantities, dividend entitlements and declared modeled payment dates. It does not independently verify raw prices, T+1 lot allocation, order sizing, liquidation installment values or actual broker receipts. The statistical supplement adds descriptive ablations and diagnostics only; it creates no new p-values, candidate selection, factor-alpha claim or economic confirmation. The 2025–2026 final holdout remains locked.
