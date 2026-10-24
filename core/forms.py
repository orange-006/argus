from django import forms
from .models import Project

class ProjectForm(forms.ModelForm):
    class Meta:
        model=Project;fields=['name','aliases','excludes','active']
        labels={'name':'品牌 / 项目名称','aliases':'品牌及产品别名','excludes':'排除词','active':'启用监测'}
        widgets={'aliases':forms.Textarea(attrs={'rows':3,'placeholder':'逗号或换行分隔'}),'excludes':forms.Textarea(attrs={'rows':2})}

class SourceForm(forms.Form):
    project=forms.ModelChoiceField(queryset=Project.objects.none(),label='监测项目')
    name=forms.CharField(max_length=100,label='来源名称')
    url=forms.URLField(max_length=2000,label='RSS / Atom / JSON Feed 订阅地址')
    interval_minutes=forms.IntegerField(min_value=15,max_value=1440,initial=30,label='采集间隔（分钟）')
    def __init__(self,*args,workspace,**kwargs):
        super().__init__(*args,**kwargs);self.fields['project'].queryset=Project.objects.filter(workspace=workspace)

class ImportForm(forms.Form):
    project=forms.ModelChoiceField(queryset=Project.objects.none(),label='所属项目')
    file=forms.FileField(label='CSV / JSON 文件（UTF-8，最大 5MB）')
    source_name=forms.CharField(max_length=100,initial='客户文件导入',label='来源名称')
    def __init__(self,*args,workspace,**kwargs):
        super().__init__(*args,**kwargs);self.fields['project'].queryset=Project.objects.filter(workspace=workspace)

class NotificationForm(forms.Form):
    group_name=forms.CharField(label='接收群名称',max_length=100)
    webhook=forms.CharField(label='企业微信机器人 Webhook（留空保留原凭证）',required=False,widget=forms.PasswordInput(render_value=False,attrs={'autocomplete':'new-password'}))
    enabled=forms.BooleanField(label='启用通知',required=False)
    push_interval_minutes=forms.TypedChoiceField(label='消息推送间隔',choices=[(v,f'每 {v} 分钟') for v in (1,5,10,20,30,60,120)],coerce=int,initial=10,help_text='已有的推送间隔在这里修改，保存后生效。首条消息可立即发送，后续消息按所选间隔排队；没有新消息时不发送。')
    threshold=forms.ChoiceField(label='风险提醒门槛',choices=[('需要关注','需要关注及以上'),('紧急核实','仅紧急核实')])
    quiet=forms.BooleanField(label='启用免打扰（北京时间）',required=False)
    quiet_start=forms.TimeField(label='免打扰开始',widget=forms.TimeInput(attrs={'type':'time'},format='%H:%M'))
    quiet_end=forms.TimeField(label='免打扰结束',widget=forms.TimeInput(attrs={'type':'time'},format='%H:%M'))
    daily_time=forms.TimeField(label='日报发送时间',widget=forms.TimeInput(attrs={'type':'time'},format='%H:%M'))
    def clean(self):
        data=super().clean()
        if data.get('quiet') and data.get('quiet_start')==data.get('quiet_end'):self.add_error('quiet_end','起止时间不能相同')
        return data

class AIForm(forms.Form):
    enabled=forms.BooleanField(label='启用 AI 辅助分析',required=False)
    api_base=forms.URLField(label='兼容接口 Base URL（HTTPS）',max_length=300)
    model=forms.CharField(label='模型名称',max_length=100,required=False)
    api_key=forms.CharField(label='API Key（留空保留原凭证）',required=False,widget=forms.PasswordInput(render_value=False,attrs={'autocomplete':'new-password'}))
    daily_limit=forms.IntegerField(label='每日最多 AI 请求数（每空间）',min_value=1,max_value=10000)

class MemberForm(forms.Form):
    username=forms.RegexField(regex=r'^[\w.@+-]{3,100}$',label='账号',max_length=100)
    password=forms.CharField(label='初始密码（至少 10 位）',min_length=10,widget=forms.PasswordInput)
    role=forms.ChoiceField(label='角色',choices=[('analyst','分析员'),('viewer','只读成员'),('admin','管理员')])
