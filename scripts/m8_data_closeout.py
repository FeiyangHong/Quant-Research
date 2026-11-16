"""Offline, append-only evidence for M8 collection and staged inputs."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from m8_data_collect import ROOT, OUT, REPORT, save, sha


def main():
    now=datetime.now(timezone.utc).isoformat()
    book=json.loads((OUT/'budget.json').read_bytes())
    log=json.loads((REPORT/'request_log.json').read_bytes())
    by_label={r['label']:r for r in book['attempts']}
    pending=[r for r in log if not r.get('receipt')]
    resolution=[]
    for row in pending:
        if row['label'] in by_label:
            record=by_label[row['label']]
            if not record.get('terminal'):raise ValueError('Unfinished attempt')
            resolution.append(dict(label=row['label'],status='TERMINAL_DURABLE_LEDGER',attempt_id=record['id']))
        elif row['label']=='annual2024_titles_sz.159939':
            replacement=by_label['annual2024_titles_sz.159939_after_local_begin_failure']
            resolution.append(dict(label=row['label'],status='LOCAL_PREWIRE_FAILURE_NO_HTTP',
                cause='Windows PermissionError in BudgetLedger.begin atomic_json replace before durable reservation and HTTP',
                durable_attempt_present=False,http_request_sent=False,
                original_registration_sha256=sha(REPORT/'requests'/(row['label']+'.json')),
                replacement_attempt_id=replacement['id'],replacement_label=replacement['label'],
                original_registration_preserved=True))
        else:raise ValueError('Unclassified request registration '+row['label'])
    assert all(r.get('terminal') for r in book['attempts'])
    assert all(book['used'][key]<=book['limits'][key] for key in book['used'])
    stage=ROOT/'data/m8_rotation/stage_v1';manifest=json.loads((stage/'manifest.json').read_bytes())
    for path,digest in manifest['source_snapshot_hashes'].items():
        assert sha(ROOT/path)==digest,path
    selected=manifest['cohort_selection']['selected_instruments']
    amount_rows=0;amount_errors=[];volume_checks=[]
    for sid in selected:
        p=json.loads((OUT/'decoded'/('holding_'+sid+'.json')).read_bytes())
        primary={r[0]:dict(zip(p['fields'],r)) for r in p['rows']}
        for day,row in primary.items():
            volume=Decimal(row['volume']);amount=Decimal(row['amount'])
            low=Decimal(row['low'])*volume;high=Decimal(row['high'])*volume
            tolerance=max(Decimal('1'),abs(amount)*Decimal('0.000001'))
            amount_rows+=1
            if amount<low-tolerance or amount>high+tolerance:
                amount_errors.append(dict(instrument_id=sid,date=day,amount=str(amount),low_bound=str(low),high_bound=str(high)))
        secondary=json.loads((OUT/'decoded'/('tencent_'+sid+'.json')).read_bytes())
        diffs=[abs(Decimal(primary[r['date']]['volume'])-Decimal(r['volume_vendor_units'])*100) for r in secondary if r['date'] in primary]
        volume_checks.append(dict(instrument_id=sid,rows=len(diffs),max_share_difference_at_empirical_100_multiplier=str(max(diffs)),
            differences_above_99=sum(d>99 for d in diffs),unit_status='EMPIRICAL_SCALE_CORROBORATION_ONLY_NOT_VENDOR_UNIT_DOCUMENTATION'))
    save(REPORT/'AMOUNT_UNIT_CHECK.json',dict(status='PASS' if not amount_errors else 'UNRESOLVED',
        source='Offline primary raw CNY amount and fund-unit volume consistency',rows=amount_rows,
        rule='low*fund_units - max(1 CNY,1e-6 amount) <= amount <= high*fund_units + tolerance',
        errors=amount_errors,secondary_amount_status='NOT_PROVIDED',secondary_volume_empirical_checks=volume_checks,
        interpretation='The amount check is an independent arithmetic consistency check, not a second-source amount observation.'))
    original_titles=json.loads((REPORT/'titles/holding_sz.159939.json').read_bytes())
    save(REPORT/'HOLDING_TITLE_SLICE_NOTE.json',dict(instrument_id='sz.159939',
        original_archive_reported_count=original_titles['reported_count'],retained_count=len(original_titles['records']),
        retained_start='2019-01-01',retained_end='2024-12-31',
        title_file_sha256=sha(REPORT/'titles/holding_sz.159939.json'),
        note='Original reported/returned counts describe the complete reused 2014-2024 archive; retained records are the exact 2019-2024 subset.'))
    failures=[{k:r.get(k) for k in ('id','kind','label','status','error','byte_count','raw_path','sha256','started_at','ingested_at')} for r in book['attempts'] if r.get('status') not in ('FETCHED','SUCCESS')]
    save(REPORT/'COLLECTION_CLOSEOUT.json',dict(as_of=now,conservative_session_start='2026-11-15T16:31:00+00:00',
        source_collection_complete=True,ledger_sha256=sha(OUT/'budget.json'),limits=book['limits'],used=book['used'],
        attempts=len(book['attempts']),terminal_attempts=sum(r.get('terminal',False) for r in book['attempts']),
        by_status=dict(Counter(r.get('status') for r in book['attempts'])),failed_attempts_retained=failures,
        registered_request_resolutions=resolution,
        time_accounting_note='This closes source collection only. Parent reports the actual final task end inclusive of waiting; this is not the final aggregate agent-hours receipt.'))
    save(REPORT/'source_manifest.json',dict(schema_version='m8-source-manifest-1.0',created_at=now,
        stage_path=stage.relative_to(ROOT).as_posix(),stage_manifest_sha256=sha(stage/'manifest.json'),
        cohort_selection_sha256=manifest['cohort_selection_sha256'],source_snapshot_hashes=manifest['source_snapshot_hashes'],
        data_files=manifest['file_sha256'],raw_input_coverage='FULL_SELECTED_HOLDING_2019_2024_AND_REQUIRED_PRE2019_FORMATION',
        source_collection_receipt_sha256=sha(REPORT/'COLLECTION_CLOSEOUT.json'),
        late_2024_annuals='Published in 2025; retrospective 2024 action/identity completeness only, actual clocks retained, never signal input',
        secondary_response_quarantine='Only bounded historical data[code].day arrays parsed. Unsolicited quote members in immutable raw responses are excluded from decoding, signals, and analysis.',
        secondary_amount_status='NOT_PROVIDED',
        local_only_reuse='All pre-existing source files retain original hashes and provenance; no claim of new independent retrieval.'))
    print(json.dumps(dict(used=book['used'],terminal=len(book['attempts']),amount_rows=amount_rows,amount_errors=len(amount_errors),pending_resolved=len(resolution))))


if __name__=='__main__':main()
