#!/bin/bash

################################################################################
## Conda usage for new users
## -------------------------
## Initialize bash for new users
################################################################################
/opt/conda/bin/conda init bash


################################################################################
## Setup Local Storage
## -------------------
## This storage is platform-persistent and supports symbolic links
## it is used to share code and software environment in a user-friendly way.
## It is not backupped. It is not safe. Please use git to preserve your work.
## Eventually, at least part of this should migrate to cvmfs.
################################################################################

## ## Example:
##
## ln -s /envs/root/bin/root-config /usr/bin/root-config
## /opt/conda/bin/conda \
##  run -p /envs/root \
##  python3 -m ipykernel install --name "hep" --display-name "HEP"
## 
## /opt/conda/bin/conda \
##  run -p /envs/MedPhys \
##  python3 -m ipykernel install --name "MedPhys" --display-name "MedPhys"
## 
## /opt/conda/bin/conda \
##  run -p /envs/modulus \
##  python3 -m ipykernel install --name "modulus" --display-name "nVidia modulus"
## 
## export ROOTSYS=/envs/root
## cp -r $ROOTSYS/etc/notebook/kernels/root /usr/local/share/jupyter/kernels

################################################################################
## Setup Cloud Storage
## -------------------
## This storage is cloud-persistent and relies on the managed RadosGW service,
## for details, please refer to rgw.cloud.infn.it.
## This storage is good for medium-size datasets shared among multiple users.
## It does not support symbolic links and it becomes slow with a large amount
## of small files. Hence, it is not good for sharing code and software 
## environments.
################################################################################

BASE_CACHE_DIR="/usr/local/share/dodasts/sts-wire/cache"
WORKAREA="/home"

####
# Temporary solution to migrate from minio to rados GW: cached rclone must be replaced.
rm -f /home/private/.cache/sts-wire/rclone
####

mkdir -p "${BASE_CACHE_DIR}"
mkdir -p /usr/local/share/dodasts/sts-wire/cache
mkdir -p /var/log/sts-wire/
mkdir -p /s3/
mkdir -p "${WORKAREA}"/rgw

function mount_rgw {
  local volume=$1;
  mkdir -p /s3/$volume;
  nice -n 19 sts-wire https://iam.cloud.infn.it/ \
      "$volume" https://rgw.cloud.infn.it/ IAMaccess object \
      "/$volume" "/s3/$volume" \
      --localCache full --tryRemount --noDummyFileCheck \
      --localCacheDir "${BASE_CACHE_DIR}/$volume" \
      &>"/var/log/sts-wire/mount_log_$volume.txt" &
  ln -s "/s3/$volume" "${WORKAREA}/rgw/$volume"
}

sleep 0.1 && mount_rgw $USERNAME || echo "Ok"  
sleep 0.2 && mount_rgw scratch || echo "Ok"

for additional_volume in $@;
do
  mount_rgw $additional_volume || echo "Ok"  ;
done

################################################################################
## Setup SSH connection
## -------------------
## Configure an ssh connection to the docker and launch a reverse proxy to a 
## bastion.
## SSH server and client should be installed in the docker for this to succeed.
################################################################################
service ssh start


################################################################################
## Custom user setup
## -----------------
## Run the .cloud-profile script the user might have in its home directory.
################################################################################

if [ -f "/mlinfn/private/.cloud-profile" ]
then
  /bin/bash /mlinfn/private/.cloud-profile || echo Ok &
fi


