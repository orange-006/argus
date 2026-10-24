"""Dedicated isolated QA database only. Never writes production records."""
import os,json
from pathlib import Path
assert os.environ.get('ARGUS_DATA_DIR','').endswith('argus-stream-e2e')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','argus.settings')
import django;django.setup()
from django.core.management import call_command
call_command('migrate',verbosity=0)
from core.models import *
from core import services as svc
from core.streams import parse_feed,newsnow_items
from core.catalog import seed_catalog
seed_catalog();user,_=User.objects.get_or_create(username='stream-e2e-owner');user.set_password('IsolatedStreamOwner42!');user.is_superuser=True;user.save()
ws,_=Workspace.objects.get_or_create(name='信息流验收');Membership.objects.get_or_create(user=user,workspace=ws)
NotificationConfig.objects.get_or_create(workspace=ws);AIConfig.objects.get_or_create(workspace=ws)
project,_=Project.objects.get_or_create(workspace=ws,name='科技')
source,_=Source.objects.get_or_create(project=project,name='阮一峰 · 真实订阅正文',defaults={'url':'https://www.ruanyifeng.com/blog/atom.xml'})
svc.collect(source,force=True)
hot,_=Source.objects.get_or_create(project=project,name='微博 · 真实榜单',defaults={'kind':'newsnow','url':'https://newsnow.busiyi.world/api/s?id=weibo'})
svc.collect(hot,force=True)
for content in Content.objects.filter(source__project=project):svc.analyze(content)
# These two follow-up snapshots are explicitly labeled QA samples, not real rank movement.
sample,_=Source.objects.get_or_create(project=project,name='验收样例 · 排名变化',defaults={'kind':'newsnow','enabled':False})
for i,items in enumerate([[{'id':'brand','title':'科技资讯 · 排名验收样例','url':'https://example.com/qa'},{'id':'other','title':'其他样例','url':'https://example.com/other'}],[{'id':'other','title':'其他样例','url':'https://example.com/other'},{'id':'brand','title':'科技资讯 · 排名验收样例','url':'https://example.com/qa'}]]):
    svc.ingest(sample,newsnow_items(json.dumps({'status':'success','updatedTime':1792200000000+i*1000,'items':items}).encode()),is_demo=True)
body=Content.objects.filter(source=source,text_origin='rss_content').first();ranked=Content.objects.get(source=sample,title='科技资讯 · 排名验收样例')
assert body and len(body.text)>1000 and ranked.observations.count()==2
Path(os.environ['ARGUS_DATA_DIR']).joinpath('qa-content.json').write_text(json.dumps({'body':body.pk,'ranked':ranked.pk}),encoding='utf-8')
print(json.dumps({'feed_bodies':Content.objects.filter(source=source,text_origin='rss_content').count(),'live_hotlist':Content.objects.filter(source=hot).count(),'fixture_ranks':list(ranked.observations.values_list('rank',flat=True))}))
