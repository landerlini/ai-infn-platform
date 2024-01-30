#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import socket
import json
from pprint import pprint, pformat
import logging
from pathlib import Path
from base64 import b64decode
from contextlib import asynccontextmanager
import traceback
import textwrap
import sys
import subprocess

from oauthenticator.oauth2 import OAuthenticator
from oauthenticator.generic import GenericOAuthenticator
from tornado import gen
from kubespawner import KubeSpawner
import requests
import yaml
import subprocess
import warnings
import asyncio
import shutil

from typing import Dict

import jinja2
import kubernetes_asyncio as k8s
from kubernetes_asyncio.client.models import (
    V1Service, 
    V1ObjectMeta, 
    V1ServiceSpec, 
    V1ServicePort
)


################################################################################
## Configurable environment
OAUTH_CALLBACK_URL = os.environ["OAUTH_CALLBACK_URL"]
OAUTH_ENDPOINT = os.environ["OAUTH_ENDPOINT"]
OAUTH_GROUPS = os.environ["OAUTH_GROUPS"]
OAUTH_ADMIN_GROUPS = os.environ["OAUTH_ADMIN_GROUPS"]
IAM_CLIENT_ID = os.environ["IAM_CLIENT_ID"]
IAM_CLIENT_SECRET = os.environ["IAM_CLIENT_SECRET"]
START_TIMEOUT = int(os.environ.get("START_TIMEOUT", 20))
NFS_MOUNT_POINT = Path(os.environ.get("NFS_MOUNT_POINT", "/nfs-shared"))
NFS_SERVER_ADDRESS = os.environ.get("NFS_SERVER_ADDRESS")
STARTUP_SCRIPT = Path(os.environ.get("STARTUP_SCRIPT", "/envs/setup.sh"))
DEBUG = os.environ.get("DEBUG", "").lower() in ["true", "yes", "y"]
HOME_NAME = os.environ.get("HOME_NAME", "home")
SSH_PORT = int(os.environ.get("SSH_PORT", 22))
JHUB_NAMESPACE = os.environ.get("JHUB_NAMESPACE", "default")
DEFAULT_SPLASH_MESSAGE = os.environ.get("DEFAULT_SPLASH_MESSAGE", "Welcome")
DEFAULT_JLAB_IMAGES = json.loads(
  os.environ.get("DEFAULT_JLAB_IMAGES", '{"Default image": "harbor.cloud.infn.it/testbed-dm/ai-infn:0.1-pre10"}')
)
GPU_MODEL_DESCRIPTION = json.loads(
  os.environ.get("GPU_MODEL_DESCRIPTION", '[]')
)
CONFIGMAP_MOUNT_PATH = Path(
    os.environ.get(
        "CONFIGMAP_MOUNT_PATH", 
        os.path.join(os.path.dirname(__file__), "jupyterhub_config.d")
    )
)

# Virtual Kubelet Dispatcher configuration
ENABLE_VKD = os.environ.get("ENABLE_VKD", "").lower() in ["true", "yes", "y"]
VKD_SIDECAR_IMAGE = os.environ.get("VKD_SIDECAR_IMAGE", "harbor.cloud.infn.it/testbed-dm/vkd-dev:v0.0")
VKD_SIDECAR_NAME = os.environ.get("VKD_SIDECAR_NAME", "vkd")
VKD_ADMIN_SERVICE_ACCOUNT = os.environ.get("VKD_ADMIN_SERVICE_ACCOUNT", "vkd-batch-admin")
VKD_ADMIN_USER_GROUP = os.environ.get("VKD_ADMIN_USER_GROUP", "vkd")
VKD_PORT = os.environ.get("VKD_PORT", "8000")
VKD_MINIO_URL = os.environ.get("VKD_MINIO_URL", f"minio-singleuser.{JHUB_NAMESPACE}:9000")
VKD_MINIO_MAXIMUM_FOLDER_SIZE_GB = os.environ.get("VKD_MINIO_MAXIMUM_FOLDER_SIZE_GB", "1.0")
VKD_IMAGE_BRANCH = os.environ.get("VKD_IMAGE_BRANCH", "main")
VKD_NAMESPACE = os.environ.get("VKD_NAMESPACE", "vkd")


SYSTEM_VOLUMES = json.loads(os.environ.get("SYSTEM_VOLUMES", '["www", "vkd"]'))


if "JUPYTERHUB_CRYPT_KEY" not in os.environ.keys():
  raise Exception(
      "Environment variable JUPYTERHUB_CRYPT_KEY not set: run `openssl rand -hex 32` to generate."
      )

log_format = '%(asctime)-22s %(levelname)-8s %(message)-90s'
logging.basicConfig(
    format=log_format,
    level=logging.VERBOSE if DEBUG else logging.INFO,
)

logging.info("Starting custom INFN configuration of JupyterHub Spawner")
for global_var in list(globals().keys()):
  if global_var.upper() == global_var:
    logging.info(f"{global_var.replace('_', ' ') + ':':<30s} {pformat(globals().get(global_var))}")
logging.info("="*16)


################################################################################
## Direct access to kubernetes APIs 

k8s.config.load_incluster_config()

@asynccontextmanager
async def kubernetes_api(group: str = 'core'):
    _API_GROUPS_ = dict(
        core=k8s.client.CoreV1Api,
        custom_object=k8s.client.CustomObjectsApi
    )

    try:
        yield _API_GROUPS_[group]()
    except k8s.client.exceptions.ApiException as exception:
        try:
            body = json.loads(exception.body)
        except json.JSONDecodeError:
            logging.error("HTTP error not returning a JSON.")
            logging.error(traceback.print_exc())
            raise Exception(f"{exception.status} ({exception.reason}) {exception.body}")
        else:
            logging.error(f"Error {exception.status} ({exception.reason})")
            message = body.get("message", "Kubernetes error")
            logging.error(message)
            logging.error(traceback.print_exc())
            raise Exception(message)
    except Exception as e:
        logging.error(str(e))
        logging.error(traceback.print_exc())
        raise Exception("Unknown kubernetes error")


################################################################################
## IAM Authenticator

class IamAuthenticator(GenericOAuthenticator):
    """
    Custom implementation of the OAuth2 authenticator.
    """

    @gen.coroutine
    def pre_spawn_start(self, user, spawner):
        """
        Function called during the spawning process to:
         * make sure the user is still authenticated and belongs to the right groups
         * copy (some) of the authentication tokens to the spawned single-user server as env var

        """
        auth_state = yield user.get_auth_state()
        if not auth_state:
            # user has no auth state
            warnings.warn("Could not retrieve user's auth_state at spawning")
            return

        # define some environment variables from auth_state
        self.log.info(auth_state)
        spawner.environment['IAM_SERVER'] = OAUTH_ENDPOINT
        spawner.environment['IAM_CLIENT_ID'] = IAM_CLIENT_ID
        spawner.environment['IAM_CLIENT_SECRET'] = IAM_CLIENT_SECRET
        spawner.environment['ACCESS_TOKEN'] = auth_state['access_token']
        spawner.environment['REFRESH_TOKEN'] = auth_state['refresh_token']
        spawner.environment['USERNAME'] = auth_state['oauth_user']['preferred_username']
        spawner.environment['JUPYTERHUB_ACTIVITY_INTERVAL'] = "15"

        user_info = auth_state[self.user_auth_state_key]
        groups = self.get_user_groups(user_info)
        spawner.environment['GROUPS'] = ":".join(groups)
        
        allowed_groups = os.environ.get("OAUTH_GROUPS", "").split(" ")
        user_allowed = any([g in allowed_groups for g in groups])

        if not user_allowed:
            error_msg = f"User is not member of any of the allowed groups: {','.join(allowed_groups)}"
            self.log.error(error_msg)
            raise Exception(error_msg)


    # async def authenticate(self, handler, data=None):
    #   auth_model = await GenericOAuthenticator.authenticate(self, handler, data)
    #   pprint ("User info:")
    #   user_info = auth_model["auth_state"][self.user_auth_state_key]
    #   pprint(user_info)
    #   pprint ("Groups:")
    #   pprint (self.get_user_groups(user_info))

    #   return auth_model




################################################################################
## SplashManager


## Try to install markdown optional dependency

class SplashManager:
    def __init__ (self, resource):
        self._resource = resource

    @property
    def resource(self):
        return self._resource

    def message(self, **kwargs):
        if os.path.exists(self.resource):
            with open(self.resource) as splash_file:
                template = splash_file.read()
        else:
            template = textwrap.dedent(f"""
              <h3>{DEFAULT_SPLASH_MESSAGE}</h3>
              <P>You are logged as: {{{{ username }}}}</P>
              <P>You are member of the following projects: {{{{ groups | join(", ") }}}} </P>
            """)
            with open(self.resource, "w") as splash_file:
                splash_file.write(template)

        return jinja2.Template(template).render(**kwargs)
        


################################################################################
## Helper static functions
def _prefer_accelerator(node_selectors: Dict[str, str], weight=1):
    """
    Internal. Format the preference for an accelerator as an nodeAffinity preference.
    """
    return dict(
        weight=weight,
        preference=dict(
            matchExpressions=[
                {'key': label, 'operator': "In", "values": [value]}
                for label, value in node_selectors.items()
                ]
            )
        )




################################################################################
## InfnSpawner
class InfnSpawner(KubeSpawner):

    @staticmethod
    async def get_accelerators(
      status_key: Literal["allocated", "allocatable", "capacity"] = "allocatable",
      default_extended_resource: str = "nvidia.com/gpu"
      ):
      """
      Complete the list of known accelerators with the number of 
      available extended_resources as retrieved from the Node.

      Return the list defined in GPU_MODEL_DESCRIPTION with an additional
      `count` key reporting the number of each known accelerator model.

      The model `name` must match from the `accelerator` label.

      Requires additional ClusterRole and ClusterRoleBinding beyond 
      the jupyterhub helm chart to work.
      """

      async with kubernetes_api() as k:
        nodes = await k.list_node()

      pprint (nodes)

      # Copy the list
      return_list = [dict(**acc, count=0) for acc in GPU_MODEL_DESCRIPTION]

      if status_key in ['allocatable', 'capacity']:
        for node in nodes.items:
          accelerator = node.metadata.labels.get("accelerator", "none")
          if accelerator != "none":
            if hasattr(node.status, status_key):
              for return_item in return_list:
                if accelerator == return_item['name']:
                  ext_res = return_item.get("extended_resource", default_extended_resource)
                  node_count = getattr(node.status, status_key).get(ext_res, 0)
                  return_item['count'] += int(node_count)

      elif status_key in ['allocated']:
        async with kubernetes_api() as k:
          pods = await k.list_namespaced_pod(namespace=JHUB_NAMESPACE)

        node_dict = {node.metadata.name: node for node in nodes.items}

        for pod in pods.items:
          node = node_dict[pod.spec.node_name]
          accelerator = node.metadata.labels.get("accelerator", "none")
          if accelerator != "none":
            for return_item in return_list:
              if accelerator == return_item['name']:
                ext_res = return_item.get("extended_resource", default_extended_resource)
                for container in pod.spec.containers:
                  if container.resources.limits is not None:
                    container_count = container.resources.limits.get(ext_res, 0)
                  elif container.resources.requests is not None:
                    container_count = container.resources.requests.get(ext_res, 0)
                  else:
                    container_count = 0
                  return_item['count'] += int(container_count)
        
      else:
        raise KeyError(f"Unexpected status_key {status_key}")
            
      return return_list
      

    async def options_from_form(self, formdata):
        options = {}
        options['img'] = formdata['img']
        container_image = ''.join(formdata['img'])
        print("SPAWN: " + container_image + " IMAGE" )
        self.image = container_image

        options['cpu'] = formdata['cpu']
        cpu = ''.join(formdata['cpu'])
        self.cpu_guarantee = 1.
        self.cpu_limit = float(cpu)

        options['mem'] = formdata['mem']
        memory = ''.join(formdata['mem'])
        self.mem_guarantee = "2G"
        self.mem_limit = memory

        accelerator = "".join(formdata['gpu'])
        if accelerator in ["none"]:
          self.node_affinity_preferred = [
            _prefer_accelerator(
              acc.get('node_selector', {'accelerator': acc.get('name')}), 
              weight=acc.get('preference_weight', 50)
              )
            for acc in GPU_MODEL_DESCRIPTION
            ]

        elif accelerator.startswith('gpu:'):
          options['gpu'] = True

          _, model_gpu, n_gpus = accelerator.split(":")
          gpu_data = {g['name']: g for g in GPU_MODEL_DESCRIPTION}.get(model_gpu)
          if gpu_data is None:
            raise Exception(f"Failed retrieving data for GPU model {model_gpu}")

          ext_res = gpu_data.get('extended_resource', 'nvidia.com/gpu')
          self.extra_resource_guarantees = {ext_res: n_gpus}
          self.extra_resource_limits = {ext_res: n_gpus}

          self.tolerations.append(
            {"key": f"nvidia.com/gpu", "operator": "Exists", "effect": "PreferNoSchedule"}
          )

          self.node_affinity_preferred = [
            _prefer_accelerator(
              gpu_data.get('node_selector', {'accelerator': gpu_data.get('name')}), 
              weight=100
              )
          ]

        logging.info("Affinity - preferred")
        logging.info(self.node_affinity_preferred)
        return options

    #################################################################################
    #### SPLASH AND AUTHORIZATION
    #### ------------------------
    #### This section has to be handled using the request module and calling an external service via APIs
    
    @property
    def splash_manager(self):
      if not hasattr(self, "_splash_manager"): 
        self._splash_manager = SplashManager(NFS_MOUNT_POINT / "www" / "splash.html" )

      return self._splash_manager

    def get_user_name(self):
      return self.oauth_client_id[len('jupyterhub-user-'):]

    def get_user_groups(self):
      return [group.name for group in self.user.groups if not group.properties.get("system", False)] 

    def get_user_storage(self):
      return [group.properties.get("storage") for group in self.user.groups if "storage" in group.properties] 

    def check_priviledge(self, op):
      system_groups = [g.name for g in self.user.groups if g.properties.get("system", False)] 
      result = op in system_groups
      logging.info(f"{self.get_user_name()} { 'has' if result else 'has not' } permission '{op}'")
      return result

    #################################################################################
    #### VOLUMES
    #### -------

    @staticmethod
    def initialize_nfs_volumes():
        if NFS_SERVER_ADDRESS is not None:
          for name in ["envs", "public", *SYSTEM_VOLUMES]:
              if not os.path.exists(NFS_MOUNT_POINT/name):
                  os.mkdir(NFS_MOUNT_POINT/name)

          setup_filepath = Path(
            f"{NFS_MOUNT_POINT}/{STARTUP_SCRIPT}".replace("//", "/").replace("//", "/")
          )
          logging.info(f"Initializing setup script, {setup_filepath}")
          if not os.path.exists(setup_filepath):
              shutil.copy2(CONFIGMAP_MOUNT_PATH/"envs-setup.sh", setup_filepath)

        else:
          logging.warning("NFS_SERVER_ADDRESS not set. Will not mount network drivers.")


    def empty_volume(self, name):
      return dict(
        name=name, 
        emptyDir=dict(
          sizeLimit="1M",
        )
      )  

    def nfs_volume(self, name):
      if not os.path.exists(NFS_MOUNT_POINT/name):
        os.mkdir(NFS_MOUNT_POINT/name)
      return dict(
        name=name, 
        nfs=dict(
          server=NFS_SERVER_ADDRESS, 
          path=f"/{name}"
        )
      )  

    def nfs_mount(self, name, path, protected=False):
      return dict(
        name=name, 
        mountPath=path,
    )
      
    @property 
    def volumes(self):
      username = self.get_user_name()

      volumes = [
        self.empty_volume('secret-mask'),
      ]

      if NFS_SERVER_ADDRESS is not None:
        volumes += [
          self.nfs_volume(f'user-{username}'),
          self.nfs_volume(f'public'),
          self.nfs_volume(f'envs'),
          ]

        for volume in SYSTEM_VOLUMES:
          if self.check_priviledge(volume):
            volumes.append(self.nfs_volume(volume))

        for group in self.get_user_groups():
          volumes += [self.nfs_volume(f'shared-{group}')]

      return volumes

    @property 
    def volume_mounts (self):
      username = self.get_user_name()
      volumes = [
        {"name": "secret-mask", "mountPath": "/var/run/secrets/kubernetes.io/serviceaccount", "readOnly": True},
      ]
      if NFS_SERVER_ADDRESS is not None:
        volumes += [
          {"name": f"user-{username}", "mountPath": f"/{HOME_NAME}/private"},
          {"name": "public", "mountPath": f"/{HOME_NAME}/shared/public"},
          {"name": "envs", "mountPath": "/envs", "readOnly": not self.check_priviledge("envs")},
          ]

        for volume in SYSTEM_VOLUMES:
          if self.check_priviledge(volume):
            volumes += [{"name": volume, "mountPath": f"/{HOME_NAME}/system/{volume}"}]

        for group in self.get_user_groups():
          volumes += [{"name": f"shared-{group}", "mountPath": f"/{HOME_NAME}/shared/{group}", "readOnly": False}]

      return volumes

    #################################################################################
    #### INITIALIZATION SCRIPT
    #### ---------------------
    
    @property
    def lifecycle_hooks(self):
        storage = self.get_user_storage()
        if NFS_SERVER_ADDRESS is not None:
            return {
                "postStart": {
                  "exec": {
                    "command": ["/bin/bash", str(STARTUP_SCRIPT)] + storage
                    }
                  }
              }

        return dict()
       
    #################################################################################
    #### ADDITIONAL SERVICES
    #### -------------------

    @property
    def service_account(self):
      if ENABLE_VKD:
        return VKD_ADMIN_SERVICE_ACCOUNT #"vkd-batch-admin"
      else:
        return None

    @property
    def extra_containers(self):
      extra_containers = []
      if ENABLE_VKD:
          extra_containers.append(
              self._extra_container_virtual_kubelet_dispatcher,
          )

      return extra_containers


    @property 
    def _extra_container_virtual_kubelet_dispatcher(self):
      """
      Configure a sidecar container for dispatching jobs via kueue,
      possibly using a virtual kueblet
      """
      environment=dict(
        BRANCH=VKD_IMAGE_BRANCH, 
        INTERVAL="60",
        JUPYTERHUB_USERNAME=str(self.get_user_name()),
        JUPYTERHUB_GROUPS=":".join(self.get_user_groups()),
        ADMIN="true" if self.check_priviledge(VKD_ADMIN_USER_GROUP) else "",
        PORT=str(VKD_PORT),
        HTTP_PREFIX=f"/user/{self.get_user_name()}/proxy/{VKD_PORT}",
        MINIO_SERVER=VKD_MINIO_URL, 
        NAMESPACE=VKD_NAMESPACE,
        ORIGIN_NAMESPACE=JHUB_NAMESPACE,
        MAXIMUM_FOLDER_SIZE_GB=VKD_MINIO_MAXIMUM_FOLDER_SIZE_GB,
        )

      secrets=dict(
          MINIO_USER={'secretKeyRef': {"name": "minio-admin", "key": "minio-admin-user"}},
          MINIO_PASSWORD={'secretKeyRef': {"name": "minio-admin", "key": "minio-admin-password"}},
        )

      return dict(
          name=VKD_SIDECAR_NAME, #"vkd",
          imagePullPolicy="IfNotPresent",
          image=VKD_SIDECAR_IMAGE, #"landerlini/vk-dispatcher:alpine.0",
          env=(
              [dict(name=k, value=v) for k,v in environment.items()] + 
              [dict(name=k, valueFrom=v) for k, v in secrets.items()]
            ),
          volumeMounts=[v for v in self.volume_mounts if v['name'] not in ['secret-mask']],
          )


    #################################################################################
    #### Configure SSH access
    #### --------------------
    #### Creates and destroy services associated to each container, to add to the DNS
    #### an entry to reach the container from bastion.
    #### To this purpose, we override the _start and stop methods with the raw calls 
    #### to the kubernetes core API.
    ####
    #### To work, it also requires:
    ####  * the bastion service enabled and the pod active
    ####  * the sshd service running in the jupyter container (via `service ssh start`)
    ####  * a valid public key stored in the `private/.ssh` directory of the jupyter
    ####    container.

    async def _start(self):
        try:
          await self._config_ssh_service()
        except:
          logging.error("SSH service could not start")
          logging.error(traceback.print_exc())
          pass
        return await KubeSpawner._start(self)


    async def stop(self, now=False):
        try:
          await self._delete_ssh_service()
        except:
          logging.error("SSH service could not be stopped")
          logging.error(traceback.print_exc())
          pass

        return await KubeSpawner.stop(self, now)



    async def _config_ssh_service(self):
      logging.info("Setup SSH service")
      async with kubernetes_api() as k:
          await k.create_namespaced_service(
            namespace=JHUB_NAMESPACE,
            body=V1Service(
              metadata=V1ObjectMeta(
                name=f"sshd-{self.get_user_name()}",
                labels={
                  "app": "jupyterhub"
                }
              ),
              spec=V1ServiceSpec(
                type="ClusterIP",
                ports=[
                  V1ServicePort(name='sshd', port=SSH_PORT)
                ],
                selector={
                  "app": "jupyterhub",
                  "hub.jupyter.org/username": self.get_user_name(),
                }
              )
            )
          )


    async def _delete_ssh_service(self):
      logging.info("Cleanup SSH service")
      async with kubernetes_api() as k:
          await k.delete_namespaced_service(
            namespace=JHUB_NAMESPACE,
            name=f"sshd-{self.get_user_name()}",
          )


################################################################################
## Authentication setup

c.JupyterHub.tornado_settings = {'max_body_size': 1048576000, 'max_buffer_size': 1048576000}
c.JupyterHub.log_level = 30

c.JupyterHub.authenticator_class = IamAuthenticator
c.GenericOAuthenticator.oauth_callback_url = OAUTH_CALLBACK_URL

c.GenericOAuthenticator.client_id = IAM_CLIENT_ID
c.GenericOAuthenticator.client_secret = IAM_CLIENT_SECRET
c.GenericOAuthenticator.authorize_url = OAUTH_ENDPOINT.strip('/') + '/authorize'
c.GenericOAuthenticator.token_url = OAUTH_ENDPOINT.strip('/') + '/token'
c.GenericOAuthenticator.userdata_url = OAUTH_ENDPOINT.strip('/') + '/userinfo'
c.GenericOAuthenticator.scope = ['openid', 'profile', 'email', 'address', 'offline_access', 'wlcg', 'wlcg.groups']
c.GenericOAuthenticator.username_claim = "preferred_username"
c.GenericOAuthenticator.allowed_groups = set(OAUTH_GROUPS.split(" "))
c.GenericOAuthenticator.admin_groups = set(OAUTH_ADMIN_GROUPS.split(" "))

c.GenericOAuthenticator.claim_groups_key = lambda d: [ g[1:] if g[0] in '/' else g for g in d["wlcg.groups"]]

c.GenericOAuthenticator.enable_auth_state = True


################################################################################
## Spawner setup

c.JupyterHub.spawner_class = InfnSpawner
InfnSpawner.initialize_nfs_volumes()

c.KubeSpawner.cmd = ["jupyterhub-singleuser"]
c.KubeSpawner.args = ["--allow-root"]
c.KubeSpawner.privileged = True
c.KubeSpawner.allow_privilege_escalation = True

c.KubeSpawner.extra_pod_config = {
    "automountServiceAccountToken": True,
        }
      
c.KubeSpawner.environment = {
  "HOME": f"/{HOME_NAME}/private",
  "SHELL": "/bin/bash",
  "JUPYTERHUB_SINGLEUSER_APP": "jupyter_server.serverapp.ServerApp",
}

c.KubeSpawner.extra_container_config = {
    "securityContext": {
            "privileged": True,
            "capabilities": {
                        "add": ["SYS_ADMIN"]
                    }
        }
}

c.JupyterHub.hub_connect_ip = 'hub.default.svc.cluster.local'
c.KubeSpawner.notebook_dir = f"/{HOME_NAME}"
c.KubeSpawner.default_url = "/lab"

c.KubeSpawner.extra_container_config = {
    "securityContext": {
            "privileged": True,
            "capabilities": {
                        "add": ["SYS_ADMIN"]
                    }
        }
}

c.KubeSpawner.http_timeout = START_TIMEOUT
c.KubeSpawner.start_timeout = START_TIMEOUT

async def aiinfn_option_form (self):
    file_name = os.path.join(CONFIGMAP_MOUNT_PATH / "spawn_form.jinja2.html")
    accelerators = await self.get_accelerators("allocatable", "nvidia.com/gpu")
    allocated_accelerators = {
        acc['name']: acc['count'] 
        for acc in await self.get_accelerators("allocated", "nvidia.com/gpu")
        }

    for acc in accelerators:
      acc['avail'] = acc['count'] - allocated_accelerators.get(acc['name'], 0)
    
    logging.info("Groups")
    logging.info([group.name for group in self.user.groups])
    logging.info([group.__dict__ for group in self.user.groups])

    id_vars = dict(
      username=self.get_user_name(),
      groups=self.get_user_groups(),
    )

    with open(file_name) as f:
      return jinja2.Template(f.read()).render(
        splash_message=self.splash_manager.message(**id_vars),
        **id_vars,
        cpus=[1, 2, 3, 4, 8],
        mem_sizes=[2, 4, 8],
        accelerators=[
          dict(
              type="gpu",
              model=acc['name'],
              desc=acc.get('description', acc),
              avail=acc['avail'],
              tot=acc['count'],
          )
          for acc in accelerators if acc['count'] > 0 and acc['name'] not in ['none']
        ],
        images = [
          dict(name=v, desc=k) for k, v in DEFAULT_JLAB_IMAGES.items()
        ],
      )

c.KubeSpawner.options_form = aiinfn_option_form

