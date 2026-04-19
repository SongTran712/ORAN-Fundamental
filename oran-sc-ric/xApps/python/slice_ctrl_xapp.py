#!/usr/bin/env python3
"""
Slice controller xApp.

Reads UE throughput from InfluxDB (written by kpm_dashboard_xapp),
classifies traffic as eMBB/URLLC/mMTC, and sends E2SM-RC Slice-Level
PRB Quota control for SST 1/2/3.

Runs independently — can be stopped/started without affecting Grafana.
"""

import signal
import time
import requests

from lib.xAppBase import xAppBase

INFLUXDB_URL   = "http://influxdb:8086"
INFLUXDB_DB    = "kpm"
E2MGR_URL      = "http://e2mgr:3800"
CTRL_INTERVAL  = 5

LOW_THR_KBPS    = 1000
DL_UL_RATIO_THR = 5.0

PROFILES = {
    #              SST1(min,max,ded)  SST2(min,max,ded)  SST3(min,max,ded)
    1: {1: (10, 60, 50), 2: (10, 30, 10), 3: (0, 20, 5)},   # eMBB dominant
    2: {1: (10, 60, 10), 2: (10, 30, 25), 3: (0, 20, 5)},   # URLLC dominant
    3: {1: (10, 60, 20), 2: (10, 30, 10), 3: (0, 20, 15)},  # mMTC dominant
}


def classify(dl, ul):
    if dl < LOW_THR_KBPS and ul < LOW_THR_KBPS:
        return 3
    if dl / max(ul, 1) < DL_UL_RATIO_THR:
        return 2
    return 1


def query_influx(q):
    try:
        r = requests.get(f"{INFLUXDB_URL}/query",
                         params={"db": INFLUXDB_DB, "q": q}, timeout=3)
        return r.json()
    except Exception:
        return {}


def get_latest_ue_metrics():
    result = query_influx(
        'SELECT last("DRB_UEThpDl"), last("DRB_UEThpUl") FROM kpm_ue GROUP BY "gnb"'
    )
    out = {}
    try:
        for series in result["results"][0]["series"]:
            node_id = series["tags"]["gnb"]
            cols = series["columns"]
            vals = series["values"][0]
            row = dict(zip(cols, vals))
            out[node_id] = {
                "dl": float(row.get("last", 0) or 0),
                "ul": float(row.get("last_1", 0) or 0),
            }
    except (KeyError, IndexError, TypeError):
        pass
    return out


def get_connected_nodes():
    try:
        r = requests.get(f"{E2MGR_URL}/v1/nodeb/states", timeout=5)
        return {n["inventoryName"] for n in r.json()
                if n.get("connectionStatus") == "CONNECTED"}
    except Exception:
        return set()


class SliceCtrlXapp(xAppBase):
    def __init__(self, http_server_port=8093, rmr_port=4563):
        super().__init__('', http_server_port, rmr_port)
        self._last_dominant = {}

    def _apply_profile(self, node_id, dominant_sst):
        if self._last_dominant.get(node_id) == dominant_sst:
            return
        label = {1: "eMBB", 2: "URLLC", 3: "mMTC"}[dominant_sst]
        print(f"[ctrl] {node_id}: {label}(SST{dominant_sst}) → applying PRB profile")
        for sst, (mn, mx, ded) in PROFILES[dominant_sst].items():
            try:
                self.e2sm_rc.control_slice_level_prb_quota(
                    node_id, 0, mn, mx, ded, ack_request=0, sst=sst
                )
                print(f"  SST{sst}: min={mn}% max={mx}% ded={ded}%")
            except Exception as e:
                print(f"  SST{sst} RC error: {e}")
        self._last_dominant[node_id] = dominant_sst
        try:
            requests.post(f"{INFLUXDB_URL}/write",
                          params={"db": INFLUXDB_DB},
                          data=f"slice_ctrl,gnb={node_id} dominant_sst={float(dominant_sst)}".encode(),
                          timeout=2)
        except Exception:
            pass

    @xAppBase.start_function
    def start(self):
        print("[slice_ctrl] started — reading InfluxDB every 5s")
        while self.running:
            nodes = get_connected_nodes()
            metrics = get_latest_ue_metrics()
            for node_id in nodes:
                if node_id in metrics:
                    dl = metrics[node_id]["dl"]
                    ul = metrics[node_id]["ul"]
                else:
                    dl, ul = 0.0, 0.0
                dom = classify(dl, ul)
                print(f"[classify] {node_id} DL={dl:.0f} UL={ul:.0f} kbps → SST{dom}")
                self._apply_profile(node_id, dom)
            time.sleep(CTRL_INTERVAL)


if __name__ == "__main__":
    xapp = SliceCtrlXapp()
    xapp.e2sm_rc.set_ran_func_id(3)
    signal.signal(signal.SIGTERM, xapp.signal_handler)
    signal.signal(signal.SIGINT,  xapp.signal_handler)
    xapp.start()
