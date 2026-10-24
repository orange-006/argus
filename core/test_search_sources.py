import json
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User
from .models import Workspace,Project,Membership,Source,SearchProviderConfig,Content,Job
from . import services as svc
from .search_sources import normalize_results,fetch_items,PROVIDERS

class SearchSourcesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ws=Workspace.objects.create(name='关键词测试')
        cls.project=Project.objects.create(workspace=cls.ws,name='测试品牌',aliases='测试产品')
        cls.user=User.objects.create_user('search-owner')
        Membership.objects.create(workspace=cls.ws,user=cls.user,role='admin')
    def setUp(self):self.client.force_login(self.user)
    def ready(self,provider='tavily',scope='web',limit=20):
        config=SearchProviderConfig.objects.create(workspace=self.ws,provider=provider,enabled=True,key_cipher=svc.encrypt('fake-test-key-123456'),daily_limit=limit)
        source=Source.objects.create(project=self.project,name='网页关键词',kind='search',url=PROVIDERS[provider][1],search_config={'provider':provider,'scope':scope})
        return config,source
    def test_all_response_shapes_and_domain_filter(self):
        fixtures={
          'tavily':{'results':[{'title':'测试品牌报道','url':'https://example.com/a','content':'报道摘要'}]},
          'anspire':{'results':[{'title':'测试品牌报道','url':'https://example.com/a','content':'报道摘要'}]},
          'bocha':{'code':200,'data':{'webPages':{'value':[{'name':'测试品牌报道','url':'https://example.com/a','summary':'报道摘要'}]}}},
        }
        for provider,data in fixtures.items():
            with self.subTest(provider=provider):
                result=normalize_results(provider,data);self.assertEqual(result[0]['text'],'报道摘要');self.assertEqual(result[0]['level'],'summary')
        scoped={'results':[{'title':'允许','url':'https://www.weibo.com/a','content':'内容'}, {'title':'伪装','url':'https://weibo.com.evil.example/a'}, {'title':'恶意','url':'javascript:alert(1)'}]}
        self.assertEqual(len(normalize_results('tavily',scoped,'weibo')),1)
        for payload in [{},[],{'error':'denied'}]:
            with self.assertRaises(svc.RemoteError):normalize_results('tavily',payload)
    def test_collection_enters_analysis_and_deduplicates(self):
        config,source=self.ready()
        raw=json.dumps({'results':[{'title':'测试品牌新闻','url':'https://example.com/a','content':'测试品牌发布新品'}]}).encode()
        with patch('core.services.remote',return_value=(200,{},raw)) as remote:
            svc.collect(source);svc.collect(source)
            self.assertNotIn('fake-test-key',remote.call_args.args[0])
            self.assertIn('Bearer fake-test-key',remote.call_args.kwargs['headers']['Authorization'])
        self.assertEqual(Content.objects.filter(source=source).count(),1)
        self.assertEqual(Job.objects.filter(kind='analyze').count(),1)
    def test_local_limit_and_disabled_service_prevent_requests(self):
        config,source=self.ready(limit=1)
        with patch('core.services.remote',return_value=(200,{},b'{"results":[]}')) as remote:
            fetch_items(source)
            with self.assertRaises(svc.RemoteError):fetch_items(source)
            remote.assert_called_once()
        config.enabled=False;config.save()
        with patch('core.services.remote') as remote:
            with self.assertRaises(svc.RemoteError):fetch_items(source)
            remote.assert_not_called()
    def test_bocha_and_anspire_request_contracts(self):
        fixtures={'bocha':{'code':200,'data':{'webPages':{'value':[]}}},'anspire':{'results':[]}}
        for provider,payload in fixtures.items():
            with self.subTest(provider=provider):
                config,source=self.ready(provider)
                with patch('core.services.remote',return_value=(200,{},json.dumps(payload).encode())) as remote:
                    self.assertEqual(fetch_items(source),[])
                    url=remote.call_args.args[0]
                    self.assertNotIn('fake-test-key',url)
                    self.assertTrue(url.startswith(PROVIDERS[provider][1]))
                    if provider=='bocha':self.assertEqual(remote.call_args.args[1],'POST')
                    else:self.assertIn('query=',url)
    def test_disabling_provider_pauses_its_sources(self):
        config,source=self.ready()
        data={'provider':'tavily','scope':'web','daily_limit':20,'interval_minutes':60}
        self.assertEqual(self.client.post('/search-sources/',data).status_code,302)
        source.refresh_from_db();config.refresh_from_db()
        self.assertFalse(source.enabled);self.assertFalse(config.enabled)
    def test_configuration_encrypts_key_and_updates_source(self):
        data={'project':self.project.pk,'provider':'tavily','scope':'weibo','query':'','api_key':'fake-test-key-123456','daily_limit':5,'interval_minutes':60,'enabled':'on'}
        self.assertEqual(self.client.post('/search-sources/',data).status_code,302)
        data['api_key']='';data['daily_limit']=8
        self.assertEqual(self.client.post('/search-sources/',data).status_code,302)
        config=SearchProviderConfig.objects.get(workspace=self.ws)
        self.assertNotIn('fake-test-key',config.key_cipher);self.assertEqual(config.daily_limit,8)
        self.assertEqual(Source.objects.filter(kind='search').count(),1)
        self.assertEqual(Job.objects.filter(kind='collect').count(),1)
        self.assertNotContains(self.client.get('/search-sources/'),'fake-test-key')
    def test_permissions_keys_and_workspace_isolation(self):
        data={'project':self.project.pk,'provider':'tavily','scope':'web','daily_limit':20,'interval_minutes':60,'enabled':'on'}
        self.assertContains(self.client.post('/search-sources/',data),'有效 API Key')
        other=Workspace.objects.create(name='其他');project=Project.objects.create(workspace=other,name='私有')
        data.update(project=project.pk,api_key='fake-test-key-123456')
        self.assertEqual(self.client.post('/search-sources/',data).status_code,200)
        self.assertFalse(SearchProviderConfig.objects.exists())
        member=Membership.objects.get(user=self.user);member.role='viewer';member.save()
        self.assertEqual(self.client.get('/search-sources/').status_code,403)
