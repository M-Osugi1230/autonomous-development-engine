from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_dashboard_is_progress_only_and_read_only() -> None:
    assert "ADE Progress" in HTML
    assert "進捗確認専用" in HTML
    assert 'id="projectGrid"' in HTML
    assert 'id="refreshButton"' in HTML
    assert 'fetch("/api/status"' in HTML
    assert 'fetch("/api/control"' not in HTML
    assert "project-command" not in HTML
    assert "decision-command" not in HTML
    assert "submit_goal" not in HTML
    assert "preview_goal" not in HTML
    assert "New Goal" not in HTML
    assert "再開 / 起動" not in HTML
    assert "再計画" not in HTML


def test_dashboard_focuses_on_status_progress_and_position() -> None:
    assert "稼働中" in HTML
    assert "監視中" in HTML
    assert "停滞の可能性" in HTML
    assert "判断待ち" in HTML
    assert "停止" in HTML
    assert "完了" in HTML
    assert "GOAL" in HTML
    assert "現在地" in HTML
    assert "最終変化" in HTML
    assert "Task ${esc(taskPosition(p))}" in HTML


def test_dashboard_surfaces_stale_projects_without_mutating_them() -> None:
    assert 'activity==="STALE"' in HTML
    assert "6時間以上、ADEの状態更新を確認できていません。" in HTML
    assert "チャットで状況確認・再開を指示してください。" in HTML
    assert "状態更新が止まっています。" in HTML


def test_secondary_technical_information_is_collapsed() -> None:
    assert '<details class="more"><summary>詳細を見る</summary>' in HTML
    assert "Current Task:" in HTML
    assert "Next:" in HTML
    assert "Failures:" in HTML
    assert "State更新:" in HTML
    assert "Workflow:" in HTML


def test_dashboard_uses_five_minute_auto_refresh() -> None:
    assert "setInterval(loadStatus,300000)" in HTML
    assert "5分ごとに自動更新" in HTML


def test_browser_keeps_credentials_and_manual_secrets_out() -> None:
    assert "Control Key" not in HTML
    assert 'type="password"' not in HTML
    assert "sessionStorage" not in HTML
    assert "X-ADE-Control-Key" not in HTML
    assert "ADE_GITHUB_TOKEN" not in HTML
