from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin

from django.contrib.messages import get_messages
from django.contrib import messages

from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe

from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface
from smartshark.mongohandler import handler

from .views.collection import JobSubmissionThread
from .models import MongoRole, SmartsharkUser, Plugin, Argument, Project, Job, PluginExecution, ExecutionHistory, ProjectMongo
import pygit2, os, shutil, re, datetime, gc, timeit

admin.site.unregister(User)


class JobAdmin(admin.ModelAdmin):
    list_display = ('job_id', 'plugin_execution', 'status', 'revision_hash')
    list_filter = ('plugin_execution__project', 'plugin_execution__plugin', 'status', 'plugin_execution__execution_type')
    search_fields = ('revision_hash',)

    actions = ['restart_job', 'set_exit', 'set_done', 'set_job_stati']

    def set_job_stati(self, request, queryset):
        interface = PluginManagementInterface.find_correct_plugin_manager()
        job_stati = interface.get_job_stati(queryset)
        i = 0
        for job in queryset:
            job.status = job_stati[i]
            job.save()
            i += 1
        messages.info(request, 'Job stati set from backend.')

    def set_exit(self, request, queryset):
        for job in queryset:
            job.status = 'EXIT'
            job.save()
        messages.info(request, 'Jobs set to EXIT.')

    def set_done(self, request, queryset):
        for job in queryset:
            job.status = 'DONE'
            job.save()
        messages.info(request, 'Jobs set to DONE.')

    def restart_job(self, request, queryset):
        repeated_plugin_executions = {}

        # add jobs to list for each separate plugin_execution
        for job in queryset:
            if job.plugin_execution.pk not in repeated_plugin_executions.keys():
                repeated_plugin_executions[job.plugin_execution.pk] = []

            repeated_plugin_executions[job.plugin_execution.pk].append(job)

        for old_pk, jobs in repeated_plugin_executions.items():

            # generate new plugin_execution objects
            new_plugin_execution = PluginExecution.objects.get(pk=old_pk)
            new_plugin_execution.pk = None
            new_plugin_execution.save()

            # create new execution history objects based on the old
            for eh in ExecutionHistory.objects.filter(plugin_execution__pk=old_pk):
                new_eh = ExecutionHistory.objects.get(pk=eh.pk)
                new_eh.pk = None
                new_eh.plugin_execution = new_plugin_execution
                new_eh.save()

            for old_job in jobs:
                new_job = Job.objects.get(pk=old_job.pk)
                new_job.pk = None
                new_job.plugin_execution = new_plugin_execution
                new_job.status = 'WAIT'
                new_job.save()

            thread = JobSubmissionThread(new_plugin_execution.project, [new_plugin_execution], create_jobs=False)
            thread.start()

    restart_job.short_description = 'Restart jobs'
    set_job_stati.short_description = 'Set job status from backend'


class PluginExecutionAdmin(admin.ModelAdmin):
    list_display = ('plugin', 'project', 'repository_url', 'execution_type', 'submitted_at')

    actions = ['restart_plugin_execution']

    def restart_plugin_execution(self, request, queryset):
        for pe in queryset:
            # create new plugin_execution with same values
            plugin_execution = PluginExecution.objects.get(pk=pe.pk)
            plugin_execution.pk = None
            plugin_execution.save()

            # rewrite execution history for arguments and new plugin_execution
            for eh in ExecutionHistory.objects.filter(plugin_execution=pe):
                ehn = ExecutionHistory.objects.get(pk=eh.pk)
                ehn.pk = None
                ehn.plugin_execution = plugin_execution
                ehn.save()

            thread = JobSubmissionThread(plugin_execution.project, [plugin_execution])
            thread.start()
        messages.info(request, 'Plugin execution restarted.')

    restart_plugin_execution.short_description = 'Restart plugin execution'


class MyUserAdmin(UserAdmin):
    def get_readonly_fields(self, request, obj=None):
        """
        Do not allow changing of account once created
        """
        if obj:
            return self.readonly_fields + ('username',)
        return self.readonly_fields


class MongoModelAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}


class SmartsharkUserAdmin(admin.ModelAdmin):
    readonly_fields = ('user', )
    fields = ('user', 'roles')


class ArgumentAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}


class ArgumentInline(admin.TabularInline):
    model = Argument
    extra = 0
    fields = ('name', 'install_value', 'plugin')
    readonly_fields = ('name', 'install_value')
    show_change_link = False
    can_delete = False
    verbose_name = 'Install Argument'
    verbose_name_plural = 'Install Arguments'

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = super(ArgumentInline, self).get_queryset(request)
        return qs.filter(type='install')


class PluginAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'description', 'plugin_type', 'active', 'installed')
    actions = ('delete_model', 'install_plugin')
    inlines = (ArgumentInline, )

    def get_formsets_with_inlines(self, request, obj=None):
        for inline in self.get_inline_instances(request, obj):
            # hide ArgumentInline in the add view
            if isinstance(inline, ArgumentInline) and obj is None:
                continue
            yield inline.get_formset(request, obj), inline

    # A little hack to remove the plugin deleted successfully message
    def changelist_view(self, request, extra_context=None):

        storage = get_messages(request)
        all_messages = list(get_messages(request))

        # Go through all messages and delete the one that the plugin was successfully deleted (this may not be the case)
        for i in range(0, len(all_messages)):
            if storage._loaded_messages[i].message.startswith('The plugin "'):
                del storage._loaded_messages[i]

        return super(PluginAdmin, self).changelist_view(request, extra_context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        """
        If plugin is changed, we need to check if the required plugins that may be added/changed are still valid
        :param request: django request
        :param object_id: id of the plugin that is to be changed
        :param form_url: url of the form that is used
        :param extra_context: possible extra content
        :return: redirect to the plugin changed page if not successful
        """
        if request.method == 'POST':
            changed_plugin = get_object_or_404(Plugin, pk=object_id)
            required_plugins = request.POST.getlist('requires')

            if len(required_plugins) != len(changed_plugin.get_required_plugins()):
                messages.error(request, 'Number of required plugins are not matching!')
                return redirect(request.get_full_path())

            for req_plugin_id in required_plugins:
                req_plugin = get_object_or_404(Plugin, pk=req_plugin_id)

                try:
                    changed_plugin.validate_required_plugins(req_plugin)
                except ValidationError as e:
                    messages.error(request, str(e))
                    return redirect(request.get_full_path())

        return super(PluginAdmin, self).change_view(request, object_id, form_url, extra_context)

    def get_fields(self, request, obj=None):
        if not obj:
            return 'archive',
        else:
            return 'name', 'author', 'version', 'description', 'plugin_type', 'archive', 'requires', 'active', \
                   'installed', 'linux_libraries'

    def get_readonly_fields(self, request, obj=None):
        if not obj:
            return 'name', 'author', 'version', 'description',  'plugin_type', 'installed', 'linux_libraries'
        else:
            return 'name', 'author', 'version', 'description', 'plugin_type', 'archive', 'installed', 'linux_libraries'

    def get_actions(self, request):
        actions = super(PluginAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def save_model(self, request, obj, form, change):
        """
        We need to overwrite this method, as for a change: we just save the model, but if the plugin is first
        added, it must be loaded from the json file in the archive.
        :param request:
        :param obj:
        :param form:
        :param change:
        :return:
        """
        if change:
            obj.save()
        else:
            plugin = Plugin()
            plugin.load_from_json(request.FILES['archive'])

    def install_plugin(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect("/smartshark/plugin/install/?ids=%s" % (",".join(selected)))

    def delete_model(self, request, obj):

        if isinstance(obj, Plugin):
            obj = [obj]

        # For all plugins that are marked to delete
        for plugin in obj:
            plugins = Plugin.objects.all().filter(requires=plugin)
            successful = True

            # Go through all plugins that require the plugin that is marked for deletion
            for requires_this_plugin in plugins:
                # If there are no problems with substitutions, go on, otherwise set successful to False
                if requires_this_plugin.get_substitution_plugin_for(plugin) is None:
                    successful = False

            # If we are not successful, we can not delete this plugin, because the requirements can not be met
            if not successful:
                messages.error(request, 'Could not delete plugin, because it is required by other plugins '
                                        'and requirements can not be matched otherwise!')

            # Otherwise, we need to go through all plugins that require this plugin again to substitute the requires
            else:
                plugin.delete()
                for requires_this_plugin in plugins:
                    fitting_plugin = requires_this_plugin.get_substitution_plugin_for(plugin)
                    requires_this_plugin.requires.add(fitting_plugin)

    delete_model.short_description = 'Delete Plugin(s)'
    install_plugin.short_description = 'Install Plugin(s)'


class ProjectAdmin(admin.ModelAdmin):
    fields = ('name', 'mongo_id')
    list_display = ('name', 'mongo_id', 'plugin_executions')
    readonly_fields = ('mongo_id', )
    actions = ['start_collection', 'show_executions', 'register_ProjectMongo']

    def get_readonly_fields(self, request, obj=None):
        """
        Do not allow changing of account once created
        """
        if obj:
            return self.readonly_fields + ('name', 'url')
        return self.readonly_fields

    def plugin_executions(self, obj):
        return mark_safe('<a class="btn btn-info" href="%s">Plugin Executions</a>' %
                         reverse('plugin_status', kwargs={'id': obj.id}))

    def start_collection(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect("/smartshark/project/collection/choose/?ids=%s" % (",".join(selected)))

    start_collection.short_description = 'Start Collection for selected Projects'

    def register_ProjectMongo(self, request, queryset):
        for proj in queryset:
            try:
                proj.projectmongo
            except ObjectDoesNotExist:
                ProjectMongo.objects.create(project=proj)
                print("Added ProjectMongo for " + proj.name)


class ProjectMongoAdmin(admin.ModelAdmin):
    list_display = ('project', 'executed_plugins','validation')
    actions = ['crawler']

    def crawler(self, request, queryset):
        mongoclient = handler.client
        db = mongoclient.smartshark
        plugin_schema = db.plugin_schema

        project_db = db.project
        open_collections = []
        open_collections.append(project_db)
        visited_collections = []
        # keymap saves the collections that can be reached from the key as values
        keymap = dict()

        # builds the keymap for the mongodb
        while (len(open_collections) != 0):

            current_collection = open_collections.pop()
            for doc in plugin_schema.find():
                for subdoc in doc["collections"]:
                    for subsubdoc in subdoc["fields"]:
                        if "reference_to" in subsubdoc:
                            if (subsubdoc["reference_to"] == current_collection.name):
                                found_collection = db[subdoc["collection_name"]]
                                if not (found_collection in open_collections):
                                    if not (found_collection in visited_collections):
                                        open_collections.append(found_collection)
                                        if current_collection.name in keymap:
                                            keymap[current_collection.name].append(found_collection.name)
                                        else:
                                            keymap[current_collection.name] = [found_collection.name]

            visited_collections.append(current_collection)

        # for some reason issue collection appears twice so I put up another filter
        final_collections = []
        for col in visited_collections:
                if col not in final_collections:
                    final_collections.append(col)


        for col in final_collections:
            if col.name not in keymap:
                keymap[col.name] = []

        # print out the detected database structure, this can be used for debugging
        # print("collections in keymap:")
        # for key in keymap:
        #     print(key, ':', keymap[key])

        # free memory after mapping is done
        del open_collections, visited_collections, final_collections, doc, subdoc ,subsubdoc
        gc.collect()

        for projmongo in queryset:
            proj = projmongo.project

            start = timeit.default_timer()
            print("Starting validation for " + proj.name)

            if (project_db.find({"name": proj.name}).count() > 0):

                projdoc = project_db.find_one({"name": proj.name})

                if "vcs_system" in keymap:

                    if (db.vcs_system.find({"project_id": projdoc["_id"]}).count() > 0):

                        vcsdoc = db.vcs_system.find_one({"project_id": projdoc["_id"]})

                        url = vcsdoc["url"]
                        vcsid = vcsdoc["_id"]
                        projmongo.vcs_id = vcsid
                        projmongo.executed_plugins = "vcsSHARK"

                        repourl = "git" + url[5:]

                        path = "../tmp-repo"
                        if os.path.isdir(path):
                            shutil.rmtree(path)

                        repo = pygit2.clone_repository(repourl,path)

                        if not repo.is_empty:

                            db_commit_hexs = []
                            for db_commit in db.commit.find({"vcs_system_id": vcsid}):
                                db_commit_hexs.append(db_commit["revision_hash"])
                            total_commit_hexs = db_commit_hexs.copy()

                            db_commit_count = len(db_commit_hexs)
                            commit_count = 0

                            for commit in repo.walk(repo.head.target, pygit2.GIT_SORT_TIME):
                                if not commit.hex in total_commit_hexs:
                                    time = datetime.datetime.utcfromtimestamp(commit.commit_time)
                                    if time < vcsdoc["last_updated"]:
                                        total_commit_hexs.append(commit.hex)
                                        commit_count+=1

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
                                    if not child.hex in total_commit_hexs:
                                        time = datetime.datetime.utcfromtimestamp(child.commit_time)
                                        if time < vcsdoc["last_updated"]:
                                            total_commit_hexs.append(child.hex)
                                            commit_count += 1

                            for hex in total_commit_hexs:
                                if hex in db_commit_hexs:
                                    db_commit_hexs.remove(hex)

                            projmongo.validation = ("commits in db: " + str(db_commit_count) + " unmatched commits: " + str(len(db_commit_hexs)))

                            # total_commit_hexs won't be needed anymore and memory can be freed
                            del total_commit_hexs
                            gc.collect()

                            # validate fileactions
                            if "file_action" in keymap:

                                counter = 0
                                validated_file_actions = 0

                                unvalidated_file_actions = 0

                                for db_commit in db.commit.find({"vcs_system_id": vcsid}):

                                    unvalidated_file_actions_ids = []
                                    for db_file_action in db.file_action.find(
                                            {"commit_id": db_commit["_id"]}):
                                        if not db_file_action["_id"] in unvalidated_file_actions_ids:
                                            unvalidated_file_actions_ids.append(db_file_action["_id"])


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
                                                filesize = patch.delta.new_file.size
                                                linesadded = patch.line_stats[1]
                                                linesremoved = patch.line_stats[2]
                                                fileisbinary = patch.delta.is_binary
                                                filemode = mode

                                                counter+= 1

                                                already_checked_file_paths.add(patch.delta.new_file.path)

                                                for db_file_action in db.file_action.find(
                                                        {"commit_id": db_commit["_id"]}).batch_size(30):

                                                    db_file = db.file.find_one({"_id": db_file_action["file_id"]})

                                                    identical = True

                                                    if not filepath == db_file["path"]:
                                                        identical = False
                                                    if not filesize == db_file_action["size_at_commit"]:
                                                        identical = False
                                                    if not linesadded == db_file_action["lines_added"]:
                                                        identical = False
                                                    if not linesremoved == db_file_action["lines_deleted"]:
                                                        identical = False
                                                    if not fileisbinary == db_file_action["is_binary"]:
                                                        identical = False
                                                    if not filemode == db_file_action["mode"]:
                                                        identical = False

                                                    if identical:
                                                        if db_file_action["_id"] in unvalidated_file_actions_ids:
                                                            validated_file_actions += 1
                                                            unvalidated_file_actions_ids.remove(db_file_action["_id"])

                                    else:
                                        diff = online_commit.tree.diff_to_tree(context_lines=0, interhunk_lines=1)

                                        for patch in diff:

                                            filepath = patch.delta.new_file.path
                                            filesize = patch.delta.new_file.size
                                            linesadded = patch.line_stats[1]
                                            linesremoved = patch.line_stats[2]
                                            fileisbinary = patch.delta.is_binary
                                            filemode = 'A'

                                            counter+= 1

                                            for db_file_action in db.file_action.find({"commit_id": db_commit["_id"]}).batch_size(30):

                                                db_file = db.file.find_one({"_id": db_file_action["file_id"]})

                                                identical = True

                                                #for initial commit filesize and linesadded never match but checking filepath should be enough
                                                if not filepath == db_file["path"]:
                                                    identical = False
                                                #if not fileisbinary == db_file_action["is_binary"]:
                                                #    identical = False
                                                if not filemode == db_file_action["mode"]:
                                                    identical = False

                                                if identical:
                                                    validated_file_actions += 1
                                                    unvalidated_file_actions_ids.remove(db_file_action["_id"])

                                    unvalidated_file_actions+= len(unvalidated_file_actions_ids)


                                projmongo.validation+=(" file_actions found: " + str(counter) + " unvalidated file_actions: " + str(unvalidated_file_actions))

                            # validate coastshark's code_entity_states
                            if "code_entity_state" in keymap:

                                unvalidated_code_entity_states = 0
                                total_code_entity_states = 0
                                #head_ref = repo.head.target
                                #head = repo.get(head_ref)
                                coastshark_executed = False

                                for db_commit in db.commit.find({"vcs_system_id": vcsid}):

                                    # print(db_commit["message"])
                                    commit = repo.get(db_commit["revision_hash"])
                                    commit_id = commit.hex
                                    ref = repo.create_reference('refs/tags/temp', commit_id)
                                    repo.checkout(ref)

                                    for db_code_entity_state in db.code_entity_state.find(
                                            {"commit_id": db_commit["_id"]}):
                                        validated = False

                                        for root, dirs, files in os.walk(path):

                                            for file in files:

                                                #if file.endswith('.py') or file.endswith('.java'):

                                                filepath = os.path.join(root, file)
                                                filepath = filepath.replace(path +"/", '')
                                                #print(file)
                                                    #print(filepath + " " + db_code_entity_state["long_name"])
                                                if filepath == db_code_entity_state["long_name"]:
                                                    validated = True
                                                    #print(filepath + " == " + db_code_entity_state["long_name"])
                                                    coastshark_executed = True

                                        if not validated:
                                            unvalidated_code_entity_states+=1
                                            #print("unvalidated: " + db_code_entity_state["long_name"])
                                        total_code_entity_states+=1

                                    repo.reset(repo.head.target.hex, pygit2.GIT_RESET_HARD)
                                    ref.delete()

                                #print("unvalidated_code_entity_states: " + str(unvalidated_code_entity_states))
                                projmongo.validation+= (" code_entity_states found: " + str(total_code_entity_states) + " unvalidated code_entity_states: " + str(unvalidated_code_entity_states))
                                #print("total_commit_hexs: " + str(total_code_entity_states))

                                if coastshark_executed:
                                    projmongo.executed_plugins+=(", coastSHARK")

                        if os.path.isdir(path):
                            shutil.rmtree(path)

                    projmongo.save()

            else:
                print(proj.name + " not found in database")

            end = timeit.default_timer() - start
            print("Finished validation for " + proj.name + " in {:.5f}s".format(end))

    crawler.short_description = 'Validate Data'


admin.site.register(ProjectMongo, ProjectMongoAdmin)
admin.site.register(User, MyUserAdmin)
admin.site.register(SmartsharkUser, SmartsharkUserAdmin)
admin.site.register(MongoRole, MongoModelAdmin)
admin.site.register(Plugin, PluginAdmin)
admin.site.register(Argument, ArgumentAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Job, JobAdmin)
admin.site.register(PluginExecution, PluginExecutionAdmin)