"""Small Eclipse Ditto HTTP client: standard library only.

Every write is a PUT of a complete document, so repeating it is harmless.
Network errors, timeouts, 408, 429 and 5xx answers are retried a bounded number
of times (a ready Ditto can still answer 503 "Please retry" for a while on a
busy host); any other 4xx fails at once with the body Ditto returned.

Credentials and the address come from the environment that the platform's
compose file provides: DITTO_URL, DITTO_USER, DITTO_PASSWORD.
"""

import base64
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class DittoError(RuntimeError):
    """A Ditto request that failed for good (after the retries)."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def quote_id(thing_id):
    """Percent-encode a thing or policy id for a URL path; ':' stays as is."""
    return urllib.parse.quote(thing_id, safe=":")


class Ditto:
    def __init__(self, url, user, password, timeout=30.0, retries=10, delay=2.0,
                 max_delay=10.0, log=None):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.max_delay = max_delay
        self.log = log or (lambda message: print(message, file=sys.stderr, flush=True))
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self._auth = "Basic " + token
        self._sleep = time.sleep

    @classmethod
    def from_env(cls, **kwargs):
        password = os.environ.get("DITTO_PASSWORD")
        if not password:
            raise DittoError("переменная окружения DITTO_PASSWORD не задана")
        return cls(os.environ.get("DITTO_URL", "http://localhost:8080"),
                   os.environ.get("DITTO_USER", "ditto"), password, **kwargs)

    # ------------------------------------------------------------------ core

    def request(self, method, path, body=None, allow_404=False):
        """Send one request to /api/2/<path>; return (status, parsed JSON or None).

        With allow_404 a 404 answer is returned as (404, None) instead of raised.
        """
        url = f"{self.url}/api/2/{path}"
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": self._auth, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        last = None
        for attempt in range(1, self.retries + 1):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return response.status, _parse(response.read())
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", "replace")
                if exc.code == 404 and allow_404:
                    return 404, None
                last = DittoError(f"{method} {path}: HTTP {exc.code} {text.strip()[:500]}",
                                  status=exc.code, body=text)
                if exc.code not in RETRY_STATUSES:
                    raise last
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                reason = getattr(exc, "reason", exc)
                last = DittoError(f"{method} {path}: нет ответа ({reason})")
            if attempt < self.retries:
                pause = min(self.delay * attempt, self.max_delay)
                self.log(f"повтор {attempt}/{self.retries - 1} через {pause:g} с: {last}")
                self._sleep(pause)
        raise last

    # ----------------------------------------------------------------- state

    def wait_ready(self, timeout=300.0, interval=3.0):
        """Wait until the search endpoint answers; raise DittoError on timeout."""
        deadline = time.monotonic() + timeout
        saved = self.retries
        self.retries = 1  # this loop does the waiting
        try:
            while True:
                try:
                    self.request("GET", "search/things?option=size(1)")
                    return
                except DittoError as exc:
                    if exc.status in (400, 401, 403):  # waiting will not fix these
                        raise
                    if time.monotonic() >= deadline:
                        raise DittoError(f"Ditto не отвечает за {timeout:g} с: {exc}") from exc
                self._sleep(interval)
        finally:
            self.retries = saved

    # -------------------------------------------------------------- policies

    def get_policy(self, policy_id):
        """The policy document, or None when it does not exist."""
        return self.request("GET", f"policies/{quote_id(policy_id)}", allow_404=True)[1]

    def put_policy(self, policy_id, body):
        """Create or replace a policy; returns 'created' or 'updated'."""
        status, _ = self.request("PUT", f"policies/{quote_id(policy_id)}", body)
        return "created" if status == 201 else "updated"

    def ensure_policy(self, policy_id, body):
        """Create the policy only when it is missing; returns 'created' or 'exists'."""
        if self.get_policy(policy_id) is not None:
            return "exists"
        self.put_policy(policy_id, body)
        return "created"

    # ---------------------------------------------------------------- things

    def put_thing(self, thing_id, body):
        """Create or replace a thing; returns 'created' or 'updated'."""
        status, _ = self.request("PUT", f"things/{quote_id(thing_id)}", body)
        return "created" if status == 201 else "updated"

    def get_thing(self, thing_id):
        """The thing document, or None when it does not exist."""
        return self.request("GET", f"things/{quote_id(thing_id)}", allow_404=True)[1]

    def put_features(self, thing_id, features):
        """Replace all features of a thing."""
        self.request("PUT", f"things/{quote_id(thing_id)}/features", features)

    def feature_value(self, thing_id, feature_id):
        """properties.value of one feature, or None when it is not there."""
        path = f"things/{quote_id(thing_id)}/features/{urllib.parse.quote(feature_id)}/properties/value"
        return self.request("GET", path, allow_404=True)[1]

    def count_things(self, ditto_filter):
        """Number of things matching a Ditto RQL filter, via the search index."""
        query = urllib.parse.urlencode({"filter": ditto_filter})
        _, data = self.request("GET", f"search/things/count?{query}")
        return int(data)


def _parse(raw):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
