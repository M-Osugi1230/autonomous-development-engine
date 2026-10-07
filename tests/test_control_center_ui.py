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
    assert "const disabled=canControl()?\"\":\" disabled\"" in HTML
    assert '$("submitGoal").disabled=!ready||!matching' in HTML
    assert '$("previewGoal").disabled=!ready||goal.length<20' in HTML


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


def test_running_projects_are_explained_in_operator_language() -> None:
    assert "現在のゴール" in HTML
    assert "今やっていること" in HTML
    assert "次に起きること" in HTML
    assert "あなたの操作" in HTML
    assert "実装エージェントの実行結果を監視しています。" in HTML
    assert "技術詳細を見る" in HTML
    assert "Raw Goal" in HTML


def test_new_goal_explains_scope_examples_and_idle_gate() -> None:
    assert "New Goalでできること" in HTML
    assert "変更できる範囲" in HTML
    assert "最大4,000文字" in HTML
    assert "PROJECT_META" in HTML
    assert "example-chip" in HTML
    assert "実行中のGoalを上書きしない安全設計です。" in HTML
    assert "projectIdle(p)" in HTML


def test_goal_requires_preview_before_start() -> None:
    assert 'id="previewGoal"' in HTML
    assert 'id="goalPreview"' in HTML
    assert "実行前プレビュー" in HTML
    assert "ADE Goal Preview" in HTML
    assert "preview_goal" in HTML
    assert "NOT STARTED" in HTML
    assert "書き換え可能範囲" in HTML
    assert "理解のために読める範囲" in HTML
    assert "実行フロー" in HTML
    assert "成功条件" in HTML
    assert "Safety Boundary" in HTML
    assert "state.previewFingerprint===goalFingerprint()" in HTML
    assert "Goalが変更されています。もう一度実行前プレビューを作成してください。" in HTML
    assert "プレビュー済みのGoalをTrusted Plannerへ投入して自律実行を開始します。" in HTML


def test_preview_does_not_dispatch_until_explicit_start() -> None:
    preview_start = HTML.index("async function requestGoalPreview")
    preview_end = HTML.index('$("projectGrid").addEventListener', preview_start)
    preview_function = HTML[preview_start:preview_end]
    assert 'command:"preview_goal"' in preview_function
    assert 'command(project,"submit_goal"' not in preview_function
    assert "まだGitHub ActionsやPlannerは起動していません。" not in HTML  # server-owned preview message


def test_browser_never_receives_github_token() -> None:
    assert "GitHubトークンはサーバー側だけに保持され、ブラウザには配布しません。" in HTML
    assert "ADE_GITHUB_TOKEN" not in HTML
