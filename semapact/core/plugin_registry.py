import logging
from typing import Callable, Dict, List, Any

LOGGER = logging.getLogger(__name__)

class PluginRegistry:
    """
    Enterprise-ready Plugin Registry for hooking into core SemaPact workflows.
    """
    _hooks: Dict[str, List[Callable]] = {}

    @classmethod
    def register_hook(cls, hook_name: str) -> Callable:
        """
        Decorator to register a hook callback.
        
        Usage:
            @PluginRegistry.register_hook("on_import_complete")
            def my_hook(contract, format, source, args):
                ...
        """
        def decorator(func: Callable) -> Callable:
            if hook_name not in cls._hooks:
                cls._hooks[hook_name] = []
            cls._hooks[hook_name].append(func)
            LOGGER.debug(f"Registered hook '{func.__name__}' for event '{hook_name}'")
            return func
        return decorator

    @classmethod
    def execute_hook(cls, hook_name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Execute all callbacks registered for a hook.
        If a callback returns a value that is not None, it is assumed to be an override/result 
        and is returned immediately. Subsequent hooks are bypassed.
        """
        if hook_name not in cls._hooks:
            return None

        for hook in cls._hooks[hook_name]:
            try:
                result = hook(*args, **kwargs)
                if result is not None:
                    return result
            except Exception as e:
                LOGGER.error(f"Error executing hook '{hook.__name__}' for event '{hook_name}': {e}")
        
        return None
