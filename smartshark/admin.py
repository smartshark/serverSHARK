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
from .models import MongoRole, SmartsharkUser, Plugin, Argument, Project, Job, PluginExecution, ExecutionHistory, \
    ProjectMongo, CommitValidation
from .datavalidation import map_database, create_local_repo, was_vcsshark_executed, was_coastshark_executed, \
    validate_commits, validate_coast_code_entity_states, validate_meco_code_entity_states, validate_file_action, \
    delete_local_repo, was_mecoshark_executed
import timeit, datetime

admin.site.unregister(User)


class JobAdmin(admin.ModelAdmin):
    list_display = ('job_id', 'plugin_execution', 'status', 'revision_hash')
    list_filter = (
    'plugin_execution__project', 'plugin_execution__plugin', 'status', 'plugin_execution__execution_type')
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
    readonly_fields = ('user',)
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
    inlines = (ArgumentInline,)

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
            return 'name', 'author', 'version', 'description', 'plugin_type', 'installed', 'linux_libraries'
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
    readonly_fields = ('mongo_id',)
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
    list_display = (
    'project', 'get_executed_plugins', 'vcs_validation', 'coast_validation', 'meco_validation', 'get_last_validation', 'get_missing_coast_hashs_as_string')
    actions = ['full_validation']

    def full_validation(self, request, queryset):
        mongoclient = handler.client
        path = "../tmp-repo"
        db = mongoclient.smartshark
        project_db = db.project

        keymap = map_database(db)

        vcs_system_exists = False
        file_action_exists = False
        code_entity_state_exists = False

        if "vcs_system" in keymap:
            vcs_system_exists = True

        if "file_action" in keymap:
            file_action_exists = True

        if "code_entity_state" in keymap:
            code_entity_state_exists = True

        for projmongo in queryset:
            proj = projmongo.project

            print("Starting validation for " + proj.name)
            start = timeit.default_timer()

            projmongo.executed_plugins.clear()

            if (project_db.find({"name": proj.name}).count() > 0):

                projdoc = project_db.find_one({"name": proj.name})

                if vcs_system_exists:

                    if (db.vcs_system.find({"project_id": projdoc["_id"]}).count() > 0):

                        if was_vcsshark_executed(db.vcs_system, projdoc["_id"]):
                            projmongo.executed_plugins.add(Plugin.objects.get(name='vcsSHARK'))

                            vcsdoc = db.vcs_system.find_one({"project_id": projdoc["_id"]})

                            repo = create_local_repo(vcsdoc, path)

                            if not repo.is_empty:

                                commit_validation = validate_commits(repo, vcsdoc, db.commit, projmongo)

                                projmongo.vcs_validation = commit_validation

                                if file_action_exists:
                                    file_action_validation = validate_file_action(repo, vcsdoc["_id"], db.commit,
                                                                                  db.file, db.file)

                                    projmongo.vcs_validation += file_action_validation

                                if code_entity_state_exists:

                                    if was_coastshark_executed(vcsdoc["_id"], db.code_entity_state, db.commit):
                                        projmongo.executed_plugins.add(Plugin.objects.get(name='coastSHARK'))

                                        coast_code_entity_state_validation = validate_coast_code_entity_states(repo,
                                                                                                               vcsdoc["_id"],
                                                                                                               path,
                                                                                                               db.commit,
                                                                                                               db.code_entity_state,
                                                                                                               projmongo)

                                        projmongo.coast_validation = coast_code_entity_state_validation

                                    if was_mecoshark_executed(vcsdoc["_id"], db.code_entity_state, db.commit):
                                        projmongo.executed_plugins.add(Plugin.objects.get(name='mecoSHARK'))

                                        meco_code_entity_state_validation = validate_meco_code_entity_states(repo,
                                                                                                             vcsdoc["_id"],
                                                                                                             path,
                                                                                                             db.commit,
                                                                                                             db.code_entity_state,
                                                                                                             projmongo)

                                        projmongo.meco_validation = meco_code_entity_state_validation

                            delete_local_repo(path)

                            if projmongo.vcs_validation == "":
                                projmongo.vcs_validation = "No Error"
                            if projmongo.coast_validation == "":
                                projmongo.coast_validation = "No Error"
                            if projmongo.meco_validation == "":
                                projmongo.meco_validation = "No Error"

                            projmongo.last_validation = datetime.datetime.now()
                            projmongo.validated = True
                            projmongo.save()

            else:
                print(proj.name + " not found in database")

            end = timeit.default_timer() - start
            print("Finished validation for " + proj.name + " in {:.5f}s".format(end))

    full_validation.short_description = 'Validate Data'


class CommitValidationAdmin(admin.ModelAdmin):
    list_display = (
    'projectmongo', 'revision_hash', 'valid', 'present', 'coast_valid', 'coast_present', 'meco_valid', 'meco_present')
    actions = ['delete_only_valid']

    def delete_only_valid(self, request, queryset):

        for validation in queryset:
            if validation.valid != validation.missing:
                if validation.coast_valid != validation.coast_missing:
                    if validation.meco_valid != validation.meco_missing:
                        validation.delete()

    delete_only_valid.short_description = 'Delete selected valid commit validations'


admin.site.register(CommitValidation, CommitValidationAdmin)
admin.site.register(ProjectMongo, ProjectMongoAdmin)
admin.site.register(User, MyUserAdmin)
admin.site.register(SmartsharkUser, SmartsharkUserAdmin)
admin.site.register(MongoRole, MongoModelAdmin)
admin.site.register(Plugin, PluginAdmin)
admin.site.register(Argument, ArgumentAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Job, JobAdmin)
admin.site.register(PluginExecution, PluginExecutionAdmin)
