#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import tempfile

import pygit2

from django.core.management.base import BaseCommand
from django.db import connections

from smartshark.models import Project, CommitVerification
from smartshark.mongohandler import handler
from smartshark.utils.projectUtils import create_local_repo_for_project, get_all_commits_of_repo, get_commit_from_database, get_code_entities_from_database
from smartshark.datacollection.executionutils import get_revisions_for_failed_verification


class Command(BaseCommand):
    help = 'Verify a project'

    db = handler.client.smartshark

    def handle(self, *args, **options):
        for p in Project.objects.all():
            self.stdout.write(p.name)
        try:
            l = input("Which project should be verified? ")
            project = Project.objects.all().get(name__iexact=l)
            self.stdout.write("Verfiy project {}".format(project.name))
        except (Project.DoesNotExist, Project.MultipleObjectsReturned) as e:
            self.stdout.write(self.style.ERROR('Error loading project: {}'.format(e)))
            sys.exit(-1)

        # add ability to request run without memeshark (which will be the default at one time in the future)
        self.use_meme = True
        l2 = input('did memeSHARK run for project {}? (Y/n)'.format(project.name))
        if l2.lower() == 'n':
            self.use_meme = False
        self.stdout.write('Assuming memeSHARK {}'.format(self.use_meme))

        # add ability to request run on only previously failed commit verifications
        self.only_failed = False
        l3 = input('only re-check previously failed commits? (y/N)')
        if l3.lower() == 'y':
            self.only_failed = True
            self.stdout.write('Only checking previously failed commits')

        with tempfile.TemporaryDirectory() as path:
            projectMongo = self.db.project.find_one({"name": project.name})

            vcsMongo = self.db.vcs_system.find_one({"project_id": projectMongo["_id"]})

            if not self.only_failed:
                l = input("Delete old verification data first? (y/N)")
                if l.lower() == 'y':
                    CommitVerification.objects.filter(project=project).delete()
                    self.stdout.write("Deleted old verification data")

            repo = create_local_repo_for_project(vcsMongo, path, project.name)

            if not repo.is_empty:

                if not self.only_failed:
                    allCommits = get_all_commits_of_repo(vcsMongo, repo)
                    self.stdout.write("Found {} commits for the project".format(len(allCommits)))
                else:
                    allCommits = get_revisions_for_failed_verification(project)
                    self.stdout.write('Found {} commits that previously failed'.format(len(allCommits)))
                    self.stdout.write('Overwriting commit verification data for {} previously failed commits'.format(len(allCommits)))

                # close connection because the above may take a long time
                connections['default'].close()

                # 2. Iterate over the commits
                num_commits = len(allCommits)
                i = 0
                for commit in allCommits:
                    # print("Commit " + commit)

                    i += 1
                    print("Commit (" + str(commit) + ") " + str(i) + '/' + str(num_commits), end='')
                    connections['default'].ensure_connection()

                    try:
                        resultModel = CommitVerification.objects.get(project=project, vcs_system=vcsMongo['url'], commit=str(commit))
                    except CommitVerification.DoesNotExist:
                        resultModel = CommitVerification()
                        resultModel.project = project
                        resultModel.vcs_system = vcsMongo['url']
                        resultModel.commit = str(commit)

                    resultModel.text = ""

                    db_commit = get_commit_from_database(self.db, commit, vcsMongo["_id"])

                    # Basic validation wihtout checkout the version
                    if not db_commit:
                        self.stdout.write('commit {} not in database, skipping validation'.format(commit))
                        continue
                    try:
                        resultModel.vcsSHARK = self.validate_vcsSHARK(db_commit, repo, resultModel)
                    except KeyError:
                        self.stdout.write('commit {} in database but not in repository, skipping validation'.format(commit))
                        continue

                    # Checkout, to validate also on file level
                    ref = repo.create_reference('refs/tags/temp', commit)

                    # pygit2.GIT_CHECKOUT_FORCE | pygit2.GIT_CHECKOUT_RECREATE_MISSING
                    repo.checkout(ref, strategy=pygit2.GIT_CHECKOUT_FORCE | pygit2.GIT_CHECKOUT_RECREATE_MISSING)

                    # 3. Iterate foreach commit over the files

                    self.validate_Metric(path, db_commit, resultModel)

                    # Save the model
                    connections['default'].ensure_connection()
                    resultModel.save()
                    #if(resultModel.vcsSHARK == False):
                    #    print(resultModel.text)

                    # Reset repo to iterate over all commits
                    repo.reset(repo.head.target.hex, pygit2.GIT_RESET_HARD)
                    ref.delete()

                    print(' verification results: vcs ({}), coast ({}), meco ({})'.format(resultModel.vcsSHARK, resultModel.coastSHARK, resultModel.mecoSHARK))

        self.stdout.write("validation complete")

    # Plugins validation methods
    def validate_vcsSHARK(self, commit, repo, resultModel):
        globalResult = True
        resultModel.text = resultModel.text + "+++ vcsSHARK +++"
        unvalidated_file_actions_ids = []
        for db_file_action in self.db.file.find(
                {"commit_id": commit["_id"]}).batch_size(30):
            if db_file_action["_id"] not in unvalidated_file_actions_ids:
                unvalidated_file_actions_ids.append(db_file_action["_id"])

        validated_file_actions = 0  # counter for the validation

        repo_commit = repo.revparse_single(commit["revision_hash"])

        SIMILARITY_THRESHOLD = 50

        if repo_commit.parents:
            for parent in repo_commit.parents:
                diff = repo.diff(parent, repo_commit, context_lines=0,
                                 interhunk_lines=1)
                # almost the same as in the normal file_action creation
                opts = pygit2.GIT_DIFF_FIND_RENAMES | pygit2.GIT_DIFF_FIND_COPIES
                diff.find_similar(opts, SIMILARITY_THRESHOLD,
                                  SIMILARITY_THRESHOLD)

                already_checked_file_paths = set()
                for patch in diff:

                    # Only if the filepath was not processed before, add new file
                    if patch.delta.new_file.path in already_checked_file_paths:
                        continue

                    # Check change mode
                    mode = 'X'
                    if patch.delta.status == 1:
                        mode = 'A'
                    elif patch.delta.status == 2:
                        mode = 'D'
                    elif patch.delta.status == 3:
                        mode = 'M'
                    elif patch.delta.status == 4:
                        mode = 'R'
                    elif patch.delta.status == 5:
                        mode = 'C'
                    elif patch.delta.status == 6:
                        mode = 'I'
                    elif patch.delta.status == 7:
                        mode = 'U'
                    elif patch.delta.status == 8:
                        mode = 'T'

                    filepath = patch.delta.new_file.path

                    repo_file_action = {
                        "size_at_commit": patch.delta.new_file.size,
                        "lines_added": patch.line_stats[1],
                        "lines_deleted": patch.line_stats[2],
                        "is_binary": patch.delta.is_binary,
                        "mode": mode
                    }

                    already_checked_file_paths.add(patch.delta.new_file.path)

                    for db_file_action in self.db.file.find(
                            {"commit_id": commit["_id"]}).batch_size(5):

                        db_file = None

                        for file in self.db.file.find({"_id": db_file_action["file_id"]}):
                            db_file = file

                        if filepath == db_file["path"]:
                            if repo_file_action.items() <= db_file_action.items():
                                if db_file_action["_id"] in unvalidated_file_actions_ids:
                                    validated_file_actions += 1
                                    unvalidated_file_actions_ids.remove(db_file_action["_id"])
                                else:
                                    resultModel.text = resultModel.text + "\n File action missing!"
                                    globalResult = False

        else:
            diff = repo_commit.tree.diff_to_tree(context_lines=0, interhunk_lines=1)

            for patch in diff:

                filepath = patch.delta.new_file.path
                filemode = 'A'

                for db_file_action in self.db.file.find(
                        {"commit_id": commit["_id"]}).batch_size(5):

                    db_file = None

                    for file in self.db.file.find({"_id": db_file_action["file_id"]}).batch_size(
                            30):
                        db_file = file

                    # for initial commit file size and lines added never match but checking filepath should be enough
                    if (filepath != db_file["path"]) or (filemode != db_file_action["mode"]):
                        validated_file_actions += 1
                        unvalidated_file_actions_ids.remove(db_file_action["_id"])
                    else:
                        resultModel.text = resultModel.text + "\n File action missing!"
                        globalResult = False

        if(len(unvalidated_file_actions_ids) != 0):
            self.stderr.write("warning: {} file actions found in the database, but not in the repo!".format(len(unvalidated_file_actions_ids)))

        # self.stdout.write("validation of file actions : {} ".format(validated_file_actions))
        return globalResult

    # File level validation
    def validate_Metric(self, path, db_commit, resultModel):
        code_entity_state_coastSHARK = []
        code_entity_state_mecoSHARK = []

        list_code_entity = get_code_entities_from_database(self.db, db_commit, self.use_meme)

        for db_code_entity_state in list_code_entity:
            if db_code_entity_state["ce_type"] == 'file':
                self.validate_coastSHARK(db_code_entity_state, code_entity_state_coastSHARK)
                self.validate_mecoSHARK(db_code_entity_state, code_entity_state_mecoSHARK)

        # Validate on coastSHARK
        resultModel.text = resultModel.text + "\n +++ coastSHARK +++"
        resultModel.coastSHARK = self.validate_on_file_level(path, code_entity_state_coastSHARK, resultModel)

        # Validate mecoSHARK
        resultModel.text = resultModel.text + "\n +++ mecoSHARK +++"
        resultModel.mecoSHARK = self.validate_on_file_level(path, code_entity_state_mecoSHARK, resultModel)

    # File level validation
    def validate_coastSHARK(self, db_code_entity_state, code_entity_state_coastSHARK):
        if "node_count" in db_code_entity_state["metrics"]:
            if db_code_entity_state["metrics"]["node_count"] > 0:
                code_entity_state_coastSHARK.append(db_code_entity_state["long_name"])

    def validate_mecoSHARK(self, db_code_entity_state, code_entity_state_mecoSHARK):
        if "LOC" in db_code_entity_state["metrics"]:
            if db_code_entity_state["metrics"]["LOC"]:
                code_entity_state_mecoSHARK.append(db_code_entity_state["long_name"])

    def validate_on_file_level(self, path, unvalidated_code_entity_state_longnames, resultModel):
        globalResult = True
        for root, dirs, files in os.walk(path):
            for file in files:
                if file.lower().endswith('.java'):

                    filepath = os.path.join(root, file)
                    filepath = filepath.replace(path + "/", '')
                    if filepath in unvalidated_code_entity_state_longnames:
                        unvalidated_code_entity_state_longnames.remove(filepath)
                    else:
                        globalResult = False
                        resultModel.text = resultModel.text + "\n -" + str(filepath)

        return globalResult
