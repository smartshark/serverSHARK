import logging

from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
from django.template.response import TemplateResponse

from django.contrib.messages import get_messages
from django.contrib import messages
from django.contrib.admin import SimpleListFilter

from django.core.exceptions import ValidationError
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.db.models import Q

from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface
from smartshark.mongohandler import handler

from .views.collection import JobSubmissionThread
from .models import MongoRole, SmartsharkUser, Plugin, Argument, Project, Job, PluginExecution, ExecutionHistory, CommitVerification

logger = logging.getLogger('django')

admin.site.unregister(User)


class PluginFailedListFilter(SimpleListFilter):
    title = _('Plugin Failed')

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'plugin_failed'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        return (
            ('failure', _('At least one plugin failed')),
            ('success', _('All plugins succeeded')),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value() == 'failure':
            return queryset.filter(Q(mecoSHARK=False) | Q(coastSHARK=False))
        else:
            return queryset.all()


class JobAdmin(admin.ModelAdmin):
    list_display = ('job_id', 'plugin_execution', 'status', 'revision_hash')
    list_filter = ('plugin_execution__project', 'plugin_execution__plugin', 'status', 'plugin_execution__execution_type')
    search_fields = ('revision_hash',)

    actions = ['restart_job', 'set_exit', 'set_done', 'set_job_stati']

    def has_add_permission(self, request, obj=None):
        return False

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
            new_plugin_execution.status = 'WAIT'
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
    list_filter = ('project',)

    actions = ['restart_plugin_execution']

    def has_add_permission(self, request, obj=None):
        return False

    def restart_plugin_execution(self, request, queryset):
        for pe in queryset:
            # create new plugin_execution with same values
            plugin_execution = PluginExecution.objects.get(pk=pe.pk)
            plugin_execution.pk = None
            plugin_execution.status = 'WAIT'
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
    list_filter = ('active', 'installed', 'plugin_type')
    actions = ('delete_model', 'install_plugin')
    inlines = (ArgumentInline, )
    change_list_template = 'smartshark/plugin/buttons.html'

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
    search_fields = ('name', 'mongo_id')

    actions = ['start_collection', 'show_executions', 'delete_data']

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
        if queryset.count() != 1:
            messages.error(request, "Can not only collect one project at a time.")
            return

        return HttpResponseRedirect("/smartshark/project/collection/choose/?project_id=%s" % (queryset[0].pk))

    start_collection.short_description = 'Start Collection for selected Project'

    def delete_data(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect("/smartshark/project/delete/?ids=%s" % (",".join(selected)))

    delete_data.short_description = 'Delete all data for selected Projects'


class CommitVerificationAdmin(admin.ModelAdmin):

    list_display = ('commit', 'project', 'vcsSHARK', 'mecoSHARK',
                    'coastSHARK')
    search_fields = ('commit',)
    list_filter = ('project__name', 'vcsSHARK', 'mecoSHARK', 'coastSHARK', PluginFailedListFilter)

    actions = ['delete_ces_list']

    def has_add_permission(self, request, obj=None):
        return False

    def delete_ces_list(self, request, queryset):
        # show validation with additional information, re-running plugins (mecoSHARK, coastSHARK for XYZ commits)
        if request.POST.get('post'):

            plugins = request.POST.getlist('plugins', [])
            if not plugins:
                raise Exception('no plugins selected')
            plugins = ','.join(plugins)

            project = request.POST.get('project', None)
            if not project:
                raise Exception('no project selected')

            revisions = request.POST.get('revisions', None)
            if not revisions:
                raise Exception('no revisions selected')

            logger.info('Re-Run collection for project_id: {}, plugin_ids: {}'.format(project, plugins))
            logger.info('Setting code_entity_states to an empty list for these commits: {}'.format(revisions))
            # we could now delete the code_entity_state lists of the commits in revisions
            matched_count = handler.clear_code_entity_state_lists(revisions, queryset[0].vcs_system)
            logger.info('Deleted code_entity_states_list for {} commits'.format(matched_count))

            # todo: should be via URL
            return HttpResponseRedirect('/smartshark/project/collection/start/?plugins={}&project_id={}&initial_exec_type=rev&initial_revisions={}'.format(plugins, project, revisions))
        else:
            # die on multiple projects!
            project = queryset[0].project
            for c in queryset:
                if c.project != project:
                    raise Exception('Queryset contains multiple projects!')

            vcs_system = queryset[0].vcs_system
            for c in queryset:
                if c.vcs_system != vcs_system:
                    raise Exception('Queryset contains multiple vcs systems')

            request.current_app = self.admin_site.name
            context = {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'title': 'Delete CodeEntityState Lists and Re-Run collection',
                'project': project,
                'queryset': queryset,
                'revisions': ','.join([obj.commit for obj in queryset]),
                'num_revisions': len(queryset),
                'plugins': Plugin.objects.filter(name__in=['mecoSHARK', 'coastSHARK'], active=True, installed=True)
            }

            return TemplateResponse(request, 'admin/confirm_ces_list_deletion.html', context)

admin.site.register(CommitVerification, CommitVerificationAdmin)
admin.site.register(User, MyUserAdmin)
admin.site.register(SmartsharkUser, SmartsharkUserAdmin)
admin.site.register(MongoRole, MongoModelAdmin)
admin.site.register(Plugin, PluginAdmin)
admin.site.register(Argument, ArgumentAdmin)
admin.site.register(Project, ProjectAdmin)
admin.site.register(Job, JobAdmin)
admin.site.register(PluginExecution, PluginExecutionAdmin)
