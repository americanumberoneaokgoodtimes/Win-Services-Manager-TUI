import os
import sys
import subprocess
import msvcrt
import json
import ctypes
import time
from typing import List, Dict, Any, Optional
from collections import defaultdict

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Enable VT100 ANSI escape sequences in Windows console
os.system('')

# Raw ANSI Color Codes
RED = "\033[91m"
GREEN = "\033[92m"
CYAN = "\033[96m"  # Light Blue
YELLOW = "\033[93m"
RESET = "\033[0m"
INVERT = "\033[7m"

# Windows Priority Class Map
NICE_MAP = {
    32: "NORMAL",
    64: "IDLE",
    128: "HIGH",
    256: "REALTIME",
    16384: "BELOW_NORMAL",
    32768: "ABOVE_NORMAL",
}

MODE_ORDER = {
    "Automatic": 0,
    "Delayed": 1,
    "Manual": 2,
    "Disabled": 3
}


class ServiceSorter:
    """Handles cycling and sorting of Windows services across different modes."""
    MODES = ["Name", "Running", "Startup-type"]

    def __init__(self, default_mode: str = "Name"):
        self.current_mode = default_mode if default_mode in self.MODES else "Name"

    def cycle_mode(self, current_mode: Optional[str] = None) -> str:
        """Cycles to the next sort mode in sequence: Name -> Running -> Startup-type -> Name"""
        active = current_mode if current_mode in self.MODES else self.current_mode
        idx = self.MODES.index(active)
        next_mode = self.MODES[(idx + 1) % len(self.MODES)]
        self.current_mode = next_mode
        return next_mode

    def sort(self, services: List[Dict[str, Any]], mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Sorts the service list based on the requested mode:
        - 'Name': Alphabetical by service name (case-insensitive)
        - 'Running': Active services first (prioritized by memory footprint descending, then name), followed by stopped
        - 'Startup-type': Automatic -> Delayed -> Manual -> Disabled, then by name
        """
        active_mode = mode if mode in self.MODES else self.current_mode
        
        if active_mode == "Running":
            return sorted(
                services,
                key=lambda s: (
                    0 if s.get("state") == "Running" else 1,
                    -(s.get("load_rank") or 0.0) if s.get("state") == "Running" else 0.0,
                    s.get("name", "").lower()
                )
            )
        elif active_mode == "Startup-type":
            return sorted(
                services,
                key=lambda s: (
                    MODE_ORDER.get(s.get("mode"), 99),
                    s.get("name", "").lower()
                )
            )
        else:  # "Name" default
            return sorted(
                services,
                key=lambda s: s.get("name", "").lower()
            )


class ServiceLoadMonitor:
    """
    Retrieves and tracks real-time system resource metrics for Windows services:
    - MEM: memory_percent & RSS in MB
    - CPU: cpu_percent over the last 60 minutes
    - THREADS: active thread count
    - IO: cumulative read_bytes + write_bytes
    - CONNECTIONS: active open sockets
    - NICE: priority class name
    """
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
        """Attaches computed resource metrics to each service dictionary in-place."""
        all_metrics = self.get_metrics(force_refresh=force_refresh)
        for srv in services:
            if srv.get("state") == "Running":
                m = all_metrics.get(srv.get("name", ""))
                if m:
                    srv["metrics"] = m
                    srv["load_rank"] = m["mem_mb"]
                    srv["metric_badge"] = m["badge"]
                else:
                    srv["metrics"] = None
                    srv["load_rank"] = 0.0
                    srv["metric_badge"] = "MEM: 0 MB, CPU: (60min) 0.00, THREADS: 0, IO: 0, CONNECTIONS: 0, NICE: NORMAL"
            else:
                srv["metrics"] = None
                srv["load_rank"] = None
                srv["metric_badge"] = ""


class ServicesTUI:
    def __init__(self):
        self.services = []
        self.selected_idx = 0
        self.scroll_offset = 0
        self.sort_mode = "Name"
        self.sorter = ServiceSorter(default_mode=self.sort_mode)
        self.load_monitor = ServiceLoadMonitor()
        
    def load_services(self):
        """Fetch all services, descriptions, dependencies, delayed states, and resource metrics."""
        sys.stdout.write("Loading services, dependencies, and resource metrics...\r")
        sys.stdout.flush()
        
        ps_command = (
            "$svc = Get-Service; "
            "$svcHash = @{}; "
            "foreach($s in $svc) { $svcHash[$s.Name] = ($s.RequiredServices.Name -join ', ') }; "
            "$cim = Get-CimInstance Win32_Service; "
            "$res = foreach($c in $cim) { "
            "    $mode = $c.StartMode; "
            "    if ($mode -eq 'Auto' -and $c.DelayedAutoStart -eq $true) { "
            "        $mode = 'Delayed' "
            "    }; "
            "    @{ Name=$c.Name; DisplayName=$c.DisplayName; State=$c.State; StartMode=$mode; Description=$c.Description; Deps=$svcHash[$c.Name] } "
            "}; "
            "$res | ConvertTo-Json -Compress"
        )
        
        try:
            result = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_command], text=True)
            raw_services = json.loads(result)
            
            self.services = []
            for srv in raw_services:
                start_mode = srv.get("StartMode", "").lower()
                if start_mode == "auto":
                    mode = "Automatic"
                elif start_mode == "delayed":
                    mode = "Delayed"
                elif start_mode == "manual":
                    mode = "Manual"
                else:
                    mode = "Disabled"
                
                self.services.append({
                    "name": srv.get("Name", "Unknown"),
                    "desc": (srv.get("Description") or srv.get("DisplayName") or "").replace("\n", " "),
                    "state": srv.get("State", ""),
                    "mode": mode,
                    "dependencies": srv.get("Deps", "")
                })

            # Attach resource telemetry metrics for all running services
            self.load_monitor.attach_load_to_services(self.services, force_refresh=True)

            # Sort list according to current sort mode
            self.apply_sort(cycle=False)

        except Exception as e:
            print(f"Error loading services: {e}")
            sys.exit(1)

    def apply_sort(self, cycle: bool = False):
        """Applies sorting to services while preserving the selected service cursor position."""
        if not self.services:
            return
            
        selected_name = self.services[self.selected_idx]["name"] if 0 <= self.selected_idx < len(self.services) else None
        
        if cycle:
            self.sort_mode = self.sorter.cycle_mode(self.sort_mode)
            
        self.services = self.sorter.sort(self.services, self.sort_mode)
        
        if selected_name:
            for idx, s in enumerate(self.services):
                if s["name"] == selected_name:
                    self.selected_idx = idx
                    break
        else:
            self.selected_idx = min(self.selected_idx, len(self.services) - 1)

    def toggle_startup_mode(self, service):
        """Cycles through Auto -> Delayed -> Manual -> Disabled using sc config"""
        name = service["name"]
        current = service["mode"]
        
        if current == "Automatic":
            new_mode = "Delayed"
            cmd = f'sc config "{name}" start= delayed-auto'
        elif current == "Delayed":
            new_mode = "Manual"
            cmd = f'sc config "{name}" start= demand'
        elif current == "Manual":
            new_mode = "Disabled"
            cmd = f'sc config "{name}" start= disabled'
        else:
            new_mode = "Automatic"
            cmd = f'sc config "{name}" start= auto'
            
        try:
            subprocess.check_call(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            service["mode"] = new_mode
            if self.sort_mode == "Startup-type":
                self.apply_sort(cycle=False)
        except subprocess.CalledProcessError:
            pass 

    def toggle_run_state(self, service):
        """Starts or stops the service using sc start / sc stop"""
        name = service["name"]
        if service["state"] == "Running":
            cmd = f'sc stop "{name}"'
            new_state = "Stopped"
        else:
            cmd = f'sc start "{name}"'
            new_state = "Running"
            
        try:
            subprocess.check_call(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            service["state"] = new_state
            if new_state == "Running":
                self.load_monitor.attach_load_to_services(self.services, force_refresh=True)
            else:
                service["metrics"] = None
                service["load_rank"] = None
                service["metric_badge"] = ""
                
            if self.sort_mode == "Running":
                self.apply_sort(cycle=False)
        except subprocess.CalledProcessError:
            pass 

    def render(self):
        # Clear screen and reset cursor to home
        sys.stdout.write("\033[2J\033[H")
        
        term_lines = os.get_terminal_size().lines
        term_cols = os.get_terminal_size().columns
        
        # Calculate exactly how many 2-line items we can fit
        visible_slots = max(1, (term_lines - 9) // 2)
        
        total = len(self.services)
        running_count = sum(1 for s in self.services if s["state"] == "Running")
        
        # Draw Header with inline color-coding for the legend
        sys.stdout.write(f"{INVERT} Services Manager TUI - Colorful Edition - HELP: {RESET}\n")
        sys.stdout.write(" Use UP/DOWN arrows to navigate,\n")
        sys.stdout.write(f" SPACEBAR to change startup mode ({GREEN}Auto{RESET}/{CYAN}Delayed{RESET}/{YELLOW}Manual{RESET}/{RED}Disabled{RESET})\n")
        sys.stdout.write(f" S to cycle sort modes: [Name -> Running -> Startup-type] (Current: {self.sort_mode})\n")
        sys.stdout.write(" R or ENTER to start or stop service (* = running)\n")
        sys.stdout.write(" Q to quit\n\n")

        sort_tag = f"Sort: [{self.sort_mode}]"
        header_text = f" Name {'-'*20} Description {'-'*4} {sort_tag} --- {total} services --- {running_count} running --- "
        header_bar = header_text[:term_cols - 1].ljust(term_cols - 1, "-")
        sys.stdout.write(f"{INVERT} {header_bar} {RESET}\n")

        # Handle scroll math
        if self.selected_idx < self.scroll_offset:
            self.scroll_offset = self.selected_idx
        elif self.selected_idx >= self.scroll_offset + visible_slots:
            self.scroll_offset = self.selected_idx - visible_slots + 1
            
        visible_services = self.services[self.scroll_offset : self.scroll_offset + visible_slots]

        for i, srv in enumerate(visible_services):
            actual_idx = self.scroll_offset + i
            is_selected = (actual_idx == self.selected_idx)
            
            # Formatting symbols
            prefix = "-> " if is_selected else "   "
            run_symbol = "*" if srv["state"] == "Running" else " "
            
            # Color coding
            color = RESET
            if srv["mode"] == "Disabled":
                color = RED
            elif srv["mode"] == "Automatic":
                color = GREEN
            elif srv["mode"] == "Delayed":
                color = CYAN
            elif srv["mode"] == "Manual":
                color = YELLOW

            # Truncate strings specifically to prevent terminal line-wrapping (which causes flicker)
            name_col = f"{run_symbol}{srv['name']}".ljust(30)
            max_desc_len = max(10, term_cols - 35)
            desc_col = srv['desc'][:max_desc_len]
            
            # Line 1: Name and Description
            sys.stdout.write(f"{prefix}{color}{name_col} {desc_col}{RESET}\n")
            
            # Line 2: Dependencies and Resource Metrics
            # Format: "MEM: 1111 MB, CPU: (60min) 1.11, THREADS: 11, IO: 111111111, CONNECTIONS: 1, NICE: NORMAL"
            dep_content = srv["dependencies"] if srv["dependencies"] else "None"
            if srv["state"] == "Running" and srv.get("metric_badge"):
                badge = srv["metric_badge"]
                avail_dep_space = term_cols - 6 - 15 - len(badge) - 2
                if avail_dep_space >= 8:
                    dep_str = dep_content[:avail_dep_space]
                    line2_content = f"      (Dependents: {dep_str}) {badge}"
                elif term_cols >= len(badge) + 14:
                    line2_content = f"      (Deps) {badge}"
                else:
                    line2_content = f"      {badge}"
            else:
                max_dep_len = max(5, term_cols - 22)
                line2_content = f"      (Dependents: {dep_content[:max_dep_len]})"

            line2_final = line2_content[:term_cols - 1]
            sys.stdout.write(f"{color}{line2_final}{RESET}\n")
        
        sys.stdout.flush()

    def run(self):
        self.load_services()
        self.render()
        
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getch()
                
                if key in (b'\x00', b'\xe0'): 
                    arrow = msvcrt.getch()
                    if arrow == b'H':  # Up
                        if self.selected_idx > 0:
                            self.selected_idx -= 1
                    elif arrow == b'P':  # Down
                        if self.selected_idx < len(self.services) - 1:
                            self.selected_idx += 1
                
                elif key == b' ': 
                    self.toggle_startup_mode(self.services[self.selected_idx])
                elif key.lower() == b's': 
                    self.apply_sort(cycle=True)
                elif key.lower() == b'r' or key == b'\r': 
                    self.toggle_run_state(self.services[self.selected_idx])
                elif key.lower() == b'q': 
                    sys.stdout.write("\033[2J\033[H") 
                    break
                
                # Re-render UI after any keystroke
                self.render()


def is_admin():
    """Checks if the script is currently running with Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


if __name__ == "__main__":
    if not is_admin():
        print("Administrator privileges required. Requesting elevation...")
        script_path = f'"{os.path.abspath(sys.argv[0])}"'
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, script_path, None, 1)
        sys.exit()

    tui = ServicesTUI()
    tui.run()
