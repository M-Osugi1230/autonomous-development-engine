from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_control_center_distinguishes_server_and_browser_key_state() -> None:
    assert 'id="metricControl"' in HTML
    assert 'id="metricBrowserKey"' in HTML
    assert "Control Key: 未設定" in HTML
    assert "Control Key: 設定済み" in HTML
    assert "サーバー側はREADYです。" in HTML
    assert "操作準備完了です。" in HTML


def test_mutations_are_disabled_until_both_controls_are_ready() -> None:
    assert "const canControl=()=>controlsReady()&&browserKeyReady()&&!state.actionBusy;" in HTML
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


def test_control_key_stays_masked_and_session_scoped() -> None:
    assert 'type="password"' in HTML
    assert "sessionStorage" in HTML
    assert "GitHubトークンはブラウザへ配布しません。" in HTML
