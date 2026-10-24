import uuid
from django.core.management.base import BaseCommand
from core.models import Source
from core.accounts import trial_blocked
from core.services import enqueue

class Command(BaseCommand):
    help='Re-read enabled real streams once to recover content and initialize ranking observations; no notifications'
    def handle(self,*args,**kwargs):
        count=0
        for source in Source.objects.filter(kind__in=['rss','newsnow','search'],enabled=True,project__active=True,project__workspace__is_demo=False).select_related('project__workspace'):
            if trial_blocked(source.project.workspace):continue
            enqueue(source.project.workspace,'collect','stream-upgrade:'+uuid.uuid4().hex,{'source_id':source.pk,'force':True});count+=1
        self.stdout.write(f'已排队完整读取 {count} 个已启用真实来源；不主动发送通知。')
