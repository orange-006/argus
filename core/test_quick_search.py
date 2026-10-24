import json
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User
from .models import Workspace,Project,Source,Content,Membership,KeywordRun,SearchProviderConfig,Delivery
from .services import work_once,encrypt
from .quick_search import execute

class QuickSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ws=Workspace.objects.create(name='一次性检索')
        cls.user=User.objects.create_user('quick-owner')
        Membership.objects.create(workspace=cls.ws,user=cls.user)
        cls.project=Project.objects.create(workspace=cls.ws,name='原有监测项目')
        cls.source=Source.objects.create(project=cls.project,name='原有订阅')
    def setUp(self):self.client.force_login(self.user)
    def test_local_search_matches_keyword_without_network_or_project_changes(self):
        Content.objects.create(source=self.source,title='目标品牌新品',text='产品介绍',external_id='a',digest='a')
        other=Workspace.objects.create(name='其他客户');project=Project.objects.create(workspace=other,name='私密');source=Source.objects.create(project=project,name='私密来源')
        Content.objects.create(source=source,title='目标品牌私密信息',external_id='b',digest='b')
        response=self.client.post('/quick-search/',{'keyword':'目标品牌','mode':'local','scope':'web'})
        self.assertEqual(response.status_code,302)
        with patch('core.services.remote') as remote:work_once();remote.assert_not_called()
        run=KeywordRun.objects.get(workspace=self.ws);self.assertEqual(run.status,'succeeded');self.assertEqual(len(run.results),1)
        self.assertEqual(Project.objects.filter(workspace=self.ws).count(),1);self.assertFalse(Delivery.objects.exists())
        self.assertEqual(self.client.get(f'/quick-search/{run.pk}/status/').json()['count'],1)
    def test_live_requires_configured_provider(self):
        response=self.client.post('/quick-search/',{'keyword':'目标品牌','mode':'live','scope':'web'})
        self.assertEqual(response.status_code,200);self.assertFalse(KeywordRun.objects.exists())
    def test_live_search_uses_keyword_and_shared_quota_without_creating_sources(self):
        config=SearchProviderConfig.objects.create(workspace=self.ws,provider='tavily',enabled=True,key_cipher=encrypt('test-key-123456'))
        self.client.post('/quick-search/',{'keyword':'指定品牌','mode':'live','provider':'tavily','scope':'web'})
        raw=json.dumps({'results':[{'title':'指定品牌报道','url':'https://example.com/a','content':'摘要'}]}).encode()
        with patch('core.services.remote',return_value=(200,{},raw)) as remote:
            work_once();self.assertIn('指定品牌',remote.call_args.kwargs['payload']['query'])
        config.refresh_from_db();self.assertEqual(config.daily_used,1)
        self.assertEqual(Source.objects.filter(project__workspace=self.ws).count(),1)
        self.assertEqual(KeywordRun.objects.get().status,'succeeded')
    def test_cooldown_and_workspace_permissions(self):
        data={'keyword':'目标品牌','mode':'local','scope':'web'}
        self.client.post('/quick-search/',data);self.client.post('/quick-search/',data)
        self.assertEqual(KeywordRun.objects.count(),1)
        other=Workspace.objects.create(name='其他');run=KeywordRun.objects.create(workspace=other,keyword='私密')
        self.assertEqual(self.client.get(f'/quick-search/{run.pk}/status/').status_code,404)
        member=Membership.objects.get(user=self.user);member.role='viewer';member.save()
        self.assertEqual(self.client.post('/quick-search/',data).status_code,403)
    def test_interrupted_live_search_is_not_automatically_repeated(self):
        run=KeywordRun.objects.create(workspace=self.ws,keyword='品牌',mode='live',status='running')
        with patch('core.quick_search.fetch_items') as fetch:execute(run);fetch.assert_not_called()
        run.refresh_from_db();self.assertEqual(run.status,'failed')
