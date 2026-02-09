"""Tests for harmonizely2hubspot app."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import app as harmonizely_app

EXAMPLE_PAYLOAD = json.loads(Path("example.json").read_text())


def test_healthcheck():
    """Test that the healthcheck endpoint returns OK."""
    with harmonizely_app.APP.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.data == b"OK"


def test_404():
    """Test that unknown paths return 404 JSON error."""
    harmonizely_app.CONFIG = {"emails": ["user@example.com"]}
    with harmonizely_app.APP.test_client() as client:
        response = client.post(
            "/unknown@example.com",
            json=EXAMPLE_PAYLOAD,
        )
        assert response.status_code == 404


def test_parse_name():
    """Test name parsing from full name string."""
    first, last = harmonizely_app.parse_name("Aarno Aukia")
    assert first == "Aarno"
    assert last == "Aukia"


def test_parse_name_with_title():
    """Test that Herr/Frau titles are stripped."""
    first, last = harmonizely_app.parse_name("Herr Max Mustermann")
    assert first == "Max"
    assert last == "Mustermann"


def test_parse_name_with_middle():
    """Test that middle names are included in first name."""
    first, last = harmonizely_app.parse_name("Johann Sebastian Bach")
    assert first == "Johann Sebastian"
    assert last == "Bach"


def test_sentry_healthcheck_sampling_root():
    """Test that healthcheck path is sampled at low rate."""
    context = {"wsgi_environ": {"REQUEST_URI": "/"}}
    assert harmonizely_app.sentry_healthcheck_sampling(context) == 0.001


def test_sentry_healthcheck_sampling_other():
    """Test that non-healthcheck paths are sampled at 100%."""
    context = {"wsgi_environ": {"REQUEST_URI": "/user@example.com"}}
    assert harmonizely_app.sentry_healthcheck_sampling(context) == 1


def test_sentry_healthcheck_sampling_empty():
    """Test that missing context is sampled at 100%."""
    assert harmonizely_app.sentry_healthcheck_sampling({}) == 1


def test_webhook_post_processes_payload():
    """Test that a valid webhook POST triggers payload processing."""
    harmonizely_app.CONFIG = {
        "emails": ["user@example.com"],
        "token": "fake-token",
    }

    with (
        harmonizely_app.APP.test_client() as client,
        patch("app.hubspot") as mock_hubspot,
        patch("app.process_payload") as mock_process,
    ):
        mock_hubspot.HubSpot.return_value = MagicMock()
        response = client.post(
            "/user@example.com",
            json=EXAMPLE_PAYLOAD,
        )
        assert response.status_code == 200
        assert response.data == b"OK"
        mock_process.assert_called_once_with(
            user_email="user@example.com", payload=EXAMPLE_PAYLOAD
        )


def test_webhook_no_payload():
    """Test that a POST with no JSON body returns 400."""
    harmonizely_app.CONFIG = {
        "emails": ["user@example.com"],
        "token": "fake-token",
    }

    with harmonizely_app.APP.test_client() as client:
        response = client.post(
            "/user@example.com",
            content_type="application/json",
            data="",
        )
        assert response.status_code == 400
