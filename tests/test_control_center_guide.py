from __future__ import annotations

from api import app


def _get(path: str) -> tuple[str, dict[str, str], str]:
    captured: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(
        app.application(
            {"REQUEST_METHOD": "GET", "PATH_INFO": path},
            start_response,
        )
    ).decode("utf-8")
    return str(captured["status"]), dict(captured["headers"]), body


def test_dashboard_shows_only_a_compact_opt_in_guide_link() -> None:
    status, headers, body = _get("/")
    assert status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert 'href="/guide"' in body
    assert ">使い方</a>" in body
    assert "最初にこれだけ覚えればOK" not in body


def test_beginner_guide_is_available_only_when_opened() -> None:
    status, headers, body = _get("/guide")
    assert status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert "はじめての使い方" in body
    assert "最初にこれだけ覚えればOK" in body
    assert "Human Action" in body
    assert "RUNNINGなら待つ" in body
    assert "実行前プレビュー" in body
    assert "このGoalで開始" in body
    assert "安全設計について" in body
    assert 'href="/"' in body
    assert "ダッシュボードへ戻る" in body


def test_guide_has_no_secret_or_control_key_handling() -> None:
    guide = app.GUIDE_PATH.read_text(encoding="utf-8")
    assert "ADE_GITHUB_TOKEN" not in guide
    assert "X-ADE-Control-Key" not in guide
    assert "sessionStorage" not in guide
