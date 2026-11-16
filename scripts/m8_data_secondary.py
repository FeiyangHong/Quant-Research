"""Full-date raw OHLC corroboration after a recorded Eastmoney source failure."""
from decimal import Decimal
import json
from pathlib import Path
from urllib.parse import urlencode
from m8_data_holdings import selection
from m8_data_collect import ROOT, OUT, REPORT, issue, save, sha

def main():
    result=[]
    for sid in selection()['selected_instruments']:
        rows={};captures=[]
        for start,end in [('2019-01-01','2020-12-31'),('2021-01-01','2022-12-31'),('2023-01-01','2024-12-31')]:
            key=sid.replace('.','');url='https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?'+urlencode(dict(param=key+',day,'+start+','+end+',640,'))
            cap=issue('tencent_'+sid+'_'+start,url,dates=start+'~'+end,route='selected_raw_price_crosscheck')
            captures.append(cap)
            if cap['status']!='FETCHED':continue
            # Current quotes/name fields in the same immutable body are quarantined,
            # not inspected, emitted, normalized, admitted, or used as signals.
            data=json.loads(Path(cap['raw_path']).read_bytes())
            if data.get('code')!=0:raise ValueError('Historical crosscheck error')
            for raw in data.get('data',{}).get(key,{}).get('day',[]):
                if not start<=raw[0]<=end or raw[0] in rows:raise ValueError('Crosscheck bounds/duplicate violation')
                row=dict(zip(['date','open','close','high','low','volume_vendor_units'],raw[:6]))
                for field in ['open','close','high','low']:
                    value=Decimal(row[field])
                    if not value.is_finite() or value<=0:raise ValueError('Invalid raw price')
                rows[row['date']]=row
        normalized=OUT/'decoded'/('tencent_'+sid+'.json');save(normalized,sorted(rows.values(),key=lambda r:r['date']))
        primary_path=OUT/'decoded'/('holding_'+sid+'.json');data=json.loads(primary_path.read_bytes())
        primary={r[0]:dict(zip(data['fields'],r)) for r in data['rows']}
        mismatches=[];comparisons=0
        for day in sorted(set(primary)&set(rows)):
            for field in ['open','close','high','low']:
                comparisons+=1;a,b=Decimal(primary[day][field]),Decimal(rows[day][field])
                if abs(a-b)>Decimal('0.00005'):mismatches.append(dict(date=day,field=field,primary=str(a),secondary=str(b)))
        missing=[d for d in primary if d not in rows and primary[d]['tradestatus']=='1' and Decimal(primary[d]['volume'])>0]
        result.append(dict(instrument_id=sid,status='MATCHED_FULL_RAW_OHLC' if not missing and not mismatches and comparisons else 'REQUIRES_REVIEW',
            comparisons=comparisons,mismatches=mismatches,missing_traded_dates=missing,
            primary_path=str(primary_path),primary_sha256=sha(primary_path),secondary_path=str(normalized),secondary_sha256=sha(normalized),
            captures=captures,price_tolerance_CNY='0.00005',volume_secondary_unit_status='NOT_USED_WITHOUT_SOURCE_UNIT_EVIDENCE',amount_secondary_status='NOT_PROVIDED',
            quarantined_fields_policy='Unsolicited quote fields archived for byte integrity; not inspected or admitted; only requested pre2025 day arrays used'))
        save(REPORT/'PRICE_RECONCILIATION.json',dict(scope='FULL_SELECTED_2019_2024_RAW_OHLC',records=result))
        print(sid,result[-1]['status'],comparisons,'missing',len(missing),'mismatch',len(mismatches),flush=True)

if __name__=='__main__':main()
