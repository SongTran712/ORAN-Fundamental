#!/usr/bin/env python3
import signal
import time
import requests

from lib.xAppBase import xAppBase

INFLUXDB_URL  = "http://influxdb:8086"
INFLUXDB_DB   = "kpm"
E2MGR_URL     = "http://e2mgr:3800"
POLL_INTERVAL = 10

NODE_METRICS = [
    "CQI", "RSRP", "RSRQ",
    "RRU.PrbTotDl",  "RRU.PrbTotUl",
    "RRU.PrbUsedDl", "RRU.PrbUsedUl",
    "RRU.PrbAvailDl","RRU.PrbAvailUl",
    "DRB.UEThpDl",   "DRB.UEThpUl",
    "DRB.RlcSduTransmittedVolumeDL", "DRB.RlcSduTransmittedVolumeUL",
    "DRB.RlcSduDelayDl",
    "RACH.PreambleDedCell",
]

UE_METRICS = [
    "CQI",
    "RSRP",
    "DRB.UEThpDl",
    "DRB.UEThpUl",
    "RRU.PrbUsedUl",
    "DRB.RlcSduDelayDl",
]

MATCH_ALL_UES = [{"matchingCondChoice": ("testCondInfo", {
    "testType": ("ul-rSRP", "true"),
    "testExpr": "lessthan",
    "testValue": ("valueInt", 1000)
})}]


def _to_float(v):
    if isinstance(v, list):
        v = v[0] if v else None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class KpmDashboardXapp(xAppBase):
    def __init__(self, http_server_port=8092, rmr_port=4562):
        super().__init__('', http_server_port, rmr_port)
        self._node_subs = {}
        self._init_db()

    def _init_db(self):
        try:
            requests.post(f"{INFLUXDB_URL}/query",
                          params={"q": f"CREATE DATABASE {INFLUXDB_DB}"},
                          timeout=3)
            print(f"InfluxDB ready: {INFLUXDB_URL}  db={INFLUXDB_DB}")
        except Exception as e:
            print(f"InfluxDB init warning: {e}")

    def _write_influx(self, measurement, tags, fields):
        if not fields:
            return
        tag_str = ",".join(
            f"{k}={v.replace(',', chr(92)+',').replace(' ', chr(92)+' ').replace('=', chr(92)+'=')}"
            for k, v in tags.items()
        )
        field_str = ",".join(f"{k}={v}" for k, v in fields.items())
        try:
            r = requests.post(f"{INFLUXDB_URL}/write",
                              params={"db": INFLUXDB_DB},
                              data=f"{measurement},{tag_str} {field_str}".encode(),
                              timeout=2)
            if r.status_code not in (204, 200):
                print(f"InfluxDB write error {r.status_code}: {r.text[:80]}")
        except Exception as e:
            print(f"InfluxDB write error: {e}")

    def node_indication_callback(self, e2_agent_id, subscription_id, hdr, msg):
        data = self.e2sm_kpm.extract_meas_data(msg).get("measData", {})
        fields = {n.replace(".", "_"): v
                  for n, raw in data.items()
                  if (v := _to_float(raw)) is not None}
        if fields:
            print(f"[node] gnb={e2_agent_id}  {len(fields)} metrics")
            self._write_influx("kpm", {"gnb": e2_agent_id}, fields)

    def ue_indication_callback(self, e2_agent_id, subscription_id, hdr, msg):
        ue_data = self.e2sm_kpm.extract_meas_data(msg).get("ueMeasData", {})
        for ue_id, ue_report in ue_data.items():
            fields = {}
            for n, raw in ue_report.get("measData", {}).items():
                v = _to_float(raw)
                if v is None:
                    continue
                fields[n.replace(".", "_")] = v
            if fields:
                print(f"[ue]   ue={ue_id}  {fields}")
                self._write_influx("kpm_ue", {"gnb": e2_agent_id, "ue": f"ue_{ue_id}"}, fields)

    def _get_connected_nodes(self):
        try:
            r = requests.get(f"{E2MGR_URL}/v1/nodeb/states", timeout=5)
            return {n["inventoryName"] for n in r.json()
                    if n.get("connectionStatus") == "CONNECTED"}
        except Exception:
            return set()

    def _subscribe_node(self, node_id):
        print(f"[+] Subscribing to {node_id}")
        sub_ids = []

        def _try(fn, *args):
            for attempt in range(1, 16):
                try:
                    fn(*args)
                    sub_ids.append(list(self.my_subscriptions.keys())[-1])
                    return
                except Exception as e:
                    code = getattr(e, 'status', None) or getattr(e, 'code', None)
                    print(f"  attempt {attempt}/15 failed ({code or e}), retry in 6s")
                    time.sleep(6)

        _try(self.e2sm_kpm.subscribe_report_service_style_1,
             node_id, 1000, NODE_METRICS, 1000,
             lambda a, s, h, m: self.node_indication_callback(a, s, h, m))

        for metric in UE_METRICS:
            _try(self.e2sm_kpm.subscribe_report_service_style_3,
                 node_id, 1000, MATCH_ALL_UES, [metric], 1000,
                 lambda a, s, h, m: self.ue_indication_callback(a, s, h, m))

        self._node_subs[node_id] = sub_ids
        print(f"[+] {node_id} subscribed  ({len(sub_ids)} subs)")

    def _unsubscribe_node(self, node_id):
        print(f"[-] Unsubscribing from {node_id}")
        for sub_id in self._node_subs.pop(node_id, []):
            try:
                self.unsubscribe(sub_id)
            except Exception as e:
                print(f"  unsubscribe {sub_id} error: {e}")

    @xAppBase.start_function
    def start(self):
        known = set()
        while self.running:
            current = self._get_connected_nodes()
            for node in current - known:
                self._subscribe_node(node)
            for node in known - current:
                print(f"[-] {node} disconnected — cleaning up subs")
                self._node_subs.pop(node, None)
            known = current
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    xapp = KpmDashboardXapp()
    xapp.e2sm_kpm.set_ran_func_id(2)
    signal.signal(signal.SIGTERM, xapp.signal_handler)
    signal.signal(signal.SIGINT,  xapp.signal_handler)
    xapp.start()
