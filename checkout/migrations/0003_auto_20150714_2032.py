# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import checkout.models


class Migration(migrations.Migration):

    dependencies = [
        ('checkout', '0002_auto_20150625_1159'),
    ]

    operations = [
        migrations.AlterField(
            model_name='checkout',
            name='state',
            field=models.ForeignKey(to='checkout.CheckoutState', default=checkout.models.default_checkout_state),
        ),
        migrations.AlterField(
            model_name='contactpaymentplaninstalment',
            name='state',
            field=models.ForeignKey(to='checkout.CheckoutState', default=checkout.models.default_checkout_state),
        ),
    ]