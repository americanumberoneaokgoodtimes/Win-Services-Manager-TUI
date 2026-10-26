"""
Service Resource Monitor Module
Retrieves and tracks real-time system resource usage for Windows services:
- memory_percent / RAM footprint in MB
- cpu_percent (from the last 60 minutes / process uptime window)
- num_threads
- IO: io_counters.read_bytes + io_counters.write_bytes
- connections count: len(connections())
- nice: process priority class name (e.g. NORMAL, HIGH, IDLE)

Formatted as:
"MEM: 1111 MB, CPU: (60min) 1.11, THREADS: 11, IO: 111111111, CONNECTIONS: 1, NICE: NORMAL"
"""

import time
from typing import List, Dict, Any, Optional
from collections import defaultdict

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

NICE_MAP = {
    32: "NORMAL",
    64: "IDLE",
    128: "HIGH",
    256: "REALTIME",
    16384: "BELOW_NORMAL",
    32768: "ABOVE_NORMAL",
}

class ServiceLoadMonitor:
    def __init__(self):
        self._cached_metrics: Dict[str, Dict[str, Any]] = {}

    def fetch_metrics(self) -> Dict[str, Dict[str, Any]]:
        """
        Gathers live process resource statistics for running services.
        Handles shared svchost.exe instances by prorating across hosted services.
        """
        if not HAS_PSUTIL:
            return {}

        now = time.time()
        pid_to_services: Dict[int, List[str]] = defaultdict(list)
        svc_to_pid: Dict[str, int] = {}

        for s in psutil.win_service_iter():
            try:
                if s.status() == 'running':
                    pid = s.pid()
                    if pid:
                        sname = s.name()
                        svc_to_pid[sname] = pid
                        pid_to_services[pid].append(sname)
            except Exception:
                pass

        procs: Dict[int, Any] = {}
        for pid in pid_to_services:
            try:
                procs[pid] = psutil.Process(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        metrics: Dict[str, Dict[str, Any]] = {}

        for sname, pid in svc_to_pid.items():
            p = procs.get(pid)
            if not p:
                continue

            shared_count = max(1, len(pid_to_services[pid]))

            # 1. MEM: memory_percent & MB
            try:
                raw_rss = p.memory_info().rss
                mem_mb = (raw_rss / (1024 * 1024)) / shared_count
                mem_pct = p.memory_percent() / shared_count
            except Exception:
                mem_mb = 0.0
                mem_pct = 0.0
            mem_str = f"{mem_mb:.1f}" if mem_mb < 10 else f"{int(round(mem_mb))}"

            # 2. CPU: cpu_percent from last 60 minutes
            try:
                cpu_sec = (p.cpu_times().user + p.cpu_times().system) / shared_count
                uptime = max(1.0, now - p.create_time())
                window_sec = min(3600.0, uptime)
                cpu_60m = (cpu_sec / window_sec) * 100.0
            except Exception:
                cpu_60m = 0.0

            # 3. THREADS: num_threads
            try:
                threads = p.num_threads()
            except Exception:
                threads = 0

            # 4. IO: read_bytes + write_bytes
            try:
                io = p.io_counters()
                io_bytes = (io.read_bytes + io.write_bytes) // shared_count
            except Exception:
                io_bytes = 0

            # 5. CONNECTIONS: len(connections())
            try:
                conns = len(p.connections())
            except Exception:
                conns = 0

            # 6. NICE: priority class
            try:
                nice_val = p.nice()
                nice_str = NICE_MAP.get(nice_val, str(nice_val))
            except Exception:
                nice_str = "NORMAL"

            badge = f"MEM: {mem_str} MB, CPU: (60min) {cpu_60m:.2f}, THREADS: {threads}, IO: {io_bytes}, CONNECTIONS: {conns}, NICE: {nice_str}"

            metrics[sname] = {
                "pid": pid,
                "shared_count": shared_count,
                "mem_mb": mem_mb,
                "memory_percent": mem_pct,
                "cpu_60m": cpu_60m,
                "threads": threads,
                "io_bytes": io_bytes,
                "conns": conns,
                "nice": nice_str,
                "badge": badge,
            }

        return metrics

    def get_metrics(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        if not self._cached_metrics or force_refresh:
            self._cached_metrics = self.fetch_metrics()
        return self._cached_metrics

    def attach_load_to_services(self, services: List[Dict[str, Any]], force_refresh: bool = False) -> None:
        """Attaches the computed resource metrics to each service dictionary in-place."""
        all_metrics = self.get_metrics(force_refresh=force_refresh)
        for srv in services:
            if srv.get("state") == "Running":
                m = all_metrics.get(srv.get("name", ""))
                if m:
                    srv["metrics"] = m
                    srv["load_rank"] = m["mem_mb"]  # Used for sorting running services by memory footprint
                    srv["metric_badge"] = m["badge"]
                else:
                    srv["metrics"] = None
                    srv["load_rank"] = 0.0
                    srv["metric_badge"] = "MEM: 0 MB, CPU: (60min) 0.00, THREADS: 0, IO: 0, CONNECTIONS: 0, NICE: NORMAL"
            else:
                srv["metrics"] = None
                srv["load_rank"] = None
                srv["metric_badge"] = ""
