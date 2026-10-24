from types import SimpleNamespace
from .models import Membership,Workspace

def access(request):
    if not request.user.is_authenticated:return None
    primary=Membership.objects.filter(user=request.user,workspace__is_demo=False).select_related('workspace').first()
    if not primary:return None
    demo_id=request.session.get('experience_workspace')
    if demo_id:
        demo=Workspace.objects.filter(pk=demo_id,is_demo=True,demo_owner=request.user).first()
        if demo:return SimpleNamespace(workspace=demo,role='analyst',get_role_display=lambda:'体验用户',primary=primary)
        request.session.pop('experience_workspace',None)
    return primary
