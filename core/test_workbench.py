from datetime import timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from .models import Workspace,Membership,Project,Source,Content,Event,EventItem,NotificationConfig,Job,Delivery,AuditLog

class WorkbenchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=User.objects.create_user('workbench-admin')
        cls.ws=Workspace.objects.create(name='工作台测试')
        Membership.objects.create(user=cls.user,workspace=cls.ws)
        cls.project=Project.objects.create(workspace=cls.ws,name='监测品牌')
        cls.source=Source.objects.create(project=cls.project,name='公开资讯',kind='rss')
        NotificationConfig.objects.create(workspace=cls.ws)
    def setUp(self):self.client.force_login(self.user)
    def content(self,source=None,external_id='one'):
        return Content.objects.create(source=source or self.source,external_id=external_id,title='监测内容',digest=external_id,relevant=True,fetched_at=timezone.now()-timedelta(days=40))
    def preview(self):return self.client.get('/history/clear/?days=all').context['token']
    def test_cleanup_is_explicit_and_scoped_preserving_configuration(self):
        content=self.content();event=Event.objects.create(project=self.project,key='one',title='事件');EventItem.objects.create(event=event,content=content)
        other=Workspace.objects.create(name='其他客户');project=Project.objects.create(workspace=other,name='秘密');source=Source.objects.create(project=project,name='私有来源')
        secret=self.content(source,'other')
        token=self.preview();self.assertTrue(Content.objects.filter(pk=content.pk).exists())
        self.client.post('/history/clear/',{'token':token,'confirmation':'错误'})
        self.assertTrue(Content.objects.filter(pk=content.pk).exists())
        self.client.post('/history/clear/',{'token':token,'confirmation':'清除历史记录'})
        self.assertFalse(Content.objects.filter(pk=content.pk).exists());self.assertFalse(Event.objects.filter(pk=event.pk).exists())
        self.assertTrue(Content.objects.filter(pk=secret.pk).exists());self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())
        self.assertTrue(Source.objects.filter(pk=self.source.pk).exists());self.assertTrue(NotificationConfig.objects.filter(workspace=self.ws).exists())
        self.assertTrue(AuditLog.objects.filter(workspace=self.ws,action='清除监测历史').exists())
    def test_running_tasks_and_pending_notifications_protect_records(self):
        content=self.content();token=self.preview()
        job=Job.objects.create(workspace=self.ws,kind='collect',key='busy',status='running')
        self.client.post('/history/clear/',{'token':token,'confirmation':'清除历史记录'})
        self.assertTrue(Content.objects.filter(pk=content.pk).exists());job.delete()
        event=Event.objects.create(project=self.project,key='protected',title='待发送事件');EventItem.objects.create(event=event,content=content)
        Delivery.objects.create(workspace=self.ws,event=event,key='pending',target_name='群',body='提醒',status='待发送')
        self.client.post('/history/clear/',{'token':self.preview(),'confirmation':'清除历史记录'})
        self.assertTrue(Content.objects.filter(pk=content.pk).exists())
    def test_cleanup_permission_and_token_required(self):
        content=self.content()
        self.client.post('/history/clear/',{'token':'invalid','confirmation':'清除历史记录'})
        self.assertTrue(Content.objects.filter(pk=content.pk).exists())
        membership=Membership.objects.get(user=self.user);membership.role='viewer';membership.save()
        self.assertEqual(self.client.get('/history/clear/').status_code,403)
    def test_screen_scopes_and_zero_states(self):
        self.assertEqual(self.client.get('/screen/').status_code,200)
        self.assertEqual(self.client.get('/screen/status/').json()['metrics']['related'],0)
        c=self.content();c.fetched_at=timezone.now();c.save()
        self.assertEqual(self.client.get('/screen/status/').json()['metrics']['related'],1)
        other=Workspace.objects.create(name='另一个');project=Project.objects.create(workspace=other,name='不可见')
        self.assertEqual(self.client.get('/screen/status/?project='+str(project.pk)).status_code,404)
