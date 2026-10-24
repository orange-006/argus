from datetime import date
from django.db import migrations

def forward(apps,schema_editor):
    Preset=apps.get_model('core','SourcePreset');Workspace=apps.get_model('core','Workspace');Member=apps.get_model('core','Membership');Project=apps.get_model('core','Project');Source=apps.get_model('core','Source');Content=apps.get_model('core','Content');Event=apps.get_model('core','Event');Delivery=apps.get_model('core','Delivery');Job=apps.get_model('core','Job')
    catalog=[
      ('chinanews','中国新闻网 · 滚动新闻','https://www.chinanews.com.cn/rss/scroll-news.xml','综合资讯','公开滚动新闻订阅，适合观察社会与行业公开报道。','新闻网站公开资讯；不包含社交平台帖子、视频或用户评论。',60),
      ('ithome','IT之家 · 科技资讯','https://www.ithome.com/rss/','科技与互联网','科技产品、数码与互联网相关资讯，更新较频繁。','科技新闻报道；品牌出现取决于来源是否报道，不能按需全网搜索。',60),
      ('solidot','Solidot · 科技观察','https://www.solidot.org/index.rss','科技与互联网','开源、科学、互联网与科技话题。','科技主题公开资讯，不提供消费品牌评论或投诉数据。',60),
      ('ruanyifeng','阮一峰的网络日志','https://www.ruanyifeng.com/blog/atom.xml','科技与互联网','技术文章与科技爱好者周刊，适合行业资讯补充。','个人博客公开文章，更新频率较低，仅保留订阅中可获得的条目。',180),
    ]
    for key,name,url,category,description,coverage,interval in catalog:
        Preset.objects.get_or_create(key=key,defaults={'name':name,'url':url,'category':category,'description':description,'coverage':coverage,'interval_minutes':interval,'verified_date':date(2026,10,17),'check_status':'发布前连接检查通过'})
    for project in Project.objects.filter(workspace__is_demo=False):
        # Relocate only demonstrably sample-only projects; never move customer data.
        if not Source.objects.filter(project=project,kind='demo').exists():continue
        if Source.objects.filter(project=project).exclude(kind='demo').exists():continue
        if Content.objects.filter(source__project=project,is_demo=False).exists():continue
        owner=Member.objects.filter(workspace_id=project.workspace_id,role='admin').order_by('pk').first()
        if not owner:continue
        demo,_=Workspace.objects.get_or_create(demo_owner_id=owner.user_id,defaults={'name':'一分钟体验空间','is_demo':True,'onboarding_complete':True})
        if not demo.is_demo:continue
        content_ids=list(Content.objects.filter(source__project=project).values_list('pk',flat=True));event_ids=list(Event.objects.filter(project=project).values_list('pk',flat=True))
        Delivery.objects.filter(event_id__in=event_ids).update(workspace_id=demo.pk,status='体验空间不发送')
        Job.objects.filter(kind='analyze',payload__content_id__in=content_ids).update(workspace_id=demo.pk)
        project.workspace_id=demo.pk;project.save(update_fields=['workspace'])
    for ws in Workspace.objects.filter(is_demo=False):
        if Project.objects.filter(workspace=ws).exists():ws.onboarding_complete=True;ws.save(update_fields=['onboarding_complete'])

class Migration(migrations.Migration):
    dependencies=[('core','0003_installation_sourcepreset_and_more')]
    operations=[migrations.RunPython(forward,migrations.RunPython.noop)]
