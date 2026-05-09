import base64
import io
import json
import re
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import main as backend_main
from backend.app.api import contract_app
from backend.app.core import settings as config
from backend.app.repositories import storage


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4//8/AwAI/AL+X1N6AAAAAElFTkSuQmCC"
)


def _configure_runtime(tmp_path: Path, *, access_key: str = "", allow_unauthenticated: bool = True):
    images_dir = tmp_path / "images"
    data_dir = tmp_path / "data"
    images_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    config.IMAGES_DIR = str(images_dir)
    config.DATA_DIR = str(data_dir)
    config.DATABASE_FILE = str(data_dir / "app.sqlite3")
    config.GALLERY_FILE = str(data_dir / "gallery.json")
    config.SETTINGS_FILE = str(data_dir / "settings.json")
    config.DEFAULT_API_URL = "https://api.example.com"
    config.DEFAULT_API_KEY = "default-key"
    config.DEFAULT_API_PATH = "/v1/images/generations"
    config.DEFAULT_RESPONSES_MODEL = "gpt-5.4"
    config.PANEL_PATH = ""
    config.ACCESS_KEY = access_key
    config.ALLOW_UNAUTHENTICATED = allow_unauthenticated
    config.ACCESS_KEY_COOKIE_NAME = "gpt_image_access"
    config.ACCESS_COOKIE_SECURE = False
    config.ACCESS_KEY_SESSION_MINUTES = 180
    config.ACCESS_MAX_FAILURES = 5
    config.ACCESS_LOCKOUT_SECONDS = 300
    config.IP_ALLOWLIST = ""
    config.TRUST_PROXY_HEADERS = False
    config.UPSTREAM_HOST_ALLOWLIST = ""
    config.WEBHOOK_HOST_ALLOWLIST = ""
    config.WEBHOOK_SIGNING_SECRET = "webhook-secret"
    config.WEBHOOK_TIMEOUT_SECONDS = 1
    config.WEBHOOK_MAX_ATTEMPTS = 1
    config.MAX_FILE_SIZE_MB = 50

    storage._db_initialized = False
    backend_main.app.state._state.clear()


@pytest.fixture()
def client(tmp_path):
    _configure_runtime(tmp_path)
    with TestClient(backend_main.app) as test_client:
        yield test_client


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/generate/{job_id}")
        assert resp.status_code == 200
        last = resp.json()
        if last["status"] in {"success", "error"}:
            return last
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {last}")


def _fake_gallery_entry(image_id: str, prompt: str, size: str, filename: str):
    storage.add_to_gallery_sync(
        image_id=image_id,
        prompt=prompt,
        size=size,
        filename=filename,
        metadata={
            "model": "gpt-image-2",
            "quality": "auto",
            "output_format": "png",
            "n": 1,
            "api_path": "/v1/images/generations",
            "api_preset_name": "Default",
        },
        image_bytes=PNG_BYTES,
    )
    return storage.get_gallery_entry(image_id)


@pytest.fixture(autouse=True)
def patch_upstream(monkeypatch):
    async def fake_generation_api(api_url, api_key, api_path, payload, api_preset_name=None, progress=None):
        if progress:
            progress("building_generation_payload", "Building generation payload")
            progress("waiting_for_api", "Waiting for upstream API response")
            progress("received_api_response", "Received upstream API response")
            progress("extracting_generation_data", "Extracting image data array")
            progress("decoding_b64_json", "Decoding b64_json image")
            progress("validating_image_bytes", "Validating decoded image")
            progress("saving_image_file", "Saving image file and gallery metadata")
        image_id = storage.generate_image_id()
        filename = f"{image_id}.png"
        entry = await storage.add_to_gallery_async(
            image_bytes=PNG_BYTES,
            image_id=image_id,
            prompt=payload.prompt,
            size=payload.size,
            filename=filename,
            metadata={
                "model": payload.model,
                "quality": payload.quality,
                "output_format": payload.output_format,
                "output_compression": payload.output_compression,
                "response_format": payload.response_format,
                "n": payload.n,
                "api_path": api_path,
                "api_preset_name": api_preset_name,
            },
        )
        return [entry]

    async def fake_edit_api(api_url, api_key, payload, image_bytes, image_filename, image_content_type, api_preset_name=None, progress=None):
        if progress:
            progress("building_edit_form", "Building multipart edit request")
            progress("uploading_edit_image", "Uploading source image and edit parameters")
            progress("received_api_response", "Received upstream API response")
            progress("extracting_edit_data", "Extracting edited image data array")
            progress("decoding_b64_json", "Decoding b64_json image")
            progress("validating_image_bytes", "Validating decoded image")
            progress("saving_images", "Saving edited images")
        image_id = storage.generate_image_id()
        filename = f"{image_id}.png"
        entry = await storage.add_to_gallery_async(
            image_bytes=PNG_BYTES,
            image_id=image_id,
            prompt=payload.prompt,
            size=payload.size,
            filename=filename,
            metadata={
                "model": payload.model,
                "quality": payload.quality,
                "output_format": payload.output_format,
                "output_compression": payload.output_compression,
                "response_format": payload.response_format,
                "n": payload.n,
                "api_path": "/v1/images/edits",
                "api_preset_name": api_preset_name,
            },
        )
        return [entry]

    monkeypatch.setattr(backend_main.proxy, "call_image_generation_api", fake_generation_api)
    monkeypatch.setattr(backend_main.proxy, "call_image_edit_api", fake_edit_api)


def test_health_and_version(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    version = client.get("/api/version")
    assert version.status_code == 200
    assert version.json()["version"]


def test_frontend_index_uses_csp_nonce(tmp_path, monkeypatch):
    _configure_runtime(tmp_path)
    build_dir = tmp_path / "frontend_build"
    build_dir.mkdir()
    (build_dir / "index.html").write_text(
        """
        <!doctype html>
        <script>
          import("/_app/immutable/entry/start.js");
        </script>
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(contract_app, "FRONTEND_BUILD_DIR", build_dir)

    with TestClient(backend_main.app) as client:
        resp = client.get("/")

    assert resp.status_code == 200
    nonce = re.search(r'<script nonce="([^"]+)">', resp.text).group(1)
    csp = resp.headers["content-security-policy"]
    assert f"'nonce-{nonce}'" in csp
    assert f"script-src-elem 'self' 'nonce-{nonce}'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src-elem", 1)[1].split(";", 1)[0]


def test_panel_path_hides_root_and_serves_panel_assets(tmp_path, monkeypatch):
    _configure_runtime(tmp_path, access_key="secret", allow_unauthenticated=False)
    config.PANEL_PATH = "/secret-panel"
    contract_app.PANEL_PATH = config.PANEL_PATH
    contract_app.AUTH_EXEMPT_PATHS.discard("/")
    contract_app.AUTH_EXEMPT_PATHS.add(config.PANEL_PATH)
    contract_app.NO_CACHE_PATHS.discard("/")
    contract_app.NO_CACHE_PATHS.add(config.PANEL_PATH)

    build_dir = tmp_path / "frontend_build"
    asset_path = build_dir / "_app" / "immutable" / "entry" / "app.js"
    asset_path.parent.mkdir(parents=True)
    (build_dir / "index.html").write_text(
        """
        <!doctype html>
        <script>
          import('/secret-panel/_app/immutable/entry/app.js');
        </script>
        """,
        encoding="utf-8",
    )
    asset_path.write_text("console.log('panel');", encoding="utf-8")
    monkeypatch.setattr(contract_app, "FRONTEND_BUILD_DIR", build_dir)

    try:
        with TestClient(backend_main.app, raise_server_exceptions=False) as client:
            root = client.get("/")
            panel = client.get("/secret-panel")
            asset = client.get("/secret-panel/_app/immutable/entry/app.js")
            old_asset = client.get("/_app/immutable/entry/app.js")
            api = client.get("/api/settings")
            scoped_api = client.get("/secret-panel/api/settings")
            scoped_health = client.get("/secret-panel/health")

        assert root.status_code == 404
        assert panel.status_code == 200
        assert asset.status_code == 200
        assert "console.log('panel')" in asset.text
        assert old_asset.status_code == 404
        assert api.status_code == 404
        assert scoped_api.status_code == 401
        assert scoped_health.status_code == 200
    finally:
        contract_app.PANEL_PATH = ""
        contract_app.AUTH_EXEMPT_PATHS.discard(config.PANEL_PATH)
        contract_app.AUTH_EXEMPT_PATHS.add("/")
        contract_app.NO_CACHE_PATHS.discard(config.PANEL_PATH)
        contract_app.NO_CACHE_PATHS.add("/")
        config.PANEL_PATH = ""


def test_access_cookie_and_status(tmp_path):
    _configure_runtime(tmp_path, access_key="secret", allow_unauthenticated=False)
    with TestClient(backend_main.app) as client:
        denied = client.get("/api/settings")
        assert denied.status_code == 401
        assert denied.json()["detail"] == "Access key required"

        bad = client.post("/api/access", json={"access_key": "nope"})
        assert bad.status_code == 401
        assert bad.json()["detail"] == "Invalid access key"

        ok = client.post("/api/access", json={"access_key": "secret"})
        assert ok.status_code == 200
        assert ok.json()["authenticated"] is True
        cookie = ok.headers["set-cookie"]
        assert "gpt_image_access=" in cookie
        assert "HttpOnly" in cookie
        assert "samesite=lax" in cookie.lower()
        assert "Secure" not in cookie

        status = client.get("/api/access/status")
        assert status.status_code == 200
        assert status.json()["authenticated"] is True
        assert status.json()["expires_at"]


def test_access_cookie_secure_auto_respects_request_scheme(tmp_path):
    _configure_runtime(tmp_path, access_key="secret", allow_unauthenticated=False)
    config.ACCESS_COOKIE_SECURE = "auto"
    with TestClient(backend_main.app) as client:
        http_ok = client.post("/api/access", json={"access_key": "secret"})
        assert http_ok.status_code == 200
        assert "Secure" not in http_ok.headers["set-cookie"]

    _configure_runtime(tmp_path, access_key="secret", allow_unauthenticated=False)
    config.ACCESS_COOKIE_SECURE = "auto"
    with TestClient(backend_main.app, base_url="https://testserver") as client:
        https_ok = client.post("/api/access", json={"access_key": "secret"})
        assert https_ok.status_code == 200
        assert "Secure" in https_ok.headers["set-cookie"]


def test_access_cookie_secure_auto_respects_trusted_proxy_proto(tmp_path):
    _configure_runtime(tmp_path, access_key="secret", allow_unauthenticated=False)
    config.ACCESS_COOKIE_SECURE = "auto"
    config.TRUST_PROXY_HEADERS = True
    with TestClient(backend_main.app) as client:
        ok = client.post(
            "/api/access",
            json={"access_key": "secret"},
            headers={"x-forwarded-proto": "https"},
        )
        assert ok.status_code == 200
        assert "Secure" in ok.headers["set-cookie"]


def test_frontend_build_assets_are_available_before_access_unlock(tmp_path, monkeypatch):
    _configure_runtime(tmp_path, access_key="secret", allow_unauthenticated=False)
    build_dir = tmp_path / "frontend_build"
    asset_path = build_dir / "_app" / "immutable" / "entry" / "app.js"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_text("console.log('ok');", encoding="utf-8")
    monkeypatch.setattr(contract_app, "FRONTEND_BUILD_DIR", build_dir)

    with TestClient(backend_main.app) as client:
        asset = client.get("/_app/immutable/entry/app.js")
        api = client.get("/api/settings")

    assert asset.status_code == 200
    assert "console.log('ok')" in asset.text
    assert api.status_code == 401


def test_access_lockout(tmp_path):
    _configure_runtime(tmp_path, access_key="secret", allow_unauthenticated=False)
    with TestClient(backend_main.app, raise_server_exceptions=False) as client:
        for _ in range(config.ACCESS_MAX_FAILURES + 1):
            resp = client.post("/api/access", json={"access_key": "wrong"})
        assert resp.status_code == 429
        assert "Too many failed attempts" in resp.json()["detail"]


def test_ip_allowlist_blocks_api_but_not_health(tmp_path):
    _configure_runtime(tmp_path)
    config.IP_ALLOWLIST = "10.0.0.1"
    with TestClient(backend_main.app, raise_server_exceptions=False) as client:
        health = client.get("/health")
        assert health.status_code == 200
        blocked = client.get("/api/version")
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "IP address is not allowed"


def test_settings_and_presets(client):
    settings = client.get("/api/settings")
    assert settings.status_code == 200
    body = settings.json()
    assert body["presets"]
    assert body["active_preset_id"]

    updated = client.post(
        "/api/settings",
        json={
            "active_preset_id": body["active_preset_id"],
            "preset_name": "Primary",
            "api_url": "https://api.example.com",
            "api_key": "new-key",
            "api_path": "/v1/responses",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["api_path"] == "/v1/responses"

    created = client.post("/api/settings/presets", json={"name": "Alt"})
    assert created.status_code == 200
    assert len(created.json()["presets"]) == 2


def test_generate_and_sse_contract(client):
    resp = client.post(
        "/api/generate",
        json={
            "prompt": "a red cube",
            "size": "1024x1024",
            "model": "gpt-image-2",
            "n": 1,
            "quality": "auto",
            "output_format": "png",
        },
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    job = _wait_for_job(client, job_id)
    assert job["status"] == "success"
    assert job["image_url"].startswith("/api/image/")

    events = client.get(f"/api/generate/{job_id}/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: job" in events.text
    assert job_id in events.text


def test_generate_and_edit_default_size_is_auto(client):
    generate = client.post(
        "/api/generate",
        json={
            "prompt": "default size",
            "model": "gpt-image-2",
            "n": 1,
            "quality": "auto",
            "output_format": "png",
        },
    )
    assert generate.status_code == 202
    generate_job = _wait_for_job(client, generate.json()["job_id"])
    assert generate_job["size"] == "auto"

    edit = client.post(
        "/api/edits",
        data={
            "prompt": "default edit size",
            "model": "gpt-image-2",
            "n": 1,
            "quality": "auto",
            "output_format": "png",
        },
        files={"image": ("input.png", PNG_BYTES, "image/png")},
    )
    assert edit.status_code == 202
    edit_job = _wait_for_job(client, edit.json()["job_id"])
    assert edit_job["size"] == "auto"


def test_edit_upload_and_gallery_flow(client):
    seeded = _fake_gallery_entry("gallery-1", "seed image", "1024x1024", "gallery-1.png")
    assert seeded is not None

    edit_upload = client.post(
        "/api/edits",
        data={
            "prompt": "make it blue",
            "size": "1024x1024",
            "model": "gpt-image-2",
            "n": 1,
            "quality": "auto",
            "output_format": "png",
        },
        files={"image": ("input.png", PNG_BYTES, "image/png")},
    )
    assert edit_upload.status_code == 202
    upload_job_id = edit_upload.json()["job_id"]
    upload_job = _wait_for_job(client, upload_job_id)
    assert upload_job["status"] == "success"

    edit_gallery = client.post(
        "/api/edits/from-gallery/gallery-1",
        data={
            "prompt": "make it green",
            "size": "1024x1024",
            "model": "gpt-image-2",
            "n": 1,
            "quality": "auto",
            "output_format": "png",
        },
    )
    assert edit_gallery.status_code == 202
    gallery_job = _wait_for_job(client, edit_gallery.json()["job_id"])
    assert gallery_job["status"] == "success"


def test_gallery_image_download_and_zip(client):
    entry = _fake_gallery_entry("gallery-zip", "zip me", "1024x1024", "gallery-zip.png")
    assert entry is not None

    image = client.get("/api/image/gallery-zip.png")
    assert image.status_code == 200
    assert image.headers["cache-control"].startswith("public")

    download = client.get("/api/download/gallery-zip.png")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]

    archive = client.get("/api/download-all")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        assert "metadata.json" in zf.namelist()
        assert "images/gallery-zip.png" in zf.namelist()
        metadata = json.loads(zf.read("metadata.json"))
        assert metadata["images"]


def test_import_archive(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps({
            "schema_version": 1,
            "exported_at": "2026-01-01T00:00:00Z",
            "app": {"name": "gpt-image-linux", "version": "v0.0.0"},
            "images": [
                {
                    "id": "import-1",
                    "prompt": "imported",
                    "size": "1024x1024",
                    "filename": "images/import-1.png",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        }))
        zf.writestr("images/import-1.png", PNG_BYTES)

    buf.seek(0)
    resp = client.post(
        "/api/import",
        files={"archive": ("archive.zip", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["imported"] == 1


def test_validation_422_and_global_500(tmp_path, monkeypatch):
    _configure_runtime(tmp_path)
    with TestClient(backend_main.app, raise_server_exceptions=False) as client:
        bad = client.post(
            "/api/generate",
            json={"prompt": "x", "size": "1025x1025"},
        )
        assert bad.status_code == 422

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(backend_main.storage, "get_gallery", boom)
        broken = client.get("/api/gallery")
        assert broken.status_code == 500
        assert broken.json()["detail"] == "Internal Server Error"
