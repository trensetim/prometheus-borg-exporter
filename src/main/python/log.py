"""Utility logging functions"""

LOGWARN=20
LOGINFO=10
LOGDEBUG=2

class DebugMode:
    """Global handle to configure whether to log debug messages"""
    _enabled: bool = False

    def is_enabled(self) -> bool:
        """Tells whether it is on"""
        return self._enabled

    def enable(self):
        """Make it on"""
        self._enabled = True

    def enable_if(self, condition: bool):
        """Enable debug mode if the condition is True"""
        if condition:
            self.enable()

DEBUG_MODE: DebugMode = DebugMode()
"""Indicates whether debug mode is enabled."""

def log(level: int, message: str):
    """Log a message to stdout depending on the log level and debug mode."""
    if level < 5 and not DEBUG_MODE.is_enabled():
        return
    print(message)
