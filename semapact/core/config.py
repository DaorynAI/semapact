import os
import yaml
from pathlib import Path
from typing import Any, Optional, Dict
import logging

LOGGER = logging.getLogger(__name__)

class ConfigManager:
    """
    Manages configuration for SemaPact.
    Resolves configuration in the following order of precedence:
    1. Explicit environment variables (if provided to get())
    2. Local configuration file (.semapact.yaml / .semapact.yaml in CWD)
    3. Global configuration file (~/.config/semapact/config.yaml / ~/.config/semapact/config.yaml)
    """

    def __init__(self):
        self.config_data: Dict[str, Any] = {}
        self._last_cwd: Optional[Path] = None
        self._overlays: list[Dict[str, Any]] = []
        self._overlay_names: list[str] = []
        self._load_configs()

    def _load_configs(self):
        self._last_cwd = Path.cwd()
        # Load global first (semapact, fallback to semapact)
        global_config_path = Path.home() / ".config" / "semapact" / "config.yaml"
        if not global_config_path.exists():
            global_config_path = Path.home() / ".config" / "semapact" / "config.yaml"
        if global_config_path.exists():
            try:
                with open(global_config_path, "r", encoding="utf-8") as f:
                    global_data = yaml.safe_load(f) or {}
                    self._update_nested(self.config_data, global_data)
            except Exception as e:
                LOGGER.warning(f"Failed to load global config from {global_config_path}: {e}")

        # Load local overriding global (semapact, fallback to semapact)
        local_config_path = Path.cwd() / ".semapact.yaml"
        if not local_config_path.exists():
            local_config_path = Path.cwd() / ".semapact.yaml"
        if local_config_path.exists():
            try:
                with open(local_config_path, "r", encoding="utf-8") as f:
                    local_data = yaml.safe_load(f) or {}
                    self._update_nested(self.config_data, local_data)
            except Exception as e:
                LOGGER.warning(f"Failed to load local config from {local_config_path}: {e}")

    def load_from_path(self, path: str | Path) -> None:
        """Load configuration from a specific YAML file path, overriding current settings."""
        config_path = Path(path)
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    self._update_nested(self.config_data, data)
            except Exception as e:
                LOGGER.warning(f"Failed to load custom config from {config_path}: {e}")
        else:
            LOGGER.warning(f"Custom config file not found: {config_path}")

    def update_config(self, config_dict: Dict[str, Any]) -> None:
        """Inject a dictionary of configurations directly into the manager."""
        self._update_nested(self.config_data, config_dict)

    def push_overlay(self, name: str, overlay: Dict[str, Any]) -> None:
        """Push a temporary configuration overlay. Higher precedence than base configs."""
        if name in self._overlay_names:
            self.pop_overlay(name)
        self._overlay_names.append(name)
        self._overlays.append(overlay)

    def pop_overlay(self, name: str) -> None:
        """Remove a specific configuration overlay by name."""
        try:
            idx = self._overlay_names.index(name)
            self._overlay_names.pop(idx)
            self._overlays.pop(idx)
        except ValueError:
            LOGGER.warning(f"Overlay '{name}' not found.")

    def _update_nested(self, d: Dict[str, Any], u: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = self._update_nested(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def get(self, key_path: str, env_var: Optional[str] = None, default: Any = None) -> Any:
        """
        Get a configuration value.
        Precedence:
        1. Environment Variable (if env_var is provided and exists)
        2. Config File Value (from key_path like 'azure.auth_method')
        3. Default Value
        """
        if env_var:
            if env_var in os.environ:
                return os.environ[env_var]
            if env_var.startswith("SEMAPACT_"):
                fallback_var = env_var.replace("SEMAPACT_", "SEMAPACT_")
                if fallback_var in os.environ:
                    return os.environ[fallback_var]
            elif env_var.startswith("SEMAPACT_"):
                fallback_var = env_var.replace("SEMAPACT_", "SEMAPACT_")
                if fallback_var in os.environ:
                    return os.environ[fallback_var]

        if self._last_cwd != Path.cwd():
            self.config_data = {}
            self._load_configs()
        
        if not key_path:
            return default

        keys = key_path.split(".")
        
        # 1. Try resolving from active overlays (last pushed has highest precedence)
        for overlay in reversed(self._overlays):
            try:
                current = overlay
                for key in keys:
                    current = current[key]
                return current
            except (KeyError, TypeError):
                continue
                
        # 2. Try resolving from base config_data
        current = self.config_data
        try:
            for key in keys:
                current = current[key]
            return current
        except (KeyError, TypeError):
            return default

# A global instance for easy import if needed
config_manager = ConfigManager()
