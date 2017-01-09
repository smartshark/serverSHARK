import os

from django.contrib import messages
from django.core.files.storage import default_storage
from django.http import HttpResponseRedirect
from django.shortcuts import render

from smartshark.forms import SparkSubmitForm
from smartshark.scp import SCPClient
from smartshark.shellhandler import ShellHandler
from smartshark.sparkconnector import SparkConnector


def spark_submit(request):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.spark_submit'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/smartshark')

    if request.method == 'POST':
        # create a form instance and populate it with data from the request:
        form = SparkSubmitForm(request.POST or None, request.FILES)
        # check whether it's valid:
        if form.is_valid():
            file_obj = request.FILES['file']
            file_name = request.user.username+"_"+str(file_obj)

            # Write file to a temp file
            with open(default_storage.path('tmp/'+file_name), 'wb+') as destination:
                for chunk in file_obj.chunks():
                    destination.write(chunk)



            # Copy analysis

            # delete temp file
            os.remove(default_storage.path('tmp/'+file_name))

            # Send batch job
            sc = SparkConnector()
            sc.submit_batch_job('~/sparkjobs/'+file_name, class_name=form.cleaned_data['class_name'],
                                args=form.cleaned_data['arguments'].split(','))

            messages.success(request, 'Spark Job submitted successfully!')
            return HttpResponseRedirect('/smartshark/spark/submit')

    # if a GET (or any other method) we'll create a blank form
    else:
        form = SparkSubmitForm(request.POST or None)

    return render(request, 'smartshark/frontend/spark/submit.html', {
        'form': form
    })

