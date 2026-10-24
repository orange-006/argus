import os,json,concurrent.futures
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','argus.settings')
import django;django.setup()
from core.services import remote
from core.streams import parse_feed,newsnow_items
from core.catalog import PRESETS
selected=[p for p in PRESETS if p.get('kind','rss')=='rss' or p['key'] in ['newsnow-weibo','newsnow-douyin','newsnow-wallstreetcn-hot']]
def probe(p):
    try:
        code,_,raw=remote(p['url'],headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'} if p.get('kind')=='newsnow' else None)
        if code!=200:raise ValueError('HTTP '+str(code))
        items=newsnow_items(raw) if p.get('kind')=='newsnow' else parse_feed(raw,p['url'])
        return {'source':p['name'],'count':len(items),'body':sum(i['level']=='fulltext' for i in items),'summary':sum(i['level']=='summary' for i in items),'title':sum(i['level']=='title' for i in items),'ranked':sum(bool(i.get('rank')) for i in items),'max_text':max((len(i['text']) for i in items),default=0)}
    except Exception as e:return {'source':p['name'],'error':str(e)[:160]}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:result=list(pool.map(probe,selected))
Path('test-results').mkdir(exist_ok=True);Path('test-results/stream-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
