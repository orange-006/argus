"""Read-only release connection checks; no customer database writes."""
import os,json,concurrent.futures
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','argus.settings')
import django
django.setup()
from core.catalog import PRESETS
from core.services import remote,parse_newsnow
import feedparser
def check(item):
    try:
        status,_,data=remote(item['url'],headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'} if item.get('kind')=='newsnow' else None)
        if status!=200:raise ValueError('HTTP '+str(status))
        if item.get('kind')=='newsnow':entries=parse_newsnow(data)
        else:
            feed=feedparser.parse(data)
            if not feed.version:raise ValueError('非 RSS/Atom')
            entries=feed.entries
        return item['key'],{'status':'连接检查通过' if entries else '连接成功 · 当前无条目','count':len(entries)}
    except Exception as exc:return item['key'],{'status':'当前检查失败','error':str(exc)[:180]}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results=dict(pool.map(check,PRESETS))
Path(__file__).with_name('core').joinpath('source_checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'total':len(results),'passed':sum('error' not in v for v in results.values()),'failed':[k for k,v in results.items() if 'error' in v]},ensure_ascii=False))
