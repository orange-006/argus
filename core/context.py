from .scope import access
def app_context(request):
    member=access(request)
    from .models import TrialAccess
    trial=TrialAccess.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    return {'trial_access':trial,'membership':member,'workspace':member.workspace if member else None,'can_edit':bool(member and member.role!='viewer'),'can_admin':bool(member and member.role=='admin'),'experience_mode':bool(member and member.workspace.is_demo),'argus_version':'1.6.0'}
