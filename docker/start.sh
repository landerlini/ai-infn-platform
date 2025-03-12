#!/bin/bash
echo "Activating conda"
source /usr/local/bin/before-notebook.d/10activate-conda-env.sh

echo "Executing"
eval "$@"

