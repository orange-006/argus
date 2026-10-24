from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0007_content_author_content_last_seen_content_revision_and_more')]

    operations = [
        migrations.AddField(
            model_name='notificationconfig',
            name='push_interval_minutes',
            field=models.PositiveIntegerField(default=10),
        ),
    ]
