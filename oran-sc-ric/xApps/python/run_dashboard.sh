#!/bin/bash
# Kill any existing xApp holding port 8092 / kpm processes
for pid in $(ls /proc | grep -E '^[0-9]+$'); do
  cat /proc/$pid/cmdline 2>/dev/null | tr '\0' ' ' | grep -qE 'kpm_mon|kpm_dashboard' && kill $pid 2>/dev/null
done
sleep 1
cd /opt/xApps
rm -f dashboard.log
python3 kpm_dashboard_xapp.py >> dashboard.log 2>&1
