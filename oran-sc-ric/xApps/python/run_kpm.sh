#!/bin/bash
for pid in $(ls /proc | grep -E '^[0-9]+$'); do
  cat /proc/$pid/cmdline 2>/dev/null | tr '\0' ' ' | grep -q 'kpm_mon' && kill $pid 2>/dev/null
done
sleep 1
cd /opt/xApps
rm -f kpm_live.log
python3 kpm_mon_xapp.py --kpm_report_style 1 --metrics DRB.UEThpUl,DRB.UEThpDl >> kpm_live.log 2>&1
