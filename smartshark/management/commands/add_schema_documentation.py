#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import json

from django.core.management.base import BaseCommand

from smartshark.mongohandler import handler


logger = logging.getLogger('django')


class Command(BaseCommand):
    """Adds additional schema documentation that is not part of plugins"""

    help = 'Adds additional schema documentation that is not part of plugins'

    def handle(self, *args, **options):

        self.stdout.write('adding additional schema information for visualSHARK')
        with open('./add_schemas/visualSHARK.json', 'r') as f:
            schema = json.loads(f.read())
            handler.add_schema(schema, 'visualSHARK_0.1.3')
        self.stdout.write('additional schema information written.')
