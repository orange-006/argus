import csv,hashlib,io,json,re,uuid,math
from datetime import timedelta
from functools import wraps
from urllib.parse import urlsplit
from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate,login,logout,update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count,Q,Subquery,OuterRef
from django.http import HttpResponse,JsonResponse,HttpResponseForbidden
from django.shortcuts import render,redirect,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import *
from .forms import *
from . import services as svc
from .scope import access

def workspace_view(write=False,admin=False):
    def decorator(fn):
        @login_required
        @wraps(fn)
        def wrapped(request,*args,**kwargs):
            member=access(request)
            if not member:return HttpResponseForbidden('账号尚未分配客户空间，请联系管理员。')
            request.ws=member.workspace;request.member=member
            from .accounts import trial_blocked
            blocked=trial_blocked(request.ws)
            if blocked:return render(request,'trial_status.html',{'trial':blocked},status=403)
            if request.ws.is_demo and request.method=='POST' and fn.__name__ in ['sources','source_collect','source_toggle','import_view','project_edit','notifications','notification_action','monitor_now']:
                return HttpResponseForbidden('体验空间只用于样例操作，不连接真实数据源、不配置外部服务、不发送消息。请先退出体验。')
            if (admin and member.role!='admin') or (write and member.role=='viewer') or (request.method=='POST' and member.role=='viewer'):return HttpResponseForbidden('当前角色没有此操作权限。')
            return fn(request,*args,**kwargs)
        return wrapped
    return decorator

def page(request,template,context=None):return render(request,template,context or {})
def page_items(request,query):return Paginator(query,20).get_page(request.GET.get('page'))
def record(request,action,detail=''):svc.audit(request.ws,request.user.username,action,detail)

def login_view(request):
    if not Membership.objects.exists():return redirect('welcome')
    if request.user.is_authenticated:return redirect('dashboard')
    if request.method=='POST':
        key=svc.digest(request.META.get('REMOTE_ADDR','unknown'))
        attempt,_=LoginAttempt.objects.get_or_create(key=key)
        if attempt.blocked_until and attempt.blocked_until>timezone.now():messages.error(request,'登录尝试过多，请 10 分钟后再试。')
        else:
            identifier=request.POST.get('username','').strip()
            if '@' in identifier:
                identity=EmailIdentity.objects.select_related('user').filter(email=identifier.casefold()).first()
                identifier=identity.user.username if identity else identifier
            user=authenticate(request,username=identifier,password=request.POST.get('password',''))
            if user:
                attempt.failures=0;attempt.blocked_until=None;attempt.save();login(request,user)
                member=Membership.objects.filter(user=user,workspace__is_demo=False).first()
                return redirect('onboarding' if member and not member.workspace.onboarding_complete and not Project.objects.filter(workspace=member.workspace).exists() else 'dashboard')
            attempt.failures=attempt.failures+1 if timezone.now()-attempt.updated_at<timedelta(minutes=10) else 1
            if attempt.failures>=8:attempt.blocked_until=timezone.now()+timedelta(minutes=10)
            attempt.save();messages.error(request,'账号或密码不正确。')
    return page(request,'login.html')

@require_POST
def logout_view(request):logout(request);return redirect('login')

@workspace_view()
def dashboard(request):
    today=timezone.localdate();contents=Content.objects.filter(source__project__workspace=request.ws)
    ev=Event.objects.filter(project__workspace=request.ws).annotate(item_count=Count('items'))
    from .onboarding import result_summary
    current=Project.objects.filter(workspace=request.ws).order_by('-created_at').first()
    source_qs=Source.objects.filter(project__workspace=request.ws)
    return page(request,'dashboard.html',{'title':'工作台','today_count':contents.filter(fetched_at__date=today,relevant=True).count(),'demo_count':contents.filter(is_demo=True).count(),'review_count':ev.filter(risk__in=['需要关注','紧急核实'],review_status='待审核').count(),'pending_count':ev.exclude(handling='已处理').exclude(review_status='已忽略').count(),'events':ev.exclude(review_status='已忽略').order_by('-last_seen')[:5],'sources':source_qs.select_related('project')[:8],'latest_report':Report.objects.filter(project__workspace=request.ws).order_by('-created_at').first(),'worker':Heartbeat.objects.filter(name='worker',updated_at__gte=timezone.now()-timedelta(seconds=90)).exists(),'current_project':current,'first_result':result_summary(current) if current else None,'has_sources':source_qs.exclude(kind='demo').exists(),'monitoring':monitor_status_data(request.ws)})

def monitor_status_data(workspace):
    jobs=Job.objects.filter(workspace=workspace,kind__in=['collect','analyze'],status__in=['pending','running'])
    last=Workspace.objects.filter(pk=workspace.pk).values_list('monitor_requested_at',flat=True).first()
    remaining=max(0,math.ceil(60-(timezone.now()-last).total_seconds())) if last else 0
    return {'queued':jobs.filter(status='pending').count(),'running':jobs.filter(status='running').count(),'active':jobs.exists(),'cooldown_seconds':remaining}

@workspace_view()
def monitor_status(request):
    response=JsonResponse(monitor_status_data(request.ws))
    response['Cache-Control']='no-store'
    return response

@require_POST
@workspace_view(write=True)
def monitor_now(request):
    sources=Source.objects.filter(project__workspace=request.ws,project__active=True,enabled=True,kind__in=['rss','newsnow','search'])
    if not sources.exists():
        messages.warning(request,'当前没有可检索的已启用来源。请先在信息来源库添加来源，并启用对应监测项目。')
        return redirect('dashboard')
    now=timezone.now()
    claimed=Workspace.objects.filter(pk=request.ws.pk).filter(Q(monitor_requested_at__isnull=True)|Q(monitor_requested_at__lte=now-timedelta(seconds=60))).update(monitor_requested_at=now)
    if not claimed:
        seconds=monitor_status_data(request.ws)['cooldown_seconds']
        messages.warning(request,f'每分钟只能立即检索一次，请等待 {seconds} 秒后重试。')
        return redirect('dashboard')
    queued=existing=0
    for source in sources:
        job=Job.objects.filter(workspace=request.ws,kind='collect',payload__source_id=source.pk,status__in=['pending','running']).first()
        if job:
            if job.status=='pending':
                job.payload={**job.payload,'force':True};job.save(update_fields=['payload'])
            existing+=1
            continue
        svc.enqueue(request.ws,'collect',f'collect-now:{source.pk}:{int(timezone.now().timestamp())//30}',{'source_id':source.pk,'force':True})
        queued+=1
    if queued or existing:
        record(request,'立即检索',f'新增 {queued} 个来源任务，复用 {existing} 个进行中任务')
        messages.success(request,f'已触发本次舆情监测：{queued} 个来源已排队，{existing} 个来源正在处理中。采集后将自动分析，结果会更新到工作台。')
    else:
        messages.warning(request,'当前没有可检索的已启用来源。请先在信息来源库添加来源，并启用对应监测项目。')
    return redirect('dashboard')

@workspace_view()
def projects(request):return page(request,'projects.html',{'title':'监测项目','projects':Project.objects.filter(workspace=request.ws).annotate(content_count=Count('source__content',distinct=True),event_count=Count('event',distinct=True))})

@workspace_view(write=True)
def project_edit(request,pk=None):
    instance=get_object_or_404(Project,pk=pk,workspace=request.ws) if pk else None
    form=ProjectForm(request.POST or None,instance=instance)
    if request.method=='POST' and form.is_valid():
        project=form.save(commit=False);project.workspace=request.ws;project.save();record(request,'保存项目',project.name);messages.success(request,'项目已保存。新内容将按当前规则分析。');return redirect('projects')
    return page(request,'form.html',{'title':'编辑监测项目' if pk else '创建监测项目','form':form,'hint':'别名与排除词用逗号或换行分隔。停用后不再自动采集，已有数据保留。'})

@workspace_view()
def sources(request):
    form=SourceForm(request.POST or None,workspace=request.ws)
    if request.method=='POST' and form.is_valid():
        try:
            svc.public_url(form.cleaned_data['url'])
            source=Source.objects.create(**form.cleaned_data)
            svc.enqueue(request.ws,'collect',f'collect-manual:{uuid.uuid4().hex}',{'source_id':source.pk});record(request,'新增 RSS 来源',source.name);messages.success(request,'来源已添加，采集任务已排队。');return redirect('sources')
        except svc.RemoteError as exc:form.add_error('url',str(exc))
    return page(request,'sources.html',{'title':'数据源状态','sources':Source.objects.filter(project__workspace=request.ws).select_related('project'),'runs':SourceRun.objects.filter(source__project__workspace=request.ws).select_related('source').order_by('-started_at')[:15],'form':form})

@require_POST
@workspace_view(write=True)
def source_collect(request,pk):
    source=get_object_or_404(Source,pk=pk,project__workspace=request.ws,kind__in=['rss','newsnow','search'])
    if not source.enabled or not source.project.active:messages.error(request,'请先启用来源和监测项目。')
    else:svc.enqueue(request.ws,'collect',f'collect-manual:{uuid.uuid4().hex}',{'source_id':source.pk,'force':True});messages.success(request,'完整读取任务已排队，将重新检查摘要与订阅正文。')
    return redirect('sources')

@require_POST
@workspace_view(write=True)
def source_toggle(request,pk):
    source=get_object_or_404(Source,pk=pk,project__workspace=request.ws,kind__in=['rss','newsnow','search']);source.enabled=not source.enabled;source.save();record(request,'来源启停',source.name);return redirect('sources')

@workspace_view()
def import_view(request):
    form=ImportForm(request.POST or None,request.FILES or None,workspace=request.ws)
    if request.method=='POST' and form.is_valid():
        upload=form.cleaned_data['file']
        try:
            rows=svc.parse_import(upload.read(5*1024*1024+1),upload.name)
            source,_=Source.objects.get_or_create(project=form.cleaned_data['project'],kind='import',name=form.cleaned_data['source_name'],defaults={'enabled':False,'status':'文件导入'})
            stats={};added=svc.ingest(source,rows,stats=stats);updated=stats.get('updated',0);SourceRun.objects.create(source=source,status='成功',fetched=len(rows),inserted=added,updated=updated)
            record(request,'导入内容',f'{source.name}：新增{added}条，更新{updated}条');messages.success(request,f'导入完成：新增 {added} 条，更新 {updated} 条，重复 {len(rows)-added-updated} 条。后台正在分析。');return redirect('contents')
        except ValueError as exc:form.add_error('file',str(exc))
    return page(request,'form.html',{'title':'导入内容','form':form,'hint':'支持 UTF-8 CSV/JSON，必需字段 title；可选 external_id、text、url、published_at、level。整批校验后入库，不会半途导入。','import_template':True})

@workspace_view()
def import_template(request):
    response=HttpResponse('\ufefftitle,text,url,published_at,external_id\r\n品牌名称与标题,反馈正文,,2026-10-17T10:00:00+08:00,example-001\r\n',content_type='text/csv; charset=utf-8');response['Content-Disposition']='attachment; filename="argus-import-template.csv"';return response

@workspace_view()
def contents(request):
    query=Content.objects.filter(source__project__workspace=request.ws).select_related('source__project','event_item__event').order_by('-fetched_at')
    q=request.GET.get('q','')[:200];status=request.GET.get('status','');project=request.GET.get('project','')
    if q:query=query.filter(Q(title__icontains=q)|Q(text__icontains=q))
    if status=='related':query=query.filter(relevant=True)
    elif status=='negative':query=query.filter(relevant=True,sentiment='负面线索')
    elif status=='pending':query=query.filter(analysis_mode='待分析')
    if project.isdigit():query=query.filter(source__project_id=int(project))
    stream=request.GET.get('stream','');level=request.GET.get('level','')
    if stream in ['rss','newsnow','import','search']:query=query.filter(source__kind=stream)
    if level in ['title','summary','fulltext']:query=query.filter(level=level)
    latest=ContentObservation.objects.filter(content=OuterRef('pk'))
    query=query.annotate(latest_rank=Subquery(latest.values('rank')[:1]),sample_count=Count('observations'))
    return page(request,'contents.html',{'title':'内容监测','items':page_items(request,query),'q':q,'status':status,'projects':Project.objects.filter(workspace=request.ws),'selected_project':project,'stream':stream,'level':level})

@workspace_view()
def content_detail(request,pk):
    content=get_object_or_404(Content.objects.select_related('source__project','event_item__event'),pk=pk,source__project__workspace=request.ws)
    return page(request,'content_detail.html',{'title':'内容与传播记录','content':content,'observations':content.observations.all()[:100],'observation_count':content.observations.count()})

@require_POST
@workspace_view(write=True)
def feedback(request,pk):
    content=get_object_or_404(Content,pk=pk,source__project__workspace=request.ws)
    action=request.POST.get('action')
    if action=='irrelevant':
        content.feedback='无关';content.relevant=False;content.reason='人工标记为无关';content.save()
        related=EventItem.objects.filter(content=content).first()
        if related:
            ev=related.event;related.delete()
            if not ev.items.exists():ev.review_status='已忽略';ev.save()
        record(request,'相关性纠正',f'内容 {pk} 标为无关');messages.success(request,'已标为无关，事件关联同步更新。')
    elif action=='reanalyze':
        content.feedback='';content.save(update_fields=['feedback']);svc.enqueue(request.ws,'analyze',f'reanalyze:{pk}:{uuid.uuid4().hex}',{'content_id':pk});messages.success(request,'重新分析已排队。')
    return redirect('contents')

@workspace_view()
def events(request):
    query=Event.objects.filter(project__workspace=request.ws).select_related('project').annotate(item_count=Count('items')).exclude(review_status='已忽略').order_by('-last_seen')
    if request.GET.get('status')=='pending':query=query.exclude(handling='已处理')
    return page(request,'events.html',{'title':'事件中心','items':page_items(request,query)})

@workspace_view()
def event_detail(request,pk):
    event=get_object_or_404(Event.objects.select_related('project'),pk=pk,project__workspace=request.ws)
    return page(request,'event.html',{'title':'事件详情','event':event,'evidence':event.items.select_related('content__source'),'logs':AuditLog.objects.filter(workspace=request.ws,detail__startswith=f'事件#{pk} ').order_by('-created_at')[:10],'deliveries':Delivery.objects.filter(workspace=request.ws,event=event).order_by('-created_at')})

@require_POST
@workspace_view(write=True)
def event_action(request,pk):
    event=get_object_or_404(Event,pk=pk,project__workspace=request.ws);action=request.POST.get('action')
    with transaction.atomic():
        if action=='approve':
            risk=request.POST.get('risk',event.risk)
            if risk not in ['一般信息','需要关注','紧急核实']:return HttpResponseForbidden('风险等级无效')
            if event.risk!=risk:event.revision+=1
            event.risk=risk;event.review_status='审核通过';event.save();delivery=svc.make_delivery(event)
            messages.success(request,'审核已通过。'+('体验空间不会发送真实通知。' if request.ws.is_demo else '通知已进入队列，具体结果请查看通知记录。' if delivery else '未达到当前提醒门槛，保留在日报中。'))
        elif action=='withdraw':
            event.review_status='待审核';event.save();Delivery.objects.filter(event=event,status__in=['待发送','免打扰延后','待验证','通知已暂停','待审核']).update(status='已取消');event.revision+=1;event.save();messages.success(request,'已撤回审核；已发送消息无法撤回。')
        elif action in ['handle','reopen']:
            event.handling='已处理' if action=='handle' else '待处理';event.note=request.POST.get('note','')[:2000];event.save();messages.success(request,'处理状态已更新。')
        elif action=='ignore':
            event.review_status='已忽略';event.save();messages.success(request,'事件已忽略，未发送的消息将停止发送。')
        elif action=='split':
            if not str(request.POST.get('item_id','')).isdigit():return HttpResponseForbidden('证据编号无效')
            item=get_object_or_404(EventItem,event=event,pk=request.POST.get('item_id'))
            if event.items.count()<2:messages.error(request,'只有一条证据，无需拆分。')
            else:
                new=Event.objects.create(project=event.project,key='split:'+uuid.uuid4().hex,title=item.content.title[:300],category=event.category,summary='人工拆分的独立事件，请重新核实。',risk=event.risk)
                item.event=new;item.save();messages.success(request,'已拆为独立事件，需重新审核。')
        else:return HttpResponseForbidden('操作无效')
        record(request,'事件操作',f'事件#{pk} {action} {event.note[:100]}')
    return redirect('event_detail',pk=pk)

@workspace_view()
def review(request):return page(request,'review.html',{'title':'审核与通知','events':Event.objects.filter(project__workspace=request.ws,review_status='待审核',risk__in=['需要关注','紧急核实']).select_related('project').annotate(item_count=Count('items')).order_by('-last_seen')})

@workspace_view()
def notifications(request):
    config,_=NotificationConfig.objects.get_or_create(workspace=request.ws)
    initial={f:getattr(config,f) for f in ['group_name','enabled','threshold','quiet','quiet_start','quiet_end','daily_time','push_interval_minutes']}
    form=NotificationForm(request.POST or None,initial=initial)
    if request.method=='POST':
        if request.member.role!='admin':return HttpResponseForbidden('仅管理员可修改通知配置')
        if form.is_valid():
            data=form.cleaned_data.copy();webhook=data.pop('webhook')
            if webhook:
                p=urlsplit(webhook)
                if p.scheme!='https' or p.hostname!='qyapi.weixin.qq.com' or p.path!='/cgi-bin/webhook/send' or p.port not in (None,443) or p.username or p.password or not re.fullmatch(r'key=[A-Za-z0-9_-]{8,100}',p.query):form.add_error('webhook','仅支持企业微信官方机器人 Webhook 地址')
            if not form.errors:
                changed=bool(webhook) or config.group_name!=data['group_name']
                if webhook:config.webhook_cipher=svc.encrypt(webhook)
                if changed:config.verified=False;config.test_accepted=False;config.version+=1
                for key,value in data.items():setattr(config,key,value)
                config.save();record(request,'保存微信通知配置','凭证不记录');messages.success(request,'配置已保存。'+('接收目标已变更，请重新测试验证。' if changed else ''));return redirect('notifications')
    return page(request,'notifications.html',{'title':'微信通知','form':form,'config':config,'deliveries':Delivery.objects.filter(workspace=request.ws).order_by('-created_at')[:30],'quiet_active':svc.quiet_now(config)})

@require_POST
@workspace_view(write=True)
def notification_action(request,pk):
    action=request.POST.get('action');config,_=NotificationConfig.objects.get_or_create(workspace=request.ws)
    if action in ['test','verify']:
        if request.member.role!='admin':return HttpResponseForbidden('仅管理员可测试和验证目标')
        if action=='verify':
            if config.test_accepted:config.verified=True;config.save();record(request,'确认测试消息已收到');messages.success(request,'目标已验证。启用通知后将按规则发送。')
            else:messages.error(request,'请先成功发送测试通知。')
        elif not config.webhook_cipher:messages.error(request,'请先保存机器人 Webhook。')
        elif Delivery.objects.filter(workspace=request.ws,kind='测试通知',created_at__gte=timezone.now()-timedelta(seconds=30)).exists():messages.error(request,'请等待 30 秒后再测试。')
        else:
            delivery=Delivery.objects.create(workspace=request.ws,key='test:'+uuid.uuid4().hex,kind='测试通知',target_name=config.group_name,target_version=config.version,body='[Argus 测试通知] 这是一条由管理员主动发送的测试消息，不代表存在真实舆情事件。')
            delivery.status='发送中';delivery.attempts=1;delivery.save()
            try:svc.wework_post(config,delivery.body);delivery.status='接口已接收';config.test_accepted=True;config.verified=False;config.save();messages.success(request,'接口已接收测试消息，请在群内核对后点击确认收到。')
            except svc.UncertainSend:delivery.status='结果未知';delivery.error='请求超时，请核对群消息';messages.error(request,delivery.error)
            except Exception:delivery.status='发送失败';delivery.error='接口拒绝或配置错误，请检查 Webhook 和网络';messages.error(request,delivery.error)
            delivery.save();record(request,'主动发送测试通知',delivery.status)
    else:
        delivery=get_object_or_404(Delivery,pk=pk,workspace=request.ws)
        if action=='confirm' and delivery.status=='结果未知':delivery.status='人工确认已收到';delivery.save();messages.success(request,'已记录人工确认，不表示群成员已读。')
        elif action in ['retry','resend'] and delivery.status in ['发送失败','结果未知','目标已变更','待验证','通知已暂停']:
            if delivery.target_version!=config.version:messages.error(request,'目标版本已经变更，不能把旧消息自动改发到新群。请重新审核事件。')
            elif delivery.status=='结果未知' and request.POST.get('confirm_duplicate')!='yes':messages.error(request,'结果未知可能已经送达，补发前必须勾选确认重复风险。')
            elif not config.enabled or not config.verified:messages.error(request,'请先启用并验证接收目标。')
            else:
                delivery.status='待发送';delivery.error='';delivery.save();svc.enqueue(request.ws,'deliver','retry-delivery:'+uuid.uuid4().hex,{'delivery_id':delivery.pk});messages.success(request,'已重新排队。')
        record(request,'通知记录操作',f'记录#{delivery.pk} {action}')
    return redirect('notifications')

@workspace_view()
def reports(request):
    if request.method=='POST':
        project=get_object_or_404(Project,pk=request.POST.get('project'),workspace=request.ws)
        svc.enqueue(request.ws,'report','report-manual:'+uuid.uuid4().hex,{'project_id':project.pk});messages.success(request,'报告生成已排队，稍后刷新。');return redirect('reports')
    return page(request,'reports.html',{'title':'监测报告','reports':Report.objects.filter(project__workspace=request.ws).select_related('project').order_by('-created_at')[:50],'projects':Project.objects.filter(workspace=request.ws)})

@workspace_view()
def report_detail(request,pk):
    report=get_object_or_404(Report,pk=pk,project__workspace=request.ws)
    return page(request,'report.html',{'title':'日报详情','report':report,'snapshot':report.snapshot})

def csv_safe(value):
    text=str(value or '')
    return "'"+text if text.startswith(('\t','\r','\n')) or text.lstrip().startswith(('=','+','-','@')) else text

@workspace_view()
def report_csv(request,pk):
    report=get_object_or_404(Report,pk=pk,project__workspace=request.ws)
    response=HttpResponse(content_type='text/csv; charset=utf-8');response['Content-Disposition']=f'attachment; filename="argus-report-{pk}.csv"';response.write('\ufeff');writer=csv.writer(response)
    writer.writerow(['项目','日期','报告修订版','事件','风险','证据标题','来源','证据级别','原文','演示数据'])
    for event in report.snapshot['events']:
        for evidence in event['evidence']:writer.writerow([csv_safe(x) for x in [report.snapshot['brand'],report.date,report.revision,event['title'],event['risk'],evidence['title'],evidence['source'],evidence['level'],evidence['url'],'是' if evidence['demo'] else '否']])
    return response

@workspace_view(admin=True)
def settings_view(request):
    config,_=AIConfig.objects.get_or_create(workspace=request.ws)
    ai_form=AIForm(initial={'enabled':config.enabled,'api_base':config.api_base,'model':config.model,'daily_limit':config.daily_limit});member_form=MemberForm()
    if request.method=='POST':
        if request.POST.get('section')=='ai':
            ai_form=AIForm(request.POST)
            if ai_form.is_valid():
                data=ai_form.cleaned_data
                try:
                    if data['enabled']:
                        svc.public_url(data['api_base'],https_only=True)
                        if not data['model'] or not (data['api_key'] or config.key_cipher):raise ValueError('启用 AI 时必须填写模型和 API Key')
                    config.enabled=data['enabled'];config.api_base=data['api_base'];config.model=data['model'];config.daily_limit=data['daily_limit']
                    if data['api_key']:config.key_cipher=svc.encrypt(data['api_key'])
                    config.save();record(request,'保存 AI 配置','密钥不记录');messages.success(request,'AI 配置已保存。未开启或接口失败时将明确标记为规则辅助分析。');return redirect('settings')
                except (ValueError,svc.RemoteError) as exc:ai_form.add_error(None,str(exc))
        elif request.POST.get('section')=='member':
            member_form=MemberForm(request.POST)
            if member_form.is_valid():
                data=member_form.cleaned_data
                try:
                    validate_password(data['password'])
                    if User.objects.filter(username=data['username']).exists():raise ValueError('该账号已存在，请使用其他账号')
                    with transaction.atomic():
                        user=User.objects.create_user(username=data['username'],password=data['password']);Membership.objects.create(user=user,workspace=request.ws,role=data['role'])
                    record(request,'创建空间成员',data['username']);messages.success(request,'成员已创建，请单独告知初始密码。');return redirect('settings')
                except (ValueError,ValidationError) as exc:member_form.add_error(None,str(exc))
    return page(request,'settings.html',{'title':'空间设置','ai_form':ai_form,'member_form':member_form,'config':config,'members':Membership.objects.filter(workspace=request.ws).select_related('user'),'analysis_count':AnalysisRun.objects.filter(content__source__project__workspace=request.ws,created_at__date=timezone.localdate()).count()})

@workspace_view()
def password_change(request):
    if request.method=='POST':
        if not request.user.check_password(request.POST.get('old','')):messages.error(request,'原密码不正确。')
        elif request.POST.get('new')!=request.POST.get('confirm'):messages.error(request,'两次新密码不一致。')
        else:
            try:
                validate_password(request.POST.get('new',''),request.user);request.user.set_password(request.POST['new']);request.user.save();update_session_auth_hash(request,request.user);record(request,'修改登录密码');messages.success(request,'密码已修改。');return redirect('dashboard')
            except ValidationError as exc:messages.error(request,'；'.join(exc.messages))
    return page(request,'password.html',{'title':'修改密码'})

@workspace_view(admin=True)
def operations(request):return page(request,'operations.html',{'title':'运行状态','jobs':Job.objects.filter(workspace=request.ws).order_by('-created_at')[:60],'heartbeats':Heartbeat.objects.all(),'audit_logs':AuditLog.objects.filter(workspace=request.ws).order_by('-created_at')[:30]})

@require_POST
@workspace_view(admin=True)
def job_retry(request,pk):
    job=get_object_or_404(Job,pk=pk,workspace=request.ws,status='failed');job.status='pending';job.attempts=0;job.run_after=timezone.now();job.save();record(request,'重试失败任务',f'任务#{pk}');messages.success(request,'任务已重新排队。');return redirect('operations')

@require_POST
@workspace_view()
def demo(request):
    from .onboarding import demo_enter
    return demo_enter(request)

def health(request):return JsonResponse({'status':'ok','application':'Argus','version':'1.6.0'})
