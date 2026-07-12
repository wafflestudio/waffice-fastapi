import sys
from types import SimpleNamespace

import pytest

from app.exceptions import ObjectStorageError
from app.services.object_storage import OCIObjectStorageService


@pytest.fixture
def configured_oci_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OCI_NAMESPACE", "namespace")
    monkeypatch.setenv("OCI_BUCKET", "bucket")
    monkeypatch.setenv("OCI_REGION", "ap-chuncheon-1")


def test_instance_principal_authentication(
    monkeypatch: pytest.MonkeyPatch, configured_oci_env
):
    signer = object()
    calls = {}

    class FakeObjectStorageClient:
        def __init__(self, config, signer=None):
            calls["config"] = config
            calls["signer"] = signer

    fake_oci = SimpleNamespace(
        auth=SimpleNamespace(
            signers=SimpleNamespace(
                InstancePrincipalsSecurityTokenSigner=lambda: signer,
                get_resource_principals_signer=lambda: None,
            )
        ),
        config=SimpleNamespace(from_file=lambda *args, **kwargs: {}),
        object_storage=SimpleNamespace(ObjectStorageClient=FakeObjectStorageClient),
    )
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setenv("OCI_OBJECT_STORAGE_AUTH", "instance_principal")

    OCIObjectStorageService()

    assert calls == {
        "config": {"region": "ap-chuncheon-1"},
        "signer": signer,
    }


def test_config_file_authentication(
    monkeypatch: pytest.MonkeyPatch, configured_oci_env
):
    config = {"region": "ap-chuncheon-1"}
    calls = {}

    def from_file(config_file, profile):
        calls["from_file"] = (config_file, profile)
        return config

    class FakeObjectStorageClient:
        def __init__(self, client_config):
            calls["client_config"] = client_config

    fake_oci = SimpleNamespace(
        auth=SimpleNamespace(signers=SimpleNamespace()),
        config=SimpleNamespace(from_file=from_file),
        object_storage=SimpleNamespace(ObjectStorageClient=FakeObjectStorageClient),
    )
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setenv("OCI_OBJECT_STORAGE_AUTH", "config_file")
    monkeypatch.setenv("OCI_CONFIG_FILE", "/tmp/oci-config")
    monkeypatch.setenv("OCI_CONFIG_PROFILE", "WAFFICE")

    OCIObjectStorageService()

    assert calls == {
        "from_file": ("/tmp/oci-config", "WAFFICE"),
        "client_config": config,
    }


def test_resource_principal_authentication(
    monkeypatch: pytest.MonkeyPatch, configured_oci_env
):
    signer = object()
    calls = {}

    class FakeObjectStorageClient:
        def __init__(self, config, signer=None):
            calls["config"] = config
            calls["signer"] = signer

    fake_oci = SimpleNamespace(
        auth=SimpleNamespace(
            signers=SimpleNamespace(
                get_resource_principals_signer=lambda: signer,
            )
        ),
        object_storage=SimpleNamespace(ObjectStorageClient=FakeObjectStorageClient),
    )
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setenv("OCI_OBJECT_STORAGE_AUTH", "resource_principal")

    OCIObjectStorageService()

    assert calls == {
        "config": {"region": "ap-chuncheon-1"},
        "signer": signer,
    }


def test_unsupported_authentication_mode(
    monkeypatch: pytest.MonkeyPatch, configured_oci_env
):
    fake_oci = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "oci", fake_oci)
    monkeypatch.setenv("OCI_OBJECT_STORAGE_AUTH", "unsupported")

    with pytest.raises(ObjectStorageError) as exc_info:
        OCIObjectStorageService()

    assert isinstance(exc_info.value.__cause__, ValueError)
