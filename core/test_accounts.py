from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase,Client
from django.utils import timezone
from django.core.management import call_command
from .models import *
from . import services as svc

class AccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create_user('originalowner',password='OriginalOwnerPass42!')
        cls.ws=Workspace.objects.create(name='原客户')
        Membership.objects.create(user=cls.owner,workspace=cls.ws,role='admin')
        cls.project=Project.objects.create(workspace=cls.ws,name='原品牌')
    def signup(self,email='person@example.com',client=None,**changes):
        data={'email':email,'workspace_name':'新客户','password':'ArgusEmailTrialPass42!','confirm':'ArgusEmailTrialPass42!','consent':'on'};data.update(changes)
        return (client or self.client).post('/register/',data)
    def test_signup_creates_independent_trial_without_platform_rights(self):
        response=self.signup(' Person@Example.COM ');self.assertRedirects(response,'/onboarding/')
        identity=EmailIdentity.objects.get(email='person@example.com');user=identity.user
        self.assertFalse(identity.verified);self.assertTrue(user.check_password('ArgusEmailTrialPass42!'))
        self.assertFalse(user.is_superuser);self.assertFalse(user.is_staff)
        trial=TrialAccess.objects.get(user=user);self.assertNotEqual(trial.workspace_id,self.ws.pk)
        self.assertAlmostEqual((trial.expires_at-timezone.now()).total_seconds(),7*86400,delta=10)
        self.assertEqual(self.client.get('/platform-admin/').status_code,403)
        self.assertEqual(self.client.get(f'/first-results/{self.project.pk}/').status_code,404)
    def test_email_login_case_insensitive(self):
        self.signup();self.client.logout()
        response=self.client.post('/login/',{'username':'PERSON@EXAMPLE.COM','password':'ArgusEmailTrialPass42!'})
        self.assertEqual(response.status_code,302);self.assertIn('_auth_user_id',self.client.session)
    def test_duplicate_email_no_partial_accounts(self):
        self.signup();before=(User.objects.count(),Workspace.objects.count());self.client.logout()
        response=self.signup('PERSON@EXAMPLE.COM')
        self.assertContains(response,'此邮箱无法用于新注册');self.assertEqual(before,(User.objects.count(),Workspace.objects.count()))
    def test_requires_password_confirmation_consent_valid_email(self):
        for changes in [{'confirm':'different'},{'consent':''},{'email':'bad'},{'password':'123','confirm':'123'}]:
            self.signup(**changes)
        self.assertEqual(EmailIdentity.objects.count(),0)
    def test_register_closed(self):
        PlatformConfig.objects.create(pk=1,signup_enabled=False)
        self.assertEqual(self.signup().status_code,403);self.assertEqual(EmailIdentity.objects.count(),0)
    def test_signup_rate_limit(self):
        for n in range(6):response=self.signup(f'person{n}@example.com',confirm='wrong')
        self.assertContains(response,'注册尝试较频繁')
    def test_no_registration_before_install_claim(self):
        Membership.objects.all().delete()
        self.assertEqual(self.signup().status_code,403)
    def test_csrf_signup_and_admin_actions(self):
        strict=Client(enforce_csrf_checks=True)
        self.assertEqual(self.signup(client=strict).status_code,403)
        self.owner.is_superuser=True;self.owner.save();strict.force_login(self.owner)
        self.assertEqual(strict.post('/platform-admin/',{'trial_days':9}).status_code,403)
    def test_membership_admin_cannot_enter_platform(self):
        self.client.force_login(self.owner)
        for path in ['/platform-admin/','/platform-admin/login/']:
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post('/platform-admin/',{'signup_enabled':'on','trial_days':30}).status_code,403)
    def test_anonymous_redirected_to_platform_login(self):
        self.assertRedirects(self.client.get('/platform-admin/'),'/platform-admin/login/')
    def test_platform_login_and_config_and_audit(self):
        call_command('platform_admin',username='originalowner');self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password('OriginalOwnerPass42!'))
        response=self.client.post('/platform-admin/login/',{'username':'originalowner','password':'OriginalOwnerPass42!'})
        self.assertRedirects(response,'/platform-admin/')
        response=self.client.post('/platform-admin/',{'trial_days':12,'signup_enabled':'on'})
        self.assertEqual(response.status_code,302);self.assertEqual(PlatformConfig.objects.get(pk=1).trial_days,12)
        self.assertTrue(PlatformAudit.objects.filter(action='更新注册与试用设置').exists())
    def test_expired_workspace_blocks_other_members_too(self):
        self.signup();trial=TrialAccess.objects.get();trial.expires_at=timezone.now()-timedelta(seconds=1);trial.save()
        self.assertEqual(self.client.get('/').status_code,403)
        another=User.objects.create_user('colleague');Membership.objects.create(user=another,workspace=trial.workspace)
        self.client.force_login(another);self.assertEqual(self.client.get('/sources/').status_code,403)
        self.assertEqual(self.client.get('/contact/').status_code,200)
    def test_suspended_user_blocked_and_no_worker_execution(self):
        self.signup();trial=TrialAccess.objects.get();trial.suspended=True;trial.save()
        self.assertEqual(self.client.get('/onboarding/').status_code,403)
        project=Project.objects.create(workspace=trial.workspace,name='试用')
        source=Source.objects.create(project=project,name='feed',url='https://example.com/feed')
        job=svc.enqueue(trial.workspace,'collect','test-paused',{'source_id':source.pk})
        with patch('core.services.remote') as remote:
            svc.work_once();remote.assert_not_called()
        job.refresh_from_db();self.assertEqual(job.status,'trial_paused')
        with self.assertRaises(svc.RemoteError):svc.collect(source)
    def test_admin_extend_and_resume_jobs(self):
        self.signup();trial=TrialAccess.objects.get();trial.expires_at=timezone.now()-timedelta(days=1);trial.suspended=True;trial.save()
        job=Job.objects.create(workspace=trial.workspace,kind='report',key='paused',status='trial_paused')
        self.owner.is_superuser=True;self.owner.save();self.client.force_login(self.owner)
        self.client.post(f'/platform-admin/trials/{trial.pk}/',{'action':'extend'})
        self.client.post(f'/platform-admin/trials/{trial.pk}/',{'action':'resume'})
        trial.refresh_from_db();job.refresh_from_db();self.assertFalse(trial.suspended);self.assertGreater(trial.expires_at,timezone.now());self.assertEqual(job.status,'pending')
    def test_forged_privilege_fields_ignored(self):
        self.signup(is_superuser='true',is_staff='true',role='admin');identity=EmailIdentity.objects.get()
        self.assertFalse(identity.user.is_superuser)
    def test_preset_hide_is_platform_only(self):
        preset=SourcePreset.objects.first();self.client.force_login(self.owner)
        self.assertEqual(self.client.post(f'/platform-admin/presets/{preset.pk}/').status_code,403)
        self.owner.is_superuser=True;self.owner.save();before=preset.enabled
        self.client.post(f'/platform-admin/presets/{preset.pk}/');preset.refresh_from_db();self.assertNotEqual(preset.enabled,before)
    def test_public_pages_and_no_wechat_auth(self):
        for path in ['/register/','/privacy/','/contact/','/platform-admin/login/']:
            self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.client.get('/auth/wechat/callback/').status_code,404)
