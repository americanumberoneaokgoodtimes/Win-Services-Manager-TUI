import os
import sys
import subprocess
import msvcrt
import json
import ctypes

# Import separate modular features
from service_sorter import ServiceSorter
from service_load import ServiceLoadMonitor

# Enable VT100 ANSI escape sequences in the Windows console
os.system('')

# Raw ANSI Color Codes
RED = "\033[91m"
GREEN = "\033[92m"
CYAN = "\033[96m"  # Light Blue
YELLOW = "\033[93m"
RESET = "\033[0m"
INVERT = "\033[7m"

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

            # Feature #2: Attach load impact metrics for all running services
            self.load_monitor.attach_load_to_services(self.services, force_refresh=True)

            # Feature #1: Sort list according to current sort mode
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
            # check_call will throw an exception if the command fails, preventing the UI state from updating falsely
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
                service["load_rank"] = None
                
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
            
            # Line 2: Dependencies and Load Metric
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
                    if arrow == b'H': # Up
                        if self.selected_idx > 0:
                            self.selected_idx -= 1
                    elif arrow == b'P': # Down
                        if self.selected_idx < len(self.services) - 1:
                            self.selected_idx += 1
                
                elif key == b' ': 
                    self.toggle_startup_mode(self.services[self.selected_idx])
                elif key.lower() == b's': 
                    # Feature #1: Cycle sort modes
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
    except:
        return False

if __name__ == "__main__":
    if not is_admin():
        # Re-run the program with admin rights. 
        # This will trigger the UAC prompt and open a new elevated window.
        print("Administrator privileges required. Requesting elevation...")
        
        # We wrap the script path in quotes to handle any spaces in the file path
        script_path = f'"{os.path.abspath(sys.argv[0])}"'
        
        # ShellExecuteW parameters: (hwnd, operation, file, parameters, directory, showcmd)
        # showcmd 1 = SW_NORMAL
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, script_path, None, 1)
        sys.exit()

    tui = ServicesTUI()
    tui.run()
