"""Offline M6 discovery audit; no market returns, selection or admission guesses.

Reuses the complete historical ETF discovery inventory, not the old R1B subset.
Source estimates are conditional acquisition routes, never impossibility proofs.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'data/raw_r1_universe/r1_2010_2024'
OUT = ROOT / 'reports/m6_r1i'
SCOPE = 'r1i-csi-historical-proxy-m6-v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path, expected=None):
    raw = Path(path).read_bytes()
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Archive identity mismatch: ' + str(path))
    return json.loads(raw)


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def main():
    manifest_path = ARCHIVE / 'universe_manifest_v3.json'
    manifest = read(manifest_path)
    original = read(ARCHIVE / manifest['inventory_path'], manifest['inventory_sha256'])
    documentary_path = ARCHIVE / 'documentary_manifest_v6.json'
    documentary = read(documentary_path)
    inventory = read(ARCHIVE / documentary['inventory_path'], documentary['inventory_sha256'])
    if {r['code'] for r in inventory} != {r['code'] for r in original}:
        raise ValueError('Documentary reconciliation lost historical identities')
    cal_source = manifest['calendar']
    cal = read(ARCHIVE / cal_source['raw_path'], cal_source['raw_sha256'])
    cal_records = [dict(zip(cal['fields'], row)) for row in cal['rows']]
    sessions = [r['calendar_date'] for r in cal_records if r['is_trading_day'] == '1']
    assert sessions == sorted(set(sessions)) and max(sessions) <= '2024-12-31'
    endpoints = []
    for entry in manifest['snapshot_queries']:
        raw = read(ARCHIVE / entry['raw_path'], entry['raw_sha256'])
        assert entry['status'] == raw['status'] == 'SUCCESS'
        endpoints.append(dict(date=entry['date'], rows=len(raw['rows']), raw_path=(ARCHIVE / entry['raw_path']).relative_to(ROOT).as_posix(), sha256=entry['raw_sha256']))
    hist_path = ARCHIVE / 'histories_b87b8e5ad646_v4.json'
    history = read(hist_path)
    histories = {}
    raw_bytes = 0
    for entry in history['query_results']:
        payload = read(ARCHIVE / entry['raw_path'], entry['raw_sha256'])
        assert payload['status'] == 'SUCCESS' and payload['query']['end'] <= '2024-12-31'
        raw_bytes += (ARCHIVE / entry['raw_path']).stat().st_size
        # This audit inspects response identity and row counts only, never prices/TR.
        histories[entry['code']] = dict(rows=len(payload['rows']), raw_path=(ARCHIVE / entry['raw_path']).relative_to(ROOT).as_posix(), sha256=entry['raw_sha256'])
    last_month = {}
    for i, day in enumerate(sessions):
        last_month[day[:7]] = i
    decisions = []
    for month, pos in sorted(last_month.items()):
        if pos + 2 >= len(sessions):
            continue
        execute = sessions[pos + 2]
        if not '2016-01-01' <= execute <= '2024-12-31':
            continue
        anchor = sessions[pos]
        qmonth = ((int(anchor[5:7])-1)//3)*3 + 1
        qstart = f'{anchor[:4]}-{qmonth:02d}-01'
        cutoff = max(day for day in sessions if day < qstart)
        decisions.append(dict(anchor=anchor, release_at=sessions[pos+1]+'T21:00:00+08:00', first_execution=execute,
                              quarter_cutoff=cutoff, period='development' if execute<'2022-01-01' else 'validation',
                              status='DATA_BLOCKED', n_eligible=None, n_ge_4=None, trend_on=None,
                              reason='Historical industry/method identity and full amount competition not admitted'))
    selection_dates = sorted({r['quarter_cutoff'] for r in decisions})
    candidates = []
    for row in inventory:
        overlap = sorted(set(row['snapshot_dates']) & set(selection_dates))
        listing = row.get('official_listing_evidence', [])
        sources = []
        for role, key in [('listing', 'official_listing_evidence'), ('identity', 'official_identity_evidence'), ('annual', 'official_annual_evidence')]:
            for source in row.get(key, []):
                published = source.get('publication_date') or source.get('report_publication_date')
                sources.append(dict(role=role, url=source.get('source_url') or source.get('report_source_url'),
                                    sha256=source.get('source_sha256') or source.get('annual_source_sha256'),
                                    publication_date=published, effective_from=None,
                                    historical_mapping_admitted=False,
                                    limitation='Document-specific evidence; no invented full effective interval'))
        candidates.append(dict(instrument_id=row['code'], first_snapshot=row['first_snapshot_seen'], last_snapshot=row['last_snapshot_seen'],
                               snapshot_dates=row['snapshot_dates'], relevant_selection_dates=overlap,
                               historical_names=[dict(x) for x in row['names']],
                               documentary_names=[r.get('name') for r in row.get('official_identity_evidence', []) if r.get('name')],
                               documented_benchmark_texts=[r.get('benchmark_text') for r in row.get('official_annual_evidence',[]) if r.get('benchmark_text')],
                               original_listing_evidence_count=len(listing),
                               source_evidence=sources, raw_history=histories.get(row['code']),
                               review_status='UNRESOLVED_HISTORICAL_SCOPE_AND_MAPPING' if overlap else 'OUTSIDE_REQUIRED_ENDPOINTS_CONDITIONAL_ON_SOURCE_COMPLETENESS',
                               scope_exclusion_by_name=False, csi_l1_id=None, csi_classification_version=None,
                               proxy_subdivision_level=None, mapping_publication_at=None, mapping_effective_from=None,
                               mapping_available_at=None, historical_identity_complete=False,
                               r1b_classification_is_r1i_evidence=False))
    relevant = [r for r in candidates if r['relevant_selection_dates']]
    missing_history = [r['instrument_id'] for r in relevant if r['raw_history'] is None]
    missing_listing = [r['instrument_id'] for r in relevant if not r['original_listing_evidence_count']]
    mean_bytes = raw_bytes / len(histories)
    plan = dict(schema_version='m6-r1i-source-plan-1', scope=SCOPE, registered_before_new_collection=True,
                source_inventory_count=len(candidates), historical_relevant_review_count=len(relevant),
                relevant_endpoint_dates=selection_dates, unresolved_amount_history_count=len(missing_history),
                missing_original_listing_count=len(missing_listing),
                terminology='Review universe is a conservative unresolved demand set, not a claim all products qualify as single-industry ETFs.',
                retained_outside_required_endpoints=[r['instrument_id'] for r in candidates if not r['relevant_selection_dates']],
                archived_history_count=len(histories), archived_raw_history_bytes=raw_bytes,
                estimates=[dict(route='Existing isolated per-ID BaoStock worker', minimum_new_sdk_calls=3*len(missing_history),
                                arithmetic='One login + one query + one logout per missing ID; pagination, retry extra',
                                gap_vs_global_1024=3*len(missing_history)-1024),
                           dict(route='Shared BaoStock session before pagination', minimum_new_sdk_calls=len(missing_history)+2,
                                arithmetic='One login/logout pair plus each missing ID; actual page counts must be measured',
                                remaining_vs_r1i_1000=1000-(len(missing_history)+2)),
                           dict(route='Individual original-document discovery plus one document', estimated_minimum_http=2*len(missing_listing),
                                arithmetic='One discovery query and one file per missing original; route estimate only, batch discovery can reduce it',
                                gap_vs_r1i_964=2*len(missing_listing)-964)],
                indicative_raw_history_body_bytes=round(mean_bytes*len(missing_history)),
                byte_estimate_limit='Historical mean over 110 R1B responses; not guaranteed, excludes documentary PDFs, pagination and retries.',
                fixed_pilot=dict(max_http_equivalents=48, max_sdk_calls=0,
                                 purpose='Historical taxonomy/method versions, original financial-realestate identity, and all-product batch listing discovery',
                                 known_first_requests=[
                                     'https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/H30199_Index_Methodology_cn.pdf',
                                     'https://static.cninfo.com.cn/finalpage/2015-04-14/1200828055.PDF'],
                                 forbidden='Mutable industryClassification URL known to currently contain2025-11 taxonomy; no post2024 taxonomy admitted',
                                 stop='End pilot on verified historical mapping/competition feasibility or concrete insufficient evidence; no indefinite expansion'),
                not_a_claim='This route estimate does not prove every free route impossible. Batch alternatives are tested before a finite stop.',
                input_hashes={p.relative_to(ROOT).as_posix():digest(p) for p in [manifest_path, documentary_path, hist_path, ARCHIVE/documentary['inventory_path']]})
    # Preserve the preregistration unchanged when the offline audit is rerun.
    if not (OUT/'SOURCE_PLAN.json').exists():
        save('SOURCE_PLAN.json', plan)
    else:
        if read(OUT/'SOURCE_PLAN.json') != plan:
            raise ValueError('Source-plan inputs changed; requires explicit new registration')
    save('candidate_inventory.json', dict(scope=SCOPE, count=len(candidates), records=candidates))
    save('monthly_data_gate.json', dict(scope=SCOPE, status='DATA_BLOCKED', decisions=decisions,
                                      denominator_by_period=dict(Counter(r['period'] for r in decisions)),
                                      denominator_by_execution_year=dict(Counter(r['first_execution'][:4] for r in decisions)),
                                      n_distribution={'UNKNOWN':len(decisions)}, n_ge4_trend_on=None,
                                      reason='Unknown inputs are not zero eligible or cash signals'))
    save('quarterly_representatives.json', dict(scope=SCOPE, status='DATA_BLOCKED', quarters=[
        dict(cutoff=d+'T21:00:00+08:00', representatives=None, status='DATA_BLOCKED', reason='Historical industry versions and competitor amounts incomplete') for d in selection_dates]))
    save('archive_audit.json', dict(scope=SCOPE, data_origin='REAL_ARCHIVED_SOURCE', synthetic=False,
        inventory_count=len(candidates), relevant_review_count=len(relevant), calendar_sessions=len(sessions),
        endpoint_count=len(endpoints), membership_rows=sum(r['rows'] for r in endpoints), endpoint_sources=endpoints,
        provider_nameless_count=sum(not r['names'] for r in inventory),
        documentary_name_count=sum(bool(r.get('official_identity_evidence')) for r in inventory),
        annual_evidence_count=sum(bool(r.get('official_annual_evidence')) for r in inventory),
        annual_evidence_published_by_2024_count=sum(any(x.get('report_publication_date','9999')<='2024-12-31' for x in r.get('official_annual_evidence',[])) for r in inventory),
        raw_history_count=len(histories), raw_history_rows=sum(r['rows'] for r in histories.values()),
        raw_history_bytes=raw_bytes, missing_raw_history_ids=missing_history, missing_original_listing_ids=missing_listing,
        historical_csi_classification_admitted_versions=0, source_hashes=plan['input_hashes'],
        existing_method_file=dict(path='data/raw_policy/csi_method_2023_bcffe454c6e7.pdf',sha256=digest(ROOT/'data/raw_policy/csi_method_2023_bcffe454c6e7.pdf'),
                                 title='Stock index calculation and maintenance rules V13.1, September2023',is_industry_classification=False),
        limitations=['Endpoint completeness remains conditional on the provider; same-provider bar crosscheck cannot prove omitted IDs absent.',
                     'Current names and retrospective annual reports do not supply historical effective classifications.',
                     'No strategy returns, momentum, IC or performance were calculated.']))
    print(json.dumps(dict(inventory=len(candidates), relevant=len(relevant), missing_history=len(missing_history), calendar_decisions=len(decisions))))


if __name__ == '__main__':
    main()
