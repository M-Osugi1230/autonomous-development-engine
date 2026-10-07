from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_control_center_keeps_manual_secrets_out_of_browser() -> None:
    assert "Control Key: 未設定" not in HTML
    assert "Control Key: 設定済み" not in HTML
    assert 'type="password"' not in HTML
    assert "sessionStorage" not in HTML
    assert "X-ADE-Control-Key" not in HTML
    assert "ADE_GITHUB_TOKEN" not in HTML


def test_dashboard_defaults_to_essential_operator_information() -> None:
    assert 'id="overviewText"' in HTML
    assert 'id="projectGrid"' in HTML
    assert 'id="humanSection" hidden' in HTML
    assert 'id="goalComposer"' in HTML
    assert 'class="more"' in HTML
    assert "Goal" in HTML
    assert "現在" in HTML
    assert "あなた" in HTML
    assert "詳細・操作" in HTML


def test_dashboard_removes_old_always_visible_metrics_and_guidance() -> None:
    assert 'id="metricProjects"' not in HTML
    assert 'id="metricRunning"' not in HTML
    assert 'id="metricHuman"' not in HTML
    assert 'id="metricControl"' not in HTML
    assert "New Goalでできること" not in HTML
    assert "PROJECT_META" not in HTML
    assert "example-chip" not in HTML
    assert "scope-grid" not in HTML


def test_project_actions_are_hidden_under_details_but_keep_mobile_event_delegation() -> None:
    assert '<details class="more"><summary>詳細・操作</summary>' in HTML
    assert 'class="button project-command"' in HTML
    assert '$("projectGrid").addEventListener("click"' in HTML
    assert 'e.target.closest("button.project-command")' in HTML
    assert 'onclick="command(' not in HTML
    assert "touch-action:manipulation" in HTML


def test_human_action_only_appears_when_a_decision_exists() -> None:
    assert '$("humanSection").hidden=decisions.length===0;' in HTML
    assert "あなたの判断が必要です" in HTML
    assert "現在、回答が必要なDecisionはありません。" not in HTML


def test_new_goal_is_collapsed_and_requires_preview_before_start() -> None:
    assert '<details class="new-goal" id="goalComposer">' in HTML
    assert "<summary>＋ New Goal</summary>" in HTML
    assert 'id="previewGoal"' in HTML
    assert 'id="goalPreview"' in HTML
    assert "実行前プレビュー" in HTML
    assert "まだ開始していません" in HTML
    assert "変更できる範囲" in HTML
    assert "成功条件" in HTML
    assert "preview_goal" in HTML
    assert "state.previewFingerprint===goalFingerprint()" in HTML


def test_preview_does_not_dispatch_until_explicit_start() -> None:
    preview_start = HTML.index("async function requestGoalPreview")
    preview_end = HTML.index('$("projectGrid").addEventListener', preview_start)
    preview_function = HTML[preview_start:preview_end]
    assert 'command:"preview_goal"' in preview_function
    assert 'command(project,"submit_goal"' not in preview_function


def test_mutations_still_require_ready_control_plane() -> None:
    assert "const canControl=()=>controlsReady()&&!state.actionBusy;" in HTML
    assert 'const disabled=canControl()?"":" disabled";' in HTML
    assert '$("submitGoal").disabled=!ready||!matching;' in HTML
    assert '$("previewGoal").disabled=!ready||goal.length<20;' in HTML


def test_action_feedback_remains_local_and_persistent() -> None:
    assert "action-result" in HTML
    assert "GitHub Actionsへ送信済みです。" in HTML
    assert 'role="status"' in HTML
    assert 'aria-live="polite"' in HTML
