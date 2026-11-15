"""M6 frozen R1I selection contract; algorithm engineering, not data admission.

The ordinary experiment runner remains closed to R1I. These kernels consume
explicit historical classification evidence and never infer it from fund names.
No return, survivor status or monthly qualification enters quarter competition.
"""
from bisect import bisect_left
import math
import pandas as pd

from .temporal import master_snapshot, representative_snapshot, master_record, TemporalStateError
from .strategy import StrategyBlockedError, _prepare, _snapshot, _matrix, _cutoff

SCOPE_VERSION='r1i-csi-historical-proxy-m6-v1'


def _mapped(master, at, ids=None):
    try:
        current=master_snapshot(master,at)
        evidenced=representative_snapshot(master,at)
    except TemporalStateError as exc:
        raise StrategyBlockedError('DATA_BLOCKED: '+str(exc)) from exc
    rows={r['instrument_id']:r for r in current.to_dict('records')}
    benchmarks=set(evidenced.instrument_id)
    result={}
    for sid in sorted(ids if ids is not None else rows):
        row=rows.get(sid)
        if row is None:
            raise StrategyBlockedError('DATA_BLOCKED: expired/unknown state '+sid)
        if row.get('listed_on','9999')>at.strftime('%Y-%m-%d'):
            continue
        ended=row.get('delisted_on')
        if isinstance(ended,str) and ended and ended<=at.strftime('%Y-%m-%d'):
            continue
        status=row.get('r1i_scope_status')
        source=pd.Timestamp(row.get('mapping_available_at'))
        if status not in {'INCLUDED','EXCLUDED'} or pd.isna(source) or source.tzinfo is None or source>at:
            raise StrategyBlockedError('DATA_BLOCKED: historical scope/mapping unavailable '+sid)
        if status=='EXCLUDED':
            result[sid]=row
            continue
        if (sid not in benchmarks or row.get('asset_type')!='ETF'
            or not all(isinstance(row.get(k),str) and row[k] for k in
                ('index_identity','benchmark_id','csi_level1_id','csi_taxonomy_version'))):
            raise StrategyBlockedError('DATA_BLOCKED: historical index/industry evidence '+sid)
        result[sid]=row
    versions={r['csi_taxonomy_version'] for r in result.values() if r['r1i_scope_status']=='INCLUDED'}
    if len(versions)>1:
        raise StrategyBlockedError('DATA_BLOCKED: mixed contemporaneous CSI taxonomy versions')
    return result


def _index_changed_in_quarter(rep, master, cutoff):
    """Inspect visible history, including a change subsequently reversed.

    Shared state resolution uses current knowledge and each historical effective
    date, so corrected false states do not survive merely as superseded rows.
    This is separate from choosing today's state and never changes publication.
    """
    start=rep['quarter_start'];end=cutoff.strftime('%Y-%m-%d')
    rows=master.loc[master.instrument_id.eq(rep['instrument_id'])].to_dict('records')
    dates={start,end}
    for row in rows:
        if pd.Timestamp(row['available_at'])>cutoff:continue
        for field in ('effective_from','effective_to'):
            value=row.get(field)
            if isinstance(value,str) and start<=value<=end:dates.add(value)
    for day in sorted(dates):
        try:row=master_record(rows,cutoff,effective_date=day)
        except TemporalStateError as exc:raise StrategyBlockedError('DATA_BLOCKED: '+str(exc)) from exc
        if row is None:
            raise StrategyBlockedError('DATA_BLOCKED: unknown within-quarter index state '+rep['instrument_id'])
        if row.get('index_identity')!=rep['index_identity']:return True
    return False


def quarter_representatives(master, bars, calendar, quarter_start):
    """Two-stage amount-only selection; every unresolved competitor blocks.

    Master scope INCLUDE/EXCLUDE must itself have historical source evidence.
    Listed <60 sessions are a known insufficient history, not a data omission.
    The returned frozen sort key survives mid-quarter taxonomy changes.
    """
    dates=list(calendar)
    if dates!=sorted(set(dates)) or quarter_start not in dates:
        raise ValueError('Ordered unique calendar containing quarter start required')
    pos=dates.index(quarter_start)
    if pos<60:raise StrategyBlockedError('DATA_BLOCKED: 60-session warmup absent')
    if pos and pd.Timestamp(dates[pos-1]).to_period('Q')==pd.Timestamp(quarter_start).to_period('Q'):
        raise ValueError('Quarter selection only on first supplied session of quarter')
    previous=dates[pos-1];at=_cutoff(previous)
    # Existing listed identities with expired state cannot silently disappear.
    candidate_ids=set(master.loc[master.listed_on.le(previous),'instrument_id'])
    mapped=_mapped(master,at,candidate_ids)
    history=_snapshot(_prepare(bars),at,['date','instrument_id'])
    amounts=_matrix(history,'amount',dates[pos-60:pos])
    candidates=[]
    for sid,row in mapped.items():
        if row['r1i_scope_status']=='EXCLUDED':continue
        if pos-bisect_left(dates,row['listed_on'])<60:continue
        if sid not in amounts:
            raise StrategyBlockedError('DATA_BLOCKED: required competitor amounts '+sid)
        values=amounts[sid]
        if len(values)!=60 or not values.map(lambda x:pd.notna(x) and math.isfinite(x) and x>=0).all():
            raise StrategyBlockedError('DATA_BLOCKED: incomplete competitor amounts '+sid)
        amount=float(values.mean())
        candidates.append(dict(instrument_id=sid,index_identity=row['index_identity'],
            benchmark_id=row['benchmark_id'],csi_level1_id=row['csi_level1_id'],
            csi_taxonomy_version=row['csi_taxonomy_version'],quarter_start=quarter_start,
            cutoff=at.isoformat(),mean_amount60=amount,
            quarter_sort_key=(-amount,row['listed_on'],sid)))
    # An exact economic index cannot have two contemporary industry identities.
    index_industries={}
    for row in candidates:
        index_industries.setdefault(row['index_identity'],set()).add(row['csi_level1_id'])
    if any(len(v)>1 for v in index_industries.values()):
        raise StrategyBlockedError('DATA_BLOCKED: conflicting exact-index industry mapping')
    first={};second={}
    for row in sorted(candidates,key=lambda x:x['quarter_sort_key']):
        first.setdefault(row['index_identity'],row)
    for row in sorted(first.values(),key=lambda x:x['quarter_sort_key']):
        second.setdefault(row['csi_level1_id'],row)
    return sorted(second.values(),key=lambda x:x['instrument_id'])


def monthly_pool(representatives, master, cutoff, eligibility):
    """Remap frozen identities; eligibility[sid] = {'qualified': bool, 'reason':str}.

    Callers must separately prove monthly age/liquidity/status/permission fields.
    Missing qualification is unknown data, never an eligible empty/cash month.
    """
    at=pd.Timestamp(cutoff)
    if pd.isna(at) or at.tzinfo is None:raise ValueError('Aware cutoff required')
    ids=[r['instrument_id'] for r in representatives]
    if len(ids)!=len(set(ids)):raise ValueError('Unique frozen representatives required')
    mapped=_mapped(master,at,set(ids));exclusions={};buckets={}
    for rep in sorted(representatives,key=lambda x:tuple(x['quarter_sort_key'])):
        sid=rep['instrument_id'];row=mapped.get(sid)
        if row is None:
            exclusions[sid]='KNOWN_DELISTED';continue
        if row['r1i_scope_status']=='EXCLUDED':
            exclusions[sid]='NO_LONGER_SINGLE_INDUSTRY_SCOPE';continue
        if _index_changed_in_quarter(rep,master,at):
            exclusions[sid]='INDEX_ECONOMIC_IDENTITY_CHANGED_UNTIL_NEXT_QUARTER';continue
        industry=row['csi_level1_id']
        if industry in buckets:
            exclusions[sid]='MERGED_INDUSTRY_LOST_FROZEN_QUARTER_KEY';continue
        buckets[industry]=sid
    eligible=[]
    for sid in sorted(buckets.values()):
        item=eligibility.get(sid)
        if not item or type(item.get('qualified')) is not bool:
            raise StrategyBlockedError('DATA_BLOCKED: monthly qualification unknown '+sid)
        if item['qualified']:eligible.append(sid)
        else:exclusions[sid]=item.get('reason') or 'FAILED_REGISTERED_MONTHLY_QUALIFICATION'
    return dict(eligible=eligible,exclusions=exclusions,
        industries={sid:mapped[sid]['csi_level1_id'] for sid in eligible},
        csi_taxonomy_versions={sid:mapped[sid]['csi_taxonomy_version'] for sid in eligible},
        risk_scaling=False)


def rule_weights(eligible, momentum, trend, variant):
    """Fixed E0/R0/E1/R1 targets. Negative relative momentum remains eligible."""
    if variant not in {'E0','R0','E1','R1'}:raise ValueError('Unknown fixed rule')
    ids=sorted(eligible)
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate eligible identities')
    if len(ids)<3:
        return dict(weights={},status='CASH_COMPLETE_POOL_LT3',risk_scaling=False)
    selected=ids
    if variant in {'R0','R1'}:
        if any(sid not in momentum or not math.isfinite(momentum[sid]) for sid in ids):
            raise StrategyBlockedError('DATA_BLOCKED: required winner/competitor momentum')
        selected=sorted(ids,key=lambda sid:(-momentum[sid],sid))[:3]
    if variant in {'E1','R1'}:
        if type(trend) is not bool:raise StrategyBlockedError('DATA_BLOCKED: trend history')
        if not trend:return dict(weights={},status='CASH_TREND_OFF',risk_scaling=False)
    return dict(weights={sid:min(.35,1/len(selected)) for sid in selected},
        status='OK_NO_RANKING_FREEDOM_N3' if len(ids)==3 else 'OK',risk_scaling=False)


def identification_gate(rows, expected_execution_dates):
    """Rows are scheduled by first planned execution date; no return input."""
    expected=set(expected_execution_dates)
    if len(expected)!=len(expected_execution_dates):raise ValueError('Duplicate expected execution dates')
    seen=set();counts={'development':0,'validation':0};years={2022:0,2023:0,2024:0}
    unknown=[];distribution={};trend_on=0
    for row in rows:
        day=row['execution_date']
        if day in seen or day not in expected:raise ValueError('Unexpected/duplicate planned execution date')
        seen.add(day)
        if not '2016-01-01'<=day<='2024-12-31':raise ValueError('Outside registered evaluation dates')
        n=row.get('eligible_count')
        if row.get('data_complete') is not True or type(n) is not int or n<0:
            unknown.append(day);continue
        distribution[str(n)]=distribution.get(str(n),0)+1
        if n>=4:
            period='development' if day<'2022-01-01' else 'validation'
            counts[period]+=1
            if period=='validation':years[int(day[:4])]+=1
            if row.get('trend_on') is True:trend_on+=1
    unknown.extend(sorted(expected-seen))
    status=('DATA_BLOCKED' if unknown else 'PASS' if counts['development']>=36 and
        counts['validation']>=24 and min(years.values())>=6 else 'LIMITED_IDENTIFICATION')
    return dict(status=status,scheduled_count=len(expected),unknown_dates=sorted(unknown),
        eligible_count_distribution=distribution,n_ge4_by_period=counts,
        n_ge4_by_validation_year=years,n_ge4_and_trend_on=trend_on if not unknown else None)
