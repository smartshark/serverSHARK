#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from django.core.management.base import BaseCommand

from smartshark.models import Project, JobVerification
from smartshark.mongohandler import handler
from smartshark.utils.projects import create_local_repo_for_project, get_all_commits_of_repo
import pygit2,os

class Command(BaseCommand):
    help = 'Verify a project'

    db = handler.client.smartshark

    def handle(self, *args, **options):
        for p in Project.objects.all():
            self.stdout.write(p.name)
        try:
            l = input("Which project should be verified? ")
            project = Project.objects.all().get(name__iexact=l)
            self.stdout.write("Calculate data tree for {}".format(project.name))
        except (Project.DoesNotExist, Project.MultipleObjectsReturned) as e:
            self.stdout.write(self.style.ERROR('Error loading project: {}'.format(e)))
            sys.exit(-1)

        path = "../tmp-repo"
        projectMongo = self.db.project.find_one({"name": project.name})
        print(projectMongo["_id"])
        vcsMongo = self.db.vcs_system.find_one({"project_id": projectMongo["_id"]})
        #if vcsMongo == None or vcsMongo["repository_type"] != 'git':
        #    self.stdout.write(self.style.ERROR('Error: repository is not a git repository'))
        #    sys.exit(-1)
        # 1. Checkout the project


        repo = create_local_repo_for_project(vcsMongo, path)
        if not repo.is_empty:
            allCommits = get_all_commits_of_repo(vcsMongo, repo)
            self.stdout.write("Found {} commits for the project".format(len(allCommits)))

            # 2. Iterate over the commits
            for commit in allCommits:
                print("Commit " + commit)

                # Add primary keys to the model
                resultModel = JobVerification()
                resultModel.project_id = project
                resultModel.vcs_system = vcsMongo["url"]
                resultModel.commit = commit
                resultModel.text = ""

                # Basic validation wihtout checkout the version
                resultModel.vcsSHARK = self.validate_vcsSHARK()

                # Checkout, to validate also on file level
                ref = repo.create_reference('refs/tags/temp', commit)
                repo.checkout(ref)

                # 3. Iterate foreach commit over the files

                db_commit = self.get_commit_from_database(commit)

                self.validate_mecoSHARK(path,db_commit, resultModel)
                self.validate_coastSHARK(path,db_commit, resultModel)

                # Save the model
                print(resultModel)
                print(resultModel.text)

                # Reset repo to iterate over all commits
                repo.reset(repo.head.target.hex, pygit2.GIT_RESET_HARD)
                ref.delete()

        print("validation complete")

    # Get commit form database
    def get_commit_from_database(self, commitHex):
        return self.db.commit.find_one({"revision_hash": commitHex})




    # Plugins validation methods
    def validate_vcsSHARK(self):
        return True

    # File level validation
    def validate_coastSHARK(self, path, db_commit, resultModel):
        resultModel.text = resultModel.text + "+++ coastSHARK +++"
        unvalidated_code_entity_state_longnames = []

        for db_code_entity_state in db_commit["code_entity_states"]:
            if db_code_entity_state["ce_type"] == 'file':
                if "node_count" in db_code_entity_state["metrics"]:
                    if db_code_entity_state["metrics"]["node_count"] > 0:
                        unvalidated_code_entity_state_longnames.append(
                            db_code_entity_state["long_name"])

        # Validate on file level
        resultModel.coastSHARK = self.validateOnFileLevel(path,unvalidated_code_entity_state_longnames,resultModel)

    def validate_mecoSHARK(self, path, db_commit, resultModel):
        resultModel.text = resultModel.text + "+++ mecoSHARK +++"
        unvalidated_code_entity_state_longnames = []

        for db_code_entity_state in db_commit["code_entity_states"]:
            if db_code_entity_state["ce_type"] == 'file':
                if "McCC" in db_code_entity_state["metrics"]:
                    if db_code_entity_state["metrics"]["McCC"]:
                        unvalidated_code_entity_state_longnames.append(
                            db_code_entity_state["long_name"])

        # Validate on file level
        resultModel.mecoSHARK = self.validateOnFileLevel(path,unvalidated_code_entity_state_longnames,resultModel)

    def validateOnFileLevel(self, path, unvalidated_code_entity_state_longnames, resultModel):
        globalResult = True
        for root, dirs, files in os.walk(path):
            for file in files:
                if file.endswith('.py') or file.endswith('.java'):

                    filepath = os.path.join(root, file)
                    filepath = filepath.replace(path + "/", '')
                    if filepath in unvalidated_code_entity_state_longnames:
                        unvalidated_code_entity_state_longnames.remove(filepath)
                    else:
                        globalResult = False
                        resultModel.text = resultModel.text + "\n -" + str(filepath)

        return globalResult