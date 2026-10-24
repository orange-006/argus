import io,json,tempfile,socket,zipfile,sqlite3
from pathlib import Path
from datetime import datetime,timedelta,time,timezone as tz
from unittest.mock import patch,Mock
from django.test import TestCase,Client,override_settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone
from .models import *
from . import services as s
from .views import csv_safe

class ArgusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=User.objects.create_user('owner',password='SafeArgusPassword12!')
        cls.ws=Workspace.objects.create(name='测试空间')
        Membership.objects.create(user=cls.user,workspace=cls.ws)
        cls.project=Project.objects.create(workspace=cls.ws,name='青禾饮品',aliases='青禾茶',excludes='青禾社区')
        cls.source=Source.objects.create(project=cls.project,name='上传文件',kind='import',enabled=False)
        cls.config=NotificationConfig.objects.create(workspace=cls.ws,quiet=False)
    def setUp(self):self.client.force_login(self.user)
    def content(self,**kwargs):
        data={'title':'青禾饮品瓶盖漏液','text':'青禾饮品包装漏液，需要售后核实。','external_id':'one'};data.update(kwargs)
        s.ingest(self.source,[data]);return Content.objects.filter(source=self.source).latest('pk')
    def event(self):
        c=self.content();s.analyze(c);return Event.objects.get(items__content=c)
    def config_ready(self):
        self.config.enabled=True;self.config.verified=True;self.config.webhook_cipher=s.encrypt('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefgh-12345678');self.config.save();return self.config

    def test_anonymous_redirects(self):
        self.client.logout()
        for path in ['/','/contents/','/notifications/','/reports/']:
            self.assertEqual(self.client.get(path).status_code,302)

    def test_monitor_now_queues_only_enabled_sources_and_deduplicates(self):
        source=Source.objects.create(project=self.project,name='公开订阅',kind='rss',url='https://example.com/feed')
        Source.objects.create(project=self.project,name='已暂停',kind='rss',enabled=False)
        other=Workspace.objects.create(name='其他空间');project=Project.objects.create(workspace=other,name='其他项目')
        Source.objects.create(project=project,name='其他客户来源',kind='rss')
        self.assertEqual(self.client.post('/monitor/now/').status_code,302)
        self.assertEqual(self.client.post('/monitor/now/').status_code,302)
        jobs=Job.objects.filter(kind='collect');self.assertEqual(jobs.count(),1)
        self.assertEqual(jobs.get().payload,{'source_id':source.pk,'force':True})
        self.assertEqual(self.client.get('/monitor/status/').json()['queued'],1)

    def test_monitor_now_requires_post_and_write_permission(self):
        self.assertEqual(self.client.get('/monitor/now/').status_code,405)
        member=Membership.objects.get(user=self.user);member.role='viewer';member.save()
        self.assertEqual(self.client.post('/monitor/now/').status_code,403)
        self.assertFalse(Job.objects.filter(kind='collect').exists())

    def test_monitor_now_cooldown_survives_refresh_and_expires(self):
        Source.objects.create(project=self.project,name='公开来源',kind='rss',url='https://example.com/feed')
        self.client.post('/monitor/now/')
        first=Workspace.objects.get(pk=self.ws.pk).monitor_requested_at
        self.assertIsNotNone(first)
        self.assertGreater(self.client.get('/monitor/status/').json()['cooldown_seconds'],0)
        self.assertContains(self.client.get('/'),'data-cooldown-seconds=')
        self.client.post('/monitor/now/')
        self.assertEqual(AuditLog.objects.filter(action='立即检索').count(),1)
        Workspace.objects.filter(pk=self.ws.pk).update(monitor_requested_at=timezone.now()-timedelta(seconds=61))
        self.client.post('/monitor/now/')
        self.assertEqual(AuditLog.objects.filter(action='立即检索').count(),2)

    def test_monitor_now_does_not_start_demo_or_disabled_projects(self):
        self.project.active=False;self.project.save()
        Source.objects.create(project=self.project,name='停用项目来源',kind='rss')
        self.client.post('/monitor/now/');self.assertFalse(Job.objects.exists())
        self.ws.is_demo=True;self.ws.save()
        self.assertEqual(self.client.post('/monitor/now/').status_code,403)

    def test_all_empty_pages_render(self):
        for path in ['/','/projects/','/projects/new/','/sources/','/import/','/contents/','/events/','/review/','/reports/','/notifications/','/settings/','/operations/','/account/password/']:
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,200)

    def test_real_pages_and_report_render(self):
        event=self.event();report=s.generate_report(self.project)
        for path in ['/', '/contents/','/events/','/review/',f'/events/{event.pk}/',f'/reports/{report.pk}/',f'/reports/{report.pk}/csv/']:
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,200)

    def test_csrf_enforced(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post('/demo/').status_code,403)

    def test_get_cannot_mutate(self):
        for path in ['/demo/','/logout/',f'/sources/{self.source.pk}/collect/']:
            self.assertEqual(self.client.get(path).status_code,405)

    def test_cross_workspace_reads_and_writes_rejected(self):
        other=Workspace.objects.create(name='另一客户');project=Project.objects.create(workspace=other,name='其他')
        event=Event.objects.create(project=project,key='other',title='私密事件');report=s.generate_report(project)
        source=Source.objects.create(project=project,name='secret',kind='rss',url='https://example.com/feed')
        for path in [f'/events/{event.pk}/',f'/projects/{project.pk}/',f'/reports/{report.pk}/',f'/reports/{report.pk}/csv/']:
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.post(f'/events/{event.pk}/action/',{'action':'approve'}).status_code,404)
        self.assertEqual(self.client.post(f'/sources/{source.pk}/collect/').status_code,404)
        self.assertNotContains(self.client.get('/events/'),'私密事件')

    def test_viewer_cannot_mutate(self):
        member=Membership.objects.get(user=self.user);member.role='viewer';member.save()
        self.assertEqual(self.client.get('/contents/').status_code,200)
        for path in ['/demo/','/projects/new/','/reports/','/notifications/']:
            self.assertEqual(self.client.post(path,{}).status_code,403)
        self.assertEqual(self.client.get('/settings/').status_code,403)

    def test_analyst_cannot_manage_settings(self):
        member=Membership.objects.get(user=self.user);member.role='analyst';member.save()
        self.assertEqual(self.client.get('/settings/').status_code,403)
        self.assertEqual(self.client.post('/notifications/',{}).status_code,403)

    def test_duplicate_import_and_job_unique(self):
        self.content();self.content()
        self.assertEqual(Content.objects.count(),1);self.assertEqual(Job.objects.count(),1)

    def test_failed_batch_rolls_back(self):
        with self.assertRaises(ValueError):s.ingest(self.source,[{'title':'valid'},{'title':''}])
        self.assertEqual(Content.objects.count(),0);self.assertEqual(Job.objects.count(),0)

    def test_import_json_csv_validation(self):
        self.assertEqual(len(s.parse_import(b'title,text\nhello,world\n','a.csv')),1)
        for body,name in [(b'{}','a.json'),(b'text\nmissing\n','a.csv'),(b'[{"title":"x","published_at":"bad"}]','a.json'),(b'[{"title":"x","url":"javascript:alert(1)"}]','a.json')]:
            with self.subTest(name=name,body=body),self.assertRaises(ValueError):s.parse_import(body,name)

    def test_rule_analysis_and_exclusion(self):
        c=self.content();s.analyze(c);c.refresh_from_db()
        self.assertTrue(c.relevant);self.assertEqual(c.sentiment,'负面线索');self.assertEqual(c.analysis_mode,'规则辅助')
        other=self.content(title='青禾社区活动',external_id='two');s.analyze(other);other.refresh_from_db();self.assertFalse(other.relevant)

    def test_near_duplicate_event_grouping(self):
        c1=self.content();s.analyze(c1)
        c2=self.content(title='青禾饮品瓶盖出现漏液',external_id='two');s.analyze(c2)
        self.assertEqual(Event.objects.count(),1);self.assertEqual(EventItem.objects.count(),2)
        s.analyze(c2);self.assertEqual(EventItem.objects.count(),2)

    def test_unrelated_events_not_forced_into_same_category(self):
        s.analyze(self.content());s.analyze(self.content(title='青禾饮品配送太慢还没发货',external_id='different',text='青禾饮品物流没有发货'))
        self.assertEqual(Event.objects.count(),2)

    def test_feedback_removes_event_evidence(self):
        event=self.event();content=Content.objects.first()
        self.client.post(f'/contents/{content.pk}/feedback/',{'action':'irrelevant'})
        event.refresh_from_db();self.assertEqual(event.review_status,'已忽略');self.assertFalse(event.items.exists())

    def test_split_requires_multiple_evidence(self):
        event=self.event();item=event.items.first()
        self.client.post(f'/events/{event.pk}/action/',{'action':'split','item_id':item.pk})
        self.assertEqual(Event.objects.count(),1)
        c=self.content(title='青禾饮品瓶盖出现漏液',external_id='two');s.analyze(c)
        self.client.post(f'/events/{event.pk}/action/',{'action':'split','item_id':item.pk})
        self.assertEqual(Event.objects.count(),2)

    def test_approve_creates_one_delivery(self):
        event=self.event()
        for _ in range(2):self.client.post(f'/events/{event.pk}/action/',{'action':'approve','risk':'需要关注'})
        self.assertEqual(Delivery.objects.count(),1)

    def test_withdraw_cancels_unsent_delivery(self):
        event=self.event();self.client.post(f'/events/{event.pk}/action/',{'action':'approve'})
        self.client.post(f'/events/{event.pk}/action/',{'action':'withdraw'})
        self.assertEqual(Delivery.objects.get().status,'已取消')

    def test_no_delivery_below_threshold(self):
        self.config.threshold='紧急核实';self.config.save();self.assertIsNone(s.make_delivery(self.event()))

    def test_paused_unverified_and_quiet_block_network(self):
        event=self.event();event.review_status='审核通过';event.save();delivery=s.make_delivery(event)
        with patch('core.services.wework_post') as send:
            s.send_delivery(delivery);delivery.refresh_from_db();self.assertEqual(delivery.status,'通知已暂停')
            self.config.enabled=True;self.config.save();s.send_delivery(delivery);delivery.refresh_from_db();self.assertEqual(delivery.status,'待验证')
            self.config_ready();self.config.quiet=True;self.config.quiet_start=time(0);self.config.quiet_end=time(23,59);self.config.save()
            with patch('core.services.quiet_now',return_value=True):s.send_delivery(delivery)
            delivery.refresh_from_db();self.assertEqual(delivery.status,'免打扰延后');send.assert_not_called()

    def test_cross_midnight_quiet_period(self):
        self.config.quiet=True;self.config.quiet_start=time(22);self.config.quiet_end=time(8)
        self.assertTrue(s.quiet_now(self.config,datetime(2026,10,17,15,tzinfo=tz.utc)))
        self.assertTrue(s.quiet_now(self.config,datetime(2026,10,17,23,tzinfo=tz.utc)))
        self.assertFalse(s.quiet_now(self.config,datetime(2026,10,17,4,tzinfo=tz.utc)))

    def test_delivery_success_is_idempotent(self):
        self.config_ready();event=self.event();event.review_status='审核通过';event.save();delivery=s.make_delivery(event)
        with patch('core.services.wework_post') as send:
            s.send_delivery(delivery);s.send_delivery(delivery);send.assert_called_once()
        delivery.refresh_from_db();self.assertEqual(delivery.status,'接口已接收')

    def test_wechat_message_contains_brief_without_url(self):
        event=self.event();delivery=s.make_delivery(event)
        self.assertIn('风险等级：需要关注',delivery.body)
        self.assertIn('来源：上传文件',delivery.body)
        self.assertIn('包装漏液',delivery.body)
        self.assertNotIn('http://',delivery.body)
        self.assertNotIn('https://',delivery.body)

    def test_queued_legacy_url_is_removed_before_wechat_send(self):
        self.config_ready();event=self.event();event.review_status='审核通过';event.save()
        delivery=Delivery.objects.create(workspace=self.ws,key='legacy-link',event=event,target_name='群',target_version=self.config.version,status='待发送',body='摘要内容 https://argus.example/events/4/')
        with patch('core.services.wework_post') as send:
            s.send_delivery(delivery)
            self.assertNotIn('http://',send.call_args.args[1]);self.assertNotIn('https://',send.call_args.args[1])

    def test_push_interval_defers_following_messages(self):
        self.config_ready();event=self.event();event.review_status='审核通过';event.save()
        previous=Delivery.objects.create(workspace=self.ws,key='previous-success',target_name='群',target_version=self.config.version,status='接口已接收',body='已发送')
        delivery=Delivery.objects.create(workspace=self.ws,key='interval-pending',event=event,target_name='群',target_version=self.config.version,status='待发送',body='新线索')
        with patch('core.services.wework_post') as send:
            s.send_delivery(delivery);send.assert_not_called()
        delivery.refresh_from_db();self.assertEqual(delivery.status,'待发送');self.assertIn('10 分钟',delivery.error)

    def test_notification_page_exposes_allowed_push_intervals(self):
        response=self.client.get('/notifications/')
        for value in ['1','5','10','20','30','60','120']:
            with self.subTest(value=value):self.assertContains(response,f'value="{value}"')

    def test_unknown_delivery_never_auto_retries(self):
        self.config_ready();event=self.event();event.review_status='审核通过';event.save();delivery=s.make_delivery(event)
        with patch('core.services.wework_post',side_effect=s.UncertainSend('timeout')) as send:
            s.send_delivery(delivery);s.send_delivery(delivery);send.assert_called_once()
        delivery.refresh_from_db();self.assertEqual(delivery.status,'结果未知')
        self.client.post(f'/notifications/{delivery.pk}/action/',{'action':'resend'})
        delivery.refresh_from_db();self.assertEqual(delivery.status,'结果未知')

    def test_config_rotation_blocks_old_target(self):
        self.config_ready();event=self.event();event.review_status='审核通过';event.save();delivery=s.make_delivery(event)
        self.config.version+=1;self.config.save()
        with patch('core.services.wework_post') as send:s.send_delivery(delivery);send.assert_not_called()
        delivery.refresh_from_db();self.assertEqual(delivery.status,'目标已变更')

    def test_interrupted_send_marked_unknown(self):
        self.config_ready();event=self.event();event.review_status='审核通过';event.save();delivery=s.make_delivery(event);delivery.status='发送中';delivery.save()
        with patch('core.services.wework_post') as send:s.send_delivery(delivery);send.assert_not_called()
        delivery.refresh_from_db();self.assertEqual(delivery.status,'结果未知')

    def test_wework_only_official_endpoint(self):
        self.config.webhook_cipher=s.encrypt('https://evil.example/cgi-bin/webhook/send?key=abcdefgh')
        with patch('core.services.remote') as remote,self.assertRaises(s.RemoteError):s.wework_post(self.config,'test')
        remote.assert_not_called()

    def test_credentials_are_encrypted_and_not_in_html(self):
        secret='super-secret-password-123';self.config.webhook_cipher=s.encrypt(secret);self.config.save()
        self.assertNotIn(secret,self.config.webhook_cipher);self.assertEqual(s.decrypt(self.config.webhook_cipher),secret)
        self.assertNotContains(self.client.get('/notifications/'),secret)

    def test_ssrf_rejects_private_mixed_and_nonstandard_ports(self):
        for address in ['127.0.0.1','10.0.0.2','169.254.169.254','::1']:
            with patch('core.services.socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(address,443))]),self.assertRaises(s.RemoteError):s.public_url('https://example.com')
        for url in ['file:///etc/passwd','https://user:pass@example.com','https://example.com:8443']:
            with self.assertRaises(s.RemoteError):s.public_url(url)

    @patch('core.services.remote')
    def test_rss_real_parser_and_dedup(self,remote):
        source=Source.objects.create(project=self.project,name='RSS',url='https://example.com/feed')
        remote.return_value=(200,{},b'<?xml version="1.0"?><rss version="2.0"><channel><title>Test</title><item><guid>1</guid><title>Test item</title><description>Body</description><link>https://example.com/a</link></item></channel></rss>')
        s.collect(source);s.collect(source);self.assertEqual(Content.objects.filter(source=source).count(),1)
        self.assertEqual(list(SourceRun.objects.values_list('inserted',flat=True)),[1,0])

    @patch('core.services.remote',return_value=(200,{},b'<!DOCTYPE rss [<!ENTITY xx SYSTEM "file:///etc/passwd">]><rss/>'))
    def test_xml_entity_rejected(self,remote):
        source=Source.objects.create(project=self.project,name='bad',url='https://example.com')
        with self.assertRaises(s.RemoteError):s.collect(source)
        source.refresh_from_db();self.assertEqual(source.status,'采集失败')

    @patch('core.services.remote',side_effect=s.RemoteError('连接失败'))
    def test_source_failure_recorded(self,remote):
        source=Source.objects.create(project=self.project,name='bad',url='https://example.com')
        with self.assertRaises(s.RemoteError):s.collect(source)
        self.assertEqual(SourceRun.objects.get().status,'失败')

    def test_worker_executes_and_reclaims_expired_lease(self):
        content=self.content();job=Job.objects.get();job.status='running';job.lease_until=timezone.now()-timedelta(minutes=1);job.save()
        self.assertTrue(s.work_once());job.refresh_from_db();content.refresh_from_db()
        self.assertEqual(job.status,'succeeded');self.assertTrue(content.relevant)

    def test_failed_task_retries_then_stops(self):
        job=s.enqueue(self.ws,'collect','badjob',{'source_id':999999})
        for index in range(3):
            Job.objects.filter(pk=job.pk).update(run_after=timezone.now()-timedelta(seconds=1));s.work_once()
        job.refresh_from_db();self.assertEqual(job.status,'failed');self.assertEqual(job.attempts,3)

    def test_report_snapshot_does_not_mutate(self):
        event=self.event();first=s.generate_report(self.project);event.title='changed';event.save();second=s.generate_report(self.project)
        first.refresh_from_db();self.assertNotEqual(first.snapshot['events'][0]['title'],'changed');self.assertEqual(second.revision,2)

    def test_csv_formula_injection_is_escaped(self):
        for text in ['=HYPERLINK("evil")','+CMD','-1+2','@formula','  =evil','\tformula']:
            self.assertTrue(csv_safe(text).startswith("'"))

    def test_demo_is_explicit_and_repeatable(self):
        self.ws.is_demo=True;self.ws.demo_owner=self.user;self.ws.save()
        # Keep an independent real membership, as actual experience mode does.
        real=Workspace.objects.create(name='真实空间');Membership.objects.filter(user=self.user).update(workspace=real)
        self.client.session.flush();self.client.force_login(self.user)
        session=self.client.session;session['experience_workspace']=self.ws.pk;session.save()
        self.assertEqual(s.load_demo(self.ws),5);self.assertEqual(s.load_demo(self.ws),0)
        self.assertEqual(Content.objects.filter(is_demo=True).count(),5)
        self.assertContains(self.client.get('/contents/'),'演示数据')

    def test_ai_schema_and_evidence_validation_falls_back(self):
        content=self.content();config=AIConfig.objects.create(workspace=self.ws,enabled=True,model='test',key_cipher=s.encrypt('secret'))
        raw=json.dumps({'choices':[{'message':{'content':json.dumps({'relevant':True,'sentiment':'负面线索','category':'产品体验','reason':'bad','evidence':'invented'})}}]}).encode()
        with patch('core.services.remote',return_value=(200,{},raw)):s.analyze(content)
        content.refresh_from_db();self.assertEqual(content.analysis_mode,'AI 失败 · 规则');self.assertTrue(content.relevant)

    def test_ai_valid_response_and_cache(self):
        content=self.content();config=AIConfig.objects.create(workspace=self.ws,enabled=True,model='test',key_cipher=s.encrypt('secret'))
        result={'relevant':True,'sentiment':'负面线索','category':'包装物流','reason':'包含包装反馈','evidence':'漏液'}
        raw=json.dumps({'choices':[{'message':{'content':json.dumps(result)}}],'usage':{'total_tokens':42}}).encode()
        with patch('core.services.remote',return_value=(200,{},raw)) as remote:s.analyze(content);s.analyze(content);remote.assert_called_once()
        self.assertEqual(AnalysisRun.objects.get().tokens,42)

    def test_ai_daily_budget_prevents_call(self):
        content=self.content();config=AIConfig.objects.create(workspace=self.ws,enabled=True,model='test',key_cipher=s.encrypt('secret'),daily_limit=1)
        AnalysisRun.objects.create(content=content,signature='used',model='test',status='失败')
        with patch('core.services.remote') as remote:s.analyze(content);remote.assert_not_called()
        content.refresh_from_db();self.assertEqual(content.analysis_mode,'预算用尽 · 规则')

    def test_no_xss_from_content(self):
        self.content(title='<script>alert(1)</script>青禾饮品')
        response=self.client.get('/contents/')
        self.assertNotContains(response,'<script>alert(1)</script>');self.assertContains(response,'&lt;script&gt;')

    def test_login_rate_limit(self):
        self.client.logout()
        for _ in range(8):self.client.post('/login/',{'username':'owner','password':'wrong'})
        response=self.client.post('/login/',{'username':'owner','password':'SafeArgusPassword12!'})
        self.assertContains(response,'登录尝试过多');self.assertNotIn('_auth_user_id',self.client.session)

    def test_password_change(self):
        self.client.post('/account/password/',{'old':'SafeArgusPassword12!','new':'AnotherSafePassword45!','confirm':'AnotherSafePassword45!'})
        self.user.refresh_from_db();self.assertTrue(self.user.check_password('AnotherSafePassword45!'))

    def test_import_http_upload(self):
        file=io.BytesIO('title,text,external_id\n青禾饮品新品,青禾饮品发布新品,item-1\n'.encode());file.name='upload.csv'
        response=self.client.post('/import/',{'project':self.project.pk,'source_name':'客户数据','file':file})
        self.assertEqual(response.status_code,302);self.assertEqual(Content.objects.count(),1)

    def test_bad_import_does_not_create_content(self):
        file=io.BytesIO(b'[{"title":"ok"},{"text":"missing title"}]');file.name='bad.json'
        self.client.post('/import/',{'project':self.project.pk,'source_name':'bad','file':file})
        self.assertFalse(Content.objects.exists())

    def test_notice_state_new_config_renders(self):
        other=Workspace.objects.create(name='新空间');user=User.objects.create_user('newuser');Membership.objects.create(workspace=other,user=user)
        self.client.force_login(user);self.assertEqual(self.client.get('/notifications/').status_code,200)

    def test_schedule_creates_single_daily_job(self):
        self.config_ready();self.config.daily_time=time(0);self.config.save()
        s.schedule();s.schedule();self.assertEqual(Job.objects.filter(kind='report').count(),1)

    def test_health_does_not_expose_secrets(self):
        self.client.logout();response=self.client.get('/health/');self.assertEqual(response.status_code,200);self.assertEqual(set(response.json()),{'status','application','version'})

    def test_rate_limit_defers_without_network(self):
        self.config_ready();event=self.event();event.review_status='审核通过';event.save();delivery=s.make_delivery(event)
        for index in range(10):Delivery.objects.create(workspace=self.ws,key='limit:'+str(index),target_name='群',status='接口已接收',body='test')
        with patch('core.services.wework_post') as send:s.send_delivery(delivery);send.assert_not_called()
        delivery.refresh_from_db();self.assertEqual(delivery.status,'待发送');self.assertIn('排队',delivery.error)

    def test_backup_closes_database_and_restores(self):
        from cryptography.fernet import Fernet
        from django.conf import settings
        with tempfile.TemporaryDirectory(dir=settings.DATA_DIR) as tmp:
            base=Path(tmp);data=base/'data';data.mkdir();key=Fernet.generate_key();(data/'.encryption-key').write_bytes(key);(data/'.django-secret').write_text('testsecret')
            source=base/'source.sqlite3'
            connection=sqlite3.connect(source);connection.execute('CREATE TABLE probe(value TEXT)');connection.execute("INSERT INTO probe VALUES('preserved')");connection.commit();connection.close()
            fake=Mock(BASE_DIR=base,DATA_DIR=data,DATABASES={'default':{'NAME':str(source)}})
            with patch('core.management.commands.backup.settings',fake):call_command('backup',stdout=io.StringIO())
            archives=list((base/'backups').glob('*.zip'));self.assertEqual(len(archives),1);self.assertFalse(list((base/'backups').glob('*.sqlite3')))
            restored=base/'restored';restored.mkdir()
            with zipfile.ZipFile(archives[0]) as archive:archive.extractall(restored)
            connection=sqlite3.connect(restored/'argus.sqlite3');self.assertEqual(connection.execute('SELECT value FROM probe').fetchone()[0],'preserved');connection.close()
            self.assertEqual((restored/'.encryption-key').read_bytes(),key)

    def test_malformed_split_id_is_rejected(self):
        event=self.event();response=self.client.post(f'/events/{event.pk}/action/',{'action':'split','item_id':'malformed'});self.assertEqual(response.status_code,403)
