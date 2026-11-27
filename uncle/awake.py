"""Keep the Sprite awake while Uncle works.

A Sprite pauses about 30 s after its last request, even if a background thread is still talking to
AgentMail or Claude, and the pause drops open connections. A task on the Sprite's management socket is
a hold: while one is live the Sprite keeps running (docs.fly.io/sprites/keeping-sprites-running).
Off a Sprite there is no socket, and this does nothing.
"""
import contextlib
import http.client
import json
import os
import socket

SOCK = os.environ.get("SPRITE_API_SOCK", "/.sprite/api.sock")


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout=5):
        super().__init__("sprite", timeout=timeout)
        self._path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(self._path)
        self.sock = s


def _call(method, path, body=None):
    if not os.path.exists(SOCK):
        return None
    conn = _UnixConnection(SOCK)
    try:
        conn.request(method, path, body=None if body is None else json.dumps(body),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        return resp.status
    except OSError:
        return None
    finally:
        conn.close()


@contextlib.contextmanager
def held(name="uncle-work", expire="10m"):
    """Hold the Sprite awake for the body of the with-block. The expiry is a backstop if we crash."""
    _call("PUT", f"/v1/tasks/{name}", {"expire": expire})
    try:
        yield
    finally:
        _call("DELETE", f"/v1/tasks/{name}")
