import secrets,uuid,json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase,Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.management import call_command
from .models import *
from .services import digest,analyze,ingest,schedule,send_delivery,make_delivery,load_demo,collect
from .catalog import seed_catalog
from .onboarding import attach_presets,result_summary

class OnboardingTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('owner',password='ArgusTestPassword22!')
        self.ws=Workspace.objects.create(name='真实空间');Membership.objects.create(workspace=self.ws,user=self.user)
        self.client.force_login(self.user);seed_catalog()
    def setup_data(self,**overrides):
        self.client.get('/onboarding/');token=self.client.session['onboarding_token']
        data={'name':'非技术用户品牌','purpose':'brand','industry':'consumer','aliases':'小品牌','excludes':'同名社区','presets':[SourcePreset.objects.get(key='chinanews').pk],'token':token};data.update(overrides);return data
    def create_project(self,**overrides):
        data=self.setup_data(**overrides);response=self.client.post('/onboarding/',data);self.assertEqual(response.status_code,302);return Project.objects.get(workspace=self.ws)

    def test_new_pages_render(self):
        for url in ['/onboarding/','/source-library/']:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,200)
    def test_home_has_single_clear_start(self):
        response=self.client.get('/');self.assertContains(response,'开始我的监测');self.assertContains(response,'先体验一分钟')
    def test_login_empty_space_enters_wizard(self):
        self.client.logout();response=self.client.post('/login/',{'username':'owner','password':'ArgusTestPassword22!'});self.assertRedirects(response,'/onboarding/')
    def test_onboarding_creates_defaults_and_collect_jobs(self):
        project=self.create_project();self.assertEqual(project.purpose,'brand');self.assertEqual(project.industry,'consumer')
        self.assertEqual(Source.objects.filter(project=project).count(),1);self.assertEqual(Job.objects.filter(kind='collect').count(),1)
        self.ws.refresh_from_db();self.assertTrue(self.ws.onboarding_complete);self.assertFalse(NotificationConfig.objects.filter(workspace=self.ws,enabled=True).exists())
    def test_duplicate_submit_is_idempotent(self):
        data=self.setup_data();self.client.post('/onboarding/',data);self.client.post('/onboarding/',data)
        self.assertEqual(Project.objects.filter(workspace=self.ws).count(),1);self.assertEqual(Source.objects.count(),1);self.assertEqual(Job.objects.count(),1)
    def test_next_wizard_creates_new_project_token(self):
        self.create_project();old=self.client.session['onboarding_token'];response=self.client.get('/onboarding/');self.assertEqual(response.status_code,200);self.assertNotEqual(old,self.client.session['onboarding_token'])
    def test_missing_sources_requires_explicit_upload(self):
        data=self.setup_data(presets=[]);self.assertContains(self.client.post('/onboarding/',data),'至少选择一个信息来源');self.assertFalse(Project.objects.exists())
        data['use_upload']='on';self.client.post('/onboarding/',data);project=Project.objects.get();self.assertEqual(result_summary(project)['stage'],'import_required')
    def test_tampered_setup_token_rejected(self):
        response=self.client.post('/onboarding/',self.setup_data(token='bad'));self.assertEqual(response.status_code,403);self.assertFalse(Project.objects.exists())
    def test_disabled_source_cannot_be_selected(self):
        preset=SourcePreset.objects.get(key='chinanews');preset.enabled=False;preset.save()
        response=self.client.post('/onboarding/',self.setup_data());self.assertEqual(response.status_code,200);self.assertFalse(Project.objects.exists())
    def test_source_library_attach_idempotent(self):
        project=Project.objects.create(workspace=self.ws,name='品牌');presets=list(SourcePreset.objects.filter(key='chinanews'))
        self.assertEqual(attach_presets(project,presets),1);self.assertEqual(attach_presets(project,presets),0);self.assertEqual(Source.objects.count(),1)
    def test_source_library_does_not_overwrite_operator_changes(self):
        preset=SourcePreset.objects.get(key='chinanews');preset.name='运营自定义';preset.enabled=False;preset.save();seed_catalog();preset.refresh_from_db();self.assertEqual(preset.name,'运营自定义');self.assertFalse(preset.enabled)
    def test_summary_collecting_and_failed(self):
        project=self.create_project();self.assertEqual(result_summary(project)['stage'],'collecting')
        Source.objects.filter(project=project).update(last_attempt=timezone.now(),status='采集失败');summary=result_summary(project)
        self.assertEqual(summary['stage'],'failed');self.assertEqual(summary['matches'],0);self.assertIn('不代表没有舆情',summary['detail'])
    def test_summary_analyzing_then_no_match(self):
        project=self.create_project();source=Source.objects.get(project=project);source.last_attempt=timezone.now();source.last_success=timezone.now();source.status='正常';source.save()
        ingest(source,[{'title':'与品牌无关的真实行业报道'}]);self.assertEqual(result_summary(project)['stage'],'analyzing')
        content=Content.objects.get();analyze(content);Job.objects.filter(kind='analyze').update(status='succeeded');summary=result_summary(project)
        self.assertEqual(summary['stage'],'no_matches');self.assertEqual(summary['total'],1);self.assertEqual(summary['matches'],0)
    def test_first_report_scheduled_once_after_successful_analysis(self):
        project=self.create_project();source=Source.objects.get(project=project);source.last_attempt=timezone.now();source.last_success=timezone.now();source.status='成功 · 无新增';source.save()
        schedule();schedule();self.assertEqual(Job.objects.filter(key=f'first-report:{project.pk}').count(),1)
    def test_first_report_not_scheduled_before_source_success(self):
        project=self.create_project();schedule();self.assertFalse(Job.objects.filter(kind='report').exists())
    def test_progress_response_scoped_to_workspace(self):
        project=self.create_project();self.assertEqual(self.client.get(f'/first-results/{project.pk}/status/').status_code,200)
        other=Workspace.objects.create(name='别的客户');other_project=Project.objects.create(workspace=other,name='私密')
        self.assertEqual(self.client.get(f'/first-results/{other_project.pk}/status/').status_code,404)
    def test_demo_is_separate_and_exit_restores(self):
        self.client.post('/experience/enter/');demo=Workspace.objects.get(demo_owner=self.user)
        self.assertTrue(demo.is_demo);self.assertEqual(Content.objects.filter(source__project__workspace=self.ws).count(),0);self.assertEqual(Content.objects.filter(source__project__workspace=demo).count(),5)
        self.assertContains(self.client.get('/'),'你正在独立体验空间');self.client.post('/experience/exit/');self.assertContains(self.client.get('/'),'真实空间');self.assertNotContains(self.client.get('/contents/'),'青禾饮品瓶盖')
    def test_demo_reentry_does_not_duplicate(self):
        self.client.post('/experience/enter/');self.client.post('/experience/enter/');self.assertEqual(Content.objects.filter(is_demo=True).count(),5)
    def test_demo_cannot_send_or_attach_source(self):
        self.client.post('/experience/enter/');demo=Workspace.objects.get(demo_owner=self.user)
        with patch('core.services.wework_post') as send:
            self.assertEqual(self.client.post('/notifications/0/action/',{'action':'test'}).status_code,403)
            self.assertEqual(self.client.post('/sources/',{}).status_code,403)
            project=Project.objects.get(workspace=demo);self.assertEqual(self.client.post('/source-library/',{'project':project.pk,'presets':[SourcePreset.objects.first().pk]}).status_code,403)
            event=Event.objects.filter(project=project,risk='需要关注').first();self.assertIsNone(make_delivery(event));send.assert_not_called()
    def test_demo_worker_cannot_send_even_with_configuration(self):
        self.client.post('/experience/enter/');demo=Workspace.objects.get(demo_owner=self.user);delivery=Delivery.objects.create(workspace=demo,key='unsafe',target_name='test',body='sample')
        with patch('core.services.wework_post') as send:send_delivery(delivery);send.assert_not_called()
        delivery.refresh_from_db();self.assertEqual(delivery.status,'体验空间不发送')
    def test_demo_cannot_consume_ai(self):
        self.client.post('/experience/enter/');demo=Workspace.objects.get(demo_owner=self.user);AIConfig.objects.filter(workspace=demo).update(enabled=True)
        content=Content.objects.filter(source__project__workspace=demo).first()
        with patch('core.services.model_analysis') as model:analyze(content);model.assert_not_called()
    def test_demo_ownership_cannot_be_forged(self):
        owner=User.objects.create_user('otherowner');other_demo=Workspace.objects.create(name='另一个体验空间',is_demo=True,demo_owner=owner);Project.objects.create(workspace=other_demo,name='不能看到的项目')
        session=self.client.session;session['experience_workspace']=other_demo.pk;session.save();self.assertNotContains(self.client.get('/projects/'),'不能看到的项目')
    def test_real_workspace_cannot_load_samples(self):
        with self.assertRaises(ValueError):load_demo(self.ws)
    def test_read_only_role_cannot_complete_wizard(self):
        Membership.objects.filter(user=self.user).update(role='viewer');self.assertEqual(self.client.get('/onboarding/').status_code,403);self.assertEqual(self.client.post('/source-library/',{}).status_code,403)
    def test_welcome_does_not_reset_existing_accounts(self):
        self.client.logout();response=self.client.get('/welcome/?token=anything');self.assertRedirects(response,'/login/');self.assertEqual(User.objects.count(),1)
    def test_setup_requires_token_and_localhost(self):
        Membership.objects.all().delete();self.client.logout();token=secrets.token_urlsafe(32);Installation.objects.create(pk=1,token_digest=digest(token))
        self.assertContains(self.client.get('/welcome/'),'请在运行 Argus 的电脑上')
        data={'username':'newowner','workspace_name':'新团队','password':'FreshArgusPass22!','confirm':'FreshArgusPass22!'}
        self.client.post('/welcome/',data);self.assertFalse(Membership.objects.exists())
        self.assertEqual(self.client.get('/welcome/?token='+token,REMOTE_ADDR='8.8.8.8').status_code,403)
        self.assertRedirects(self.client.get('/welcome/?token='+token),'/welcome/')
        response=self.client.post('/welcome/',data);self.assertRedirects(response,'/onboarding/');self.assertTrue(User.objects.get(username='newowner').check_password('FreshArgusPass22!'));self.assertFalse(NotificationConfig.objects.get().enabled)
    def test_setup_rejects_expired_token(self):
        Membership.objects.all().delete();self.client.logout();token='expired';Installation.objects.create(pk=1,token_digest=digest(token),created_at=timezone.now()-timedelta(days=2))
        self.client.get('/welcome/?token='+token);self.assertContains(self.client.get('/welcome/'),'请在运行 Argus 的电脑上')

    def test_upgrade_moves_only_sample_only_project(self):
        import importlib
        from django.apps import apps
        sample=Project.objects.create(workspace=self.ws,name='旧版样例项目');source=Source.objects.create(project=sample,name='旧样例',kind='demo',enabled=False)
        Content.objects.create(source=source,external_id='legacy',title='演示',digest='legacy',is_demo=True)
        real=Project.objects.create(workspace=self.ws,name='客户真实项目');Source.objects.create(project=real,name='客户上传',kind='import')
        importlib.import_module('core.migrations.0004_seed_catalog_and_isolate_legacy_demo').forward(apps,None)
        sample.refresh_from_db();real.refresh_from_db();self.assertTrue(sample.workspace.is_demo);self.assertEqual(real.workspace_id,self.ws.pk)

    def test_upgrade_preserves_mixed_real_and_demo_project(self):
        import importlib
        from django.apps import apps
        mixed=Project.objects.create(workspace=self.ws,name='混合项目');source=Source.objects.create(project=mixed,name='旧样例',kind='demo',enabled=False);Source.objects.create(project=mixed,name='客户上传',kind='import')
        Content.objects.create(source=source,external_id='legacy',title='演示',digest='legacy',is_demo=True)
        importlib.import_module('core.migrations.0004_seed_catalog_and_isolate_legacy_demo').forward(apps,None)
        mixed.refresh_from_db();self.assertEqual(mixed.workspace_id,self.ws.pk)

    def test_viewer_can_experience_without_gaining_real_write_permission(self):
        Membership.objects.filter(user=self.user).update(role='viewer');self.client.post('/experience/enter/');self.assertEqual(self.client.get('/events/').status_code,200)
        self.client.post('/experience/exit/');self.assertEqual(self.client.post('/projects/new/',{'name':'unauthorized'}).status_code,403)
