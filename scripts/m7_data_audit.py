"""Offline original listing and raw-amount dependencies; no account returns."""
from bisect import bisect_left
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess

from m7_data_collect import ROOT, OUT, REPORT, COHORT, save
from quant_research.providers.official import listing_evidence
from quant_research.data import date_only_available_at

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def calendar():
    root=ROOT/'data/normalized_csi/h00300_2010_2024_v1'
    manifest=json.loads((root/'manifest.json').read_bytes())
    for path,digest in manifest['files'].items():
        if sha(root/path)!=digest:raise ValueError('Reused benchmark/calendar hash mismatch '+path)
    payload=json.loads(next((root/'calendar_evidence/raw').glob('*a1*.json')).read_bytes())
    return [r[0] for r in payload['rows'] if r[1]=='1']

def extracted(cap):
    raw=Path(cap['raw_path'])
    if sha(raw)!=cap['sha256']:raise ValueError('Source hash mismatch')
    out=OUT/'text'/(cap['sha256']+'.txt');out.parent.mkdir(parents=True,exist_ok=True)
    if not out.exists():
        run=subprocess.run(['pdftotext','-layout',str(raw),str(out)],capture_output=True,timeout=30)
        if run.returncode:raise ValueError('PDF extraction failed')
    return out,out.read_text(encoding='utf8')

def identities():
    sessions=calendar();logs=json.loads((REPORT/'request_log.json').read_bytes());bylabel={r['label']:r for r in logs}
    result=[]
    plan=json.loads((REPORT/'SOURCE_PLAN.json').read_bytes())
    indices={'sz.159936':'000989','sz.159938':'000991','sz.159939':'000993','sz.159940':'000992','sz.159944':'000987','sz.159945':'000986','sz.159946':'000990'}
    for listing in plan['listings']:
        sid=listing['instrument_id']
        if sid=='sz.159940':
            fact=next(r for r in json.loads((ROOT/'reports/m6_r1i/source_evidence.json').read_bytes())['facts'] if r['label']=='r1i_financial_realestate_2015')
            cap=dict(raw_path=fact['raw_path'],sha256=fact['sha256'],ingested_at=fact['ingested_at']);url=fact['url']
        else:cap=bylabel['listing_'+sid]['receipt'];url=listing['source_url']
        path,text=extracted(cap)
        doc=dict(instrument_id=sid,title=listing['title'],publication_date=listing['publication_date'],source_url=url,pdf_sha256=cap['sha256'],pdf_path=cap['raw_path'],text_path=str(path),document_kind='LISTING_NOTICE')
        row=listing_evidence(doc,text,sessions)
        row.update(raw_path=cap['raw_path'],ingested_at=cap.get('ingested_at'),exact_index_id=indices[sid])
        compact=re.sub(r'\s+','',text)
        row['index_code_found_in_original']=indices[sid] in compact
        row['security_code_found_in_original']=sid[3:] in compact
        row['delisted_on']='2018-12-28' if sid=='sz.159946' else None
        result.append(row)
    save(REPORT/'identity_evidence.json',result)
    return result

def eligibility():
    sessions=calendar();master={r['instrument_id']:r for r in identities()};byid={};coverage=[]
    for sid in COHORT:
        path=OUT/'decoded'/('history_'+sid+'.json');payload=json.loads(path.read_bytes())
        rows=[dict(zip(payload['fields'],r)) for r in payload['rows']];byid[sid]={r['date']:r for r in rows}
        first=master[sid]['listed_on'];end=master[sid]['delisted_on'] or '2025-01-01'
        expected=[d for d in sessions if first<=d<end]
        missing=sorted(set(expected)-set(byid[sid]));extra=sorted(set(byid[sid])-set(expected))
        coverage.append(dict(instrument_id=sid,raw_path=str(path),sha256=sha(path),expected=len(expected),observed=len(rows),missing_dates=missing,extra_dates=extra,
            zero_amount_dates=[r['date'] for r in rows if Decimal(r['amount'])==0],status_values=sorted(set(r['tradestatus'] for r in rows)),units=dict(amount='CNY',volume='ETF_SHARES')))
    months=[]
    for i,day in enumerate(sessions[:-2]):
        if day<'2016-01-01' or day[:7]==sessions[i+1][:7]:continue
        members=[]
        for sid in COHORT:
            m=master[sid];age=i-bisect_left(sessions,m['listed_on'])+1
            reason=None;median=None;missing=[]
            if m['delisted_on'] and day>=m['delisted_on']:reason='DELISTED'
            elif age<252:reason='LISTED_LESS_THAN_252'
            else:
                window=sessions[i-19:i+1];missing=[d for d in window if d not in byid[sid]]
                if missing:reason='UNKNOWN_MISSING_AMOUNTS'
                else:
                    amounts=sorted(Decimal(byid[sid][d]['amount']) for d in window);median=(amounts[9]+amounts[10])/2
                    if byid[sid][day]['tradestatus'] not in ('0','1'):reason='UNKNOWN_STATUS'
                    elif byid[sid][day]['tradestatus']=='0':reason='SUSPENDED'
                    elif median<20000000:reason='MEDIAN_AMOUNT_BELOW_20M'
            members.append(dict(instrument_id=sid,listed_sessions=age,median_amount20=str(median) if median is not None else None,
                status='UNKNOWN' if reason and reason.startswith('UNKNOWN') else 'INELIGIBLE' if reason else 'ELIGIBLE_RAW_PENDING_LIFECYCLE',reason=reason,missing_dates=missing))
        n=None if any(r['status']=='UNKNOWN' for r in members) else sum(r['status']=='ELIGIBLE_RAW_PENDING_LIFECYCLE' for r in members)
        months.append(dict(anchor=day,released_at=date_only_available_at(day,sessions),base_execution=sessions[i+2],delay_execution=sessions[i+3] if i+3<len(sessions) else None,N_raw=n,members=members))
    result=dict(scope='R1I_FIXED_COHORT_V1',stage='RAW_AMOUNTS_BEFORE_RETURNS',qualification_complete=False,
        outstanding='Lifecycle/permission and exact necessary action coverage require review; raw amount pass is not final eligibility',
        months=months,N_raw_distribution=dict(Counter(str(r['N_raw']) for r in months)),coverage=coverage,
        raw_eligible_months={sid:sum(next(m for m in r['members'] if m['instrument_id']==sid)['status']=='ELIGIBLE_RAW_PENDING_LIFECYCLE' for r in months) for sid in COHORT})
    save(REPORT/'RAW_ELIGIBILITY.json',result)
    print(json.dumps({k:result[k] for k in ['N_raw_distribution','raw_eligible_months']}))

if __name__=='__main__':eligibility()
