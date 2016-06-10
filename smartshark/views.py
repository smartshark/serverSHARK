from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404

# Create your views here.
from smartshark.forms import ProjectForm
from smartshark.models import Project


def collection(request, ids):
    projects = []
    for project_id in ids:
        projects.append(get_object_or_404(Project, pk=project_id))

    # if this is a POST request we need to process the form data
    if request.method == 'POST':
        if 'cancel' in request.POST:
            return HttpResponseRedirect('/admin/smartshark/project')

        # create a form instance and populate it with data from the request:
        form = ProjectForm(request.POST)
        # check whether it's valid:
        if form.is_valid():
            print(form.cleaned_data)
            # check requirements
            # 1. check for each plugin if required plugin is set and installed
            # 2. if plugin with this name + project is in queue -> error
            # 3. order: first plugins without requirements (can directly be sent)
            # 4. rest is put into a queue (signal: projectname/plugin/?status=success


            # add plugin exec

            messages.success(request, 'Started the data collection for %d project(s) with %d plugin(s)'
                             % (len(projects), len(form.cleaned_data['plugins'])))
            return HttpResponseRedirect('/admin/smartshark/project')

    # if a GET (or any other method) we'll create a blank form
    else:
        form = ProjectForm()

    return render(request, 'smartshark/project/action_collection.html', {
        'form': form,
        'projects': projects,

    })