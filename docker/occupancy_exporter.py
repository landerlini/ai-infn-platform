"""
occupancy_exporter.py

Occupancy Exporter is a prometheus python exporter designed to retrieve the 
disk usage in particular for the NFS volume.

It is capable of exporting the space used by subfolders. 

In this first version the data size is computed by looping (in Python)
on the files in each folder. This can be done more effeciently relying 
on du or on languages for looping. This is left for future optimization.

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

import os
import json
import time
import timeit
import logging
from pathlib import Path
from typing import Dict
logger = logging.getLogger('prom-nfs')

from prometheus_client.registry import Collector

PORT = int(os.environ.get("PORT", '9400'))
ACTIVE_SUBPATHS = json.loads(os.environ.get("MONITORING_SUBPATHS", '["NFS"]'))
DEBUG = os.environ.get("DEBUG", "false").lower() in ('yes', 'true', 'y')
PATHS = json.loads(
  os.environ.get("MONITORING_PATHS", 
    '{"NFS": "/exports/nfs/nfs", "/envs": "/exports/nfs/nfs/envs", "S3": "/exports/minio"}'
    )
  )
VOLUMES = json.loads(
  os.environ.get("MONITORING_VOLUMES", 
    '{"nVME": "/exports"}'
    )
  )

METRICS = dict()

log_format = '%(asctime)-22s %(levelname)-8s %(message)-90s'
logging.basicConfig(
    format=log_format,
    level=logging.DEBUG if DEBUG else logging.INFO,
)



class FilesystemRunner:
    @staticmethod
    def _get_paths():
      """Internal. Returns the list of paths to scan."""
      paths = {k: Path(v) for k, v in PATHS.items()}
      for label, root in [item for item in paths.items()]:
        if label in ACTIVE_SUBPATHS:
          paths.update({str(k):k for k in root.glob('*') if k.is_dir()})

      return paths

    @staticmethod
    def used_disk():
        """Used disk metric"""
        logging.debug("Computing used disk")

        used_disk = GaugeMetricFamily(
          'storage_used_disk', 
          'Disk storage used in bytes', 
          labels=['dir']
          )

        ## Fill used disk metrics
        for label, path in FilesystemRunner._get_paths().items():
          used_disk.add_metric([label], 
            sum(f.stat().st_size for f in path.glob('**/*') if f.is_file())
          )

        return used_disk

    @staticmethod
    def number_of_files():
        """Used disk metric"""
        logging.debug("Computing number of files")
        
        # Number of files
        number_of_files = CounterMetricFamily(
          'storage_number_of_files', 
          'Number of files on disk', 
          labels=['dir']
          )

        ## Fill used disk metrics
        for label, path in FilesystemRunner._get_paths().items():
          number_of_files.add_metric([label], 
            len([f for f in path.glob('**/*') if f.is_file()])
          )

        return number_of_files

    @staticmethod
    def avail_disk(volumes: Dict[str, str]):
      """Available disk size"""
      # Available disk size
      logging.debug("Computing Available disk space")
      avail_disk = GaugeMetricFamily(
        'storage_avail_disk', 
        'Disk storage available in bytes', 
        labels=['dir']
        )
        
      ## Fill available disk metrics
      for label, path in volumes.items():
        statvfs = os.statvfs(path)
        avail_disk.add_metric([label], 
            statvfs.f_frsize * statvfs.f_bavail
        )

      return avail_disk

    @staticmethod
    def total_disk(volumes: Dict[str, str]):
      """Total volume size"""
      logging.debug("Computing TOTAL disk space")
      # Total disk size
      total_disk = GaugeMetricFamily(
        'storage_total_disk', 
        'Total disk storage size in bytes', 
        labels=['dir']
        )
        
      for label, path in volumes.items():
        statvfs = os.statvfs(path)
        total_disk.add_metric([label], 
            statvfs.f_frsize * statvfs.f_blocks
        )

      return total_disk

    def update_metrics(self):
        global METRICS
        start_time = timeit.default_timer()
        METRICS['number_of_files'] = self.number_of_files()
        METRICS['used_disk'] = self.used_disk()
        METRICS['avail_disk'] = self.avail_disk(VOLUMES)
        METRICS['total_disk'] = self.total_disk(VOLUMES)
        stop_time = timeit.default_timer()
        logging.debug(f"Last scan required {stop_time - start_time} seconds")
        METRICS['scan_time'] = GaugeMetricFamily(
          'storage_scan_time_seconds', 
          'Time required to perform a full scan of the filesystem', 
          float(stop_time - start_time)
          )


class CustomCollector(Collector):
    def collect(self):
      """Collect aggregation function"""
      if 'number_of_files' in METRICS:
        yield METRICS['number_of_files']

      if 'used_disk' in METRICS:
        yield METRICS['used_disk']

      if 'avail_disk' in METRICS:
        yield METRICS['avail_disk']

      if 'total_disk' in METRICS:
        yield METRICS['total_disk']

      if 'scan_time' in METRICS:
        yield METRICS['scan_time']


REGISTRY.register(CustomCollector())

if __name__ == '__main__':
    # Print the status
    print ("DEBUG: ", DEBUG)
    print ("PATHS: ", PATHS)
    print ("VOLUMES: ", VOLUMES)
    print ("ACTIVE_SUBPATHS: ", ACTIVE_SUBPATHS)

    # Start up the server to expose the metrics.
    start_http_server(PORT)

    fs_runner = FilesystemRunner()

    while True: 
        fs_runner.update_metrics()
        time.sleep(10)


