"""Beginner-first setup, curated source attachment and isolated experience mode."""
import secrets,uuid
from datetime import timedelta
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden,JsonResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import *
from .catalog import seed_catalog
from . import services as svc
from .views import workspace_view

PURPOSES=[('brand','关注我的品牌口碑'),('competitor','观察竞品动态'),('industry','了解行业资讯')]
INDUSTRIES=[('tech','科技与互联网'),('consumer','消费与零售'),('other','其他行业')]

class AccountForm(forms.Form):
    username=forms.RegexField(regex=r'^[\w.@+-]{3,100}$',label='设置登录账号',max_length=100)
    workspace_name=forms.CharField(label='团队 / 工作空间名称',max_length=100,initial='我的品牌空间')
    password=forms.CharField(label='设置密码（至少 10 位）',widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    confirm=forms.CharField(label='再次输入密码',widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    def clean(self):
        data=super().clean()
        if data.get('password')!=data.get('confirm'):self.add_error('confirm','两次密码不一致')
        if data.get('password'):
            try:validate_password(data['password'])
            except ValidationError as exc:self.add_error('password',exc)
        if User.objects.filter(username=data.get('username','')).exists():self.add_error('username','该账号已存在')
        return data

class OnboardingForm(forms.Form):
    purpose=forms.ChoiceField(choices=PURPOSES,label='你主要想做什么？')
    industry=forms.ChoiceField(choices=INDUSTRIES,label='所属行业')
    name=forms.CharField(label='品牌、竞品或行业关键词',max_length=100)
    aliases=forms.CharField(label='其他叫法 / 产品名（可选）',required=False,max_length=1000)
    excludes=forms.CharField(label='容易混淆的名称（可选）',required=False,max_length=1000)
    presets=forms.ModelMultipleChoiceField(queryset=SourcePreset.objects.none(),required=False)
    use_upload=forms.BooleanField(label='暂不选择来源，稍后导入自己的文件',required=False)
    token=forms.CharField(widget=forms.HiddenInput)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.fields['presets'].queryset=SourcePreset.objects.filter(enabled=True)
    def clean(self):
        data=super().clean()
        if not data.get('presets') and not data.get('use_upload'):self.add_error('presets','至少选择一个信息来源，或选择稍后导入文件')
        return data

def welcome(request):
    if Membership.objects.filter(workspace__is_demo=False).exists():return redirect('dashboard' if request.user.is_authenticated else 'login')
    # New installation can only be claimed through the local launcher's one-time token.
    if request.META.get('REMOTE_ADDR') not in ['127.0.0.1','::1']:return HttpResponseForbidden('首次创建账号请在运行 Argus 的电脑上完成。')
    installation=Installation.objects.filter(pk=1,claimed=False).first()
    token=request.GET.get('token','')
    if token and installation and secrets.compare_digest(svc.digest(token),installation.token_digest):
        request.session['setup_proof']=installation.token_digest
        return redirect('welcome')
    authorized=bool(installation and request.session.get('setup_proof') and secrets.compare_digest(request.session['setup_proof'],installation.token_digest) and timezone.now()-installation.created_at<timedelta(hours=24))
    form=AccountForm(request.POST or None)
    if request.method=='POST' and authorized and form.is_valid():
        with transaction.atomic():
            if not Installation.objects.filter(pk=1,claimed=False).update(claimed=True):return redirect('login')
            user=User.objects.create_user(username=form.cleaned_data['username'],password=form.cleaned_data['password'])
            user.is_superuser=True;user.is_staff=True;user.save(update_fields=['is_superuser','is_staff'])
            ws=Workspace.objects.create(name=form.cleaned_data['workspace_name']);Membership.objects.create(user=user,workspace=ws,role='admin')
            NotificationConfig.objects.create(workspace=ws,public_base_url=request.build_absolute_uri('/').rstrip('/'));AIConfig.objects.create(workspace=ws)
        request.session.pop('setup_proof',None)
        path=settings.DATA_DIR/'.setup-token'
        if path.exists():path.unlink()
        login(request,user);return redirect('onboarding')
    return render(request,'welcome.html',{'form':form,'authorized':authorized})

def attach_presets(project,presets):
    added=0
    with transaction.atomic():
        for preset in presets:
            source,created=Source.objects.get_or_create(project=project,preset_key=preset.key,defaults={'kind':preset.kind,'name':preset.name,'url':preset.url,'interval_minutes':preset.interval_minutes})
            if created:
                added+=1;svc.enqueue(project.workspace,'collect',f'first-source:{source.pk}',{'source_id':source.pk})
    return added

@workspace_view(write=True)
def onboarding(request):
    if request.ws.is_demo:
        messages.info(request,'请先退出体验空间，再创建自己的真实监测。');return redirect('dashboard')
    seed_catalog()
    token=request.session.setdefault('onboarding_token',uuid.uuid4().hex)
    if request.method=='GET' and Project.objects.filter(workspace=request.ws,onboarding_key=token).exists():
        token=uuid.uuid4().hex;request.session['onboarding_token']=token
    initial={'purpose':'brand','industry':'other','token':token,'presets':list(SourcePreset.objects.filter(enabled=True,key='chinanews').values_list('pk',flat=True))}
    form=OnboardingForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        if not secrets.compare_digest(form.cleaned_data['token'],token):return HttpResponseForbidden('设置页面已过期，请重新打开。')
        with transaction.atomic():
            project,created=Project.objects.get_or_create(onboarding_key=token,defaults={'workspace':request.ws,'name':form.cleaned_data['name'],'purpose':form.cleaned_data['purpose'],'industry':form.cleaned_data['industry'],'aliases':form.cleaned_data['aliases'],'excludes':form.cleaned_data['excludes']})
            if project.workspace_id!=request.ws.pk:return HttpResponseForbidden('项目范围无效')
            if created:
                attach_presets(project,form.cleaned_data['presets'])
                NotificationConfig.objects.get_or_create(workspace=request.ws)
                AIConfig.objects.get_or_create(workspace=request.ws)
                request.ws.onboarding_complete=True;request.ws.save(update_fields=['onboarding_complete'])
                svc.audit(request.ws,request.user.username,'完成首次设置',project.name)
        return redirect('first_results',pk=project.pk)
    selected=set(str(x) for x in (request.POST.getlist('presets') if request.method=='POST' else initial['presets']))
    return render(request,'onboarding.html',{'title':'开始我的监测','form':form,'presets':SourcePreset.objects.filter(enabled=True),'selected_presets':selected,'purpose_choices':PURPOSES,'industry_choices':INDUSTRIES})

def result_summary(project):
    if not project:return None
    sources=Source.objects.filter(project=project,kind__in=['rss','newsnow','search'])
    content=Content.objects.filter(source__project=project,is_demo=False)
    pending=Job.objects.filter(kind='analyze',status__in=['pending','running'],payload__content_id__in=content.values_list('pk',flat=True)).count()
    total=content.count();matches=content.filter(relevant=True).count()
    waiting=sources.filter(last_attempt__isnull=True,enabled=True).count();running=sources.filter(status='采集中').count()
    failures=sources.filter(status='采集失败').count();success=sources.filter(last_success__isnull=False).count()
    paused=sources.filter(enabled=False).count()
    stage='ready';title='首次检查已完成';detail=f'已获得 {total} 条来源内容，发现 {matches} 条与你关注对象相关的提及。'
    if not sources.exists() and not total:stage='import_required';title='项目已准备好，等待你的内容';detail='你选择了自行导入。上传文件后，系统会自动识别提及并形成事件。'
    elif waiting or running:stage='collecting';title='正在检查你选择的信息来源';detail='系统正在获取真实内容，页面会自动更新。若来源网络较慢，可先返回工作台。'
    elif pending:stage='analyzing';title='内容已获得，正在识别相关提及';detail=f'还有 {pending} 条内容等待分析。来源资讯不会自动算作品牌提及。'
    elif failures and not success and not total:stage='failed';title='来源暂时没有连接成功';detail='这不代表没有舆情。系统会按来源间隔再次检查，你也可以重试或导入自己的内容。'
    elif not total and paused==sources.count() and paused:stage='paused';title='所选来源已暂停';detail='请到来源管理启用来源，或导入文件后继续。'
    elif not matches:stage='no_matches';title='已检查来源，暂未发现相关提及';detail=f'实际获得 {total} 条来源资讯，尚未匹配你的关注对象。可补充产品名或其他叫法；也可能这些来源没有报道该对象。'
    elif failures:stage='partial';title='发现相关提及，部分来源仍异常';detail=f'已发现 {matches} 条相关提及，有 {failures} 个来源未成功，结果仅反映已获得的内容。'
    return {'stage':stage,'title':title,'detail':detail,'total':total,'matches':matches,'pending':pending,'failures':failures,'success':success,'finished':stage not in ['collecting','analyzing'],'project_id':project.pk,'sources':[{'name':s.name,'status':s.status,'last_success':timezone.localtime(s.last_success).strftime('%m-%d %H:%M') if s.last_success else '尚无成功记录'} for s in sources]}

@workspace_view()
def first_results(request,pk):
    project=get_object_or_404(Project,pk=pk,workspace=request.ws)
    return render(request,'first_results.html',{'title':'我的首次监测','project':project,'result':result_summary(project),'report':Report.objects.filter(project=project).order_by('-created_at').first()})

@workspace_view()
def first_results_status(request,pk):
    project=get_object_or_404(Project,pk=pk,workspace=request.ws)
    data=result_summary(project);report=Report.objects.filter(project=project).order_by('-created_at').first();data['report_id']=report.pk if report else None
    return JsonResponse(data)

@workspace_view()
def source_library(request):
    seed_catalog()
    project_id=request.POST.get('project') if request.method=='POST' else request.GET.get('project')
    project=Project.objects.filter(workspace=request.ws,pk=project_id).first() if str(project_id or '').isdigit() else Project.objects.filter(workspace=request.ws).first()
    if request.method=='POST':
        if request.ws.is_demo:return HttpResponseForbidden('体验空间不接入真实网络数据，请先退出体验。')
        if not project:messages.error(request,'请先创建或选择监测项目。')
        else:
            ids=request.POST.getlist('presets');presets=list(SourcePreset.objects.filter(enabled=True,pk__in=[int(x) for x in ids if x.isdigit()]))
            if not presets:messages.error(request,'请至少选择一个来源。')
            else:
                added=attach_presets(project,presets);svc.audit(request.ws,request.user.username,'添加推荐来源',str(added));messages.success(request,f'已添加 {added} 个来源，连接检查和首次采集正在进行。已有来源不会重复添加。');return redirect('first_results',pk=project.pk)
    attached=set(Source.objects.filter(project=project).exclude(preset_key='').values_list('preset_key',flat=True)) if project else set()
    return render(request,'source_library.html',{'title':'信息来源库','presets':SourcePreset.objects.filter(enabled=True),'projects':Project.objects.filter(workspace=request.ws),'project':project,'attached':attached})

@require_POST
@login_required
def demo_enter(request):
    membership=Membership.objects.filter(user=request.user,workspace__is_demo=False).first()
    if not membership:return HttpResponseForbidden('尚未分配客户空间')
    with transaction.atomic():
        demo,created=Workspace.objects.get_or_create(demo_owner=request.user,defaults={'name':'一分钟体验空间','is_demo':True,'onboarding_complete':True})
        if not demo.is_demo:return HttpResponseForbidden('体验空间无效')
        NotificationConfig.objects.get_or_create(workspace=demo,defaults={'enabled':False})
        AIConfig.objects.get_or_create(workspace=demo,defaults={'enabled':False})
        svc.load_demo(demo)
    request.session['experience_workspace']=demo.pk
    messages.info(request,'已进入独立体验空间，以下均为样例；不会采集真实来源或发送消息。');return redirect('dashboard')

@require_POST
@login_required
def demo_exit(request):
    request.session.pop('experience_workspace',None);messages.success(request,'已返回你的真实工作空间，样例不会进入真实报告。');return redirect('dashboard')
