# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|

  # Every Vagrant development environment requires a box. You can search for
  # boxes at https://vagrantcloud.com/search.
  config.vm.box = "ubuntu/xenial64"

  # this sets the vagrant name
  config.vm.define :ServerSHARK do |t|
  end
  
  config.vm.box_check_update = true

  config.vm.network "forwarded_port", guest: 8000, host: 8001, host_ip: "127.0.0.1"
  config.vm.network "forwarded_port", guest: 27017, host: 27018, host_ip: "127.0.0.1"

  config.vm.provider "virtualbox" do |vb|
    vb.memory = "2048"
    vb.name = "ServerSHARK"
  end

  # create pem for mongodb
  config.vm.provision "shell", inline: <<-SHELL
    cd /etc/ssl/
    openssl req -newkey rsa:2048 -new -x509 -days 365 -nodes -out mongodb-cert.crt -keyout mongodb-cert.key -batch -subj "/C=DE/ST=Goettingen/L=Niedersachsen/O=GA/OU=SWE/CN=localhost"
    cat mongodb-cert.key mongodb-cert.crt > mongodb.pem
  SHELL

  config.vm.provision "shell", inline: <<-SHELL
    apt-get update
    apt-get install -y git python3-venv python3-pip python3-cffi libgit2-24 libgit2-dev libmysqlclient-dev
    apt-get install -y build-essential libtool pkg-config autoconf python3-dev libffi-dev
    apt-get install -y redis-server

    debconf-set-selections <<< 'mysql-server mysql-server/root_password password balla'
    debconf-set-selections <<< 'mysql-server mysql-server/root_password_again password balla'

    apt-get install -y mongodb mysql-server

    service mysql start
    mysql -u root --password=balla -e "CREATE DATABASE IF NOT EXISTS servershark CHARACTER SET utf8 COLLATE utf8_general_ci;"
    
    #no tls for now
    #sed -i 's/\#sslOnNormalPorts = true/sslOnNormalPorts = true/g' /etc/mongodb.conf
    #sed -i 's/\#sslPEMKeyFile = \/etc\/ssl\/mongodb.pem/sslPEMKeyFile = \/etc\/ssl\/mongodb.pem/g' /etc/mongodb.conf

    service mongodb start
    mongo admin --eval "db.getSiblingDB('smartshark').addUser('root', 'balla')"

    rm -rf /srv/www/serverSHARK/
    mkdir -p /srv/www/
    cd /srv/www
    git clone https://github.com/smartshark/serverSHARK.git
    cd serverSHARK
    python3 -m venv .
    source bin/activate
    pip install -r requirements.txt
  SHELL
  
  config.vm.provision "file", source: "./server/settings_vagrant.py", destination: "~/settings.py"

  config.vm.provision "shell", inline: <<-SHELL
    cp /home/ubuntu/settings.py /srv/www/serverSHARK/server/
    cd /srv/www/serverSHARK/
    source bin/activate
    
    pip install redis

    python manage.py migrate
    echo "from django.contrib.auth.models import User; User.objects.create_superuser('admin', 'admin@example.com', 'alpaca')" | python manage.py shell

    python manage.py runserver 0.0.0.0:8000
  SHELL
end
