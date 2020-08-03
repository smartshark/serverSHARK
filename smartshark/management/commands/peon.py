#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import timeit
import sys
import os
import subprocess

import redis

from django.conf import settings
from django.db import connections
from django.core.management.base import BaseCommand

from smartshark.models import Job


class Command(BaseCommand):
    """Worker Process used for localqueueconnector.

    This worker connects to a redis queue to execute jobs for the localqueueconnector.
    """

    help = 'Worker Process'

    def add_arguments(self, parser):
        pass

    def loop(self):
        while True:
            # this blocks on empty queue
            el = self.con.blpop(self.job_queue, timeout=settings.LOCALQUEUE['timeout'])
            if not el:
                continue
            data = json.loads(el[1].decode('utf-8'))

            # we have an ugly distinction for jobs here, if a job_id is set we save the result into the db
            # if not we have an intermediate step, e.g., create a directory for which we do not persist the result into the datbaase
            job_id = None
            if 'job_id' in data.keys():
                job_id = data['job_id']

            if 'shell' in data.keys():
                start = timeit.default_timer()

                self.stdout.write('executing: {} ... '.format(data['shell']), ending=b'')
                sys.stdout.flush()

                # close db connection because we may have long running jobs
                connections['default'].close()
                if job_id:
                    # The peon writes these files as they are asynchronly directly accessed over PluginManagement, this is set to change in the future
                    job = Job.objects.get(pk=data['job_id'])
                    plugin_execution_output_path = os.path.join(self.output_path, str(job.plugin_execution.pk))
                    subprocess.run(['mkdir', '-p', plugin_execution_output_path])
                    output_file = os.path.join(plugin_execution_output_path, str(job_id) + '_out.txt')
                    error_file = os.path.join(plugin_execution_output_path, str(job_id) + '_err.txt')

                    success = False
                    with open(output_file, 'w') as out:
                        with open(error_file, 'w') as err:
                            try:
                                success = True
                                subprocess.run(data['shell'].split(), stdout=out, stderr=err, check=True, universal_newlines=True)
                            except subprocess.CalledProcessError:
                                success = False

                    end = timeit.default_timer() - start
                    self.stdout.write('finished in {:.5f}s '.format(end), ending=b'')

                    # TODO: backchannel for results (for job_id this should be possible, everything else not at the moment)
                    # self.con.rpush(self.result_queue, json.dumps({'job_id': data['job_id'], 'result': 'DONE'}))
                    job = Job.objects.get(pk=data['job_id'])
                    if success:
                        job.status = 'DONE'
                    else:
                        job.status = 'EXIT'
                    job.save()

                    # analogous to the HPC jobs we set the job to exit if we have output to stderr
                    error_text = ''
                    with open(error_file, 'r') as err:
                        error_text = err.read()
                        if len(error_text) > 0:
                            job.status = 'EXIT'
                            job.save()
                            success = False

                    if success:
                        self.stdout.write(self.style.SUCCESS('[OK]'))
                    else:
                        self.stdout.write(self.style.ERROR('[ERROR]'))
                        # self.stderr.write(res.stderr.decode('utf-8'))
                        self.stderr.write(error_text)

                else:  # no job_id, intermediate step
                    res = subprocess.run(data['shell'].split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                    end = timeit.default_timer() - start
                    self.stdout.write('finished in {:.5f}s '.format(end), ending=b'')

                    if res.returncode > 0:
                        self.stdout.write(self.style.ERROR('[ERROR]'))
                        self.stderr.write(res.stderr.decode('utf-8'))
                    else:
                        self.stdout.write(self.style.SUCCESS('[OK]'))

                self.stdout.write('{} jobs left in queue'.format(self.con.llen(self.job_queue)))

    def handle(self, *args, **options):
        self.con = redis.from_url(settings.LOCALQUEUE['redis_url'])
        self.job_queue = settings.LOCALQUEUE['job_queue']
        self.result_queue = settings.LOCALQUEUE['result_queue']

        self.output_path = settings.LOCALQUEUE['plugin_output']

        self.stdout.write('listening...')

        try:
            self.loop()
        except KeyboardInterrupt as e:
            self.stdout.write('stopping listening')
