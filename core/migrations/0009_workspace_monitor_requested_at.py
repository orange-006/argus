from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[('core','0008_notification_push_interval')]
    operations=[migrations.AddField(model_name='workspace',name='monitor_requested_at',field=models.DateTimeField(blank=True,null=True))]
