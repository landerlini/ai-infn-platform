"""
gpu_alloc_exporter.py

Occupancy Exporter is a prometheus python exporter designed to retrieve the 
number of extended resources available and allocated.

Released under MIT licence.
(c) Istituto Nazionale di Fisica Nucleare (2024)

"""
from prometheus_client import (
    start_http_server, 
    Summary, 
  )

from prometheus_client.core import (
    GaugeMetricFamily, 
    CounterMetricFamily, 
    REGISTRY,
  )

from contextlib import contextmanager
import os
import json
import time
import timeit
import logging
from pathlib import Path
from typing import Dict, Literal

import traceback

from prometheus_client.registry import Collector
import kubernetes as k8s
from kubernetes.client.models import (
    V1Service, 
    V1ObjectMeta, 
    V1ServiceSpec, 
    V1ServicePort
)

PORT = int(os.environ.get("PORT", '9400'))
DEBUG = os.environ.get("DEBUG", "false").lower() in ('yes', 'true', 'y')
EXTENDED_RESOURCES = json.loads(
    os.environ.get("EXTENDED_RESOURCES",
      '["nvidia.com/gpu"]'
      )
    )

MONITORED_NAMESPACES = json.loads(
    os.environ.get("MONITORED_NAMESPACES",
      '["default"]'
      )
    )

INTERSCAN_PAUSE = int(os.environ.get("INTERSCAN_PAUSE", "2"))

NODE_LABEL_FOR_MODEL = os.environ.get("NODE_LABEL_FOR_MODEL", "nvidia.com/product")

METRICS = dict()

## Logging configuration
log_format = '%(asctime)-22s %(levelname)-8s %(message)-90s'
logging.basicConfig(
    format=log_format,
    level=logging.DEBUG if DEBUG else logging.INFO,
)
logger = logging.getLogger('prom-gpu')

## Kubernetes configuration
k8s.config.load_incluster_config()


@contextmanager
def kubernetes_api(group: Literal['core', 'custom_object'] = 'core'):
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
            logger.error("HTTP error not returning a JSON.")
            logger.error(traceback.print_exc())
            raise Exception(f"{exception.status} ({exception.reason}) {exception.body}")
        else:
            logger.error(f"Error {exception.status} ({exception.reason})")
            message = body.get("message", "Kubernetes error")
            logger.error(message)
            logger.error(traceback.print_exc())
            raise Exception(message)
    except Exception as e:
        logger.error(str(e))
        logger.error(traceback.print_exc())
        raise Exception("Unknown kubernetes error")


class ExtendedResourceRunner:
    @staticmethod
    def get_allocatable_accelerators():
      """
      Loops over the nodes to count the number of allocatable 
      extended resources listed in EXTENDED_RESOURCES.

      Return a GaugeMetricFamily metric with labels:
       - node:
          name of the Kubernetes node provisioning the accelerator

       - model: 
          model of the accelerator as inferred from NODE_LABEL_FOR_MODEL

       - extended_resource:
          name of the extended resource (e.g. nvidia.com/gpu)

      """

      with kubernetes_api() as k:
        nodes = k.list_node()

      number_of_allocatable_accelerator = GaugeMetricFamily(
        'allocatable_accelerators', 
        'Number of accelerators that can be allocated', 
        labels=['node', 'model', 'extended_resource']
        )

      for node in nodes.items:
        node_name = node.metadata.name
        model_name = node.metadata.labels.get(NODE_LABEL_FOR_MODEL, "Generic")
        for extended_resource in EXTENDED_RESOURCES:
          node_count = int(getattr(node.status, "allocatable").get(extended_resource, 0))
          if node_count > 0:
            number_of_allocatable_accelerator.add_metric(
                [node_name, model_name, extended_resource],
                node_count
                )

      return number_of_allocatable_accelerator
              

    @staticmethod
    def get_allocated_accelerators():
      """
      Loops over the nodes to count the number of allocatable 
      extended resources listed in EXTENDED_RESOURCES.

      Return a GaugeMetricFamily metric with labels:
       - node:
          name of the Kubernetes node provisioning the accelerator

       - model: 
          model of the accelerator as inferred from NODE_LABEL_FOR_MODEL

       - extended_resource:
          name of the extended resource (e.g. nvidia.com/gpu)

      """

      with kubernetes_api() as k:
        nodes = k.list_node()

      number_of_allocated_accelerator = GaugeMetricFamily(
        'allocated_accelerators', 
        'Number of files on disk', 
        labels=['node', 'model', 'extended_resource', 'namespace', 'pod']
        )


      with kubernetes_api() as k:
        pods = k.list_pod_for_all_namespaces()

      node_dict = {node.metadata.name: node for node in nodes.items}

      for pod in pods.items:
        if pod.metadata.namespace not in MONITORED_NAMESPACES: continue
        pod_name = pod.metadata.name
        node = node_dict[pod.spec.node_name]
        node_name = node.metadata.name
        model_name = node.metadata.labels.get(NODE_LABEL_FOR_MODEL, "Generic")
        for extended_resource in EXTENDED_RESOURCES:
          pod_counter = 0
          for container in pod.spec.containers:
            if container.resources.limits is not None:
              pod_counter += int(container.resources.limits.get(extended_resource, 0))
            elif container.resources.requests is not None:
              pod_counter += int(container.resources.requests.get(extended_resource, 0))

          if pod_counter > 0:  
            number_of_allocated_accelerator.add_metric(
                [node_name, model_name, extended_resource, pod.metadata.namespace, pod_name],
                pod_counter
                )
                  
        
      return number_of_allocated_accelerator
      
    def update_metrics(self):
        global METRICS
        start_time = timeit.default_timer()
        METRICS['allocatable_accelerators'] = self.get_allocatable_accelerators()
        METRICS['allocated_accelerators'] = self.get_allocated_accelerators()
        stop_time = timeit.default_timer()
        logger.debug(f"Last scan required {stop_time - start_time} seconds")
        METRICS['scan_time'] = GaugeMetricFamily(
          'accelerator_alloc_scan_time_seconds', 
          'Time required to perform a full scan of nodes and of the pods', 
          float(stop_time - start_time)
          )


class CustomCollector(Collector):
    def collect(self):
      """Collect aggregation function"""
      if 'allocated_accelerators' in METRICS:
        yield METRICS['allocated_accelerators']

      if 'allocatable_accelerators' in METRICS:
        yield METRICS['allocatable_accelerators']

      if 'scan_time' in METRICS:
        yield METRICS['scan_time']


REGISTRY.register(CustomCollector())

if __name__ == '__main__':
    # Print the status
    print ("DEBUG:                ", DEBUG)
    print ("PORT:                 ", PORT)
    print ("EXTENDED_RESOURCES:   ", EXTENDED_RESOURCES)
    print ("MONITORED_NAMESPACES: ", MONITORED_NAMESPACES)
    print ("NODE_LABEL_FOR_MODEL: ", NODE_LABEL_FOR_MODEL)
    print ("INTERSCAN_PAUSE:      ", INTERSCAN_PAUSE)

    # Start up the server to expose the metrics.
    start_http_server(PORT)

    # Extended Resource Runner
    ext_res_runner = ExtendedResourceRunner()

    # Loop 
    while True: 
        ext_res_runner.update_metrics()
        time.sleep(INTERSCAN_PAUSE)



