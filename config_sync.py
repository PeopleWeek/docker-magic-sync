#!/usr/bin/env python

from __future__ import print_function
import sys
import yaml
import os
from string import Template
import pwd
import re


class Config:

    config = {'volumes': {}}
    supervisor_conf_folder = '/etc/supervisor.conf.d/'
    unison_template_path = '/etc/supervisor.unison.tpl.conf'
    unison_defaults = '-auto -batch -repeat watch'

    def read_yaml(self, config_file):
        """
        Read YAML file and returns the configuration
        """
        with open(config_file, 'r') as stream:
            try:
                return yaml.load(stream)
            except yaml.YAMLError as exc:
                print(exc)

    def write_supervisor_conf(self):
        """
        Generates supervisor configuration for unison
        """
        if 'volumes' in self.config:
            for i, (volume, conf) in enumerate(self.config['volumes'].iteritems(), 1):
                conf.update({'port': 5000 + int(i)})
                template = open(self.unison_template_path)
                with open(self.supervisor_conf_folder + 'unison' + conf['name'] + '.conf', 'w') as f:
                    f.write(Template(template.read()).substitute(conf))

    def create_user(self, user, uid):
        """
        Create the user on the system. If the user and the uid doesn't exist, simply create it.
        If the uid is not used, but user exists, modify existing user to set the appropriate uid.
        If the uid is used, but user doesn't exists, rename existing user and create home directory.
        """
        if uid:
            uid_str = " -u " + str(uid) + " "
            # if uid doesn't exist on the system
            if int(uid) not in [x[2] for x in pwd.getpwall()]:
                # if user doesn't exist on the system
                if user not in [y[0] for y in pwd.getpwall()]:
                    cmd="useradd " + user + uid_str + " -m"
                    os.system(cmd)
                else:
                    cmd="usermod " + uid_str + user
                    os.system(cmd)
            else:
                # get username with uid
                for existing_user in pwd.getpwall():
                    if existing_user[2] == int(uid):
                        user_name = existing_user[0]
                cmd="mkdir -p /home/" + user + " && usermod --home /home/" + user + " --login " + user + " " + str(user_name) + " && chown -R " + user + " /home/" + user
                os.system(cmd)
        else:
            if user not in [x[0] for x in pwd.getpwall()]:
                cmd="useradd " + user + " -m"
                os.system(cmd)
            else:
                print("user already exists")
        self.debug("CMD:" + cmd)

    def set_permissions(self, user, folder, recursive=False):
        """
        Set permissions to the folder
        """
        args = ' -R ' if recursive else ''
        if user != 'root':
            os.system("chown " + args + user + " " + folder)

    def generate_ignore_string(self, ignores, sync_method='unison'):
        """
        Generates an ignore string depending on the type of sync command, currently supports:
        - unison
        - tar
        """
        if type(ignores) is str:
            ignores = ignores.split(':')
        if sync_method == 'unison':
            separator = "' -ignore 'Path "
            return separator[1:] + separator.join(ignores) + "' "
        elif sync_method == 'tar':
            separator = " --exclude "
            return separator + separator.join(ignores) + ' '

    def set_defaults(self):
        """
        Set values for configured volumes to sync:
         - volume: the volume path
         - name: autogenerated from path, replacing / by -
         - user: user to be mapped to the folder, set in config by volumes, or globally by ENV variable SYNC_USER
         - homedir: autogenerated, path to the home directory of the user
         - uid: the uid of the user, set in config by volumes, or globally by ENV variable SYNC_UID
        :return: 
        """
        if 'volumes' in self.config:
            for i, (volume, conf) in enumerate(self.config['volumes'].iteritems(), 1):
                self.config['volumes'][volume]['volume'] = volume
                self.config['volumes'][volume]['name'] = re.sub(r'\/', '-', volume)
                if 'user' in conf:
                    user = conf['user']
                    self.config['volumes'][volume]['homedir'] = '/home/' + conf['user']
                elif 'SYNC_USER' in os.environ:
                    user = os.environ['SYNC_USER']
                    self.config['volumes'][volume]['user'] = os.environ['SYNC_USER']
                    self.config['volumes'][volume]['homedir'] = '/home/' + os.environ['SYNC_USER']
                else:
                    user = self.config['volumes'][volume]['user'] = self.config['volumes'][volume]['name'][1:8]
                    self.config['volumes'][volume]['homedir'] = '/home/' + self.config['volumes'][volume]['name'][1:8]
                if 'uid' in conf:
                    self.config['volumes'][volume]['uid'] = uid = conf['uid']
                elif 'SYNC_UID' in os.environ:
                    self.config['volumes'][volume]['uid'] = uid = os.environ['SYNC_UID']
                else:
                  raise Exception('Unable to grab uid from config file or env variable. Ensure you have set SYNC_UID ! ')
                if 'ignore' in conf:
                    self.config['volumes'][volume]['unison_ignore'] = self.generate_ignore_string(conf['ignore'], 'unison')
                elif 'SYNC_IGNORE' in os.environ:
                    self.config['volumes'][volume]['ignore'] = os.environ['SYNC_IGNORE']
                    self.config['volumes'][volume]['unison_ignore'] = self.generate_ignore_string(os.environ['SYNC_IGNORE'], 'unison')
                else:
                    self.config['volumes'][volume]['ignore'] = ''
                    self.config['volumes'][volume]['unison_ignore'] = ''
                if 'unison_defaults' not in conf and 'SYNC_UNISON_DEFAULTS' in os.environ:
                    self.config['volumes'][volume]['unison_defaults'] = os.environ['SYNC_UNISON_DEFAULTS']
                elif 'unison_defaults' not in conf:
                    self.config['volumes'][volume]['unison_defaults'] = self.unison_defaults
                self.create_user(user, uid)
                self.set_permissions(user, volume)

    def merge_discovered_volumes(self):
        """ 
        Read config file auto generated on container start by docker-gen.
        Merges the `magic` folders with the ones configured in the provided config file, if any.
        """
        volumes = self.read_yaml('/volumes.yml')
        for volume in volumes['volumes']:
            if '.magic' in volume:
                if not self.config or volume not in self.config['volumes']:
                    self.config['volumes'][volume.replace('.magic', '')] = {}

    def initial_sync(self):
        """ 
        When starting the container, copies the files from host to container
        """
        if 'volumes' in self.config:
            for volume, conf in self.config['volumes'].iteritems():
                command = 'unison ' + volume + '.magic ' + volume + ' -numericids -auto -batch ' + self.generate_ignore_string(conf['ignore'], 'unison')
                self.debug(command)
                os.system(command)
                self.set_permissions(conf['user'], volume, True)

    def debug(self, message):
        print(message)

    def set(self, config_file):
        if config_file:
            self.config = self.read_yaml(config_file)
        self.merge_discovered_volumes()
        self.set_defaults()
        self.write_supervisor_conf()
        self.initial_sync()

c = Config()
c.set(sys.argv[1])

