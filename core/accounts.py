"""Public email/password registration and separate platform administration."""
import uuid
from datetime import timedelta
from functools import wraps
from django import forms
from django.contrib import messages
from django.contrib.auth import login,authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.db.models import F
from django.http import HttpResponseForbidden,HttpResponseBadRequest
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from .models import User,Membership,Workspace,NotificationConfig,AIConfig,PlatformConfig,EmailIdentity,TrialAccess,PlatformAudit,LoginAttempt,SourcePreset,Project,Source
from . import services as svc

def config():return PlatformConfig.objects.filter(pk=1).first()
def email_normalize(value):return value.strip().casefold()

def rate_allowed(request,prefix,limit=5,minutes=60):
    key=svc.digest(prefix+':'+request.META.get('REMOTE_ADDR','unknown'))
    with transaction.atomic():
        attempt,_=LoginAttempt.objects.get_or_create(key=key)
        if not attempt.blocked_until or attempt.blocked_until<=timezone.now():
            attempt.failures=0;attempt.blocked_until=timezone.now()+timedelta(minutes=minutes);attempt.save()
        LoginAttempt.objects.filter(pk=attempt.pk).update(failures=F('failures')+1)
        attempt.refresh_from_db()
        return attempt.failures<=limit

class RegisterForm(forms.Form):
    email=forms.EmailField(max_length=254,label='邮箱',widget=forms.EmailInput(attrs={'autocomplete':'email','placeholder':'你的常用邮箱'}))
    workspace_name=forms.CharField(max_length=100,label='团队 / 工作空间名称',initial='我的 Argus 空间')
    password=forms.CharField(label='密码（至少 10 位）',max_length=128,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    confirm=forms.CharField(label='再次输入密码',max_length=128,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    consent=forms.BooleanField(label='我已阅读并同意试用与隐私说明')
    def clean_email(self):
        email=email_normalize(self.cleaned_data['email'])
        if EmailIdentity.objects.filter(email=email).exists():raise forms.ValidationError('此邮箱无法用于新注册，请尝试登录或联系管理员。')
        return email
    def clean(self):
        d=super().clean()
        if d.get('password')!=d.get('confirm'):self.add_error('confirm','两次密码不一致')
        if d.get('password'):
            try:validate_password(d['password'],User(email=d.get('email','')))
            except ValidationError as exc:self.add_error('password',exc)
        return d

@never_cache
def register(request):
    if request.user.is_authenticated:return redirect('dashboard')
    c=config();opened=c.signup_enabled if c else True
    form=RegisterForm(request.POST if request.method=='POST' else None)
    if request.method=='POST':
        if not opened:return HttpResponseForbidden('注册暂时关闭，请联系管理员。')
        if not Membership.objects.filter(workspace__is_demo=False).exists():return HttpResponseForbidden('平台尚未完成首次初始化，请由管理员先完成设置。')
        if not rate_allowed(request,'signup'):form.add_error(None,'注册尝试较频繁，请一小时后再试。')
        elif form.is_valid():
            try:
                with transaction.atomic():
                    d=form.cleaned_data
                    user=User.objects.create_user(username='email_'+uuid.uuid4().hex,email=d['email'],password=d['password'])
                    EmailIdentity.objects.create(user=user,email=d['email'])
                    ws=Workspace.objects.create(name=d['workspace_name'])
                    Membership.objects.create(user=user,workspace=ws,role='admin')
                    TrialAccess.objects.create(user=user,workspace=ws,expires_at=timezone.now()+timedelta(days=c.trial_days if c else 7))
                    NotificationConfig.objects.create(workspace=ws);AIConfig.objects.create(workspace=ws)
                    PlatformAudit.objects.create(actor='self-registration',action='邮箱注册独立试用空间',target=str(user.pk))
                login(request,user,backend='django.contrib.auth.backends.ModelBackend')
                messages.success(request,'注册成功，先设置你想关注的对象。');return redirect('onboarding')
            except IntegrityError:form.add_error('email','此邮箱无法用于新注册，请尝试登录或联系管理员。')
    return render(request,'register.html',{'form':form,'signup_open':opened,'trial_days':c.trial_days if c else 7})

def platform_only(fn):
    @wraps(fn)
    def wrapped(request,*args,**kwargs):
        if not request.user.is_authenticated:return redirect('platform_login')
        if not request.user.is_active or not request.user.is_superuser:return HttpResponseForbidden('仅平台管理员可访问。客户空间管理员无此权限。')
        return fn(request,*args,**kwargs)
    return never_cache(wrapped)

@never_cache
def platform_login(request):
    if request.user.is_authenticated:
        return redirect('platform_admin') if request.user.is_superuser else HttpResponseForbidden('仅平台管理员可访问。')
    if request.method=='POST':
        if not rate_allowed(request,'platform-login',limit=10,minutes=10):messages.error(request,'登录尝试过多，请 10 分钟后重试。')
        else:
            user=authenticate(request,username=request.POST.get('username',''),password=request.POST.get('password',''))
            if user and user.is_superuser:
                login(request,user);PlatformAudit.objects.create(actor=user.username,action='登录平台后台');return redirect('platform_admin')
            messages.error(request,'账号、密码或平台管理权限无效。')
    return render(request,'platform_login.html')

class PlatformConfigForm(forms.Form):
    signup_enabled=forms.BooleanField(required=False,label='开放邮箱注册')
    trial_days=forms.IntegerField(min_value=1,max_value=30,initial=7,label='新用户试用天数（不改变已有试用）')

@platform_only
def platform_admin(request):
    c=config();form=PlatformConfigForm(initial={'signup_enabled':c.signup_enabled,'trial_days':c.trial_days} if c else {'signup_enabled':True,'trial_days':7})
    if request.method=='POST':
        form=PlatformConfigForm(request.POST)
        if form.is_valid():
            PlatformConfig.objects.update_or_create(pk=1,defaults=form.cleaned_data)
            PlatformAudit.objects.create(actor=request.user.username,action='更新注册与试用设置');messages.success(request,'已保存注册与试用设置。');return redirect('platform_admin')
    return render(request,'platform_admin.html',{'form':form,'trials':TrialAccess.objects.select_related('user','workspace','user__emailidentity').order_by('-created_at')[:100],'audits':PlatformAudit.objects.order_by('-created_at')[:30],'presets':SourcePreset.objects.order_by('category','name'),'user_count':EmailIdentity.objects.count(),'project_count':Project.objects.filter(workspace__is_demo=False).count()})

@require_POST
@platform_only
def trial_action(request,pk):
    with transaction.atomic():
        trial=get_object_or_404(TrialAccess.objects.select_for_update(),pk=pk)
        action=request.POST.get('action')
        if action=='suspend':trial.suspended=True
        elif action=='resume':trial.suspended=False
        elif action=='extend':trial.expires_at=max(trial.expires_at,timezone.now())+timedelta(days=7)
        else:return HttpResponseBadRequest('无效操作')
        trial.save()
        if not trial.suspended and trial.expires_at>timezone.now():
            from .models import Job
            Job.objects.filter(workspace=trial.workspace,status='trial_paused').update(status='pending',error='')
        PlatformAudit.objects.create(actor=request.user.username,action='试用管理：'+action,target=str(trial.user_id))
    return redirect('platform_admin')

@require_POST
@platform_only
def preset_action(request,pk):
    with transaction.atomic():
        preset=get_object_or_404(SourcePreset.objects.select_for_update(),pk=pk)
        preset.enabled=not preset.enabled;preset.save(update_fields=['enabled'])
        PlatformAudit.objects.create(actor=request.user.username,action='预设目录启停',target=preset.key)
    messages.success(request,'已更新来源库。此设置不改变客户已添加的来源。');return redirect('platform_admin')

def trial_blocked(workspace):
    trial=TrialAccess.objects.select_related('user').filter(workspace=workspace).first()
    return trial if trial and (trial.suspended or trial.expires_at<=timezone.now() or not trial.user.is_active) else None

class TrialMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if request.user.is_authenticated and not request.path.startswith(('/platform-admin/','/register/','/login/','/logout/','/contact/','/static/','/site/','/health/')):
            trial=TrialAccess.objects.filter(user=request.user).first()
            if trial and (trial.suspended or trial.expires_at<=timezone.now()):return render(request,'trial_status.html',{'trial':trial},status=403)
        return self.get_response(request)

def contact(request):return render(request,'contact.html')

def privacy(request):return render(request,'privacy.html')

def website(request,asset='index.html'):
    from pathlib import Path
    from django.conf import settings
    from django.http import FileResponse,Http404
    import mimetypes
    if asset=='register.html':return redirect('register')
    if asset=='login.html':return redirect('login')
    if asset not in ['index.html','style.css','app.js','favicon.svg','contact-wechat.jpg']:raise Http404
    path=Path(settings.BASE_DIR)/'website'/asset
    if not path.is_file():raise Http404
    response=FileResponse(path.open('rb'),content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream')
    response['X-Content-Type-Options']='nosniff'
    return response
