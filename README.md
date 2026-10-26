# Win-Services-Manager-TUI

A fast, interactive, keyboard-driven Windows Services Manager Terminal User Interface (TUI) featuring real-time process resource telemetry, dynamic multi-mode sorting, and instant service lifecycle configuration.

---

## Features

- **Interactive ANSI Terminal UI**: Clean VT100 ANSI color-coded interface with zero terminal line-wrapping, smooth viewport scrolling, and real-time status indicators (`*` for running services).
- **Dynamic Multi-Mode Sorting (`S` key)**:
  - **`Name`**: Alphabetical ordering ($A \to Z$).
  - **`Running`**: Active services grouped first (prioritized by resource footprint descending), followed by stopped services.
  - **`Startup-type`**: Ordered by startup configuration lifecycle (`Automatic` $\to$ `Delayed` $\to$ `Manual` $\to$ `Disabled`).
  - *Maintains active cursor selection across sort reorderings.*
- **Granular Per-Service Resource Telemetry**: Displays concrete resource impact after each service's dependency entry:
  ```text
  (Dependents: LanmanWorkstation) MEM: 66 MB, CPU: (60min) 0.03, THREADS: 5, IO: 589108, CONNECTIONS: 4, NICE: HIGH
  ```
  - **`MEM`**: Memory Working Set (RSS) in megabytes.
  - **`CPU: (60min)`**: Average CPU utilization percentage over the last 60 minutes (or elapsed process uptime).
  - **`THREADS`**: Total active OS execution threads.
  - **`IO`**: Combined read and write transfer bytes (`read_bytes + write_bytes`).
  - **`CONNECTIONS`**: Active socket count.
  - **`NICE`**: Process priority class name (`NORMAL`, `HIGH`, `BELOW_NORMAL`, `ABOVE_NORMAL`, `IDLE`, `REALTIME`).
- **Container Footprint Attribution**: Automatically prorates memory, CPU time, and handle counts for services co-hosted in shared `svchost.exe` or `lsass.exe` instances so individual services are not falsely charged for the entire container.
- **In-Place Service Management**:
  - Toggle startup mode directly via `sc config`.
  - Start or stop services with immediate UI state refresh.
  - Automatic Windows UAC privilege elevation check upon launch.

---

## Keyboard Controls

| Key | Action | Description |
|---|---|---|
| **`UP` / `DOWN`** | Navigate | Move cursor up and down through the service list with automatic scrolling. |
| **`SPACEBAR`** | Toggle Startup Type | Cycle startup mode: `Auto` $\to$ `Delayed` $\to$ `Manual` $\to$ `Disabled`. |
| **`S`** | Cycle Sort Mode | Switch list order: `Name` $\to$ `Running` $\to$ `Startup-type`. |
| **`R` / `ENTER`** | Start / Stop Service | Starts a stopped service or stops a running service (`*` designates running). |
| **`Q`** | Quit | Clears the terminal and exits cleanly. |

---

## Directory Structure

```text
Win-Services-Manager-TUI/
├── win-services-tui3.py       # Main TUI entrypoint & event loop
├── service_sorter.py          # Modular sorting engine (Name, Running, Startup-type)
├── service_load.py            # High-speed process telemetry & attribution engine
├── requirements.txt           # Python dependencies (psutil)
└── README.md                  # Project documentation & usage guide
```

---

## Installation & Setup

### Prerequisites
- **Operating System**: Windows 10, Windows 11, or Windows Server (x64)
- **Python**: Python 3.8 or newer
- **Permissions**: Administrator privileges are recommended to inspect all system processes and modify service configurations. The script will automatically trigger a Windows UAC prompt if elevation is needed.

### Clone and Run

```powershell
# Clone the repository
git clone https://github.com/americanumberoneaokgoodtimes/Win-Services-Manager-TUI.git
cd Win-Services-Manager-TUI

# Install dependencies
pip install -r requirements.txt

# Run the TUI
python win-services-tui3.py
```

---

## Architecture & Calculation Details

### 1. Rolling 60-Minute CPU Percentage
Because Windows does not retain historical kernel CPU timeseries per process without active ETW tracing, the 60-minute metric evaluates accumulated CPU execution time (user + kernel mode) against the process active execution window:

$$\text{cpu\_percent} = \frac{\text{user\_seconds} + \text{kernel\_seconds}}{\min(3600\text{s}, \text{uptime})} \times 100$$

### 2. Shared Container (`svchost.exe`) Attribution
Windows bundles certain system services into shared `svchost.exe` instances. Rather than attributing the host's entire Working Set RAM or handle table to every hosted service, `service_load.py` groups services by PID and divides the container footprint evenly across active hosted services.

### 3. Native Speed
Process and service enumeration leverages `psutil` C-level bindings, retrieving the entire running system state in under 50 milliseconds without polling lag.

---

## License

MIT License. See repository for full terms.
