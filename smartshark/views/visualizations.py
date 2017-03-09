import locale

from django.shortcuts import render
from smartshark.mongohandler import handler


def overview(request):
    num_projects = handler.get_number_of_projects()
    num_commits = handler.get_number_of_commits()
    num_persons = handler.get_number_of_people()
    num_mailing_messages = handler.get_number_of_mailing_messages()
    num_issues = handler.get_number_of_issues()
    num_code_entity_states = handler.get_number_of_code_entity_states()
    num_issue_comments = handler.get_number_of_issue_comments()
    num_issue_systems = handler.get_number_of_issue_systems()
    num_vcs_systems = handler.get_number_of_vcs_systems()
    num_mailing_lists = handler.get_number_of_mailing_lists()
    num_issue_events = handler.get_number_of_issue_events()
    num_clones = handler.get_number_of_clones()
    num_code_group_states = handler.get_number_of_code_group_states()
    num_file_changes = handler.get_number_of_file_changes()
    num_hunks = handler.get_number_of_hunks()



    return render(request, 'smartshark/frontend/visualizations/overview.html',
                  {
                      'projects': "{:,}".format(num_projects),
                      'commits': "{:,}".format(num_commits),
                      'persons': "{:,}".format(num_persons),
                      'mailing_messages': "{:,}".format(num_mailing_messages),
                      'issues': "{:,}".format(num_issues),
                      'code_entity_states': "{:,}".format(num_code_entity_states),
                      'issue_comments': "{:,}".format(num_issue_comments),
                      'issue_systems': "{:,}".format(num_issue_systems),
                      'vcs_systems': "{:,}".format(num_vcs_systems),
                      'mailing_lists': "{:,}".format(num_mailing_lists),
                      'issue_events': "{:,}".format(num_issue_events),
                      'code_group_states': "{:,}".format(num_code_group_states),
                      'clones': "{:,}".format(num_clones),
                      'hunks': "{:,}".format(num_hunks),
                      'file_changes': "{:,}".format(num_file_changes),
                  }
    )