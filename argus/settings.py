from pathlib import Path
import os, secrets
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('ARGUS_DATA_DIR', str(BASE_DIR / 'data'))).resolve()
DATA_DIR.mkdir(parents=True,exist_ok=True)
secret_file = DATA_DIR / '.django-secret'
if not secret_file.exists():
    secret_file.write_text(secrets.token_urlsafe(48), encoding='utf-8')
SECRET_KEY = os.environ.get('ARGUS_SECRET_KEY') or secret_file.read_text(encoding='utf-8').strip()
DEBUG = os.environ.get('ARGUS_DEBUG') == '1'
ALLOWED_HOSTS = os.environ.get('ARGUS_ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(',')
INSTALLED_APPS = ['django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','core']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
MIDDLEWARE.insert(6,'core.accounts.TrialMiddleware')
ROOT_URLCONF = 'argus.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','core.context.app_context']}}]
DATABASES = {'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('ARGUS_DB', str(DATA_DIR/'argus.sqlite3')),'OPTIONS':{'timeout':30}}}
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR/'static']
STATIC_ROOT = BASE_DIR/'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = os.environ.get('ARGUS_HTTPS') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator','OPTIONS':{'min_length':10}}]
