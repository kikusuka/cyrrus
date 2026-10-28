"""
Tests for the services registry.
"""
import pytest
from cyrrus.services import (
    get_service,
    list_services,
    list_service_ids,
    service_to_dict,
    detect_services,
    _SERVICES,
)


class TestServiceRegistry:
    """Test service registry functionality."""

    def test_get_service_existing(self):
        """Test retrieving an existing service."""
        service = get_service("ollama")
        assert service is not None
        assert service.id == "ollama"
        assert service.display_name == "Ollama"
        assert service.kind == "local"

    def test_get_service_nonexistent(self):
        """Test retrieving a nonexistent service returns None."""
        service = get_service("nonexistent")
        assert service is None

    def test_list_services(self):
        """Test listing all services."""
        services = list_services()
        assert len(services) > 0
        assert all(s.id in _SERVICES for s in services)

    def test_list_service_ids(self):
        """Test listing all service IDs."""
        ids = list_service_ids()
        assert len(ids) > 0
        assert set(ids) == set(_SERVICES.keys())

    def test_service_to_dict(self):
        """Test converting a service to dictionary."""
        service = get_service("ollama")
        d = service_to_dict(service)
        assert isinstance(d, dict)
        assert d["id"] == "ollama"
        assert d["display_name"] == "Ollama"
        assert d["kind"] == "local"

    def test_all_services_have_required_fields(self):
        """Test that all services have required fields."""
        for service in list_services():
            assert service.id
            assert service.display_name
            assert service.kind in ("local", "hosted")
            assert service.provider_type
            assert service.default_base_url
            assert service.help_text

    def test_local_services_have_probe_url(self):
        """Test that local services have probe URLs (except custom)."""
        for service in list_services():
            if service.kind == "local" and service.id != "custom":
                assert service.probe_url is not None

    def test_hosted_services_have_api_key_env_var(self):
        """Test that hosted services have API key env var suggestions."""
        for service in list_services():
            if service.kind == "hosted":
                assert service.api_key_env_var is not None


class TestDetectServices:
    """Test service detection functionality."""

    def test_detect_services_returns_dict(self):
        """Test that detect_services returns a dictionary."""
        results = detect_services(timeout=0.1)
        assert isinstance(results, dict)

    def test_detect_services_all_keys_present(self):
        """Test that detect_services includes all service IDs."""
        results = detect_services(timeout=0.1)
        for service_id in list_service_ids():
            assert service_id in results

    def test_detect_services_values_are_bool(self):
        """Test that detect_services returns boolean values."""
        results = detect_services(timeout=0.1)
        for value in results.values():
            assert isinstance(value, bool)

    def test_detect_services_timeout_parameter(self):
        """Test that timeout parameter is respected."""
        # This test doesn't validate actual timeout behavior,
        # just that the function accepts the parameter
        results = detect_services(timeout=0.5)
        assert isinstance(results, dict)

    def test_probe_url_nonexistent_returns_false(self):
        """Test that probing a nonexistent URL returns False."""
        from cyrrus.services import _probe_url
        result = _probe_url("http://localhost:99999/nonexistent", timeout=0.1)
        assert result is False
