"""Offline source-byte and Decimal eligibility proof, without production imports."""
from collections import Counter
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path
import re
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
LISTED = {'sz.159936': '2014-06-25', 'sz.159938': '2015-01-08',
          'sz.159939': '2015-02-05', 'sz.159940': '2015-04-17',
          'sz.159944': '2015-07-06', 'sz.159945': '2015-07-06',
          'sz.159946': '2015-07-13'}


def read(relative):
    return json.loads((ROOT / relative).read_text('utf-8'))


def main():
    budget = read('data/raw_m7/budget.json')
    receipts = budget['attempts']
    hashes = {}
    def raw_receipt(rec):
        data = Path(rec['raw_path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == rec['sha256']
        assert len(data) == rec['byte_count']
        hashes[rec['raw_path']] = rec['sha256']
        return data
    def document(label):
        rec = next(r for r in receipts if r['label'] == label)
        s = raw_receipt(rec).decode('utf-8-sig')
        return re.sub(r'\s+', '', html.unescape(re.sub(r'<[^>]+>', '', s)))
    cohort = document('cohort_20160104')
    assert '2016-01-04' in cohort and '截至2015年12月31日' in cohort
    for sid in LISTED:
        assert sid[3:] in cohort
    event = document('exit_159946_20181226')
    assert '终止上市日：2018年12月28日' in event
    assert '终止上市的权益登记日：2018年12月27日' in event
    assert '上市交易日：2015年7月13日' in event
    assert '2018年12月26日' in event and '广发基金管理有限公司' in event
    calendar_path = ROOT / 'data/admitted_r1/phase2_v1/development/calendar.json'
    assert hashlib.sha256(calendar_path.read_bytes()).hexdigest() == '8200cca2c04cc847ebddf43c0783ff1b8d15b28a9d11e48a3b3f51661c4e52ae'
    calendar = sorted(set(json.loads(calendar_path.read_bytes()) + read('data/admitted_r1/phase2_v1/validation/calendar.json')))
    assert calendar[-1] == '2024-12-31'
    series, coverage, units, anomalies = {}, {}, {}, []
    for sid, listing in LISTED.items():
        records = []
        for rec in receipts:
            if rec['kind'] == 'baostock_wire_attempts' and rec['label'] == 'history_' + sid:
                wire = raw_receipt(rec).decode('utf-8')
                payload, _ = json.JSONDecoder().raw_decode(wire[wire.index('{'):])
                records.extend(payload['record'])
        assert records and all(row[1] == sid and row[9] == '3' for row in records)
        assert len({row[0] for row in records}) == len(records)
        final = '2018-12-27' if sid == 'sz.159946' else '2024-12-31'
        dates = [d for d in calendar if listing <= d <= final]
        assert [row[0] for row in records] == dates, sid
        # Verify the convenience decode did not omit, transform or reorder rows.
        assert records == read('data/raw_m7/decoded/history_' + sid + '.json')['rows']
        series[sid] = {r[0]: r for r in records}
        coverage[sid] = dict(first=dates[0], last=dates[-1], count=len(records), missing_sessions=0)
        unit_checks = 0
        for row in records:
            volume, amount = Decimal(row[7]), Decimal(row[8])
            assert volume >= 0 and amount >= 0 and row[11] in ('0', '1')
            if row[11] == '0':
                assert volume == amount == 0
            if volume:
                # Source precision is tested in yuan, not a price tolerance
                # which would grow with volume. No raw value is changed.
                vwap = amount / volume
                if not Decimal(row[4]) - Decimal('.002') <= vwap <= Decimal(row[3]) + Decimal('.002'):
                    anomalies.append(dict(instrument_id=sid,date=row[0],volume=row[7],amount=row[8],
                                          low=row[4],high=row[3],implied_vwap=str(vwap)))
                assert volume * Decimal(row[4]) - 1 <= amount <= volume * Decimal(row[3]) + 1, (sid,row[0])
                unit_checks += 1
        units[sid] = unit_checks
    months = []
    qualifying = Counter()
    for i, day in enumerate(calendar[:-2]):
        if not '2016-01-29' <= day <= '2024-11-29' or day[:7] == calendar[i+1][:7]:
            continue
        members = []
        for sid, listing in LISTED.items():
            age = sum(listing <= d <= day for d in calendar)
            med = None
            valid = False
            reason = 'TOO_YOUNG'
            if sid == 'sz.159946' and day >= '2018-12-28':
                reason = 'DELISTED'
            elif age >= 252:
                window = [series[sid][d] for d in calendar[i-19:i+1]]
                med = median(Decimal(r[8]) for r in window)
                assert (med - 1 >= 20000000) == (med + 1 >= 20000000), (sid,day,'precision can alter eligibility')
                valid = med >= 20000000 and window[-1][11] == '1'
                reason = 'RAW_QUALIFIED' if valid else 'AMOUNT_OR_SUSPENSION'
            qualifying[sid] += int(valid)
            members.append(dict(instrument_id=sid, listed_sessions=age,
                                median_amount20=str(med) if med is not None else None,
                                raw_qualified=valid, reason=reason))
        months.append(dict(anchor=day, release=calendar[i+1], execution=calendar[i+2],
                           N_upper_bound=sum(r['raw_qualified'] for r in members), members=members))
    assert len(months) == 107 and months[0]['anchor'] == '2016-01-29'
    assert months[0]['release'] == '2016-02-01' and months[0]['execution'] == '2016-02-02'
    author = read('reports/m7_cohort/RAW_ELIGIBILITY.json')['months']
    assert len(author) == len(months)
    for actual, expected in zip(author, months):
        assert actual['anchor'] == expected['anchor'] and actual['N_raw'] == expected['N_upper_bound']
        for a, e in zip(actual['members'], expected['members']):
            assert a['instrument_id'] == e['instrument_id']
            assert a['listed_sessions'] == e['listed_sessions']
            assert a['median_amount20'] == e['median_amount20']
    distribution = dict(Counter(r['N_upper_bound'] for r in months))
    output = dict(status='PASS_RAW_AMOUNTS_AND_SOURCE_BOUNDARIES', new_network_attempts=0,
                  source_hashes=hashes, listing_dates_hand_read_from_original_PDF_page1=LISTED,
                  raw_coverage=coverage, unit_crosschecks=units, months=months,
                  tiny_trade_amount_precision_anomalies=anomalies,
                  all_amounts_within_one_yuan_of_OHLC_volume_bounds=True,
                  eligibility_invariant_under_plus_minus_one_yuan_amount_error=True,
                  N_upper_bound_distribution=distribution, raw_qualified_months=dict(qualifying),
                  dead_member_always_ineligible=qualifying['sz.159946'] == 0,
                  limitation='Lifecycle and permission can only further restrict this raw upper bound; final admission reviewed separately. No return or account outcome used.')
    (ROOT / 'reports/m7_review/independent_raw_probe.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps({k:output[k] for k in ('status','raw_coverage','N_upper_bound_distribution','raw_qualified_months','dead_member_always_ineligible')}, indent=2))


if __name__ == '__main__':
    main()
