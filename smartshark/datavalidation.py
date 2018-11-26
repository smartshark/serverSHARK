import pygit2, os, shutil, re, datetime
from .models import CommitValidation


def map_database(db, print_map=False):
    # performs a breadth search to find all collections and how they can be traversed down from project
    keymap = dict()
    plugin_schema = db.plugin_schema
    project_db = db.project

    open_collections = []
    open_collections.append(project_db)
    visited_collections = []

    while (len(open_collections) != 0):

        current_collection = open_collections.pop()
        for doc in plugin_schema.find():
            for subdoc in doc["collections"]:
                for subsubdoc in subdoc["fields"]:
                    if "reference_to" in subsubdoc:
                        if (subsubdoc["reference_to"] == current_collection.name):
                            found_collection = db[subdoc["collection_name"]]
                            if found_collection not in open_collections:
                                if found_collection not in visited_collections:
                                    if not found_collection == current_collection:
                                        open_collections.append(found_collection)
                                        if current_collection.name in keymap.keys():
                                            keymap[current_collection.name].append(found_collection.name)
                                        else:
                                            keymap[current_collection.name] = [found_collection.name]

        visited_collections.append(current_collection)
    # adds all collections which do not have any further collections attached to them
    for col in visited_collections:
        if col.name not in keymap:
            keymap[col.name] = []

    # option to print out the current database structure
    if print_map:
        print("collections in keymap:")
        for key in keymap:
            print(key, ':', keymap[key])

    return keymap


def create_local_repo(vcsdoc, path):
    url = vcsdoc["url"]
    # removes the https and replaces it with git
    repo_url = "git" + url[5:]
    if os.path.isdir(path):
        shutil.rmtree(path)

    repo = pygit2.clone_repository(repo_url, path)

    return repo


def was_vcsshark_executed(vcs_col, proj_id):
    return vcs_col.find({"project_id": proj_id}).count() > 0


def validate_commits(repo, vcsdoc, commit_col, projectmongo):
    vcsid = vcsdoc["_id"]
    db_commit_hexs = []
    for db_commit in commit_col.find({"vcs_system_id": vcsid}):
        db_commit_hexs.append(db_commit["revision_hash"])
    total_commit_hexs = []

    for commit in repo.walk(repo.head.target, pygit2.GIT_SORT_TIME):
        if commit.hex not in total_commit_hexs:
            time = datetime.datetime.utcfromtimestamp(commit.commit_time)
            if time < vcsdoc["last_updated"]:
                total_commit_hexs.append(commit.hex)

    # inspired by vcsshark gitparser.py
    references = set(repo.listall_references())

    regex = re.compile('^refs/tags')
    tags = set(filter(lambda r: regex.match(r), repo.listall_references()))

    branches = references - tags

    for branch in branches:
        commit = repo.lookup_reference(branch).peel()
        # Walk through every child
        for child in repo.walk(commit.id,
                               pygit2.GIT_SORT_TIME | pygit2.GIT_SORT_TOPOLOGICAL):
            if child.hex not in total_commit_hexs:
                time = datetime.datetime.utcfromtimestamp(child.commit_time)
                if time < vcsdoc["last_updated"]:
                    total_commit_hexs.append(child.hex)

    for tag in tags:
        commit = repo.lookup_reference(tag).peel()

        if commit.hex not in total_commit_hexs:
            time = datetime.datetime.utcfromtimestamp(commit.commit_time)
        if time < vcsdoc["last_updated"]:
            total_commit_hexs.append(commit.hex)

        for child in repo.walk(commit.id, pygit2.GIT_SORT_TIME | pygit2.GIT_SORT_TOPOLOGICAL):
            if child.hex not in total_commit_hexs:
                time = datetime.datetime.utcfromtimestamp(child.commit_time)
                if time < vcsdoc["last_updated"]:
                    total_commit_hexs.append(child.hex)

    missing = set(total_commit_hexs) - set(db_commit_hexs)
    unmatched = set(db_commit_hexs) - set(total_commit_hexs)

    unmatched_commits = len(unmatched)
    missing_commits = len(missing)

    # create or update the commitvalidation object for each commit
    make_commitvalidations(unmatched, projectmongo=projectmongo, valid=False, missing=False)
    make_commitvalidations(missing, projectmongo=projectmongo, valid=True, missing=True)
    make_commitvalidations((set(total_commit_hexs) - missing), projectmongo=projectmongo, valid=True, missing=False)

    results = ""
    if unmatched_commits > 0:
        results += "unmatched commits: " + str(unmatched_commits) + " "
    if missing_commits > 0:
        results += "missing commits: " + str(missing_commits) + " "

    return results


def make_commitvalidations(commits, projectmongo, valid, missing):
    # using this filter has proven to be faster then just running update_or_create for everything
    for commit in list(commits):
        if CommitValidation.objects.filter(projectmongo=projectmongo, revision_hash__exact=commit, valid=valid,
                                           missing=missing).exists():
            commits.remove(commit)
    for commit in commits:
        CommitValidation.objects.update_or_create(projectmongo=projectmongo, revision_hash=commit,
                                                  defaults={'valid': valid, 'missing': missing})


def validate_file_action(repo, vcsid, commit_col, file_action_col, file_col):
    file_action_counter = 0
    validated_file_actions = 0

    unvalidated_file_actions = 0

    for db_commit in commit_col.find({"vcs_system_id": vcsid}).batch_size(30):

        unvalidated_file_actions_ids = []
        for db_file_action in file_action_col.find(
                {"commit_id": db_commit["_id"]}).batch_size(30):
            if db_file_action["_id"] not in unvalidated_file_actions_ids:
                unvalidated_file_actions_ids.append(db_file_action["_id"])
        file_action_counter += len(unvalidated_file_actions_ids)

        hex = db_commit["revision_hash"]

        online_commit = repo.revparse_single(hex)

        SIMILARITY_THRESHOLD = 50

        filepath = ''
        filesize = 0
        linesadded = 0
        linesremoved = 0
        fileisbinary = None
        filemode = ''

        if online_commit.parents:
            for parent in online_commit.parents:
                diff = repo.diff(parent, online_commit, context_lines=0,
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

                    for db_file_action in file_action_col.find(
                            {"commit_id": db_commit["_id"]}).batch_size(5):

                        db_file = None

                        for file in file_col.find({"_id": db_file_action["file_id"]}):
                            db_file = file

                        identical = False

                        if filepath == db_file["path"]:
                            if repo_file_action.items() <= db_file_action.items():
                                identical = True

                        if identical:
                            if db_file_action["_id"] in unvalidated_file_actions_ids:
                                validated_file_actions += 1
                                unvalidated_file_actions_ids.remove(db_file_action["_id"])

        else:
            diff = online_commit.tree.diff_to_tree(context_lines=0, interhunk_lines=1)

            for patch in diff:

                filepath = patch.delta.new_file.path
                filemode = 'A'

                for db_file_action in file_action_col.find(
                        {"commit_id": db_commit["_id"]}).batch_size(5):

                    db_file = None

                    for file in file_col.find({"_id": db_file_action["file_id"]}).batch_size(
                            30):
                        db_file = file

                    identical = True

                    # for initial commit file size and lines added never match but checking filepath should be enough
                    if not filepath == db_file["path"]:
                        identical = False
                    if not filemode == db_file_action["mode"]:
                        identical = False

                    if identical:
                        validated_file_actions += 1
                        unvalidated_file_actions_ids.remove(db_file_action["_id"])

        unvalidated_file_actions += len(unvalidated_file_actions_ids)

    results = ""

    if unvalidated_file_actions > 0:
        results += "unmatched file_actions: " + str(unvalidated_file_actions) + " "
    if (file_action_counter - validated_file_actions) > 0:
        results += "missing file_actions: " + str((file_action_counter - validated_file_actions)) + " "

    return results


def was_coastshark_executed(vcsid, code_entity_state_col, commit_col, compressed=False):
    coastshark_executed = False
    # search until the first code_entity_state with coastshark specific data was found
    for db_commit in commit_col.find({"vcs_system_id": vcsid}).batch_size(30):
        if compressed:
            if "code_entity_states" in db_commit:
                for code_entity_state in db_commit["code_entity_states"]:
                    if "node_count" in code_entity_state["metrics"]:
                        if code_entity_state["metrics"]["node_count"] > 0:
                            coastshark_executed = True
                            return coastshark_executed
        else:
            if code_entity_state_col.find({"commit_id": db_commit["_id"]}).count() > 0:
                for code_entity_state in code_entity_state_col.find({"commit_id": db_commit["_id"]}):
                    if "node_count" in code_entity_state["metrics"]:
                        if code_entity_state["metrics"]["node_count"] > 0:
                            coastshark_executed = True
                            return coastshark_executed

    return coastshark_executed


def was_mecoshark_executed(vcsid, code_entity_state_col, commit_col, compressed=False):
    mecoshark_executed = False
    # search until the first code_entity_state with mecoshark specific data was found
    for db_commit in commit_col.find({"vcs_system_id": vcsid}).batch_size(30):
        if compressed:
            if "code_entity_states" in db_commit:
                for code_entity_state in db_commit["code_entity_states"]:
                    if "McCC" in code_entity_state["metrics"]:
                        if code_entity_state["metrics"]["McCC"]:
                            mecoshark_executed = True
                            return mecoshark_executed
        else:
            if code_entity_state_col.find({"commit_id": db_commit["_id"]}).count() > 0:
                for code_entity_state in code_entity_state_col.find({"commit_id": db_commit["_id"]}):
                    if "McCC" in code_entity_state["metrics"]:
                        if code_entity_state["metrics"]["McCC"]:
                            mecoshark_executed = True
                            return mecoshark_executed

    return mecoshark_executed


def validate_coast_code_entity_states(repo, vcsid, path, commit_col, code_entity_state_col, projectmongo,
                                      compressed=False):
    unvalidated_code_entity_states = 0
    total_code_entity_states = 0
    missing_code_entity_states = 0
    # for every code_entity_state checks the values and saves the longname
    # after repo checkout for the current commit the files are checked against the list of longnames
    for db_commit in commit_col.find({"vcs_system_id": vcsid}).batch_size(30):

        valid = False
        missing = True

        missing_so_far = missing_code_entity_states

        commit = repo.get(db_commit["revision_hash"])
        commit_id = commit.hex
        ref = repo.create_reference('refs/tags/temp', commit_id)
        repo.checkout(ref)
        unvalidated_code_entity_state_longnames = []

        if compressed:
            for db_code_entity_state in db_commit["code_entity_states"]:
                if db_code_entity_state["ce_type"] == 'file':
                    if "node_count" in db_code_entity_state["metrics"]:
                        if db_code_entity_state["metrics"]["node_count"] > 0:
                            unvalidated_code_entity_state_longnames.append(
                                db_code_entity_state["long_name"])
        else:
            for db_code_entity_state in code_entity_state_col.find(
                    {"commit_id": db_commit["_id"]}):
                if db_code_entity_state["ce_type"] == 'file':
                    if "node_count" in db_code_entity_state["metrics"]:
                        if db_code_entity_state["metrics"]["node_count"] > 0:
                            unvalidated_code_entity_state_longnames.append(
                                db_code_entity_state["long_name"])

        total_code_entity_states += len(unvalidated_code_entity_state_longnames)

        for root, dirs, files in os.walk(path):

            for file in files:

                if file.endswith('.py') or file.endswith('.java'):

                    filepath = os.path.join(root, file)
                    filepath = filepath.replace(path + "/", '')
                    if filepath in unvalidated_code_entity_state_longnames:
                        unvalidated_code_entity_state_longnames.remove(filepath)
                    else:
                        missing_code_entity_states += 1

        unvalidated_code_entity_states += len(unvalidated_code_entity_state_longnames)

        repo.reset(repo.head.target.hex, pygit2.GIT_RESET_HARD)
        ref.delete()

        if len(unvalidated_code_entity_state_longnames) == 0:
            valid = True
        if missing_code_entity_states == missing_so_far:
            missing = False
        update_coast_commitvalidation(db_commit["revision_hash"], projectmongo, valid, missing)

    results = ""

    if unvalidated_code_entity_states > 0:
        results += "unmatched coast code_entity_states: " + str(unvalidated_code_entity_states) + " "

    if missing_code_entity_states > 0:
        results += "missing coast code_entity_states: " + str(missing_code_entity_states) + " "

    return results


def validate_meco_code_entity_states(repo, vcsid, path, commit_col, code_entity_state_col, projectmongo,
                                     compressed=False):
    unvalidated_code_entity_states = 0
    total_code_entity_states = 0
    missing_code_entity_states = 0
    # for every code_entity_state checks the values and saves the longname
    # after repo checkout for the current commit the files are checked against the list of longnames
    for db_commit in commit_col.find({"vcs_system_id": vcsid}).batch_size(30):

        valid = False
        missing = True

        missing_so_far = missing_code_entity_states

        commit = repo.get(db_commit["revision_hash"])
        commit_id = commit.hex
        ref = repo.create_reference('refs/tags/temp', commit_id)
        repo.checkout(ref)
        unvalidated_code_entity_state_longnames = []

        if compressed:
            for db_code_entity_state in db_commit["code_entity_states"]:
                if db_code_entity_state["ce_type"] == 'file':
                    if "McCC" in db_code_entity_state["metrics"]:
                        if db_code_entity_state["metrics"]["McCC"]:
                            unvalidated_code_entity_state_longnames.append(
                                db_code_entity_state["long_name"])
        else:
            for db_code_entity_state in code_entity_state_col.find(
                    {"commit_id": db_commit["_id"]}):
                if db_code_entity_state["ce_type"] == 'file':
                    if "McCC" in db_code_entity_state["metrics"]:
                        if db_code_entity_state["metrics"]["McCC"]:
                            unvalidated_code_entity_state_longnames.append(
                                db_code_entity_state["long_name"])

        total_code_entity_states += len(unvalidated_code_entity_state_longnames)

        for root, dirs, files in os.walk(path):

            for file in files:
                # TODO add support for C and C++ file extensions
                if file.endswith('.py') or file.endswith('.java'):

                    filepath = os.path.join(root, file)
                    filepath = filepath.replace(path + "/", '')
                    if filepath in unvalidated_code_entity_state_longnames:
                        unvalidated_code_entity_state_longnames.remove(filepath)
                    else:
                        missing_code_entity_states += 1

        unvalidated_code_entity_states += len(unvalidated_code_entity_state_longnames)

        repo.reset(repo.head.target.hex, pygit2.GIT_RESET_HARD)
        ref.delete()

        if len(unvalidated_code_entity_state_longnames) == 0:
            valid = True
        if missing_code_entity_states == missing_so_far:
            missing = False
        update_meco_commitvalidation(db_commit["revision_hash"], projectmongo, valid, missing)

    results = ""

    if unvalidated_code_entity_states > 0:
        results += "unmatched meco code_entity_states: " + str(unvalidated_code_entity_states) + " "

    if missing_code_entity_states > 0:
        results += "missing meco code_entity_states: " + str(missing_code_entity_states) + " "

    return results


def update_coast_commitvalidation(hash, projectmongo, valid, missing):
    # print("updating coast commitvalidation valid: " + str(valid)+ " missing: " + str(missing))
    if not CommitValidation.objects.filter(revision_hash__exact=hash, projectmongo=projectmongo, coast_valid=valid,
                                           coast_missing=missing).exists():
        CommitValidation.objects.filter(revision_hash__exact=hash, projectmongo=projectmongo).update(coast_valid=valid,
                                                                                                     coast_missing=missing)


def update_meco_commitvalidation(hash, projectmongo, valid, missing):
    if not CommitValidation.objects.filter(revision_hash__exact=hash, projectmongo=projectmongo, meco_valid=valid,
                                           meco_missing=missing).exists():
        CommitValidation.objects.filter(revision_hash__exact=hash, projectmongo=projectmongo).update(meco_valid=valid,
                                                                                                     meco_missing=missing)


def delete_local_repo(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
