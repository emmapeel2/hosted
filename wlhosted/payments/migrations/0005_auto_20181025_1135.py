# -*- coding: utf-8 -*-
# Generated by Django 1.11.16 on 2018-10-25 09:35
from __future__ import unicode_literals

from django.db import migrations, models
import django_countries.fields
import vies.models
import vies.validators


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0004_auto_20181025_1130'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customer',
            name='address',
            field=models.CharField(max_length=200, null=True, verbose_name='Address'),
        ),
        migrations.AlterField(
            model_name='customer',
            name='city',
            field=models.CharField(max_length=200, null=True, verbose_name='Post code code and city'),
        ),
        migrations.AlterField(
            model_name='customer',
            name='country',
            field=django_countries.fields.CountryField(max_length=2, null=True, verbose_name='Country'),
        ),
        migrations.AlterField(
            model_name='customer',
            name='name',
            field=models.CharField(max_length=200, null=True, verbose_name='Company name'),
        ),
        migrations.AlterField(
            model_name='customer',
            name='vat',
            field=vies.models.VATINField(blank=True, help_text='Please fill in Europe Union VAT ID, keep the field blank if not applicable.', max_length=14, null=True, validators=[vies.validators.VATINValidator(validate=True, verify=True)], verbose_name='European VAT ID'),
        ),
    ]
