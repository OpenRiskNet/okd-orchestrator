#!/usr/bin/env python

"""create.py - create the world.
"""

from __future__ import print_function

import argparse
from builtins import input
import glob
import os
import sys

import yaml

from utils import io


def _main(cli_args, deployment_name):
    """Deployment entry point.

    :param cli_args: The command-line arguments
    :type cli_args: ``list``
    :param deployment_name: The deployment file (excluding the extension)
    :type deployment_name: ``str``
    :returns: True on success
    :rtype: ``bool``
    """

    deployment_file = 'deployments/{}.yaml'.format(deployment_name)
    if not os.path.exists(deployment_file):
        io.error(('No config file ({}) for an "{}" deployment'.
                 format(deployment_file, deployment_name)))
        return False
    with open(deployment_file, 'r') as stream:
        deployment = yaml.load(stream)

    # There must be an openshift/inventories directory
    inventory_dir = deployment['openshift']['inventory_dir']
    if not os.path.isdir('openshift/inventories/{}'.format(inventory_dir)):
        io.error('Missing "openshift/inventories" directory')
        print('Expected to find the inventory directory "{}"'
              ' but it was not there.'.format(inventory_dir))
        print('Every deployment must have an "inventories" directory')
        return False

    # -----
    # Hello
    # -----
    io.banner(deployment['name'], full_heading=True, quiet=False)
    if not cli_args.auto_acknowledge:

        confirmation_word = io.get_confirmation_word()
        target = 'CREATE the Cluster' \
            if cli_args.cluster else 'INSTALL OpenShift'
        confirmation = input('Enter "{}" to {}: '.
                             format(confirmation_word, target))
        if confirmation != confirmation_word:
            print('Phew! That was close!')
            return True

    # ------
    # Render (jinja2 files)
    # ------
    # Translate content of Jinja2 template files
    # using the deployment configuration's YAML file content.

    if not cli_args.skip_rendering:

        cmd = './render.py {}'.format(deployment_name)
        cwd = '.'
        rv, _ = io.run(cmd, cwd, cli_args.quiet)
        if not rv:
            return False

    # -------
    # Ansible (A specific version)
    # -------
    # Install the ansible version name in the deployment file

    cmd = 'pip install --upgrade pip'
    rv, _ = io.run(cmd, '.', cli_args.quiet)
    if not rv:
        return False

    cmd = 'pip install ansible=={}'. \
        format(deployment['ansible']['version'])
    rv, _ = io.run(cmd, '.', cli_args.quiet)
    if not rv:
        return False

    t_dir = deployment['terraform']['dir']
    if cli_args.cluster:

        # ---------
        # Terraform
        # ---------
        # Create compute instances for the cluster.

        if not cli_args.skip_terraform:

            cmd = 'terraform init'
            cwd = 'terraform/{}'.format(t_dir)
            rv, _ = io.run(cmd, cwd, cli_args.quiet)
            if not rv:
                return False

            cmd = 'terraform apply' \
                  ' -auto-approve' \
                  ' -state=.terraform.{}'.format(deployment_name)
            cwd = 'terraform/{}'.format(t_dir)
            rv, _ = io.run(cmd, cwd, cli_args.quiet)
            if not rv:
                return False

        # -------
        # Ansible
        # -------
        # Run the bastion site file.

        if not cli_args.skip_pre_openshift:

            extra_env = ''
            if deployment['cluster']['master']['generate_cert']:
                extra_env += ' -e master_cert_email={}'. \
                    format(os.environ['TF_VAR_master_certbot_email'])
                extra_env += ' -e public_hostname={}'. \
                    format(deployment['cluster']['public_hostname'])
            keypair_name = os.environ['TF_VAR_keypair_name']
            cmd = 'ansible-playbook site.yaml' \
                  ' {}' \
                  ' -e keypair_name={}' \
                  ' -e deployment={}'.format(extra_env,
                                             keypair_name,
                                             inventory_dir)
            cwd = 'ansible/bastion'
            rv, _ = io.run(cmd, cwd, cli_args.quiet)
            if not rv:
                return False

        if not cli_args.skip_terraform:

            # Now expose the Bastion's IP
            cmd = 'terraform output' \
                  ' -state=.terraform.{}'.format(deployment_name)
            cwd = 'terraform/{}'.format(t_dir)
            rv, _ = io.run(cmd, cwd, cli_args.quiet)
            if not rv:
                return False

        # Leave.
        return True

    # If we get here we're installing OpenShift
    # (on a cluster that is assumed to exist).
    #
    # From this point we're installing and configuring OpenShift...

    # -----
    # Clone (OpenShift Ansible)
    # -----
    # ...and checkout the revision defined by the deployment tag.

    # If the expected clone directory does not exist
    # then clone OpenShift Ansible.
    if not os.path.exists('openshift-ansible'):

        cmd = 'git clone' \
              ' https://github.com/openshift/openshift-ansible.git' \
              ' --no-checkout'
        cwd = '.'
        rv, _ = io.run(cmd, cwd, cli_args.quiet)
        if not rv:
            return False

    # Checkout the required OpenShift Ansible TAG
    cmd = 'git checkout tags/{}'. \
        format(deployment['openshift']['ansible_tag'])
    cwd = 'openshift-ansible'
    rv, _ = io.run(cmd, cwd, cli_args.quiet)
    if not rv:
        return False

    # -------
    # Ansible (Pre-OpenShift)
    # -------

    if not cli_args.skip_pre_openshift:

        extra_env = ''
        if deployment['cluster']['master']['generate_cert']:
            extra_env += ' -e public_hostname={}'. \
                format(deployment['cluster']['public_hostname'])
        cmd = 'ansible-playbook site.yaml' \
              ' {}' \
              ' -i ../../openshift/inventories/{}/inventory'.\
            format(extra_env, inventory_dir)
        cwd = 'ansible/pre-os'
        rv, _ = io.run(cmd, cwd, cli_args.quiet)
        if not rv:
            return False

    # -------
    # Ansible (OpenShift)
    # -------
    # Deploy OpenShift using the playbooks named in the deployment
    # from the checked-out version.

    if not cli_args.skip_openshift:

        for play in deployment['openshift']['play']:
            cmd = 'ansible-playbook ../openshift-ansible/playbooks/{}' \
                  ' -i inventories/{}/inventory'.format(play, inventory_dir)
            cwd = 'openshift'
            rv, _ = io.run(cmd, cwd, cli_args.quiet)
            if not rv:
                return False

    # -------
    # Ansible (Post-OpenShift)
    # -------

    if not cli_args.skip_post_openshift:

        cmd = 'ansible-playbook site.yaml'
        cwd = 'ansible/post-os'
        rv, _ = io.run(cmd, cwd, cli_args.quiet)
        if not rv:
            return False

    # -------
    # Success
    # -------

    # OK if we get here.
    # Cluster created and OpenShift installed.
    return True


if __name__ == '__main__':

    # Parse the command-line then run the main method.
    PARSER = argparse. \
        ArgumentParser(description='The Informatics Matters Orchestrator.'
                                   ' Creates the cloud-based execution'
                                   ' platform using tools like Terraform and'
                                   ' Ansible.')

    PARSER.add_argument('-q', '--quiet',
                        help='Decrease output verbosity',
                        action='store_true')

    PARSER.add_argument('-c', '--cluster',
                        help='Create the cluster, do not install OpenShift',
                        action='store_true')

    PARSER.add_argument('-o', '--okd',
                        help='Create the OpenShift/OKD installation'
                             ' (on an existing cluster)',
                        action='store_true')

    PARSER.add_argument('-d', '--display-deployments',
                        help='Display known deployments',
                        action='store_true')

    PARSER.add_argument('-sr', '--skip-rendering',
                        help='Skip the Jinja2 rendering stage',
                        action='store_true')

    PARSER.add_argument('-st', '--skip-terraform',
                        help='Skip the terraform stage',
                        action='store_true')

    PARSER.add_argument('-spr', '--skip-pre-openshift',
                        help='Skip the Pre-OpenShift deployment stage',
                        action='store_true')

    PARSER.add_argument('-so', '--skip-openshift',
                        help='Skip the OpenShift deployment stage',
                        action='store_true')

    PARSER.add_argument('-spo', '--skip-post-openshift',
                        help='Skip the Post-OpenShift deployment stage',
                        action='store_true')

    PARSER.add_argument('--auto-acknowledge',
                        help='Skip the create confirmation question',
                        action='store_true')

    PARSER.add_argument('deployment', metavar='DEPLOYMENT',
                        type=str, nargs='?',
                        help='The name of the deployment')

    ARGS = PARSER.parse_args()

    # User must have specified 'cluster' or 'open-shift'
    if not ARGS.cluster and not ARGS.okd:
        print('Must specify --cluster or --okd')
        sys.exit(1)

    deployments = glob.glob('deployments/*.yaml')
    # If there are no deployments, we can do nothing!
    if not deployments:
        print('The deployments directory is empty')
        sys.exit(1)

    # Deal with special cases...
    # 1. 'display deployments'
    if ARGS.display_deployments:
        for deployment in deployments:
            # Display the deployment without the path
            # and removing the '.yaml' suffix.
            print(os.path.basename(deployment)[:-5])
        sys.exit(0)

    # If a deployment wasn't named, and there's more than one,
    # then the user must name one...
    if not ARGS.deployment:
        if len(deployments) > 1:
            print('ERROR: You need to supply the name of a deployment.\n'
                  '       The following are available:')
            for deployment in deployments:
                # Display the deployment without the path
                # and removing the '.yaml' suffix.
                print(os.path.basename(deployment)[:-5])
            sys.exit(1)
        deployment_file = os.path.basename(deployments[0])[:-5]
    else:
        deployment_file = ARGS.deployment

    # Load the deployment's configuration file...
    config_file = 'deployments/{}.yaml'.format(deployment_file)
    if not os.path.exists(config_file):
        io.error('No config file ({}) for an "{}" deployment'.
                 format(config_file, deployment_file))
        sys.exit(1)

    # Go...
    success = _main(ARGS, deployment_file)

    # Done
    # ...or failed and exhausted retry attempts!
    if not success:
        io.error('Failed to start cluster')
        # Return non-zero exit value to the shell...
        sys.exit(1)
