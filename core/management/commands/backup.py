import sqlite3,zipfile
from contextlib import closing
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help='Consistent local SQLite backup including encryption keys. Store securely.'
    def handle(self,*args,**kwargs):
        folder=settings.BASE_DIR/'backups';folder.mkdir(exist_ok=True)
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        database=folder/f'argus-{stamp}.sqlite3'
        with closing(sqlite3.connect(settings.DATABASES['default']['NAME'])) as source,closing(sqlite3.connect(database)) as dest:source.backup(dest)
        archive=folder/f'argus-{stamp}.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(database,'argus.sqlite3')
            for name in ['.django-secret','.encryption-key']:
                path=settings.DATA_DIR/name
                if path.exists():z.write(path,name)
        database.unlink()
        self.stdout.write(str(archive))
        self.stdout.write('备份包含密钥，请存放在受控加密位置，不要公开分享。')
