import pygit2, os, shutil, re, datetime


def map_database(db):
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

    for col in visited_collections:
        if col.name not in keymap:
            keymap[col.name] = []

    #print("collections in keymap:")
    #for key in keymap:
    #    print(key, ':', keymap[key])

    return keymap


def create_local_repo(vcsdoc, path):

    url = vcsdoc["url"]
    repourl = "git" + url[5:]
    if os.path.isdir(path):
        shutil.rmtree(path)

    repo = pygit2.clone_repository(repourl, path)

    return repo


def was_vcsshark_executed(vcs_col, proj_id):

    return vcs_col.find({"project_id": proj_id}).count() > 0


def validate_commits(repo, vcsdoc, commit_col):

    vcsid = vcsdoc["_id"]
    db_commit_hexs = []
    for db_commit in commit_col.find({"vcs_system_id": vcsid}):
        db_commit_hexs.append(db_commit["revision_hash"])
    total_commit_hexs = [] #db_commit_hexs.copy()

    db_commit_count = len(db_commit_hexs)
    commit_count = 0

    for commit in repo.walk(repo.head.target, pygit2.GIT_SORT_TIME):
        if commit.hex not in total_commit_hexs:
            time = datetime.datetime.utcfromtimestamp(commit.commit_time)
            if time < vcsdoc["last_updated"]:
                total_commit_hexs.append(commit.hex)
                commit_count += 1

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
                    commit_count += 1

    for tag in tags:
        commit = repo.lookup_reference(tag).peel()

        if commit.hex not in total_commit_hexs:
            time = datetime.datetime.utcfromtimestamp(commit.commit_time)
        if time < vcsdoc["last_updated"]:
            total_commit_hexs.append(commit.hex)
            commit_count += 1

        for child in repo.walk(commit.id, pygit2.GIT_SORT_TIME | pygit2.GIT_SORT_TOPOLOGICAL):
            if child.hex not in total_commit_hexs:
                time = datetime.datetime.utcfromtimestamp(child.commit_time)
                if time < vcsdoc["last_updated"]:
                    total_commit_hexs.append(child.hex)
                    commit_count += 1

    missing = set(total_commit_hexs) - set(db_commit_hexs)
    unmatched = set(db_commit_hexs) - set(total_commit_hexs)

    unmatched_commits = len(unmatched)
    missing_commits = len(missing)

    results = ""
    if unmatched_commits>0:
        results+= "unmatched commits: " + str(unmatched_commits) + " "
    if missing_commits>0:
        results+= "missing commits: " + str(missing_commits) + " "

    return results


def validate_file_action(repo, vcsid, commit_col, file_action_col, file_col):

    counter = 0
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

                    counter += 1

                    already_checked_file_paths.add(patch.delta.new_file.path)

                    for db_file_action in file_action_col.find(
                            {"commit_id": db_commit["_id"]}).batch_size(5):

                        db_file = None

                        # for file in db.file.find({"_id": db_file_action["file_id"]},
                        #                         no_cursor_timeout=True):
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

                counter += 1

                for db_file_action in file_action_col.find(
                        {"commit_id": db_commit["_id"]}).batch_size(5):

                    db_file = None

                    for file in file_col.find({"_id": db_file_action["file_id"]}).batch_size(
                            30):
                        db_file = file

                    identical = True

                    # for initial commit filesize and linesadded never match but checking filepath should be enough
                    if not filepath == db_file["path"]:
                        identical = False
                    if not filemode == db_file_action["mode"]:
                        identical = False

                    if identical:
                        validated_file_actions += 1
                        unvalidated_file_actions_ids.remove(db_file_action["_id"])

        unvalidated_file_actions += len(unvalidated_file_actions_ids)

    results = ""

    if unvalidated_file_actions>0:
        results+= "unmatched file_actions: " + str(unvalidated_file_actions) + " "
    if (file_action_counter - validated_file_actions)>0:
        results+= "missing file_actions: " + str((file_action_counter - validated_file_actions)) + " "

    return results


def was_coastshark_executed(vcsid, code_entity_state_col, commit_col, compressed=False):

    coastshark_executed = False

    for db_commit in commit_col.find({"vcs_system_id": vcsid}).batch_size(30):
        if compressed:
            if "code_entity_states" in db_commit:
                for code_entity_state in db_commit["code_entity_states"]:
                    if code_entity_state["metrics"]["node_count"] > 0:
                        coastshark_executed = True
                        return coastshark_executed
        else:
            if code_entity_state_col.find({"commit_id": db_commit["_id"]}).count() > 0:
                for code_entity_state in code_entity_state_col.find({"commit_id":db_commit["_id"]}):
                    if "node_count" in code_entity_state["metrics"]:
                        if code_entity_state["metrics"]["node_count"] > 0:
                            coastshark_executed = True
                            return coastshark_executed

    return coastshark_executed


def validate_code_entity_states(repo, vcsid, path, commit_col, code_entity_state_col, compressed=False):

    unvalidated_code_entity_states = 0
    total_code_entity_states = 0
    missing_code_entity_states = 0

    for db_commit in commit_col.find({"vcs_system_id": vcsid}).batch_size(30):

        commit = repo.get(db_commit["revision_hash"])
        commit_id = commit.hex
        ref = repo.create_reference('refs/tags/temp', commit_id)
        repo.checkout(ref)
        unvalidated_code_entity_state_longnames = []

        if compressed:
            for db_code_entity_state in db_commit["code_entity_states"]:
                if "node_count" in db_code_entity_state["metrics"]:
                    if db_code_entity_state["metrics"]["node_count"] > 0:
                        unvalidated_code_entity_state_longnames.append(
                            db_code_entity_state["long_name"])
        else:
            for db_code_entity_state in code_entity_state_col.find(
                    {"commit_id": db_commit["_id"]}):
                if "node_count" in db_code_entity_state["metrics"]:
                    if db_code_entity_state["metrics"]["node_count"]>0:
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

    results = ""

    if unvalidated_code_entity_states>0:
        results+= "unmatched code_entity_states: " + str(unvalidated_code_entity_states) + " "

    if missing_code_entity_states>0:
        results+= "missing code_entity_states: " + str(missing_code_entity_states) + " "

    return results


def delete_local_repo(path):

    if os.path.isdir(path):
        shutil.rmtree(path)

