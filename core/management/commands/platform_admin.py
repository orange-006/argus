from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth.models import User
from core.models import PlatformAudit

class Command(BaseCommand):
    help='Grant platform administrator access to an existing owner account; never resets passwords'
    def add_arguments(self,parser):parser.add_argument('--username',required=True)
    def handle(self,*args,**options):
        user=User.objects.filter(username=options['username'],is_active=True).first()
        if not user:raise CommandError('指定账号不存在或已停用')
        if not user.is_superuser:
            user.is_superuser=True;user.is_staff=True;user.save(update_fields=['is_superuser','is_staff'])
            PlatformAudit.objects.create(actor='local-console',action='授予平台管理员权限',target=str(user.pk))
        self.stdout.write('平台管理员权限已准备好，密码保持不变。')
