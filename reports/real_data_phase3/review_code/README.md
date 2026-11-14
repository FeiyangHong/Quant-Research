# Execution review reproduction

These are read-only engineering-review artifacts. They are outside the frozen strategy source. No vendor raw data is included.

From the repository root, run the commands in `../REPRODUCE.md`. `review_real_execution.py` reads the requested matrix summaries and admitted datasets; it never imports or calls the strategy or backtest engine. Both complete 224-run grids must be checked before the overall result can be PASS. The 16 toy tests validate detection of altered quotes, permissions, sizes, T+1, capacity and the three observed decimal-rounding defects; they do not generate a backtest.

The immutable rejected-v1 record is `../execution_review_v1_failed.json`. It binds the review code and all reviewed table hashes, with 224 development runs and 128 completed validation runs. The validation matrix was intentionally stopped; it is not a complete 224-run result.

To reproduce the stopped-v1 diagnostic helper, restore the archived copies to `work/` (no frozen source is changed):

```powershell
Copy-Item -LiteralPath reports/real_data_phase3/review_code/review_real_execution.py -Destination work/review_real_execution.py
Copy-Item -LiteralPath reports/real_data_phase3/review_code/review_partial_validation_v1.py -Destination work/review_partial_validation_v1.py
.venv/Scripts/python.exe -c "import runpy; runpy.run_path('work/review_partial_validation_v1.py', run_name='__main__')"
```

The helper audits only registry entries with a COMPLETED terminal state and writes `work/execution_review_validation_v1_stopped.json`. Keep original data and run directories in place: source manifests bind the retained local raw paths and hashes. Do not overwrite the rejected-v1 report with a new result; use the main reviewer for corrected matrices.
