import secrets
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.conf import settings
from core.models import Workspace,Membership,NotificationConfig,AIConfig,Installation
from core.services import encryption,digest
from core.catalog import seed_catalog
from django.utils import timezone

class Command(BaseCommand):
    help='Create initial local administrator; does not reset existing users'
    def handle(self,*args,**kwargs):
        encryption()
        seed_catalog()
        if Membership.objects.filter(workspace__is_demo=False).exists():self.stdout.write('Argus 已初始化，保留现有账号和数据。');return
        path=settings.DATA_DIR/'.setup-token'
        if not path.exists():path.write_text(secrets.token_urlsafe(32),encoding='ascii')
        token=path.read_text(encoding='ascii').strip()
        Installation.objects.update_or_create(pk=1,defaults={'token_digest':digest(token),'claimed':False,'created_at':timezone.now()})
        self.stdout.write('首次使用已准备好。启动器将打开账号创建页面，无需查找密码文件。')
