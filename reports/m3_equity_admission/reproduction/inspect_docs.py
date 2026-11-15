import json,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from quant_research.providers.equity_audit import fetch_http
from quant_research.providers.baostock import write_immutable
out=ROOT/'data/raw_equity_admission'
extra=[]
for label,url in {
'maotai_dividend_20230626':'https://www.moutaichina.com/maotaigf/fileDir/resource/cms/article/408428/561111/2023062617072666236.pdf',
'leshi_distribution_20150506':'https://static.cninfo.com.cn/finalpage/2015-05-06/1200968345.PDF',
}.items():
    extra.append(fetch_http(out,label,url))
write_immutable(out/'http_extra_manifest.json',extra)
records=json.loads((out/'http_probe_manifest.json').read_bytes())+extra
textroot=ROOT/'work/equity_data_audit/text'
textroot.mkdir(parents=True,exist_ok=True)
for record in records:
    if record.get('content_type','').startswith('application/pdf'):
        subprocess.run(['pdftotext','-layout',record['raw_path'],str(textroot/(record['id']+'.txt'))],check=True)
print(json.dumps([{'id':r['id'],'status':r['status']} for r in extra]))
