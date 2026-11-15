# Superseded read-only audit draft

The first M4 read-only audit draft incorrectly classified zero affected execution dependencies. Its raw grid dictionary used `scope` for ACCOUNT/WARMUP. The trigger construction merged that dictionary after assigning the intended query scope:

```python
triggers.append({"run_id": run_id, "path": run["path"], "scope": scope,
                 "detail": detail, **row})
```

This overwrote HELD_OPEN_AND_CLOSE / ORDER_EXECUTION / other query scopes, so downstream scope membership could never detect an execution impact. The first draft's zero-impact conclusion was invalid until the corrected audit completed.

The exact repair keeps calendar scope under `account_scope` and places query fields after the copied row:

```python
"account_scope": "ACCOUNT" if day >= data["account_start"] else "WARMUP"
triggers.append({**row, "run_id": run_id, "path": run["path"], "scope": scope,
                 "detail": detail})
```

The original draft summary, trigger contexts and per-run coverage are preserved here. The original script SHA256 is bound in the saved summary. `test_temporal_query_scope_cannot_be_overwritten_by_input_calendar_scope` now injects a held-position discrepancy and verifies it raises the observed-impact count. This is an audit implementation repair, not a strategy trial, source-data revision, new parameter grid or new performance experiment. The existing448 R1 outputs were never edited or rerun.
