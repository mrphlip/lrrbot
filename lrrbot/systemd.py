import logging
import os
import ctypes
import ctypes.util

log = logging.getLogger("lrrbot.systemd")

try:
	libsystemd = ctypes.CDLL(ctypes.util.find_library("systemd"))
	libsystemd.sd_notify.argtypes = [ctypes.c_int, ctypes.c_char_p]
	
	def notify(status):
		libsystemd.sd_notify(0, status.encode('utf-8'))
except OSError as e:
	log.warning("failed to load libsystemd: {}", e)

	def notify(status):
		pass

class Service:
	def __init__(self, loop):
		self.loop = loop

		timeout_usec = os.environ.get("WATCHDOG_USEC")
		if timeout_usec is not None:
			self.timeout = (int(timeout_usec) * 1e-6) / 2
			self.watchdog_handle = self.loop.call_later(self.timeout, self.watchdog)

		self.subsystems = {"irc"}

	def watchdog(self):
		notify("WATCHDOG=1")
		self.watchdog_handle = self.loop.call_later(self.timeout, self.watchdog)

	def subsystem_started(self, subsystem):
		if subsystem in self.subsystems:
			self.subsystems.remove(subsystem)
			if self.subsystems == set():
				notify("READY=1")
