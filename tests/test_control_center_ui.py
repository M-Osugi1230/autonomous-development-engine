from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_control_center_has_no_manual_control_key_ui() -> None:
    assert 'id="metricControl"' in HTML
    assert 'id="metricBrowserKey"' not in HTML
    assert "Control Key: 未設定" not in HTML
    assert "Control Key: 設定済み" not in HTML
    assert 'type="password"' not in HTML
    assert "sessionStorage" not in HTML
    assert "X-ADE-Control-Key" not in HTML
    assert "Control Keyの入力は不要です。" in HTML


def test_mutations_require_only_ready_control_plane() -> None:
    assert "const canControl=()=>controlsReady()&&!state.actionBusy;" in HTML
    assert '$("submitGoal").disabled=!canControl()' in HTML
    assert "const disabled=canControl()?\"\":\" disabled\"" in HTML


def test_mobile_project_commands_use_event_delegation_not_inline_handlers() -> None:
    assert 'class="button project-command"' in HTML
    assert '$("projectGrid").addEventListener("click"' in HTML
    assert 'e.target.closest("button.project-command")' in HTML
    assert 'onclick="command(' not in HTML
    assert 'touch-action:manipulation' in HTML


def test_project_action_feedback_is_persistent_and_local_to_card() -> None:
    assert "action-result" in HTML
    assert "タップを受け付けました。" in HTML
    assert "GitHub Actionsへ送信済みです。" in HTML
    assert 'role="status"' in HTML
    assert 'aria-live="polite"' in HTML


def test_browser_never_receives_github_token() -> None:
    assert "GitHubトークンはサーバー側だけに保持され、ブラウザには配布しません。" in HTML
    assert "ADE_GITHUB_TOKEN" not in HTML
