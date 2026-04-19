#!/bin/bash
# Run a KPM demo scenario.
# Edit demo.env to change defaults, or pass CLI flags to override.
#
# Examples:
#   bash run_demo.sh
#   bash run_demo.sh --mode homogeneous --ues 5 --cqi 12
#   bash run_demo.sh --mode grouped --groups 12:2,6:3,2:1
#   bash run_demo.sh --mode dynamic --ues 4 --change-interval 8

# Kill any previous demo instance
for pid in $(ls /proc | grep -E '^[0-9]+$'); do
  cat /proc/$pid/cmdline 2>/dev/null | tr '\0' ' ' | grep -q 'demo_scenario' \
    && kill $pid 2>/dev/null
done
sleep 1

cd /opt/xApps

# Source defaults from demo.env, then allow CLI overrides
set -a
source /opt/xApps/demo.env
set +a

python3 demo_scenario.py "$@"
