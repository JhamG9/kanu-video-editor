from fastapi.testclient import TestClient

from kanu.api.app import app

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"]


def test_lut_endpoint():
    r = client.post("/api/lut", json={})
    assert r.status_code == 200 and len(r.content) == 33 ** 3 * 3


def test_upload_list_frame_and_settings(tiny_video):
    with open(tiny_video, "rb") as fh:
        r = client.put("/api/upload?name=PRUEBA.mp4", content=fh.read())
    assert r.status_code == 200 and r.json()["name"] == "PRUEBA.mp4"
    clips = client.get("/api/clips").json()["clips"]
    assert [c["name"] for c in clips] == ["PRUEBA.mp4"]
    r = client.get("/api/frame?clip=PRUEBA.mp4&t=1&w=320")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    info = client.get("/api/clip?clip=PRUEBA.mp4").json()
    s = info["settings"]
    s["contrast"] = 20
    s["status"] = "manual"
    r = client.post("/api/settings?clip=PRUEBA.mp4", json=s)
    assert r.json()["settings"]["contrast"] == 20


def test_errors_come_as_json():
    r = client.get("/api/clip?clip=no-existe.mp4")
    assert r.status_code == 404 and "error" in r.json()


def test_style_delete_needs_explicit_flag():
    assert client.post("/api/style/delete").status_code == 400


def test_json_body_without_content_type():
    """La interfaz envía JSON sin cabecera Content-Type: la API debe aceptarlo igual."""
    r = client.post("/api/lut", content=b'{"contrast": 20}', headers={"content-type": "text/plain"})
    assert r.status_code == 200 and len(r.content) == 33 ** 3 * 3
