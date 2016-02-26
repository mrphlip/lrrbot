import logging
import os

log = logging.getLogger("lrrbot.systemd")

try:
    from systemd.daemon import notify
except ImportError:
    log.warning("`python-systemd` not installed")

    def notify(status, unset_environment=False, pid=0, fds=None):
        return False

class Service:
    def __init__(self, loop):
        self.loop = loop

        timeout_usec = os.environ.get("WATCHDOG_USEC")
        if timeout_usec is not None:
            self.timeout = (int(timeout_usec) * 1e-6) / 2
            self.watchdog_handle = self.loop.call_later(self.timeout, self.watchdog)

        self.subsystems = {"irc", "whispers"}

    def watchdog(self):
        notify("WATCHDOG=1")
        self.watchdog_handle = self.loop.call_later(self.timeout, self.watchdog)

    def subsystem_started(self, subsystem):
        self.subsystems.remove(subsystem)
        if self.subsystems == set():
            notify("READY=1")
