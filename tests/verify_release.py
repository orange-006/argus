"""Opt-in live RSS and consistent backup verification. Run on a test instance only."""
import os,sys,json,sqlite3,zipfile,tempfile,io
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','argus.settings')
import django
django.setup()
from django.core.management import call_command
from core.models import Workspace,Project,Source,SourceRun,Content
from core.services import collect
from cryptography.fernet import Fernet

workspace=Workspace.objects.create(name='发布验收隔离空间')
project=Project.objects.create(workspace=workspace,name='阮一峰',aliases='科技,AI,GitHub')
source=Source.objects.create(project=project,name='公开 Atom 验收',url='https://www.ruanyifeng.com/blog/atom.xml',enabled=False)
collect(source);first=Content.objects.filter(source=source).count()
collect(source);second=Content.objects.filter(source=source).count()
assert first>0 and first==second,(first,second)
stream=io.StringIO();call_command('backup',stdout=stream)
archive=sorted((ROOT/'backups').glob('*.zip'))[-1]
with tempfile.TemporaryDirectory() as temp:
    target=Path(temp)
    with zipfile.ZipFile(archive) as zip_file:zip_file.extractall(target)
    connection=sqlite3.connect(target/'argus.sqlite3');integrity=connection.execute('PRAGMA integrity_check').fetchone()[0];count=connection.execute('SELECT count(*) FROM core_content').fetchone()[0];connection.close()
    assert integrity=='ok' and count>=second
    token=Fernet((ROOT/'data'/'.encryption-key').read_bytes()).encrypt(b'Argus restore canary')
    assert Fernet((target/'.encryption-key').read_bytes()).decrypt(token)==b'Argus restore canary'
result={'live_rss':{'url':source.url,'first_count':first,'after_repeat_count':second,'runs':list(SourceRun.objects.filter(source=source).values('status','fetched','inserted'))},'backup_restore':{'integrity':integrity,'content_rows':count,'key_restore':True}}
(ROOT/'test-results').mkdir(exist_ok=True);(ROOT/'test-results'/'release-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
