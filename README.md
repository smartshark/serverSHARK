# serverSHARK

## local deployment for plugin development / debugging
A Vagrantfile is provided which installs a Virtualbox VM with the current serverSHARK.

```shell
cp Vagrantfile_template Vagrantfile
cp server/settings_template_vagrant.py server/settings_vagrant.py

# change the setting values
vi Vagrantfile
vi server/settings_vagrant.py

# boot up vm
vagrant up
```

Run the serverSHARK Webserver
```shell
vagrant ssh
sudo -i
cd /srv/www/serverSHARK/
source bin/activate
python manage.py runserver 0.0.0.0:8000
```

Run the worker process
```shell
vagrant ssh
sudo -i
cd /srv/www/serverSHARK/
source bin/activate
python manage.py peon
```

After everything is running point your browser to http://127.0.0.1:8001/admin
You can then login with user admin and your confiugred adminpass from the Vagrantfile.
The smartSHARK MongoDB is exposed with port 27018 (as can be seen in the Vagrantfile).


## Hints for production deployment

The deployment options ultimately rely on your setup. Usually the Django backend is run using WSGI with Gunicorn or UWSGI. There also should be a webserver like Nginx which handles static content and SSL.
The execution also depends on your infrastructure options. In our case we use a SLURM HPC System so that should work more or less out of the box. 
If you deploy serverSHARK on a bigger machine you could also run multiple worker processes to increase mining speed.


## First Steps

### Plugin Installation

After installing the serverSHARK and making sure that the worker and the serverSHARK processes are running the serverSHARK needs plugins to collect data.
Plugins are basically command line executables that are zipped which can be installed on the serverSHARK. Depending on the setup they are then orchestrated to run in a HPC-Cluster, local queue like described above or other multi-worker setups.
Information about plugins can be accessed [here](https://smartshark.github.io/fordevs/).

Most plugins can be directly installed via their releases on Github via the serverSHARK administration. To do this just select plugins in the serversHARK administration then the add plugin from github button in the top right corner.
The dropdown contains the available Plugins, after clicking on the select button you can chose a version and click on add plugin. This loads the plugin from Github into the serverSHARK.

After this the plugin has to be installed and activated. Just select the checkbox and in the dropdown below the list select install plugin.
This sends a message to the worker which then extracts and installs the plugin. After that the plugin can be activated by clicking on its name in the list and checking the activate checkbox.

The plugins have dependencies on each other, e.g., the coastSHARK collects AST node counts but it relies on the vcsSHARK because the vcsSHARK loads all repository information into the database.


### Creating Projects

After installing the plugins we can create a new project for which we wish to collect data.
Just click on Projects, then on add Project.
Give the project a name and click on save. Then it should appear in the list of projects.


### Running Plugins

To execute a Plugin you select the checkbox in the list of projects for the desired project then at the bottom select start collection for selected project from the dropdown and click on ok.
In the next screen select the plugin which you which to use, if the project is new start with the vcsSHARK to collect repository information.
Be sure to only select one plugin to run in this step. After that you can support additional information to the plugin.
In case of the vcsSHARK you need to support the Git URL of the project. After that you can start the plugin.

This creates a message to the worker process which then executes the plugin, you can see the state of the execution via the Plugin Executions button in the project list.


### Plugin Order

The vcsSHARK provides the basic repository information so this plugin should come first.
After that you can use the mecoSHARK to collect static source code metrics and coastSHARK to collect AST node counts.
Usually this collects a massive amount of data which can then be compacted using the memeSHARK plugin.

After that you can collect refactoring information using the refSHARK and the rSHARK which utilize different refactoring detection implementations.

For a full list of available Plugins check [our Github](https://github.com/smartshark/) and our [website](https://smartshark.github.io/plugins/).
