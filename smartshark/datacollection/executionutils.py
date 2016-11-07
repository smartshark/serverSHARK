import string
import os
import subprocess
from collections import OrderedDict, defaultdict

import pygit2
import re

from server.settings import DATABASES
from smartshark.models import Job


def get_revisions_for_failed_plugins(plugins, project):
    revisions = []
    for plugin in plugins:
        revisions.extend(plugin.get_revision_hashes_of_failed_jobs_for_project(project))
    return revisions


def get_all_revisions(project):
    revisions = set()
    path_to_repo = os.path.join(os.path.dirname(__file__), 'temp', project.name)

    # Clone project
    subprocess.run(['git', 'clone', project.url, path_to_repo])

    discovered_repo = pygit2.discover_repository(path_to_repo)
    repository = pygit2.Repository(discovered_repo)

    revisions = set()
    for commit in repository.walk(repository.head.target, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_REVERSE):
        revisions.add(str(commit.id))

    subprocess.run(['rm', '-rf', path_to_repo])

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


def create_jobs_for_execution(project, plugin_executions, execution, revisions):
    jobs_temp = defaultdict(list)
    ret_jobs = []

    # We need to check if we need the actual list of revisions. This is the
    # case if the plugin should be executed on all or new revisions
    if execution == 'all' or execution == 'new':
        all_revisions = get_all_revisions(project)

    for plugin_execution in plugin_executions:
        req_jobs = find_required_jobs(plugin_execution, jobs_temp)

        if plugin_execution.plugin.plugin_type == 'repo' or plugin_execution.plugin.plugin_type == 'other':
            job = Job(plugin_execution=plugin_execution)
            job.save()

            for req_job in req_jobs:
                job.requires.add(req_job)
            job.save()

            jobs_temp[plugin_execution.plugin.id].append(job)
            ret_jobs.append(job)

        elif plugin_execution.plugin.plugin_type == 'rev':
            revisions_to_execute_plugin_on = []

            if execution == 'all':
                revisions_to_execute_plugin_on = all_revisions
            elif execution == 'rev':
                if len(revisions.split(",")) == 1:
                    revisions_to_execute_plugin_on.append(revisions)
                else:
                    # If only some revisions (comma-separated list) need to be executed, create path and add it to list
                    for revision in revisions.split(","):
                        revisions_to_execute_plugin_on.append(revision)

            elif execution == 'new':
                # Get all jobs that were executed with this plugin on this project
                jobs = plugin_execution.plugin.get_all_jobs_for_project(plugin_execution.project)
                job_revision_hashes = [job.revision_hash for job in jobs]

                # Go through all paths: If the revision was already processed by a job, it is not new, so exclude it
                for revision in all_revisions:
                    if revision not in job_revision_hashes:
                        revisions_to_execute_plugin_on.append(revision)

            elif execution == 'error':
                # Get all revisions on which this plugin failed (in some revisions) on this project. Important:
                # if the plugin on revision X failed in first run, but worked on revision X in the second it is not longer
                # marked as failing for this revision
                revisions = get_revisions_for_failed_plugins([plugin_execution.plugin], plugin_execution.project)
                for revision in revisions:
                    revisions_to_execute_plugin_on.append(revision)

            # Create command
            for revision in revisions_to_execute_plugin_on:
                job = Job(plugin_execution=plugin_execution, revision_hash=revision)
                job.save()

                for req_job in req_jobs:
                    job.requires.add(req_job)
                job.save()

                jobs_temp[plugin_execution.plugin.id].append(job)
                ret_jobs.append(job)

    return ret_jobs