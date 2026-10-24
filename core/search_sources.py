"""Original API adapters: public indexed pages, never platform-private crawling."""
import json
from urllib.parse import urlencode,urlsplit
from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone
from .models import Project,Source,SearchProviderConfig,Job
from .streams import clean,safe_link
from .views import workspace_view,page,record

PROVIDERS={
 'tavily':('Tavily 网页检索','https://api.tavily.com/search','https://docs.tavily.com/documentation/api-reference/endpoint/search'),
 'bocha':('博查中文网页检索','https://api.bochaai.com/v1/web-search','https://open.bochaai.com/'),
 'anspire':('安思派网页检索','https://plugin.anspire.cn/api/ntsearch/search','https://open.anspire.cn/quick'),
}
SCOPES={
 'web':('公开网页',()),'weibo':('微博公开网页',('weibo.com','weibo.cn')),
 'xhs':('小红书公开网页',('xiaohongshu.com',)),
 'douyin':('抖音公开网页',('douyin.com',)),
 'kuaishou':('快手公开网页',('kuaishou.com',)),
 'bilibili':('B站公开网页',('bilibili.com',)),
 'tieba':('贴吧公开网页',('tieba.baidu.com',)),
 'zhihu':('知乎公开网页',('zhihu.com',)),
}

def normalize_results(provider,payload,scope='web'):
    from .services import RemoteError
    if not isinstance(payload,dict):raise RemoteError('搜索接口返回格式错误')
    if payload.get('error') or payload.get('errors'):raise RemoteError('搜索接口返回错误，请检查服务账号权限和额度')
    if provider=='bocha':
        if payload.get('code',200) not in [200,0,'200']:raise RemoteError('搜索接口未返回成功状态，请检查账号额度与权限')
        data=payload.get('data')
        if not isinstance(data,dict):raise RemoteError('搜索接口缺少结果数据')
        rows=(data.get('webPages') or {}).get('value',[])
    else:rows=payload.get('results')
    if not isinstance(rows,list):raise RemoteError('搜索接口缺少可读取的结果列表')
    domains=SCOPES.get(scope,SCOPES['web'])[1]
    result=[]
    for row in rows[:20]:
        if not isinstance(row,dict):continue
        url=safe_link(row.get('url',''));title=clean(row.get('title') or row.get('name',''),1000)
        if not url or not title:continue
        host=(urlsplit(url).hostname or '').lower()
        if domains and not any(host==d or host.endswith('.'+d) for d in domains):continue
        text=clean(row.get('summary') or row.get('content') or row.get('snippet',''),20000)
        result.append({'external_id':url,'title':title,'text':text,'summary':text[:1500],'url':url,
          'published_at':row.get('published_date') or row.get('datePublished') or row.get('date'),
          'level':'summary' if text else 'title','text_origin':'web_search_snippet'})
    return result

def fetch_items(source):
    from . import services as svc
    provider=source.search_config.get('provider');scope=source.search_config.get('scope','web')
    if provider not in PROVIDERS or scope not in SCOPES:raise svc.RemoteError('搜索来源配置无效，请重新接入')
    config=SearchProviderConfig.objects.filter(workspace=source.project.workspace,provider=provider,enabled=True).first()
    if not config or not config.key_cipher:raise svc.RemoteError('关键词搜索尚未启用，请先配置对应搜索服务的 API Key')
    today=timezone.localdate()
    SearchProviderConfig.objects.filter(pk=config.pk).exclude(usage_date=today).update(usage_date=today,daily_used=0)
    if not SearchProviderConfig.objects.filter(pk=config.pk,enabled=True,usage_date=today,daily_used__lt=F('daily_limit')).update(daily_used=F('daily_used')+1):
        raise svc.RemoteError('今日搜索调用上限已达到，明天自动恢复；失败请求也计入本地上限')
    names=[source.project.name]+svc.words(source.project.aliases)[:3]
    query=source.search_config.get('query') or ' OR '.join('"'+n.replace('"',' ')+'"' for n in names)
    domains=SCOPES[scope][1]
    if domains:query+=' ('+' OR '.join('site:'+d for d in domains)+')'
    endpoint=PROVIDERS[provider][1]
    headers={'Authorization':'Bearer '+svc.decrypt(config.key_cipher),'Accept':'application/json'}
    if provider=='anspire':
        endpoint+='?'+urlencode({'query':query[:1000],'top_k':10,'Insite':','.join(domains)})
        status,_,raw=svc.remote(endpoint,headers=headers,redirects=0)
    else:
        payload={'query':query[:1000],'count':10,'summary':True,'freshness':'noLimit'} if provider=='bocha' else {'query':query[:1000],'max_results':10,'topic':'general','search_depth':'basic','include_answer':False}
        if provider=='tavily' and domains:payload['include_domains']=list(domains)
        status,_,raw=svc.remote(endpoint,'POST',headers=headers,payload=payload,redirects=0)
    if status!=200:raise svc.RemoteError(f'搜索服务返回 HTTP {status}，请检查密钥、服务权限和额度')
    try:data=json.loads(raw)
    except (ValueError,UnicodeDecodeError):raise svc.RemoteError('搜索服务返回无法解析的数据')
    return normalize_results(provider,data,scope)

class SearchSourceForm(forms.Form):
    project=forms.ModelChoiceField(queryset=Project.objects.none(),label='监测项目',required=False)
    provider=forms.ChoiceField(choices=[(k,v[0]) for k,v in PROVIDERS.items()],label='搜索服务')
    scope=forms.ChoiceField(choices=[(k,v[0]) for k,v in SCOPES.items()],label='检索范围')
    query=forms.CharField(label='检索词（可选）',max_length=500,required=False,help_text='留空使用项目名称和别名。填写后替代默认检索词。')
    api_key=forms.CharField(label='该搜索服务的 API Key（留空保留已存凭证）',max_length=500,required=False,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    daily_limit=forms.IntegerField(label='该服务每日最多调用次数（当前空间共享）',min_value=1,max_value=1000,initial=20,help_text='失败及重试请求也计数。本地调用次数上限不等于服务商费用上限；请同时限制服务商账号额度。')
    interval_minutes=forms.TypedChoiceField(label='关键词检索间隔',coerce=int,initial=60,choices=[(v,f'{v} 分钟') for v in [10,20,30,60,120]])
    enabled=forms.BooleanField(label='启用该服务并接入所选项目，保存后执行首次检索',required=False)
    def __init__(self,*args,workspace,**kwargs):
        super().__init__(*args,**kwargs);self.workspace=workspace
        self.fields['project'].queryset=Project.objects.filter(workspace=workspace,active=True)
    def clean_api_key(self):
        key=self.cleaned_data['api_key']
        if key and (len(key)<8 or any(c.isspace() for c in key)):raise forms.ValidationError('密钥格式不正确，请只填写 API Key，不要添加 Bearer 前缀或空格')
        return key
    def clean(self):
        data=super().clean()
        if data.get('enabled') and not data.get('project'):self.add_error('project','启用检索时请选择一个已启用的监测项目')
        provider=data.get('provider')
        if data.get('enabled') and not data.get('api_key') and not SearchProviderConfig.objects.filter(workspace=self.workspace,provider=provider).exclude(key_cipher='').exists():
            self.add_error('api_key','启用前需要填写对应服务的有效 API Key')
        return data

@workspace_view(admin=True)
def search_sources(request):
    from . import services as svc
    if request.ws.is_demo:return HttpResponseForbidden('体验空间不配置外部搜索服务，请先退出体验。')
    provider=request.GET.get('provider','tavily')
    initial={'provider':provider if provider in PROVIDERS else 'tavily'}
    config=SearchProviderConfig.objects.filter(workspace=request.ws,provider=initial['provider']).first()
    if config:initial.update(enabled=config.enabled,daily_limit=config.daily_limit)
    sources=Source.objects.filter(project__workspace=request.ws,kind='search').select_related('project')
    selected=sources.filter(search_config__provider=initial['provider'])
    if request.GET.get('project','').isdigit():selected=selected.filter(project_id=int(request.GET['project']))
    if request.GET.get('scope') in SCOPES:selected=selected.filter(search_config__scope=request.GET['scope'])
    source=selected.first()
    if source:initial.update(project=source.project_id,scope=source.search_config.get('scope','web'),query=source.search_config.get('query',''),interval_minutes=source.interval_minutes)
    form=SearchSourceForm(request.POST or None,workspace=request.ws,initial=initial)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        with transaction.atomic():
            config,_=SearchProviderConfig.objects.get_or_create(workspace=request.ws,provider=d['provider'])
            config.enabled=d['enabled'];config.daily_limit=d['daily_limit']
            if d['api_key']:config.key_cipher=svc.encrypt(d['api_key'])
            config.save()
            if not d['enabled']:
                Source.objects.filter(project__workspace=request.ws,kind='search',search_config__provider=d['provider']).update(enabled=False)
            else:
                source,_=Source.objects.update_or_create(project=d['project'],preset_key='search-'+d['provider']+'-'+d['scope'],defaults={
                 'kind':'search','name':PROVIDERS[d['provider']][0]+' · '+SCOPES[d['scope']][0],'url':PROVIDERS[d['provider']][1],
                 'enabled':True,'interval_minutes':d['interval_minutes'],'search_config':{'provider':d['provider'],'scope':d['scope'],'query':d['query']}})
                if not Job.objects.filter(workspace=request.ws,kind='collect',payload__source_id=source.pk,status__in=['pending','running']).exists():
                    svc.enqueue(request.ws,'collect','search-connect:'+str(source.pk)+':'+str(timezone.now().timestamp()),{'source_id':source.pk,'force':True})
        record(request,'保存关键词搜索配置','服务：'+d['provider']+'；密钥不记录')
        messages.success(request,'配置已保存。'+('首次关键词检索已排队，请在来源记录查看实际结果。' if d['enabled'] else '该服务保持关闭，不会调用外部搜索接口。'))
        return redirect('/search-sources/?'+urlencode({'provider':d['provider'],'project':d['project'].pk if d['project'] else '','scope':d['scope']}))
    configurations={c.provider:c for c in SearchProviderConfig.objects.filter(workspace=request.ws)}
    cards=[]
    for key,(name,url,docs) in PROVIDERS.items():
        c=configurations.get(key)
        cards.append({'key':key,'name':name,'docs':docs,'enabled':bool(c and c.enabled),'configured':bool(c and c.key_cipher),'used':c.daily_used if c and c.usage_date==timezone.localdate() else 0,'limit':c.daily_limit if c else 20})
    return page(request,'search_sources.html',{'title':'关键词检索来源','form':form,'providers':cards,'sources':sources})
