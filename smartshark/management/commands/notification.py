from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from smartshark.models import PluginExecution
from django.conf import settings

class Command(BaseCommand):
    help = 'E-Mail Notification for jobs in the HPC system'


    def handle(self, *args, **options):
      executions = PluginExecution.objects.all().filter(status="WAIT")
      finishedJobs = []
      print("Checking", executions.count(), "PluginExecutions")
      for execution in executions:
          if(execution.has_unfinished_jobs()):
              print(execution.plugin.name, "on", execution.project.name ,":Execution is still running")
          else:
              print(execution.plugin.name, "on", execution.project.name ,":Execution is done")
              finishedJobs.append(execution)
              execution.status = 'DONE'
              execution.save()

      if(len(finishedJobs) > 0):
          self.sendMail(finishedJobs)




    def sendMail(self, data):
      emailBody = "The following jobs are ready: \n\r"
      for execution in data:
          (done, exits) = execution.get_counts_of_jobstatus()
          emailBody = emailBody + "- " + execution.plugin.name + " on "+ execution.project.name + "(" + str(done) + "/" + str(exits) + ")\n\r"
      send_mail('Job Status', emailBody, settings.EMAIL_HOST_USER,
                  [settings.NOTIFICATION_RECEIVER])