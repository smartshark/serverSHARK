# -*- coding: utf-8 -*-
# Generated by Django 1.9.9 on 2018-10-08 22:02
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('smartshark', '0040_auto_20180918_0148'),
    ]

    operations = [
        migrations.DeleteModel(
            name='ProjectMongo',
        ),
        migrations.RemoveField(
            model_name='project',
            name='executions',
        ),
        migrations.CreateModel(
            name='ProjectMongo',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vcs_id', models.CharField(blank=True, default='None', max_length=50, null=True)),
                ('issue_id', models.CharField(blank=True, default='None', max_length=50, null=True)),
                ('mailing_id', models.CharField(blank=True, default='None', max_length=50, null=True)),
                ('validation', models.TextField(blank=True, default='None', null=True)),
                ('executed_plugins', models.ManyToManyField(blank=True, to='smartshark.Plugin')),
                ('project', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='smartshark.Project')),
            ],
        ),
    ]
