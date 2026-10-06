from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_control_center_distinguishes_server_and_browser_key_state() -> None:
    assert 'id="metricControl"' in HTML
    assert 'id="metricBrowserKey"' in HTML
    assert "Control Key: 未設定" in HTML
    assert "Control Key: 設定済み" in HTML
    assert "サーバー側はREADYです。ただし、この端末のControl Keyが未設定です。" in HTML
    assert "操作準備完了です。" in HTML


def test_mutations_are_disabled_until_both_controls_are_ready() -> None:
    assert "const canControl=()=>controlsReady()&&browserKeyReady()&&!state.actionBusy;" in HTML
    assert "controlDisabledAttr()" in HTML
    assert '$("submitGoal").disabled=!canControl();' in HTML


def test_control_action_result_is_persistent_and_secret_is_not_rendered() -> None:
    assert 'id="operationNotice"' in HTML
    assert "GitHub Actionsへ送信済みです。" in HTML
    assert "Control Keyそのものは画面に表示しません。" in HTML
    assert 'type="password"' in HTML
    assert "sessionStorage" in HTML
