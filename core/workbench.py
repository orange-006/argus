"""Workspace-scoped history maintenance and read-only monitoring screen."""
from datetime import timedelta
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Count,F
from django.http import JsonResponse,HttpResponseForbidden
from django.shortcuts import redirect,get_object_or_404
from django.utils import timezone
from .models import Content,Event,Report,SourceRun,Source,Project,Job,Workspace,AnalysisRun,Delivery,Heartbeat
from .views import workspace_view,page,record

TERMINAL=['接口已接收','人工确认已收到','已取消','未达提醒门槛','体验空间不发送']

def history_queries(ws,before):
    protected=Delivery.objects.filter(workspace=ws).exclude(status__in=TERMINAL)
    content=Content.objects.filter(source__project__workspace=ws,fetched_at__lt=before)
    protected_events=protected.filter(event_id__isnull=False).values('event_id')
    protected_reports=protected.filter(report_id__isnull=False).values('report_id')
    content=content.exclude(event_item__event_id__in=protected_events).exclude(pk__in=AnalysisRun.objects.filter(created_at__date=timezone.localdate()).values('content_id'))
    events=Event.objects.filter(project__workspace=ws,last_seen__lt=before).exclude(pk__in=protected_events).exclude(items__content__in=Content.objects.filter(source__project__workspace=ws).exclude(pk__in=content.values('pk')))
    reports=Report.objects.filter(project__workspace=ws,created_at__lt=before).exclude(pk__in=protected_reports)
    runs=SourceRun.objects.filter(source__project__workspace=ws,started_at__lt=before).exclude(status='运行中')
    return content,events,reports,runs

@workspace_view(admin=True)
def clear_history(request):
    if request.ws.is_demo:return HttpResponseForbidden('演示空间不清理真实历史。')
    days=request.GET.get('days','30')
    if days not in ['7','30','90','all']:days='30'
    before=timezone.now() if days=='all' else timezone.now()-timedelta(days=int(days))
    if request.method=='POST':
        try:
            data=signing.loads(request.POST.get('token',''),salt='argus-history',max_age=600)
            if data['ws']!=request.ws.pk or data['user']!=request.user.pk:raise ValueError()
            before=timezone.datetime.fromisoformat(data['before'])
        except (signing.BadSignature,ValueError,KeyError,TypeError):
            messages.error(request,'清理预览已过期或无效，请重新确认范围。');return redirect('clear_history')
        if request.POST.get('confirmation','').strip()!='清除历史记录':
            messages.error(request,'请输入“清除历史记录”确认操作。');return redirect('clear_history')
        with transaction.atomic():
            # Acquire the SQLite write lock before checking workers and deleting.
            Workspace.objects.filter(pk=request.ws.pk).update(name=F('name'))
            if Job.objects.filter(workspace=request.ws,status='running').exists():
                messages.error(request,'当前有后台任务正在处理，请待本轮任务完成后再清理。');return redirect('clear_history')
            content,events,reports,runs=history_queries(request.ws,before)
            event_ids=list(events.values_list('pk',flat=True))
            count=content.count()
            Job.objects.filter(workspace=request.ws,kind='analyze',payload__content_id__in=content.values('pk')).exclude(status='running').delete()
            content.delete()
            Event.objects.filter(project__workspace=request.ws,pk__in=event_ids,items__isnull=True).delete()
            reports.delete();runs.delete()
            record(request,'清除监测历史',f'清理截止 {before.isoformat()}，内容 {count} 条；保留配置与微信发送记录')
        messages.success(request,f'历史清理完成，已删除 {count} 条监测内容。后续采集会继续产生新记录。')
        return redirect('dashboard')
    queries=history_queries(request.ws,before)
    counts=dict(zip(['contents','events','reports','runs'],[q.count() for q in queries]))
    token=signing.dumps({'ws':request.ws.pk,'user':request.user.pk,'before':before.isoformat()},salt='argus-history')
    return page(request,'clear_history.html',{'title':'清除历史记录','days':days,'before':before,'counts':counts,'token':token,'busy':Job.objects.filter(workspace=request.ws,status='running').exists()})

def screen_data(request):
    project_id=request.GET.get('project','')
    projects=Project.objects.filter(workspace=request.ws)
    if project_id:
        project=get_object_or_404(projects,pk=project_id) if project_id.isdigit() else get_object_or_404(projects,pk=0)
        projects=projects.filter(pk=project.pk)
    contents=Content.objects.filter(source__project__in=projects,is_demo=request.ws.is_demo)
    events=Event.objects.filter(project__in=projects).exclude(review_status='已忽略')
    sources=Source.objects.filter(project__in=projects,enabled=True,project__active=True).exclude(kind__in=['demo','import'])
    today=timezone.localdate();now=timezone.now();related=contents.filter(relevant=True)
    trend=[]
    for offset in range(6,-1,-1):
        day=today-timedelta(days=offset);daily=related.filter(fetched_at__date=day)
        trend.append({'date':day.strftime('%m-%d'),'total':daily.count(),'negative':daily.filter(sentiment='负面线索').count()})
    healthy=failed=waiting=0;signals=[]
    for source in sources:
        if source.status=='采集失败':failed+=1
        elif source.last_success and source.last_success>=now-timedelta(minutes=max(5,source.interval_minutes*2)):healthy+=1
        else:waiting+=1
        if len(signals)<12:signals.append({'name':source.name,'status':source.status,'time':timezone.localtime(source.last_success).strftime('%H:%M') if source.last_success else '尚无成功记录'})
    distribution=list(related.filter(fetched_at__date=today).values('source__name').annotate(count=Count('pk')).order_by('-count')[:7])
    return {'workspace':request.ws.name,'demo':request.ws.is_demo,'updated':timezone.localtime(now).strftime('%Y-%m-%d %H:%M:%S'),
      'metrics':{'fetched':contents.filter(fetched_at__date=today).count(),'related':related.filter(fetched_at__date=today).count(),'negative':related.filter(fetched_at__date=today,sentiment='负面线索').count(),'review':events.filter(review_status='待审核',risk__in=['需要关注','紧急核实']).count()},
      'trend':trend,'signals':signals,'sources':{'total':sources.count(),'healthy':healthy,'failed':failed,'waiting':waiting},
      'worker':Heartbeat.objects.filter(name='worker',updated_at__gte=now-timedelta(seconds=90)).exists(),
      'distribution':[{'name':row['source__name'],'count':row['count']} for row in distribution],
      'events':[{'title':e.title,'risk':e.risk,'project':e.project.name,'status':e.review_status,'time':timezone.localtime(e.last_seen).strftime('%m-%d %H:%M'),'url':f'/events/{e.pk}/'} for e in events.select_related('project').order_by('-last_seen')[:8]]}

@workspace_view()
def monitoring_screen(request):
    return page(request,'screen.html',{'data':screen_data(request),'projects':Project.objects.filter(workspace=request.ws),'selected_project':request.GET.get('project','')})

@workspace_view()
def monitoring_screen_status(request):
    response=JsonResponse(screen_data(request));response['Cache-Control']='no-store';return response
