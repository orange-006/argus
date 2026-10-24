import time,logging
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.conf import settings
from core.services import schedule,work_once

class Command(BaseCommand):
    help='Run durable database task worker with scheduler (one local process)'
    def add_arguments(self,parser):parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        if options['once']:schedule();work_once();return
        lock=(settings.DATA_DIR/'worker.lock').open('a+b')
        try:
            lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
            if __import__('os').name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.stderr.write('Argus Worker 已在此数据目录运行，拒绝重复启动。');return
        last=0
        while True:
            try:
                close_old_connections()
                if time.monotonic()-last>20:schedule();last=time.monotonic()
                if not work_once():time.sleep(2)
            except KeyboardInterrupt:return
            except Exception as exc:
                logging.error('Worker cycle failed (%s); retrying',type(exc).__name__)
                time.sleep(5)
