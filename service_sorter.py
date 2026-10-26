"""
Service Sorter Module
Provides cycling and sorting strategies for Windows Services:
- 'Name': Alphabetical by service name
- 'Running': Running services first (ordered by load impact descending, then name), followed by stopped services
- 'Startup-type': Ordered by startup lifecycle (Automatic -> Delayed -> Manual -> Disabled), then name
"""

from typing import List, Dict, Any, Optional

MODE_ORDER = {
    "Automatic": 0,
    "Delayed": 1,
    "Manual": 2,
    "Disabled": 3
}

class ServiceSorter:
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
        - 'Name': alphabetical by service name
        - 'Running': running services first (sorted by load rank descending, then name), followed by stopped
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
        else: # "Name" default
            return sorted(
                services,
                key=lambda s: s.get("name", "").lower()
            )
