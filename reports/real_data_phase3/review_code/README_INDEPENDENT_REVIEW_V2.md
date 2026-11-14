# V2 engineering replacement review

Use this version for the corrected matrices. Every v1 attempt is invalidated: 352 completed outputs and one aborted run remain preserved for audit, and none is eligible as performance evidence. The earlier development inventory PASS concerns only calendars, aggregate units/share rounding and dividend entitlements/model dates. It did not audit trade notional, commissions or slippage amounts and cannot override the subsequent engineering failure.

The original review files and hashes are retained. `independent_review_code_manifest_v2.json` adds new adapters; it does not replace the earlier manifest. Statistical definitions remain unchanged. The v2 adapter verifies the same 448 economic configurations, admitted data manifests and primary capital, accepts the newly registered corrected source hash, and refuses v1 matrix directories.

Restore original `work/` paths from both archive manifests before replay. The scripts resolve repository paths and imports from that layout. Run from the repository root in PowerShell:

```powershell
@'
from pathlib import Path
import hashlib, json

base = Path('reports/real_data_phase3/review_code')
for filename in ('independent_review_code_manifest.json', 'independent_review_code_manifest_v2.json'):
    manifest = json.loads((base / filename).read_bytes())
    for item in manifest['files']:
        payload = Path(item['archived_path']).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item['sha256']
        target = Path(item['original_path'])
        if target.exists():
            assert hashlib.sha256(target.read_bytes()).hexdigest() == item['sha256'], str(target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
print('Original and v2 review files restored or verified')
'@ | .venv/Scripts/python.exe -
```

The archive's `.gitattributes` preserves original CRLF/LF bytes. Do not run automatic line-ending conversion over hash-bound files. Use the locked Python environment and preserve the registered snapshots and run directories. Summaries contain absolute matrix paths; replay requires those paths to resolve, including `F:\QuantTrade\Quant-Research\runs\real_r1_development_v2` and its validation counterpart.

Selfchecks open no actual results:

```powershell
.venv/Scripts/python.exe work/independent_inventory_review.py --selfcheck
.venv/Scripts/python.exe work/run_independent_inventory_matrix_v3.py --selfcheck
.venv/Scripts/python.exe work/run_independent_inventory_development_v2.py --selfcheck
```

To check retained v1 history without interpreting old returns:

```powershell
.venv/Scripts/python.exe work/audit_invalidated_v1_history.py --output work/replayed_invalidated_v1_history.json
```

This audit projects identity/status/hash fields from the old archive and byte-hashes its preserved output tables. It records all 353 attempts, the 63 independent engineering findings, the limited earlier inventory verdict and the disclosed incidental display of the first archived metrics during an initial structure check. It performs no old-return analysis or selection. Archived registries already include the invalidation marker; the aborted attempt's append timestamp comes from its registry.

After the complete v2 development matrix is explicitly released:

```powershell
.venv/Scripts/python.exe work/run_independent_inventory_development_v2.py --output work/replayed_inventory_development_v2.json
```

After all 448 corrected runs and the main result summary are complete:

```powershell
.venv/Scripts/python.exe work/run_independent_inventory_matrix_v3.py --summary reports/real_data_phase3/results_summary.json --registered-plan reports/real_data_phase3/registered_plan_v2.json --output work/replayed_inventory_matrix_v2.json
.venv/Scripts/python.exe work/independent_statistical_diagnostics_v2.py --summary reports/real_data_phase3/results_summary.json --registered-plan reports/real_data_phase3/registered_plan_v2.json --output work/replayed_statistical_diagnostics_v2.json
```

Use new output names. Timestamped review outputs will have different whole-file hashes on replay; deterministic checks, bound inputs and numerical diagnostics must agree. The statistical supplement includes the invalidated-generation history and retains `BLOCKED_HURDLE`, descriptive-only diagnostics, no new p-values, no factor-alpha claim and the locked 2025–2026 holdout.

Inventory scope remains limited: raw-price validation, T+1 lot replay, order sizing, trade-fee arithmetic, liquidation installment values and actual broker receipt proof require separate evidence. Preparing these adapters is not an overall v2 engine PASS.
