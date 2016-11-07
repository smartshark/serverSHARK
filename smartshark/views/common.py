from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404

from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface
from smartshark.filters import JobExecutionFilter
from smartshark.models import PluginExecution, Job, Project


def index(request):
    return render(request, 'smartshark/frontend/index.html')


def plugin_execution_status(request, id):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.plugin_execution_status'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')
    interface = PluginManagementInterface.find_correct_plugin_manager()
    plugin_execution = get_object_or_404(PluginExecution, pk=id)

    # Get all jobs from all plugin_executions which did not terminate yet
    # Update the job stati for these jobs
    jobs = Job.objects.filter(plugin_execution=plugin_execution, status='WAIT').all()
    job_stati = interface.get_job_stati(jobs)
    i = 0
    for job in jobs:
        job.status = job_stati[i]
        job.save()
        i += 1

    job_filter = JobExecutionFilter(request.GET, queryset=Job.objects.all().filter(plugin_execution=plugin_execution))

    # Set up pagination
    paginator = Paginator(job_filter.qs, 10)
    page = request.GET.get('page')
    try:
        jobs = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        jobs = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        jobs = paginator.page(paginator.num_pages)

    return render(request, 'smartshark/project/plugin_execution_status.html', {
        'plugin_execution': plugin_execution,
        'filter': job_filter,
        'jobs': jobs,
        'overall': len(job_filter.qs)
    })


def plugin_status(request, id):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.plugin_status'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    project = get_object_or_404(Project, pk=id)
    execution_list = PluginExecution.objects.all().filter(project=project).order_by('-submitted_at')

    paginator = Paginator(execution_list, 10)
    page = request.GET.get('page')
    try:
        executions = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        executions = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        executions = paginator.page(paginator.num_pages)



    return render(request, 'smartshark/project/plugin_status.html', {
        'executions': executions,
    })


def job_output(request, id, type):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.job_output'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    job = get_object_or_404(Job, pk=id)

    interface = PluginManagementInterface.find_correct_plugin_manager()
    print(type)
    if type == 'output':
        output = interface.get_output_log(job)
    elif type == 'error':
        output = interface.get_error_log(job)
    elif type == 'arguments':
        return render(request, 'smartshark/job/execution_arguments.html', {
            'exe_arguments': job.plugin_execution.executionhistory_set.all().order_by('execution_argument__position'),
            'cmd': interface.get_sent_bash_command(job),
        })

    return render(request, 'smartshark/job/output.html', {
        'output': '\n'.join(output),
        'job': job,
    })
