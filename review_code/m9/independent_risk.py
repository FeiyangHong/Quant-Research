"""Independent risk expectations from source TR and current unscaled weights.

Production risk/target code is never imported here. Decimal scalar basket
returns preserve the covariance implicit in simultaneous observations.
"""
from collections import defaultdict
from decimal import Decimal, localcontext
from independent_accounts import D


def risk(source, anchor, release, weights):
    days = source['calendar']
    position = days.index(anchor)
    assert position >= 60
    window = days[position-59:position+1]
    cutoff = release+'T21:00:00+08:00'
    grouped = defaultdict(list)
    for row in source['bars']:
        if row['date'] <= anchor and row['instrument_id'] in weights:
            grouped[row['date'],row['instrument_id']].append(row)
    known = {}
    for key, rows in grouped.items():
        choices = [r for r in rows if r['available_at'] <= cutoff]
        if choices:
            known[key] = max(choices,key=lambda r:r['available_at'])
    complete, missing, baskets = [], [], []
    for day in window:
        prior = days[days.index(day)-1]
        returns, failed = {}, []
        for sid,w in weights.items():
            if not w:
                continue
            endpoints=[]
            for label,date in [('start',prior),('end',day)]:
                row=known.get((date,sid))
                if row is None:
                    failed.append((sid,label,'MISSING_ROW')); continue
                if row.get('total_return_available_at',row['available_at']) > cutoff:
                    failed.append((sid,label,'UNAVAILABLE_TR')); continue
                try:
                    value=D(str(row.get('total_return_index')))
                    valid=value.is_finite() and value>0
                except Exception:
                    valid=False
                if not valid:
                    failed.append((sid,label,'INVALID_TR')); continue
                endpoints.append(value)
            if len(endpoints)==2:
                returns[sid]=endpoints[1]/endpoints[0]-1
        if failed:
            missing.append(dict(date=day,reasons=failed))
        else:
            complete.append(day)
            baskets.append(sum((D(str(w))*returns[sid] for sid,w in weights.items() if w),D(0)))
    if len(baskets)<45:
        raise ValueError(('INSUFFICIENT_SYNC_RETURNS',len(baskets),missing))
    with localcontext() as ctx:
        ctx.prec=40
        mean=sum(baskets)/len(baskets)
        variance=sum((x-mean)**2 for x in baskets)/(len(baskets)-1)
        sigma=(variance*252).sqrt()
        assert sigma.is_finite()
        alpha=min(D(1),D('.10')/sigma) if sigma else D(1)
    return dict(window_return_dates=window,complete_dates=complete,complete_count=len(complete),
                missing=missing,sigma=sigma,alpha=alpha,zero_variance=sigma==0)


def add_risk(source, unscaled, fixed_c=None):
    result=[]
    for entry in unscaled:
        item=dict(entry)
        item['risk']=risk(source,entry['anchor'],entry['release'],entry['weights']) if entry['weights'] else None
        item['alpha_applied']=fixed_c if fixed_c is not None else (item['risk']['alpha'] if item['risk'] else None)
        item['scaled_weights']={sid:w*item['alpha_applied'] for sid,w in entry['weights'].items()}
        result.append(item)
    return result
