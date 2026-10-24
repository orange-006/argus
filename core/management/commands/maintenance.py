from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Content,Job,AuditLog,LoginAttempt

class Command(BaseCommand):
    help='Preview retention cleanup (content 90 days, completed jobs 14 days). Use --apply to execute.'
    def add_arguments(self,parser):parser.add_argument('--apply',action='store_true')
    def handle(self,*args,**options):
        now=timezone.now()
        groups={'过期内容':Content.objects.filter(fetched_at__lt=now-timedelta(days=90)),'历史成功任务':Job.objects.filter(status='succeeded',created_at__lt=now-timedelta(days=14)),'旧登录计数':LoginAttempt.objects.filter(updated_at__lt=now-timedelta(days=30))}
        for name,query in groups.items():
            self.stdout.write(f'{name}: {query.count()}')
            if options['apply']:query.delete()
        self.stdout.write('已执行清理' if options['apply'] else '仅预览，未删除。执行前建议备份。')
