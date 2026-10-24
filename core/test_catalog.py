import json
from unittest.mock import patch
from django.test import TestCase
from core.catalog import PRESETS,seed_catalog,registry
from core.models import Workspace,Project,SourcePreset,Source,Job
from core.onboarding import attach_presets,result_summary
from core.services import parse_newsnow,RemoteError,collect

class ExpandedCatalogTests(TestCase):
    def test_canonical_registry_complete(self):
        actual={p['key'][8:] for p in PRESETS if p.get('kind')=='newsnow'}
        self.assertEqual(actual,{k for k,v in registry.items() if not v.get('redirect')})
        self.assertEqual(len({p['key'] for p in PRESETS}),len(PRESETS))
    def test_parser_validates_and_keeps_title_only(self):
        items=parse_newsnow(json.dumps({'status':'cache','items':[{'id':1,'title':'测试','url':'https://example.com/a','extra':{'text':'untrusted'}},{'title':'bad','url':'javascript:alert(1)'}]}).encode())
        self.assertEqual(len(items),1);self.assertEqual(items[0]['text'],'');self.assertEqual(items[0]['level'],'title')
        for payload in [{'status':'error','items':[]},[],{'status':'cache','items':{}}]:
            with self.assertRaises(RemoteError):parse_newsnow(json.dumps(payload).encode())
    def test_attach_dispatch_dedup_and_status(self):
        seed_catalog();ws=Workspace.objects.create(name='catalog');project=Project.objects.create(workspace=ws,name='测试')
        preset=SourcePreset.objects.get(key='newsnow-weibo')
        self.assertEqual(attach_presets(project,[preset]),1);self.assertEqual(attach_presets(project,[preset]),0)
        source=Source.objects.get(project=project);self.assertEqual(source.kind,'newsnow')
        self.assertEqual(result_summary(project)['stage'],'collecting')
        payload=json.dumps({'status':'cache','items':[{'title':'测试新闻','url':'https://example.com/a','id':'a'}]}).encode()
        with patch('core.services.remote',return_value=(200,{},payload)):
            collect(source);collect(source)
        self.assertEqual(source.contents.count(),1) if hasattr(source,'contents') else self.assertEqual(source.content_set.count(),1)
        self.assertEqual(Job.objects.filter(kind='analyze').count(),1)
