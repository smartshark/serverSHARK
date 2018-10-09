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
import pygit2, os, shutil, re

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
    list_display = ('project', 'validation')
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
                        #print(current_collection.name + "_id")
                        #if current_collection.name + "_id" in subsubdoc:
                            if (subsubdoc["reference_to"] == current_collection.name):
                            #if (subsubdoc[current_collection.name + "_id"] == current_collection.name + "_id"):
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

        print("collections in keymap:")
        for key in keymap:
            print(key, ':', keymap[key])

        for projmongo in queryset:
            proj = projmongo.project

            if (project_db.find({"name": proj.name}).count() > 0):

                projdoc = project_db.find_one({"name": proj.name})

                if "vcs_system" in keymap:

                    if (db.vcs_system.find({"project_id": projdoc["_id"]}).count() > 0):

                        vcsdoc = db.vcs_system.find_one({"project_id": projdoc["_id"]})

                        url = vcsdoc["url"]
                        vcsid = vcsdoc["_id"]

                        repourl = "git" + url[5:]

                        path = "../tmp-repo"
                        if os.path.isdir(path):
                            shutil.rmtree(path)

                        repo = pygit2.clone_repository(repourl,path)

                        if not repo.is_empty:

                            print(proj.name + " is not empty")

                            db_commit_hexs = []
                            for db_commit in db.commit.find({"vcs_system_id": vcsid}):
                                db_commit_hexs.append(db_commit["revision_hash"])
                            total_commit_hexs = db_commit_hexs.copy()

                            db_commit_count = len(db_commit_hexs)
                            commit_count = 0

                            for commit in repo.walk(repo.head.target, pygit2.GIT_SORT_TIME):
                                # print(commit.message)
                                #if commit.hex in db_commit_hexs:
                                #    db_commit_hexs.remove(commit.hex)
                                    # print("removed " + commit.hex)
                                if not commit.hex in total_commit_hexs:
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
                                    #if child.hex in db_commit_hexs:
                                    #    db_commit_hexs.remove(child.hex)
                                    if not child.hex in total_commit_hexs:
                                        total_commit_hexs.append(child.hex)
                                        commit_count += 1

                            for hex in total_commit_hexs:
                                if hex in db_commit_hexs:
                                    db_commit_hexs.remove(hex)

                            print("commits in db: " + str(db_commit_count) + " unmatched commits: " + str(len(db_commit_hexs)) + " commits found online: " + str(len(total_commit_hexs)) + " commits missing in db: " + str(commit_count))

                            projmongo.validation = ("commits in db: " + str(db_commit_count) + " unmatched commits: " + str(len(db_commit_hexs)) + " commits found online: " + str(len(total_commit_hexs)) + " commits missing in db: " + str(commit_count))
                            projmongo.save()

                            if(len(db_commit_hexs)>0):
                                print(str(len(db_commit_hexs)) + " unmatched commits in db. " + str(db_commit_count) + " commits matched.")
                                for hex in db_commit_hexs:
                                    print(hex)

                            if(len(db_commit_hexs)==0):
                                print("All " + str(db_commit_count) + " commits in db matched")

                            if(commit_count>db_commit_count):
                                print(str(commit_count-db_commit_count) + " commits not in db")

                        if os.path.isdir(path):
                            shutil.rmtree(path)
                            print(proj.name + " clone deleted")

            else:
                print(proj.name + " not found in database")

    """
        if "commit" in keymap:

            for proj in queryset:

                projectmap = dict()
                commitcount = 0
                last_updated = []
                ces_missing = -1

                if (project.find({"name": proj.name}).count() > 0):
                    print("found " + proj.name + " in project collection")
                    projdoc = project.find_one({"name": proj.name})
                    projectmap["project"] = [projdoc["_id"]]

                    projectmap["vcs_system"] = []
                    git_url = ""

                    for doc in db.vcs_system.find():
                        if doc["project_id"] in projectmap["project"]:
                            projectmap["vcs_system"].append(doc["_id"])
                            last_updated.append(doc["last_updated"])
                            url = doc["url"]

                    if "code_entity_state" in keymap:

                        ces_missing = 0
                        node_count_missing = 0

                        for vcs_id in projectmap["vcs_system"]:

                            for commit in db.commit.find({"vcs_system_id": vcs_id}):
                                ces_count = 0
                                ces_count = db.code_entity_state.find({"commit_id": commit["_id"]}).count()
                                #for ces in db.code_entity_state.find({"commit_id": commit["_id"]}):
                                if ces_count == 0:
                                    ces_missing+= 1
                                for ces in db.code_entity_state.find({"commit_id": commit["_id"]}):
                                    if not ces["metrics"]["node_count"]>0:
                                        node_count_missing+= 1


                    for vcs_id in projectmap["vcs_system"]:
                        commitcount+= db.commit.find({"vcs_system_id": vcs_id}).count()


                    # TODO: add try except and dynamic url generation from mongodb
                    github_baseurl = "https://api.github.com/repos/"
                    repo = url[19:]

                    contributors_url = github_baseurl + repo + "/contributors"
                    commit_head_url = github_baseurl + repo + "/git/refs/heads/master"
                    commit_url = github_baseurl + repo + "/commits/"

                    #'https://api.github.com/repos/openintents/safe/contributors'
                    req = requests.get(contributors_url)
                    data = req.json()
                    online_commitcount = 0
                    for contributor in data:
                        online_commitcount+= contributor['contributions']
                        online_commitcount+= 1

                    #'https://api.github.com/repos/openintents/safe/git/refs/heads/master'
                    req = requests.get(commit_head_url)
                    data = req.json()
                    #print(data)
                    sha = data["object"]["sha"]
                    #for ref in data:
                    #        sha = ref["object"]["sha"]

                    req = requests.get((commit_url + sha))
                    data = req.json()
                    newest_update = data['commit']['author']['date']
                    newest_update_format = datetime.datetime.strptime(newest_update, "%Y-%m-%dT%H:%M:%SZ")

                    #req = requests.post('https://api.github.com/repos/openintents/safe/contributors', json={'query' : query})


                        #for doc in db["commit"]:
                           # if doc["vcs_system_id"] in projectmap["vcs_system"]:
                    new_executions = ""
                    new_executions = "Found commits: " + str(commitcount)
                    new_executions+= "/" + str(online_commitcount)
                    new_executions+= " last updates: "
                    for date in last_updated:
                        new_executions+= date.strftime("%B %d, %Y")
                        new_executions+= " "
                    new_executions+= "newest release: "
                    new_executions+= newest_update_format.strftime("%B %d, %Y")

                    if ces_missing>= 0:
                        new_executions+=  " commits without any code_entity_states: " + str(ces_missing)

                    if node_count_missing>=0:
                        new_executions+= " code_entity_states without node_count: " + str(node_count_missing)

                    proj.executions = new_executions
                    proj.save()
    """

    """
        for proj in queryset:
            projectmap = dict()
            if(project.find({"name": proj.name}).count()>0):
                print("found " + proj.name + " in project collection")
                open_collections = []
                open_collections.append(project)
                projdoc = project.find_one({"name" : proj.name})
                projectmap["project"] = [projdoc["_id"]]
                visited_collections = []
                while(len(open_collections)!=0):
                    current_collection = open_collections.pop()
                    for collection_name in keymap[current_collection.name]:
                        found_collection = db[collection_name]
                        if not (found_collection in open_collections):
                            if not (found_collection in visited_collections):
                                open_collections.append(found_collection)
                                if current_collection.name in projectmap:
                                    for id in projectmap[current_collection.name]:
                                        if (found_collection.find().count()>0):
                                            for doc in found_collection.find({current_collection.name + "_id": id}):
                                                if found_collection.name in projectmap:
                                                    projectmap[found_collection.name].append(doc["_id"])
                                                else:
                                                    projectmap[found_collection.name] = [doc["_id"]]
                                                #print("found for " + proj.name + " in " + found_collection.name + " total: ", len(projectmap[found_collection.name]))
                                else:
                                    print("No Data for " + proj.name + " in " + current_collection.name)
                    visited_collections.append(current_collection)
            else:
                print(proj.name + " not found in project collection")
            new_datacounts = ""
            print("for Project " + proj.name + " was found:")
            for key in projectmap:
                print(key + " count:", len(projectmap[key]))
            for key in projectmap:
                count = len(projectmap[key])
                new_datacounts += key + " : " + str(count) + "\n"
            proj.datacounts = new_datacounts
            proj.projectmap = str(projectmap)
            proj.save()
        """

    """
    def update_executions(self, request, queryset):
        mongoclient = handler.client
        mongodb = mongoclient.smartshark
        #plugins = Plugin.objects.all()

        for proj in queryset:
            #modified = False
            exelist = []

            #for pl in plugins:
                # schema = mongodb.plugin_schema.find_one({"plugin": pl})

# find project in mongodb
            try:
                mongoproj = mongodb.project.find_one({"name": proj.name})
                projid = mongoproj["_id"]
            except TypeError:
                continue
# find the vcs_system for the project
            try:
                mongovcs = mongodb.vcs_system.find_one({"project_id": projid})
                if(mongovcs["project_id"]==projid):
                    if('vcsSHARK' not in exelist):
                        exelist.append("vcsSHARK")
                        #modified = True
            except TypeError:
                pass

# find the commit from coastshark
            try:
                mongovcs = mongodb.vcs_system.find_one({"project_id": projid})
                vcsid = mongovcs["_id"]
                mongocommit = mongodb.commit.find_one({"vcs_system_id": vcsid})
                if (mongocommit["vcs_system_id"]==vcsid):
                    mongocommitid = mongocommit["_id"]
                    mongoces = mongodb.code_entity_state.find_one({"commit_id":mongocommitid})
                    if(mongoces["_id"]==mongocommitid):
                        if('coastSHARK' not in exelist):
                            exelist.append("coastSHARK")
                            #modified = True
            except TypeError:
                pass

            if(len(exelist)>0):
                proj.executions = " ".join(exelist)
                proj.save()

            else:
                proj.executions = "None"
                proj.save

            #if('Keine' in exelist and len(exelist)>1):
            #    exelist.remove('Keine')
            #    modified = True

            #if modified:
            #    proj.executions = " ".join(exelist)
            #    proj.save()

        return

    update_executions.short_description = 'Check MongoDB for new Pluginexecutions'
    
    """


admin.site.register(ProjectMongo, ProjectMongoAdmin)
admin.site.register(User, MyUserAdmin)
admin.site.register(SmartsharkUser, SmartsharkUserAdmin)
admin.site.register(MongoRole, MongoModelAdmin)
admin.site.register(Plugin, PluginAdmin)
admin.site.register(Argument, ArgumentAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Job, JobAdmin)
admin.site.register(PluginExecution, PluginExecutionAdmin)