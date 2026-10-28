import io
import json

import pytest
from conftest import settings

from parsewright.ta_builder import package
from parsewright.tools.splunk_client import SplunkClient, SplunkError, spl_name

APP = "TA-parsewright-acme-vpn__test_abcd1234"


class FakeService:
    def __init__(self, rows=None):
        self.posts: list[tuple] = []
        self.searches: list[str] = []
        self.rows = rows or []
        self.jobs = self

    def post(self, path, **kw):
        self.posts.append((path, kw))

    def delete(self, path):
        self.posts.append(("DELETE " + path, {}))

    def oneshot(self, spl, **kw):
        self.searches.append(spl)
        return io.BytesIO(json.dumps({"results": self.rows}).encode())


@pytest.fixture
def client(tmp_path):
    return SplunkClient(
        settings(tmp_path), search=FakeService([{"count": "3"}]), deploy=FakeService()
    )


@pytest.mark.parametrize("index", ["main", "pw", "_internal", "pw_x OR index=main"])
def test_ingest_refuses_non_pw_indexes(client, index):
    with pytest.raises(ValueError):
        client.ingest(index, "acme:vpn__test_abcd1234_a1", "x", "src")
    assert client.deploy.posts == []


def test_ingest_posts_to_receivers_simple(client):
    client.ingest("pw_test", "acme:vpn__test_abcd1234_a1", "a\nb", "acme_vpn_json")
    path, kw = client.deploy.posts[0]
    assert path == "receivers/simple" and kw["index"] == "pw_test" and kw["body"] == b"a\nb"
    assert kw["host"] == "parsewright-sample"  # never the lab's real address


@pytest.mark.parametrize(
    "name", ["x OR index=main", "x | delete", 'x" OR "1', "x`macro`", "x [search *]", "X"]
)
def test_spl_names_cannot_inject(name):
    with pytest.raises(ValueError):
        spl_name(name)


def test_count_scopes_by_index_and_sourcetype(client):
    assert client.count("pw_test", "acme:vpn__test_abcd1234_a1") == 3
    assert client.search.searches[0] == (
        "| tstats count where index=pw_test sourcetype=acme:vpn__test_abcd1234_a1"
    )


def test_install_rechecks_hash_and_location(tmp_path, client):
    pkg = package.build(tmp_path, APP, "0.0.1", {"props": {"acme:vpn": {"TZ": "UTC"}}})
    client.install(pkg)
    path, kw = client.deploy.posts[-1]
    assert path == "apps/local" and kw["filename"] is True and kw["update"] is True

    pkg.path.write_bytes(b"swapped")
    with pytest.raises(SplunkError, match="changed"):
        client.install(pkg)

    elsewhere = tmp_path / "sub"
    elsewhere.mkdir()
    moved = package.Package(path=elsewhere / "x.tgz", app=APP, sha256=pkg.sha256)
    with pytest.raises(ValueError, match="outside"):
        client.install(moved)


@pytest.mark.parametrize("app", ["Splunk_SA_CIM", "search", "TA-parsewright-acme-vpn"])
def test_install_and_uninstall_refuse_non_test_apps(tmp_path, client, app):
    with pytest.raises(ValueError):
        client.uninstall(app)
    fake = package.Package(path=tmp_path / "x.tgz", app=app, sha256="0")
    with pytest.raises(ValueError):
        client.install(fake)
    assert client.deploy.posts == []
