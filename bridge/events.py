"""The latest of everything the page shows, handed to every connected browser."""

import threading


class EventHub:
    """Latest pose, telemetry, receivers and status events. Each publish bumps a sequence
    number, so every Server-Sent Events stream wakes up and sends what changed."""

    def __init__(self):
        self._cond = threading.Condition()
        self._seq = 0
        self.pose = None
        self.tele = None
        self.rx = None
        self.status = {"type": "status", "connected": False, "source": None,
                       "pmc": None, "master": None, "error": "starting"}

    def _publish(self, **latest):
        with self._cond:
            for name, event in latest.items():
                setattr(self, name, event)
            self._seq += 1
            self._cond.notify_all()

    def publish_pose(self, pose):
        self._publish(pose=pose)

    def publish_tele(self, tele):
        self._publish(tele=tele)

    def publish_status(self, **changes):
        with self._cond:                   # merge under the lock (it's reentrant)
            self._publish(status={**self.status, **changes})

    def publish_receivers(self, receivers):
        """The boards and cage points, from a saguaro.ReceiverHub."""
        self._publish(rx={"type": "receivers", "boards": receivers.snapshot(), "points": receivers.points.as_list()})

    def wait(self, seq, timeout):
        """Block until something newer than `seq` is published (or timeout); return all of it."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq != seq, timeout)
            return self._seq, self.pose, self.tele, self.rx, dict(self.status)
