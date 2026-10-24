"""One-off keyword queries: no permanent project or notification side effects."""
from datetime import timedelta
from types import SimpleNamespace
from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Q,F
from django.http import JsonResponse,HttpResponseForbidden
from django.shortcuts import redirect,get_object_or_404
from django.utils import timezone
from .models import KeywordRun,Content,Workspace,SearchProviderConfig
from .search_sources import PROVIDERS,SCOPES,fetch_items
from .views import workspace_view,page,record

class QuickSearchForm(forms.Form):
    keyword=forms.CharField(label='检索关键词',min_length=2,max_length=100,widget=forms.TextInput(attrs={'placeholder':'例如：品牌名称、产品名、行业话题','autofocus':True}))
    mode=forms.ChoiceField(label='检索方式',choices=[('local','已采集内容检索 · 免费'),('live','联网即时检索 · 使用已配置搜索服务')])
    provider=forms.ChoiceField(label='联网搜索服务',choices=[],required=False)
    scope=forms.ChoiceField(label='联网范围',choices=[(k,v[0]) for k,v in SCOPES.items()],initial='web')
    def __init__(self,*args,workspace,**kwargs):
        super().__init__(*args,**kwargs);self.workspace=workspace
        configured=SearchProviderConfig.objects.filter(workspace=workspace,enabled=True).exclude(key_cipher='').values_list('provider',flat=True)
        self.fields['provider'].choices=[('','请选择已启用的服务')]+[(k,PROVIDERS[k][0]) for k in configured if k in PROVIDERS]
    def clean(self):
        data=super().clean()
        if data.get('mode')=='live' and not data.get('provider'):self.add_error('provider','请先在“关键词检索来源”中启用并配置一个搜索服务')
        return data

def execute(run):
    from .services import RemoteError
    if run.status=='running':
        KeywordRun.objects.filter(pk=run.pk,status='running').update(status='failed',error='上次检索进程中断，未自动重复调用。请确认服务商用量后重新检索。',finished_at=timezone.now())
        return
    if run.status!='pending':return
    if not KeywordRun.objects.filter(pk=run.pk,status='pending').update(status='running'):return
    try:
        if run.mode=='live':
            proxy=SimpleNamespace(project=SimpleNamespace(workspace=run.workspace,name=run.keyword,aliases=''),search_config={'provider':run.provider,'scope':run.scope,'query':run.keyword})
            rows=fetch_items(proxy)
            results=[{'title':r['title'],'text':r['text'][:1000],'url':r['url'],'source':PROVIDERS[run.provider][0],'level':'搜索摘要' if r['text'] else '仅标题','time':str(r.get('published_at') or '')[:100]} for r in rows]
        else:
            contents=Content.objects.filter(source__project__workspace=run.workspace,is_demo=False).filter(Q(title__icontains=run.keyword)|Q(text__icontains=run.keyword)).select_related('source').order_by('-fetched_at')[:100]
            results=[{'title':c.title,'text':c.text[:1000],'url':f'/contents/{c.pk}/','source':c.source.name,'level':c.level_label,'time':timezone.localtime(c.fetched_at).strftime('%m-%d %H:%M')} for c in contents]
        KeywordRun.objects.filter(pk=run.pk).update(status='succeeded',results=results,error='',finished_at=timezone.now())
    except Exception as exc:
        error=str(exc)[:280] if isinstance(exc,RemoteError) else '本次检索失败，请检查来源配置后重试。'
        KeywordRun.objects.filter(pk=run.pk).update(status='failed',error=error,finished_at=timezone.now())

@workspace_view(write=True)
def quick_search(request,pk=None):
    from . import services as svc
    if request.ws.is_demo:return HttpResponseForbidden('请退出演示空间后使用关键词即时检索。')
    run=get_object_or_404(KeywordRun,pk=pk,workspace=request.ws) if pk else None
    initial={'keyword':run.keyword,'mode':run.mode,'provider':run.provider,'scope':run.scope} if run else {'mode':'local','scope':'web'}
    form=QuickSearchForm(request.POST or None,workspace=request.ws,initial=initial)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        with transaction.atomic():
            Workspace.objects.filter(pk=request.ws.pk).update(name=F('name'))
            previous=KeywordRun.objects.filter(workspace=request.ws,created_at__gt=timezone.now()-timedelta(seconds=60)).first()
            if previous:
                messages.warning(request,'每分钟可提交一次关键词即时检索，请稍后重试。')
                return redirect('quick_search_run',pk=previous.pk)
            run=KeywordRun.objects.create(workspace=request.ws,keyword=d['keyword'],mode=d['mode'],provider=d.get('provider') or '',scope=d['scope'])
            svc.enqueue(request.ws,'keyword','keyword:'+str(run.pk),{'run_id':run.pk},run_after=timezone.now()-timedelta(days=1))
            record(request,'关键词即时检索',d['keyword']+' · '+d['mode'])
        return redirect('quick_search_run',pk=run.pk)
    return page(request,'quick_search.html',{'title':'关键词即时检索','form':form,'run':run,'history':KeywordRun.objects.filter(workspace=request.ws).order_by('-created_at')[:8]})

@workspace_view(write=True)
def quick_search_status(request,pk):
    run=get_object_or_404(KeywordRun,pk=pk,workspace=request.ws)
    response=JsonResponse({'status':run.status,'results':run.results,'error':run.error,'mode':run.mode,'keyword':run.keyword,'count':len(run.results)})
    response['Cache-Control']='no-store';return response
