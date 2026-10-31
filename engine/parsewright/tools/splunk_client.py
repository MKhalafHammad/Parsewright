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
from parsewright.ta_builder.naming import require_pw_index, require_real_app, require_test_app
from parsewright.ta_builder.package import DESCRIPTION, Package, packages_dir, sha256

# Names interpolated into SPL must be plain: test sourcetypes are [a-z0-9_:-] only.
SPL_NAME = re.compile(r"[a-z0-9_:-]+")
WARN_COMPONENTS = "DateParserVerbose, LineBreakingProcessor, AggregatorMiningProcessor"
INGEST_HOST = "parsewright-sample"
# Splunk's documented props.conf defaults for the keys Parsewright writes, used to tell an
# override in local/ (or another app) from the system default (lab-findings Q11: the [default]
# stanza cannot be read over REST). Keys absent here have no default.
PROPS_SYSTEM_DEFAULTS = {
    "SHOULD_LINEMERGE": "true",
    "LINE_BREAKER": "([\\r\\n]+)",
    "MAX_TIMESTAMP_LOOKAHEAD": "128",
    "TRUNCATE": "10000",
    "MAX_EVENTS": "256",
    "KV_MODE": "auto",
}
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

    def install(self, pkg: Package, promotion: bool = False) -> None:
        """Install or replace an app from the packages folder, after re-checking its hash.

        Only test apps, except during promotion, which installs the approved real-name TA.
        """
        (require_real_app if promotion else require_test_app)(pkg.app)
        root = packages_dir(self.packages).resolve()
        path = pkg.path.resolve()
        if path.parent != root:
            raise ValueError(f"package {path} is outside PARSEWRIGHT_PACKAGES_DIR")
        if sha256(path) != pkg.sha256:
            raise SplunkError("package changed after it was built; refusing to install (T5.9)")
        # update=False on promotion: Splunk itself refuses to overwrite an existing app (M3).
        self.deploy.post("apps/local", name=str(path), filename=True, update=not promotion)

    def update_app(self, pkg: Package, expected_version: str) -> None:
        """Replace a promoted TA in place (update=true keeps its local/, lab-findings Q11), only if
        the installed copy is the Parsewright TA at the version the registry expects."""
        require_real_app(pkg.app)
        installed = self.app_info(pkg.app)
        if installed is None:
            raise SplunkError(f"{pkg.app} is not installed; nothing to update in place")
        if installed.get("version") != expected_version:
            raise SplunkError(
                f"{pkg.app} is installed at version {installed.get('version')!r}, not the "
                f"registry's {expected_version!r}; refusing to replace it"
            )
        if installed.get("description") != DESCRIPTION:
            raise SplunkError(f"{pkg.app} was not installed by Parsewright; refusing to replace it")
        root = packages_dir(self.packages).resolve()
        path = pkg.path.resolve()
        if path.parent != root:
            raise ValueError(f"package {path} is outside PARSEWRIGHT_PACKAGES_DIR")
        if sha256(path) != pkg.sha256:
            raise SplunkError("package changed after it was built; refusing to install (T5.9)")
        self.deploy.post("apps/local", name=str(path), filename=True, update=True)

    def app_info(self, app: str) -> dict | None:
        """An installed app's version and description, or None if it is not installed."""
        try:
            body = self.deploy.get(f"apps/local/{app}", output_mode="json").body.read()
        except binding.HTTPError as e:
            if e.status == 404:
                return None
            raise
        content = json.loads(body)["entry"][0]["content"]
        return {
            "version": str(content.get("version", "")),
            "description": content.get("description"),
        }

    def props_effective(self, app: str, sourcetype: str) -> dict[str, str]:
        """The props Splunk applies to a sourcetype in the app's context: its default/ merged
        with its local/ and any other app's exported settings (empty if there are none)."""
        require_real_app(app)
        try:
            body = self.search.get(
                f"configs/conf-props/{spl_name(sourcetype)}",
                owner="nobody",
                app=app,
                output_mode="json",
            ).body.read()
        except binding.HTTPError as e:
            if e.status == 404:
                return {}
            raise
        content = json.loads(body)["entry"][0]["content"]
        return {k: str(v) for k, v in content.items() if not k.startswith("eai:")}

    def app_exists(self, app: str) -> bool:
        try:
            self.deploy.get(f"apps/local/{app}")
        except binding.HTTPError as e:
            if e.status == 404:
                return False
            raise
        return True

    def props_exist(self, sourcetype: str) -> bool:
        """Does any app (or Splunk's own defaults) already define props for this sourcetype?"""
        try:
            self.search.get(f"configs/conf-props/{spl_name(sourcetype)}", owner="nobody", app="-")
        except binding.HTTPError as e:
            if e.status == 404:
                return False
            raise
        return True

    def transforms_exist(self, names: list[str]) -> list[str]:
        """Existing transform names among `names`, over REST (the collision check, Q7)."""
        found = []
        for name in names:
            try:
                self.search.get(
                    f"configs/conf-transforms/{spl_name(name)}", owner="nobody", app="-"
                )
            except binding.HTTPError as e:
                if e.status == 404:
                    continue
                raise
            found.append(name)
        return found

    def uninstall(self, app: str) -> None:
        require_test_app(app)
        try:
            self.deploy.delete(f"apps/local/{app}")
        except binding.HTTPError as e:
            if e.status != 404:
                raise

    def ingest(self, index: str, sourcetype: str, body: str, source: str) -> None:
        """Post raw data through receivers/simple (Q8). Only pw_ indexes are accepted (T5.1)."""
        # Validate before touching the near-admin deploy token at all.
        index, sourcetype, source = require_pw_index(index), spl_name(sourcetype), spl_name(source)
        self.deploy.post(
            "receivers/simple",
            body=body.encode("utf-8"),
            index=index,
            sourcetype=sourcetype,
            source=source,
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

    def count(self, index: str, sourcetype: str, source: str | None = None) -> int:
        rows = self._rows(
            f"| tstats count where index={require_pw_index(index)} "
            f"sourcetype={spl_name(sourcetype)}{_by_source(source)}"
        )
        return int(rows[0].get("count", 0)) if rows else 0

    def wait_stable(
        self, index: str, sourcetype: str, timeout: float = 120, source: str | None = None
    ) -> int:
        """Poll until two consecutive non-zero counts match (design "Validation mechanics")."""
        seen, end = -1, time.monotonic() + timeout
        while time.monotonic() < end:
            time.sleep(2)
            now = self.count(index, sourcetype, source)
            if now and now == seen:
                return now
            seen = now
        return max(seen, 0)

    def events(self, index: str, sourcetype: str) -> list[tuple[int, str]]:
        """(epoch seconds, raw) for every event of one attempt, oldest first."""
        return [(t, raw) for t, _, raw in self.events_with_indextime(index, sourcetype)]

    def events_with_indextime(
        self, index: str, sourcetype: str, source: str | None = None
    ) -> list[tuple[int, int, str]]:
        """(epoch, _indextime, raw) per event: _indextime exposes the timestamp fallback."""
        rows = self._rows(
            f"search index={require_pw_index(index)} sourcetype={spl_name(sourcetype)}"
            f"{_by_source(source)} | eval t=floor(_time), it=_indextime "
            "| sort 0 t | table t it _raw"
        )
        return [(int(r["t"]), int(r.get("it") or 0), r.get("_raw", "")) for r in rows]

    def field_rows(self, index: str, sourcetype: str, source: str | None = None) -> list[dict]:
        """Every search-time field of every event, keyed by epoch t (the manifest key)."""
        return self._rows(
            f"search index={require_pw_index(index)} sourcetype={spl_name(sourcetype)}"
            f"{_by_source(source)} | eval t=floor(_time) | fields - _* | table t *"
        )

    def report_rows(
        self, index: str, sourcetype: str, first: int, source: str | None = None
    ) -> list[dict]:
        """The first events with their raw text and parsed fields in the same row."""
        return self._rows(
            f"search index={require_pw_index(index)} sourcetype={spl_name(sourcetype)}"
            f"{_by_source(source)} | sort 0 _time | head {int(first)} "
            "| eval t=floor(_time) | table t _raw *"
        )

    def field_summary(
        self, index: str, sourcetype: str, first: int, source: str | None = None
    ) -> list[dict]:
        """fieldsummary over the first `first` events by time: the sample the agents saw."""
        return self._rows(
            f"search index={require_pw_index(index)} sourcetype={spl_name(sourcetype)}"
            f"{_by_source(source)} | sort 0 _time | head {int(first)} | fieldsummary maxvals=5"
        )

    def datamodel_rows(
        self, model: str, dataset: str, index: str, sourcetype: str, source: str | None = None
    ) -> list[dict]:
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
            f"| datamodel {model} {dataset} search | search sourcetype={spl_name(sourcetype)}"
            f"{_by_source(source)} | eval t=floor(_time) | table t {root}.*"
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


def _by_source(source: str | None) -> str:
    """An extra source filter: an update ingests old and new samples under one sourcetype."""
    return f" source={spl_name(source)}" if source else ""


def ingest_source(path: Path) -> str:
    """A source name safe for SPL, derived from the file name."""
    return re.sub(r"[^a-z0-9_:-]+", "_", path.name.lower()).strip("_") or "sample"
