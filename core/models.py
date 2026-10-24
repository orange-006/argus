from django.db import models
from datetime import time
from django.contrib.auth.models import User
from django.utils import timezone

class PlatformConfig(models.Model):
    signup_enabled=models.BooleanField(default=True)
    trial_days=models.PositiveIntegerField(default=7)
    updated_at=models.DateTimeField(auto_now=True)

class EmailIdentity(models.Model):
    user=models.OneToOneField(User,on_delete=models.CASCADE)
    email=models.CharField(max_length=254,unique=True)
    verified=models.BooleanField(default=False)
    consent_at=models.DateTimeField(default=timezone.now)
    created_at=models.DateTimeField(auto_now_add=True)

class TrialAccess(models.Model):
    workspace=models.OneToOneField('Workspace',on_delete=models.CASCADE,related_name='trial_access')
    user=models.OneToOneField(User,on_delete=models.CASCADE)
    expires_at=models.DateTimeField()
    suspended=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)

class PlatformAudit(models.Model):
    actor=models.CharField(max_length=150)
    action=models.CharField(max_length=100)
    target=models.CharField(max_length=150,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

class Workspace(models.Model):
    name=models.CharField(max_length=100)
    is_demo=models.BooleanField(default=False)
    demo_owner=models.OneToOneField(User,on_delete=models.CASCADE,null=True,blank=True,related_name='experience_workspace')
    onboarding_complete=models.BooleanField(default=False)
    monitor_requested_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

class Membership(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE)
    workspace=models.ForeignKey(Workspace,on_delete=models.CASCADE)
    role=models.CharField(max_length=20,default='admin',choices=[('admin','管理员'),('analyst','分析员'),('viewer','只读成员')])
    class Meta: constraints=[models.UniqueConstraint(fields=['user','workspace'],name='unique_membership')]

class Project(models.Model):
    workspace=models.ForeignKey(Workspace,on_delete=models.CASCADE)
    name=models.CharField(max_length=100)
    aliases=models.TextField(blank=True)
    excludes=models.TextField(blank=True)
    active=models.BooleanField(default=True)
    purpose=models.CharField(max_length=20,default='brand')
    industry=models.CharField(max_length=30,default='other')
    onboarding_key=models.CharField(max_length=64,blank=True,unique=True,null=True)
    first_report_requested=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class Source(models.Model):
    project=models.ForeignKey(Project,on_delete=models.CASCADE)
    name=models.CharField(max_length=100)
    kind=models.CharField(max_length=16,default='rss')
    url=models.URLField(max_length=2000,blank=True)
    enabled=models.BooleanField(default=True)
    interval_minutes=models.PositiveIntegerField(default=30)
    last_attempt=models.DateTimeField(null=True,blank=True)
    last_success=models.DateTimeField(null=True,blank=True)
    status=models.CharField(max_length=32,default='尚未采集')
    etag=models.CharField(max_length=300,blank=True)
    modified=models.CharField(max_length=300,blank=True)
    preset_key=models.CharField(max_length=50,blank=True,db_index=True)
    search_config=models.JSONField(default=dict,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['project','preset_key'],condition=~models.Q(preset_key=''),name='unique_project_preset')]

class Installation(models.Model):
    token_digest=models.CharField(max_length=64,blank=True)
    claimed=models.BooleanField(default=False)
    created_at=models.DateTimeField(default=timezone.now)

class SourcePreset(models.Model):
    kind=models.CharField(max_length=20,default="rss")
    key=models.CharField(max_length=50,unique=True)
    name=models.CharField(max_length=100)
    url=models.URLField(max_length=2000)
    category=models.CharField(max_length=30)
    description=models.CharField(max_length=500)
    coverage=models.CharField(max_length=500)
    content_level=models.CharField(max_length=30,default='标题与摘要')
    interval_minutes=models.PositiveIntegerField(default=60)
    verified_date=models.DateField(null=True,blank=True)
    check_status=models.CharField(max_length=50,default='待检查')
    usage_note=models.CharField(max_length=500,default='公开订阅源；如用于商业展示或分发，请由运营方确认许可范围。')
    enabled=models.BooleanField(default=True)

class SourceRun(models.Model):
    source=models.ForeignKey(Source,on_delete=models.CASCADE)
    started_at=models.DateTimeField(default=timezone.now)
    status=models.CharField(max_length=32,default='运行中')
    fetched=models.PositiveIntegerField(default=0)
    inserted=models.PositiveIntegerField(default=0)
    updated=models.PositiveIntegerField(default=0)
    error=models.CharField(max_length=300,blank=True)

class Content(models.Model):
    source=models.ForeignKey(Source,on_delete=models.CASCADE)
    external_id=models.CharField(max_length=64)
    title=models.CharField(max_length=1000)
    text=models.TextField(blank=True)
    summary=models.TextField(blank=True)
    author=models.CharField(max_length=300,blank=True)
    text_origin=models.CharField(max_length=30,blank=True)
    last_seen=models.DateTimeField(null=True,blank=True)
    url=models.URLField(max_length=2000,blank=True)
    published_at=models.DateTimeField(null=True,blank=True)
    fetched_at=models.DateTimeField(default=timezone.now)
    level=models.CharField(max_length=16,default='title')
    digest=models.CharField(max_length=64)
    revision=models.PositiveIntegerField(default=1)
    relevant=models.BooleanField(default=False)
    sentiment=models.CharField(max_length=16,default='待分析')
    reason=models.TextField(blank=True)
    evidence=models.TextField(blank=True)
    analysis_mode=models.CharField(max_length=32,default='待分析')
    is_demo=models.BooleanField(default=False)
    feedback=models.CharField(max_length=16,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['source','external_id'],name='unique_content')]
        indexes=[models.Index(fields=['fetched_at']),models.Index(fields=['relevant','sentiment'])]

    @property
    def level_label(self):
        if self.text_origin in ['rss_content','json_content']:return '订阅正文（源可能截断）'
        return {'title':'仅标题','summary':'摘要','fulltext':'已提供文本'}.get(self.level,'仅标题')

class ContentObservation(models.Model):
    content=models.ForeignKey(Content,on_delete=models.CASCADE,related_name='observations')
    snapshot_key=models.CharField(max_length=64)
    rank=models.PositiveIntegerField()
    observed_at=models.DateTimeField(default=timezone.now)
    upstream_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['content','snapshot_key'],name='unique_content_snapshot')]
        ordering=['-observed_at','-pk']

class Event(models.Model):
    project=models.ForeignKey(Project,on_delete=models.CASCADE)
    key=models.CharField(max_length=150)
    title=models.CharField(max_length=300)
    category=models.CharField(max_length=50,default='品牌动态')
    summary=models.TextField(blank=True)
    risk=models.CharField(max_length=16,default='一般信息')
    review_status=models.CharField(max_length=16,default='待审核')
    handling=models.CharField(max_length=16,default='待处理')
    note=models.TextField(blank=True)
    first_seen=models.DateTimeField(default=timezone.now)
    last_seen=models.DateTimeField(default=timezone.now)
    revision=models.PositiveIntegerField(default=1)
    class Meta: constraints=[models.UniqueConstraint(fields=['project','key'],name='unique_event')]

class EventItem(models.Model):
    event=models.ForeignKey(Event,on_delete=models.CASCADE,related_name='items')
    content=models.OneToOneField(Content,on_delete=models.CASCADE,related_name='event_item')

class NotificationConfig(models.Model):
    workspace=models.OneToOneField(Workspace,on_delete=models.CASCADE)
    group_name=models.CharField(max_length=100,default='品牌运营群')
    webhook_cipher=models.TextField(blank=True)
    enabled=models.BooleanField(default=False)
    verified=models.BooleanField(default=False)
    test_accepted=models.BooleanField(default=False)
    version=models.PositiveIntegerField(default=1)
    threshold=models.CharField(max_length=16,default='需要关注')
    quiet=models.BooleanField(default=True)
    quiet_start=models.TimeField(default=time(22,0))
    quiet_end=models.TimeField(default=time(8,0))
    daily_time=models.TimeField(default=time(18,0))
    push_interval_minutes=models.PositiveIntegerField(default=10)
    public_base_url=models.URLField(max_length=300,default='http://127.0.0.1:8765')

class Delivery(models.Model):
    workspace=models.ForeignKey(Workspace,on_delete=models.CASCADE)
    event=models.ForeignKey(Event,on_delete=models.SET_NULL,null=True,blank=True)
    report=models.ForeignKey('Report',on_delete=models.SET_NULL,null=True,blank=True)
    kind=models.CharField(max_length=30,default='风险提醒')
    key=models.CharField(max_length=200,unique=True)
    target_version=models.PositiveIntegerField(default=1)
    target_name=models.CharField(max_length=100)
    status=models.CharField(max_length=30,default='待发送')
    body=models.TextField()
    attempts=models.PositiveIntegerField(default=0)
    error=models.CharField(max_length=300,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

class Report(models.Model):
    project=models.ForeignKey(Project,on_delete=models.CASCADE)
    date=models.DateField()
    revision=models.PositiveIntegerField(default=1)
    snapshot=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['project','date','revision'],name='unique_report_revision')]

class AIConfig(models.Model):
    workspace=models.OneToOneField(Workspace,on_delete=models.CASCADE)
    enabled=models.BooleanField(default=False)
    api_base=models.URLField(default='https://api.deepseek.com/v1',max_length=300)
    model=models.CharField(max_length=100,default='')
    key_cipher=models.TextField(blank=True)
    daily_limit=models.PositiveIntegerField(default=200)

class SearchProviderConfig(models.Model):
    workspace=models.ForeignKey(Workspace,on_delete=models.CASCADE)
    provider=models.CharField(max_length=20)
    enabled=models.BooleanField(default=False)
    key_cipher=models.TextField(blank=True)
    daily_limit=models.PositiveIntegerField(default=20)
    usage_date=models.DateField(default=timezone.localdate)
    daily_used=models.PositiveIntegerField(default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['workspace','provider'],name='unique_workspace_search_provider')]

class AnalysisRun(models.Model):
    content=models.ForeignKey(Content,on_delete=models.CASCADE)
    signature=models.CharField(max_length=64)
    model=models.CharField(max_length=100)
    prompt_version=models.CharField(max_length=20,default='v1')
    status=models.CharField(max_length=20)
    tokens=models.PositiveIntegerField(default=0)
    result=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['content','signature'],name='unique_analysis')]

class Job(models.Model):
    workspace=models.ForeignKey(Workspace,on_delete=models.CASCADE)
    kind=models.CharField(max_length=30)
    key=models.CharField(max_length=200,unique=True)
    payload=models.JSONField(default=dict)
    status=models.CharField(max_length=20,default='pending')
    attempts=models.PositiveIntegerField(default=0)
    run_after=models.DateTimeField(default=timezone.now)
    lease_until=models.DateTimeField(null=True,blank=True)
    lease_token=models.CharField(max_length=64,blank=True)
    error=models.CharField(max_length=300,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

class AuditLog(models.Model):
    workspace=models.ForeignKey(Workspace,on_delete=models.CASCADE)
    actor=models.CharField(max_length=100)
    action=models.CharField(max_length=100)
    detail=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)

class Heartbeat(models.Model):
    name=models.CharField(max_length=50,unique=True)
    updated_at=models.DateTimeField(default=timezone.now)

class LoginAttempt(models.Model):
    key=models.CharField(max_length=64,unique=True)
    failures=models.PositiveIntegerField(default=0)
    blocked_until=models.DateTimeField(null=True,blank=True)
    updated_at=models.DateTimeField(auto_now=True)

class KeywordRun(models.Model):
    workspace=models.ForeignKey(Workspace,on_delete=models.CASCADE)
    keyword=models.CharField(max_length=100)
    mode=models.CharField(max_length=16,default='local')
    provider=models.CharField(max_length=20,blank=True)
    scope=models.CharField(max_length=20,default='web')
    status=models.CharField(max_length=16,default='pending')
    results=models.JSONField(default=list)
    error=models.CharField(max_length=300,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    finished_at=models.DateTimeField(null=True,blank=True)
