# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('auditlog', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='auditentry',
            options={'verbose_name_plural': 'audit entries'},
        ),
    ]
