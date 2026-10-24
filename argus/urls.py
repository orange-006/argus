from django.urls import path
from core import views
from core import onboarding
from core import accounts
from core import search_sources
from core import workbench
from core import quick_search
urlpatterns = [
 path('site/',accounts.website,name='website'),path('site/<path:asset>',accounts.website,name='website_asset'),
 path('register/',accounts.register,name='register'),path('contact/',accounts.contact,name='contact'),path('privacy/',accounts.privacy,name='privacy'),
 path('platform-admin/login/',accounts.platform_login,name='platform_login'),path('platform-admin/',accounts.platform_admin,name='platform_admin'),
 path('platform-admin/trials/<int:pk>/',accounts.trial_action,name='trial_action'),path('platform-admin/presets/<int:pk>/',accounts.preset_action,name='preset_action'),
 path('welcome/',onboarding.welcome,name='welcome'),path('onboarding/',onboarding.onboarding,name='onboarding'),
 path('first-results/<int:pk>/',onboarding.first_results,name='first_results'),path('first-results/<int:pk>/status/',onboarding.first_results_status,name='first_results_status'),
 path('search-sources/',search_sources.search_sources,name='search_sources'),
 path('source-library/',onboarding.source_library,name='source_library'),path('experience/enter/',onboarding.demo_enter,name='demo_enter'),path('experience/exit/',onboarding.demo_exit,name='demo_exit'),
 path('login/',views.login_view,name='login'),path('logout/',views.logout_view,name='logout'),path('',views.dashboard,name='dashboard'),
 path('quick-search/',quick_search.quick_search,name='quick_search'),path('quick-search/<int:pk>/',quick_search.quick_search,name='quick_search_run'),path('quick-search/<int:pk>/status/',quick_search.quick_search_status,name='quick_search_status'),
 path('history/clear/',workbench.clear_history,name='clear_history'),
 path('screen/',workbench.monitoring_screen,name='monitoring_screen'),path('screen/status/',workbench.monitoring_screen_status,name='monitoring_screen_status'),
 path('monitor/now/',views.monitor_now,name='monitor_now'),path('monitor/status/',views.monitor_status,name='monitor_status'),
 path('projects/',views.projects,name='projects'),path('projects/new/',views.project_edit,name='project_new'),path('projects/<int:pk>/',views.project_edit,name='project_edit'),
 path('sources/',views.sources,name='sources'),path('sources/<int:pk>/collect/',views.source_collect,name='source_collect'),path('sources/<int:pk>/toggle/',views.source_toggle,name='source_toggle'),
 path('import/',views.import_view,name='import'),path('import/template/',views.import_template,name='import_template'),
 path('contents/',views.contents,name='contents'),path('contents/<int:pk>/feedback/',views.feedback,name='feedback'),
 path('contents/<int:pk>/',views.content_detail,name='content_detail'),
 path('events/',views.events,name='events'),path('events/<int:pk>/',views.event_detail,name='event_detail'),path('events/<int:pk>/action/',views.event_action,name='event_action'),
 path('review/',views.review,name='review'),path('notifications/',views.notifications,name='notifications'),path('notifications/<int:pk>/action/',views.notification_action,name='notification_action'),
 path('reports/',views.reports,name='reports'),path('reports/<int:pk>/',views.report_detail,name='report_detail'),path('reports/<int:pk>/csv/',views.report_csv,name='report_csv'),
 path('settings/',views.settings_view,name='settings'),path('account/password/',views.password_change,name='password_change'),path('operations/',views.operations,name='operations'),
 path('jobs/<int:pk>/retry/',views.job_retry,name='job_retry'),path('demo/',views.demo,name='demo'),path('health/',views.health,name='health'),
]
