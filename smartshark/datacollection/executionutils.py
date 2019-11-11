import os
import subprocess
from collections import defaultdict

import pygit2
import re

from django.db.models import Q

from smartshark.models import Job, CommitVerification
from smartshark.mongohandler import handler


def get_revisions_for_failed_verification(project):
    # we ensure that commits missing vcsSHARK are first
    vcs = [cv.commit for cv in CommitVerification.objects.filter(project=project).filter(vcsSHARK=False)]
    plugins = [cv.commit for cv in CommitVerification.objects.filter(project=project).filter(Q(mecoSHARK=False) | Q(coastSHARK=False)).filter(vcsSHARK=True)]
    return vcs + plugins


def get_revisions_for_failed_plugins(plugins, project):
    revisions = []
    for plugin in plugins:
        revisions.extend(plugin.get_revision_hashes_of_failed_jobs_for_project(project))
    return revisions


def get_all_revisions(plugin_execution):
    """Return all revisions that are stored in the mongodb for this url."""
    revisions = set()
    for rev in handler.get_revisions_for_url(plugin_execution.repository_url):
        revisions.add(rev['revision_hash'])
    return revisions


def find_required_jobs(plugin_execution, all_jobs):
    job_list = []
    required_plugins = plugin_execution.plugin.requires.all()

    # If there are required plugins
    if required_plugins:
        # go through all plugins and set the jobs as required
        for req_plugin in required_plugins:
            for plugin_id, jobs_list in all_jobs.items():
                if req_plugin.id == plugin_id:
                    job_list.extend(jobs_list)

    return job_list


def create_job(plugin_execution, req_jobs, revision_hash=None):
    job = Job(plugin_execution=plugin_execution, revision_hash=revision_hash)
    job.save()

    for req_job in req_jobs:
        job.requires.add(req_job)
    job.save()

    return job


def create_jobs_for_execution(project, plugin_executions):
    jobs_temp = defaultdict(list)
    ret_jobs = []

    # We have three plugin_types that are interesting here: repo, rev and other. We need to define to handle them
    # separately
    for plugin_execution in plugin_executions:
        req_jobs = find_required_jobs(plugin_execution, jobs_temp)

        if plugin_execution.plugin.plugin_type == 'other':
            job = create_job(plugin_execution, req_jobs)
            jobs_temp[plugin_execution.plugin.id].append(job)
            ret_jobs.append(job)

        if plugin_execution.plugin.plugin_type == 'repo':
            job = create_job(plugin_execution, req_jobs)
            jobs_temp[plugin_execution.plugin.id].append(job)
            ret_jobs.append(job)

        if plugin_execution.plugin.plugin_type == 'rev':
            revisions_to_execute_plugin_on = []

            # We need to get all actual revisions first, if we want to execute them on all revisions or new ones
            if plugin_execution.execution_type == 'all' or plugin_execution.execution_type == 'new':
                all_revisions = get_all_revisions(plugin_execution)

            if plugin_execution.execution_type == 'all':
                revisions_to_execute_plugin_on = all_revisions
            elif plugin_execution.execution_type == 'rev':
                if len(plugin_execution.revisions.split(",")) == 1:
                    revisions_to_execute_plugin_on.append(plugin_execution.revisions)
                else:
                    # If only some revisions (comma-separated list) need to be executed, create path and add it to list
                    for revision in plugin_execution.revisions.split(","):
                        revisions_to_execute_plugin_on.append(revision)

            elif plugin_execution.execution_type == 'new':
                # Get all jobs that were executed with this plugin on this project
                jobs = plugin_execution.plugin.get_all_jobs_for_project(plugin_execution.project)
                job_revision_hashes = [job.revision_hash for job in jobs]

                # Go through all paths: If the revision was already processed by a job, it is not new, so exclude it
                for revision in all_revisions:
                    if revision not in job_revision_hashes:
                        revisions_to_execute_plugin_on.append(revision)

            elif plugin_execution.execution_type == 'error':
                # Get all revisions on which this plugin failed (in some revisions) on this project. Important:
                # if the plugin on revision X failed in first run, but worked on revision X in the second it is not
                # longer marked as failing for this revision
                revisions = get_revisions_for_failed_plugins([plugin_execution.plugin], plugin_execution.project)
                for revision in revisions:
                    revisions_to_execute_plugin_on.append(revision)

            elif plugin_execution.execution_type == 'ver':
                revisions_to_execute_plugin_on = get_revisions_for_failed_verification(plugin_execution.project)

            # Create command
            for revision in revisions_to_execute_plugin_on:
                job = create_job(plugin_execution, req_jobs, revision_hash=revision)

                jobs_temp[plugin_execution.plugin.id].append(job)
                ret_jobs.append(job)

    return ret_jobs
