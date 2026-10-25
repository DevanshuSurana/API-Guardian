from fastapi.testclient import TestClient

from main import app


def test_dashboard_serves_declared_favicon():
    client = TestClient(app)

    response = client.get("/favicon.svg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert "<svg" in response.text


def test_conventional_favicon_path_redirects_to_icon():
    client = TestClient(app)

    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.url.path == "/favicon.svg"
    assert response.headers["content-type"] == "image/svg+xml"


def test_dashboard_keeps_scan_submission_in_page_and_shows_findings():
    client = TestClient(app)

    response = client.get("/ui")

    assert response.status_code == 200
    assert "event.preventDefault()" in response.text
    assert "api('/api/migrations/analyze'" in response.text
    assert "Suggested fix:" in response.text
    assert "Potential issues" in response.text
