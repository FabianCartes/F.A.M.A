"""Inert process transport for admission/permission tests; never executes ML."""
from queue import Queue
class DeferredTrainingProcess:
    def __init__(self, target, *, args, seed):
        self.events = Queue()
        self.alive = True
        self.exitcode = None
    def start(self): pass
    def is_alive(self): return self.alive
    def receive(self, timeout=None): return self.events.get(timeout=timeout)
    def request_stop(self):
        self.alive = False
        self.exitcode = 0
        self.events.put({"type":"progress","snapshot":{"status":"stopped"}})
        self.events.put({"type":"finished"})
    def join(self, timeout=None): pass
    def close(self): pass
    def abort_start(self): self.request_stop()
