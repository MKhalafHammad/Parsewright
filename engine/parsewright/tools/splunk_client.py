"""The only path to Splunk: two scoped tokens, timeouts on every call, names checked in code.

- deploy token (near-admin, R8): install/uninstall test apps, ingest into the pw_ test index.
- search token: counts, event times, splunkd warnings. Never reaches an agent or a prompt.
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import splunklib.binding as binding
import splunklib.client as client
from splunklib.results import JSONResultsReader

from parsewright.config import Settings
from parsewright.ta_builder.naming import require_pw_index, require_test_app
from parsewright.ta_builder.package import Package, packages_dir, sha256

# Names interpolated into SPL must be plain: test sourcetypes are [a-z0-9_:-] only.
SPL_NAME = re.compile(r"[a-z0-9_:-]+")
WARN_COMPONENTS = "DateParserVerbose, LineBreakingProcessor, AggregatorMiningProcessor"
INGEST_HOST = "parsewright-sample"
# Fixed names only: data model and dataset names are never taken from an agent.
ROOTS = {"Authentication": "Authentication", "Network_Traffic": "All_Traffic", "Web": "Web"}
DATASETS = {
    ("Authentication", "Authentication"),
    ("Authentication", "Failed_Authentication"),
    ("Authentication", "Successful_Authentication"),
    ("Network_Traffic", "All_Traffic"),
    ("Network_Traffic", "Allowed_Traffic"),
    ("Network_Traffic", "Blocked_Traffic"),
    ("Web", "Web"),
}


class SplunkError(RuntimeError):
    pass


def spl_name(value: str) -> str:
    if not SPL_NAME.fullmatch(value):
        raise ValueError(f"refusing to put {value!r} into SPL")
    return value


def connect(settings: Settings, token: str, timeout: int = 60) -> client.Service:
    # shortcut: TLS verify off for the self-signed lab cert (design "Deferred", R2).
    return client.connect(
        host=settings.splunk_host,
        port=settings.splunk_port,
        splunkToken=token,
        verify=False,
        autologin=False,
        handler=binding.handler(timeout=timeout),
    )


class SplunkClient:
    def __init__(self, settings: Settings, search: Any = None, deploy: Any = None):
        self.packages = settings.packages_dir
        self.search = search or connect(settings, settings.splunk_search_token)
        self.deploy = deploy or connect(settings, settings.splunk_deploy_token)

    # --- deploy token -------------------------------------------------------------------

    def install(self, pkg: Package) -> None:
        """Install or replace a test app from the packages folder, after re-checking its hash."""
        require_test_app(pkg.app)
        root = packages_dir(self.packages).resolve()
        path = pkg.path.resolve()
        if path.parent != root:
            raise ValueError(f"package {path} is outside PARSEWRIGHT_PACKAGES_DIR")
        if sha256(path) != pkg.sha256:
            raise SplunkError("package changed after it was built; refusing to install (T5.9)")
        self.deploy.post("apps/local", name=str(path), filename=True, update=True)

    def uninstall(self, app: str) -> None:
        require_test_app(app)
        try:
            self.deploy.delete(f"apps/local/{app}")
        except binding.HTTPError as e:
            if e.status != 404:
                raise

    def ingest(self, index: str, sourcetype: str, body: str, source: str) -> None:
        """Post raw data through receivers/simple (Q8). Only pw_ indexes are accepted (T5.1)."""
        self.deploy.post(
            "receivers/simple",
            body=body.encode("utf-8"),
            index=require_pw_index(index),
            sourcetype=spl_name(sourcetype),
            source=spl_name(source),
            # A fixed synthetic host: otherwise Splunk records the sender's address, which
            # would put the lab's real IP into events, evidence and prompts.
            host=INGEST_HOST,
        )

    # --- search token -------------------------------------------------------------------

    def _rows(self, spl: str, earliest: str | float = "0") -> list[dict]:
        stream = self.search.jobs.oneshot(
            spl, output_mode="json", earliest_time=str(earliest), count=0
        )
        return [r for r in JSONResultsReader(stream) if isinstance(r, dict)]

    def count(self, index: str, sourcetype: str) -> int:
        rows = self._rows(
            f"| tstats count where index={require_pw_index(index)} "
            f"sourcetype={spl_name(sourcetype)}"
        )
        return int(rows[0].get("count", 0)) if rows else 0

    def wait_stable(self, index: str, sourcetype: str, timeout: float = 120) -> int:
        """Poll until two consecutive non-zero counts match (design "Validation mechanics")."""
        seen, end = -1, time.monotonic() + timeout
        while time.monotonic() < end:
            time.sleep(2)
            now = self.count(index, sourcetype)
            if now and now == seen:
                return now
            seen = now
        return max(seen, 0)

    def events(self, index: str, sourcetype: str) -> list[tuple[int, str]]:
        """(epoch seconds, raw) for every event of one attempt, oldest first."""
        return [(t, raw) for t, _, raw in self.events_with_indextime(index, sourcetype)]

    def events_with_indextime(self, index: str, sourcetype: str) -> list[tuple[int, int, str]]:
        """(epoch, _indextime, raw) per event: _indextime exposes the timestamp fallback."""
        rows = self._rows(
            f"search index={require_pw_index(index)} sourcetype={spl_name(sourcetype)} "
            "| eval t=floor(_time), it=_indextime | sort 0 t | table t it _raw"
        )
        return [(int(r["t"]), int(r.get("it") or 0), r.get("_raw", "")) for r in rows]

    def field_rows(self, index: str, sourcetype: str) -> list[dict]:
        """Every search-time field of every event, keyed by epoch t (the manifest key)."""
        return self._rows(
            f"search index={require_pw_index(index)} sourcetype={spl_name(sourcetype)} "
            "| eval t=floor(_time) | fields - _* | table t *"
        )

    def field_summary(self, index: str, sourcetype: str, first: int) -> list[dict]:
        """fieldsummary over the first `first` events by time: the sample the agents saw."""
        return self._rows(
            f"search index={require_pw_index(index)} sourcetype={spl_name(sourcetype)} "
            f"| sort 0 _time | head {int(first)} | fieldsummary maxvals=5"
        )

    def datamodel_rows(self, model: str, dataset: str, index: str, sourcetype: str) -> list[dict]:
        """Events of this attempt as the CIM data model sees them (fields as Root.field).

        Data model output has no `index` field, so filtering on it drops every event; the
        attempt's sourcetype is unique per job and attempt, and the CIM index macros already
        limit the models to the test indexes.
        """
        if (model, dataset) not in DATASETS:
            raise ValueError(f"unknown data model dataset {model}.{dataset}")
        require_pw_index(index)
        root = ROOTS[model]
        return self._rows(
            f"| datamodel {model} {dataset} search | search sourcetype={spl_name(sourcetype)} "
            f"| eval t=floor(_time) | table t {root}.*"
        )

    def reload_search_time(self) -> None:
        """Safety net if a reinstall's search-time settings are not visible yet."""
        for conf in ("props", "transforms", "eventtypes", "tags"):
            self.deploy.get(f"configs/conf-{conf}/_reload")

    def parser_warnings(
        self, sourcetype: str, since: float, app: str, caught_up_to: float, timeout: float = 60
    ) -> list[str]:
        """splunkd parsing warnings and messages that mention this attempt (Q7, T2.11).

        An empty answer is trusted only once _internal has indexed past caught_up_to; until
        then it may just be late, so a timeout raises (and the check fails closed).
        """
        end = time.monotonic() + timeout
        while True:
            rows = self._rows(
                "| tstats max(_indextime) as t where index=_internal sourcetype=splunkd"
            )
            if rows and float(rows[0].get("t") or 0) >= caught_up_to:
                break
            if time.monotonic() > end:
                raise TimeoutError("_internal did not catch up; cannot trust 'no warnings'")
            time.sleep(2)
        rows = self._rows(
            "search index=_internal sourcetype=splunkd log_level IN (WARN, ERROR) "
            f'component IN ({WARN_COMPONENTS}) "{spl_name(sourcetype)}" '
            "| head 3 | table _raw",
            earliest=int(since),
        )
        found = [r.get("_raw", "") for r in rows]
        body = self.search.get("messages", output_mode="json", count=0).body.read()
        for entry in json.loads(body).get("entry", []):
            text = " ".join(str(v) for v in entry.get("content", {}).values())
            if require_test_app(app) in text or sourcetype in text:
                found.append(text)
        return found


def ingest_source(path: Path) -> str:
    """A source name safe for SPL, derived from the file name."""
    return re.sub(r"[^a-z0-9_:-]+", "_", path.name.lower()).strip("_") or "sample"
