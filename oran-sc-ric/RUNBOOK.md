# ORAN Simulation Runbook

## 1. Start the Stack

```bash
cd /mnt/d/ORAN_ML_sim/ez-version/oran-sc-ric
docker compose down --remove-orphans
docker compose up --build -d
```

Wait for gNB to connect to RIC:
```bash
docker logs -f srsran_gnb | grep -m1 "E2 Setup Response"
```

## 2. Start srsUE (new terminal)

```bash
sudo ip netns add ue1 2>/dev/null; true
sudo ./srsue /mnt/d/ORAN_ML_sim/ez-version/oran-sc-ric/e2-agents/srsRAN/ue_zmq.conf
```

Wait for `RRC Connected` and `PDU Session Established`.

Verify UE has IP:
```bash
sudo ip netns exec ue1 ip addr show tun_srsue
```

## 3. Start iperf3 Server (keep running for all tests)

```bash
docker exec -d open5gs_5gc iperf3 -s
```

## 4. Watch Slice Controller (new terminal)

```bash
docker logs -f slice_ctrl_xapp
```

---

## QoS Test 1 — eMBB (Streaming / Heavy Download)

High DL, low UL → classifier picks SST1 → max PRB to eMBB slice.

```bash
sudo ip netns exec ue1 iperf3 -c 10.45.1.1 -b 20M -t 60
```

Expected slice_ctrl_xapp output:
```
[classify] ... DL=20000 UL=0 kbps → SST1
[ctrl] dominant=eMBB(SST1) → applying PRB profile
  SST1: min=10% max=30% ded=30%
```

---

## QoS Test 2 — URLLC (Video Call / Gaming)

Symmetric DL + UL → classifier picks SST2 → max PRB to URLLC slice.

Run both directions simultaneously (2 terminals):

**Terminal A — DL (server → UE):**
```bash
sudo ip netns exec ue1 iperf3 -c 10.45.1.1 -b 5M -R -t 60
```

**Terminal B — UL (UE → server):**
```bash
sudo ip netns exec ue1 iperf3 -c 10.45.1.1 -b 5M -t 60
```

Expected:
```
[classify] ... DL=5000 UL=5000 kbps → SST2
[ctrl] dominant=URLLC(SST2) → applying PRB profile
  SST2: min=20% max=100% ded=70%
```

---

## QoS Test 3 — mMTC (IoT / Sensor)

Low continuous traffic both directions → classifier picks SST3.

**Terminal A — low rate DL:**
```bash
sudo ip netns exec ue1 iperf3 -c 10.45.1.1 -u -b 50K -R -t 120
```

**Terminal B — low rate UL:**
```bash
sudo ip netns exec ue1 iperf3 -c 10.45.1.1 -u -b 50K -t 120
```

Expected:
```
[classify] ... DL=50 UL=50 kbps → SST3
[ctrl] dominant=mMTC(SST3) → applying PRB profile
  SST3: min=5% max=30% ded=20%
```

---

## Useful Commands

```bash
# Check all containers running
docker compose ps

# gNB logs
docker logs -f srsran_gnb

# KPM dashboard logs
docker logs -f python_xapp_runner

# Slice controller logs
docker logs -f slice_ctrl_xapp

# Ping through UE to verify connectivity
sudo ip netns exec ue1 ping -c5 10.45.1.1

# Grafana
http://localhost:3000  (admin / admin)

# Restart slice controller only (without affecting Grafana)
docker restart slice_ctrl_xapp

# Full teardown
docker compose down
```
