"""Argus Windows/local launcher. Runs Waitress and a supervised durable worker."""
import os,sys,subprocess,threading,time,webbrowser,socket
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE','argus.settings')
os.environ.setdefault('PYTHONUTF8','1')

def main():
    host=os.environ.get('ARGUS_HOST','127.0.0.1');port=int(os.environ.get('ARGUS_PORT','8765'))
    try:
        with socket.socket() as s:s.bind((host,port))
    except OSError:
        print(f'端口 {port} 已被占用。如果 Argus 已启动，请打开 http://127.0.0.1:{port}。否则设置 ARGUS_PORT 更换端口。');return 1
    for args in [['migrate','--noinput'],['bootstrap'],['collectstatic','--noinput']]:
        subprocess.run([sys.executable,'manage.py',*args],cwd=ROOT,check=True)
    import django
    django.setup()
    from django.conf import settings
    runtime_data=settings.DATA_DIR
    pidfile=runtime_data/'server.pid';pidfile.write_text(str(os.getpid()),encoding='ascii')
    from django.core.wsgi import get_wsgi_application
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from waitress import serve
    application=StaticFilesHandler(get_wsgi_application())
    stop=threading.Event();children=[]
    def worker_loop():
        runtime_data.mkdir(exist_ok=True)
        with (runtime_data/'worker.log').open('a',encoding='utf-8') as log:
            while not stop.is_set():
                child=subprocess.Popen([sys.executable,'manage.py','worker'],cwd=ROOT,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));children[:]=[child]
                while child.poll() is None and not stop.wait(2):pass
                if stop.is_set():
                    if child.poll() is None:child.terminate()
                    break
                stop.wait(4)
    thread=threading.Thread(target=worker_loop,daemon=True);thread.start()
    url=f'http://127.0.0.1:{port}'
    print('\nArgus 已启动：'+url+'\n首次运行可在浏览器创建自己的账号；升级后原账号继续有效。\n关闭本窗口将停止服务。\n')
    from core.models import Membership
    setup_path=runtime_data/'.setup-token'
    browser_url=url+('/welcome/?token='+setup_path.read_text(encoding='ascii').strip() if not Membership.objects.exists() and setup_path.exists() else '')
    if os.environ.get('ARGUS_NO_BROWSER')!='1':threading.Timer(2,lambda:webbrowser.open(browser_url)).start()
    try:serve(application,host=host,port=port,threads=4,channel_timeout=120,ident='Argus')
    except KeyboardInterrupt:pass
    finally:
        stop.set()
        for child in children:
            if child.poll() is None:child.terminate()
        thread.join(timeout=5)
        if pidfile.exists():pidfile.unlink()
    return 0
if __name__=='__main__':sys.exit(main())
