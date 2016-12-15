import tarfile
import json

from django.core.exceptions import ValidationError


class PluginInformationHandler(object):
    info_file_required_fields = ['name', 'author', 'version', 'plugin_type', 'requires', 'arguments',
                                 'description', 'linux_libraries', 'created_collections']
    info_file_created_collection_required_fields = ['name', 'shard_key']
    info_file_requires_required_fields = ['name', 'operator', 'version']
    info_file_argument_required_fields = ['name', 'required', 'position', 'type', 'description']

    error_messages = {
        'tar_file': "Invalid tar file.",
        'info_file': "info.json not found in tar archive.",
        'schema_file': "schema.json not found in tar archive.",
        'schema_file_json': "schema.json is not parsable. Please put valid json in there.",
        'info_file_json': "info.json is not parsable. Please put valid json in there.",
        'info_file_key': "info.json not found in tar archive.",
        'schema_file_key': "schema.json not found in tar archive.",
        'install_sh': "install.sh not found in tar archive.",
        'execute_sh': "execute.sh not found in tar archive."
    }

    def __init__(self, file):
        if isinstance(file, str):
            file = open(file, 'rb')
        else:
            # Set pointer back
            file.seek(0)

        try:
            self.tar = tarfile.open(fileobj=file)
        except tarfile.TarError as e:
            raise ValidationError(self.error_messages['tar_file'], 'tar_file')

        try:
            self.info_json = json.loads(self.tar.extractfile('info.json').read().decode('utf-8'))
        except json.decoder.JSONDecodeError:
            raise ValidationError(self.error_messages['info_file_json'], 'info_file_json')
        except KeyError:
            raise ValidationError(self.error_messages['info_file_key'], 'info_file_key')

        try:
            self.schema = json.loads(self.tar.extractfile('schema.json').read().decode('utf-8'))
        except json.decoder.JSONDecodeError:
            raise ValidationError(self.error_messages['schema_file_json'], 'schema_file_json')
        except KeyError:
            raise ValidationError(self.error_messages['schema_file_key'], 'schema_file_key')

        try:
            self.tar.extractfile('install.sh').read()
        except KeyError:
            raise ValidationError(self.error_messages['install_sh'], 'install_sh')

        try:
            self.tar.extractfile('execute.sh').read()
        except KeyError:
            raise ValidationError(self.error_messages['execute_sh'], 'execute_sh')

    def get_info(self):
        return self.info_json

    def get_schema(self):
        return self.schema

    def validate_tar(self):
        self.validate_info_file()
        self.validate_schema_file()

    def validate_info_file(self):
        self.validate_info_structure()
        self.validate_plugin_requirements()
        self.validate_plugin_arguments()

    def validate_schema_file(self):
        self.validate_schema_structure()

    def validate_info_structure(self):
        for field in self.info_file_required_fields:
            if field not in self.info_json:
                raise ValidationError("%s not in info_json" % field, 'info_file_%s' % field)

        for created_collection_fields in self.info_json['created_collections']:
            for field in self.info_file_created_collection_required_fields:
                if field not in created_collection_fields:
                    raise ValidationError("%s not in info_json created_collections attribute" % field,
                                          'info_file_created_collections_%s' %field)

        for requires_fields in self.info_json['requires']:
            for field in self.info_file_requires_required_fields:
                if field not in requires_fields:
                    raise ValidationError("%s not in info_json requires attribute." % field, 'info_file_requires_%s'
                                          % field)

        for argument_fields in self.info_json['arguments']:
            for field in self.info_file_argument_required_fields:
                if field not in argument_fields:
                    raise ValidationError("%s not in info_json arguments attribute." % field, 'info_file_arugment_%s'
                                          % field)

    def validate_plugin_requirements(self):
        for req_plugin in self.info_json['requires']:
            plugins = self.find_required_plugins(req_plugin)
            if len(plugins) == 0:
                raise ValidationError("Plugin requirements for this plugin can not be matched. Plugin %s "
                                      "with version %s %s is not in this database." % (req_plugin['name'],
                                                                                       req_plugin['operator'],
                                                                                       req_plugin['version']),
                                      'info_file_requirements')
            installed_plugins = [plugin for plugin in plugins if plugin.installed]
            if len(installed_plugins) == 0:
                raise ValidationError("Plugin requirements for this plugin can not be matched. Plugin %s "
                                      "with version %s %s is not installed." % (req_plugin['name'],
                                                                                req_plugin['operator'],
                                                                                req_plugin['version']),
                                      'info_file_requirements_installed')

    def validate_plugin_arguments(self):
        install_arguments = []
        execution_arguments = []
        # get all arguments
        for argument_fields in self.info_json['arguments']:
            if argument_fields['type'] == 'install':
                install_arguments.append({'position': argument_fields['position'],
                                          'required': argument_fields['required']})
            elif argument_fields['type'] == 'execute':
                execution_arguments.append({'position': argument_fields['position'],
                                            'required': argument_fields['required']})
            else:
                raise ValidationError("Argument %s does not have a valid type (install or execute)" %
                                      argument_fields['name'])

        # sort them according to position
        install_arguments_sorted = sorted(install_arguments, key=lambda k: k['position'])
        execution_arguments_sorted = sorted(execution_arguments, key=lambda k: k['position'])

        # validate them:
        # 1) position must not be missing (e.g. position 1, position 3)
        pos = 1
        for install_argument in install_arguments_sorted:
            if install_argument['position'] != pos:
                raise ValidationError("Positions are not consistent (e.g., position 3 follows position 1).")

            pos += 1

        pos = 1
        for execute_argument in execution_arguments_sorted:
            if execute_argument['position'] != pos:
                raise ValidationError("Positions are not consistent (e.g., position 3 follows position 1).")

            pos += 1

    def validate_schema_structure(self):
        pass

    @staticmethod
    def find_required_plugins(req_plugin):
        from .models import Plugin
        db_plugins = []
        if req_plugin['operator'] == '>=':
            db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version__gte=req_plugin['version'],
                                                     active=True, installed=True)
        elif req_plugin['operator'] == '<=':
            db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version__lte=req_plugin['version'],
                                                     active=True, installed=True)
        elif req_plugin['operator'] == '>':
            db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version__gt=req_plugin['version'],
                                                     active=True, installed=True)
        elif req_plugin['operator'] == '<':
            db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version__lt=req_plugin['version'],
                                                     active=True, installed=True)
        else:
            db_plugins = Plugin.objects.all().filter(name=req_plugin['name'], version=req_plugin['version'],
                                                     active=True, installed=True)

        return db_plugins

    def find_fitting_plugins(self):
        fitting_plugins = []

        for req_plugin in self.info_json['requires']:
            plugins = self.find_required_plugins(req_plugin)
            installed_plugins = [plugin for plugin in plugins if plugin.installed]
            fitting_plugins.append(max(installed_plugins, key=lambda x:x.version))
        return fitting_plugins

    def get_arguments(self):
        from .models import Argument
        arguments = []
        for argument_desc in self.info_json['arguments']:
                argument = Argument()
                argument.name = argument_desc['name']
                argument.required = argument_desc['required']
                argument.position = argument_desc['position']
                argument.type = argument_desc['type']
                argument.description = argument_desc['description']
                arguments.append(argument)

        return arguments


