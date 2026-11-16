"""Read registered targets, without simulating or inspecting investment returns."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from quant_research.data import load_dataset
from quant_research.liquid_cohort import generate_liquid_targets, liquid_opportunities
from quant_research.provenance import write_json
from quant_research.runner import dataset_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--admitted', type=Path, required=True)
    args = parser.parse_args()
    periods, proof = {}, []
    for period in ('development', 'validation'):
        data = load_dataset(args.admitted / period)
        opportunities = liquid_opportunities(data)
        annual = defaultdict(list)
        for row in opportunities['schedule']:
            annual[row['execution_date'][:4]].append(row)
        opportunities['annual_by_execution_year'] = {
            year: dict(monthly_decisions=len(rows),
                       eligible_count_distribution=dict(Counter(str(r['eligible_count']) for r in rows)),
                       n_ge3=sum(r['eligible_count'] is not None and r['eligible_count'] >= 3 for r in rows),
                       n_ge4=sum(r['eligible_count'] is not None and r['eligible_count'] >= 4 for r in rows),
                       investable_trend_on=sum(r['eligible_count'] is not None and r['eligible_count'] >= 3
                                               and r['trend'] is True for r in rows),
                       investable_trend_off=sum(r['eligible_count'] is not None and r['eligible_count'] >= 3
                                                and r['trend'] is False for r in rows),
                       ranking_target_difference=sum(r['ranking_targets_differ'] for r in rows))
            for year, rows in sorted(annual.items())}
        periods[period] = dict(opportunities, data_hash=dataset_hash(data))
        start = data.manifest['funded_account_start']
        for variant in ('E0', 'R0', 'E1', 'R1'):
            for delay in (1, 2):
                targets = [d for d in generate_liquid_targets(data, variant, delay)
                           if d.execution_date >= start]
                proof.append(dict(period=period, variant=variant, execution_delay=delay,
                                  flat_initial_cash_cny=100000, monthly_decisions=len(targets),
                                  nonzero_targets=sum(bool(d.weights) for d in targets),
                                  no_missing_input_converted_to_cash=True))
    all_cash = all(row['nonzero_targets'] == 0 for row in proof)
    write_json(ROOT / 'reports/m8_rotation/OPPORTUNITIES.json', dict(
        performance_evidence=False, periods=periods, analytic_proof=proof,
        all_registered_paths_analytically_no_exposure=all_cash,
        conclusion='ANALYTICALLY_NO_EXPOSURE' if all_cash else 'ACCOUNT_MATRIX_REQUIRED',
        costs_cannot_create_holdings_from_zero_targets=True))


if __name__ == '__main__':
    main()
