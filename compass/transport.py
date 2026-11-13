"""Persistent HTTPS pool; warm-up never generates content or sends user context."""
import threading
import time
import requests


class Cancellation:
    def __init__(self):
        self.event = threading.Event()
        self.response = None
        self.lock = threading.Lock()

    def is_set(self):
        return self.event.is_set()

    def bind(self, response):
        with self.lock:
            self.response = response
        if self.is_set():
            response.close()

    def set(self):
        self.event.set()
        with self.lock:
            response = self.response
        if response is not None:
            # Closing a blocked socket must never hold the GUI thread.
            threading.Thread(target=response.close, daemon=True).start()


class GeminiTransport:
    def __init__(self, session=None, clock=time.monotonic):
        self.session = session or requests.Session()
        self.session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
        self.clock = clock
        self.last_used = -float("inf")
        self.warming = False
        self.lock = threading.Lock()

    def post(self, *args, **kwargs):
        self.last_used = self.clock()
        return self.session.post(*args, **kwargs)

    def get(self, *args, **kwargs):
        self.last_used = self.clock()
        return self.session.get(*args, **kwargs)

    def prewarm(self):
        with self.lock:
            if self.warming or self.clock() - self.last_used < 45:
                return
            self.warming = True
        def work():
            try:
                # An unauthenticated, non-generation request establishes DNS/TCP/TLS.
                with self.session.get("https://generativelanguage.googleapis.com/", timeout=(3, 3)) as response:
                    _ = response.content  # consume body so urllib3 can return connection to pool
                self.last_used = self.clock()
            except requests.RequestException:
                pass  # warm-up failure never blocks coaching or retries an answer
            finally:
                with self.lock:
                    self.last_used = self.clock()
                    self.warming = False
        threading.Thread(target=work, daemon=True, name="gemini-warmup").start()
