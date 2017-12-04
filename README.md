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
