from __future__ import annotations

from html import escape
from string import Template

from .mission_control import MissionControlSnapshot


def _text(value: object | None, fallback: str = "—") -> str:
    if value is None:
        return fallback
    return escape(str(value), quote=True)


def _status_class(value: str | None) -> str:
    normalized = (value or "").upper()
    if normalized in {"RUNNING", "READY", "COMPLETED", "VERIFIED"}:
        return "status-good"
    if normalized in {"RECOVERING", "PAUSED_QUOTA", "WAITING", "PENDING"}:
        return "status-warn"
    if normalized in {"HUMAN_WAIT", "FAILED", "BLOCKED"}:
        return "status-attention"
    return "status-neutral"


def _campaign_progress(snapshot: MissionControlSnapshot) -> tuple[int, int, int]:
    campaign = snapshot.campaign or {}
    completed_raw = campaign.get("completed_tasks")
    total_raw = campaign.get("total_tasks")
    try:
        completed = int(completed_raw)
        total = int(total_raw)
    except (TypeError, ValueError):
        completed = snapshot.completed_tasks
        total = snapshot.completed_tasks + snapshot.failed_tasks + snapshot.queue_depth
        if snapshot.current_task_id is not None and total <= completed:
            total = completed + 1
    total = max(total, completed, 0)
    percent = 100 if total == 0 and snapshot.queue_exhausted else (
        round((completed / total) * 100) if total > 0 else 0
    )
    return completed, total, max(0, min(100, percent))


def _decision_cards(snapshot: MissionControlSnapshot) -> str:
    if not snapshot.open_decisions:
        return '<p class="empty">No open human decisions.</p>'

    cards: list[str] = []
    for decision in snapshot.open_decisions:
        options = "".join(
            f"<li>{_text(option)}</li>"
            for option in decision.options
        )
        cards.append(
            """
            <article class="decision-card">
              <div class="decision-topline">
                <span class="badge badge-attention">{priority}</span>
                <span class="mono">{decision_id}</span>
              </div>
              <h3>{question}</h3>
              <p class="muted">Blocking task · {blocking_task}</p>
              <ul class="options">{options}</ul>
            </article>
            """.format(
                priority=_text(decision.priority),
                question=_text(decision.question),
                decision_id=_text(decision.decision_id),
                blocking_task=_text(decision.blocking_task_id),
                options=options,
            )
        )
    return "".join(cards)


def _checkpoint_card(snapshot: MissionControlSnapshot) -> str:
    checkpoint = snapshot.checkpoint
    if checkpoint is None:
        return '<p class="empty">No checkpoint is present.</p>'

    return """
    <dl class="detail-grid">
      <div><dt>Task</dt><dd>{task}</dd></div>
      <div><dt>State</dt><dd>{state}</dd></div>
      <div><dt>Attempt</dt><dd>{attempt}</dd></div>
      <div><dt>Replans</dt><dd>{replans}</dd></div>
      <div><dt>Failure kind</dt><dd>{failure}</dd></div>
      <div><dt>Resume after</dt><dd>{resume}</dd></div>
      <div><dt>Provider session</dt><dd>{provider_session}</dd></div>
    </dl>
    """.format(
        task=_text(checkpoint.task_id),
        state=_text(checkpoint.state),
        attempt=_text(checkpoint.attempt),
        replans=_text(checkpoint.replan_count),
        failure=_text(checkpoint.failure_kind),
        resume=_text(checkpoint.resume_after),
        provider_session="present" if checkpoint.provider_session_present else "none",
    )


def _warnings(snapshot: MissionControlSnapshot) -> str:
    if not snapshot.warnings:
        return '<p class="ok-message">No warnings.</p>'
    items = "".join(f"<li>{_text(warning)}</li>" for warning in snapshot.warnings)
    return f'<ul class="warning-list">{items}</ul>'


def _preview_card(snapshot: MissionControlSnapshot) -> str:
    preview = snapshot.preview
    if preview is None:
        return '<p class="empty">No latest output registered.</p>'

    return """
    <div class="output-card">
      <div>
        <div class="eyebrow">{kind}</div>
        <strong>{title}</strong>
        <p class="muted">Task {task} · {updated}</p>
      </div>
      <a class="button-link" href="{url}" target="_blank" rel="noopener noreferrer">Open output</a>
    </div>
    """.format(
        kind=_text(preview.kind),
        task=_text(preview.task_id),
        updated=_text(preview.updated_at),
        url=_text(preview.url),
        title=_text(preview.title),
    )


def _activity_feed(snapshot: MissionControlSnapshot) -> str:
    if not snapshot.activity:
        return '<p class="empty">No activity recorded yet.</p>'

    items: list[str] = []
    for event in snapshot.activity:
        task = (
            f'<span class="activity-task mono">{_text(event.task_id)}</span>'
            if event.task_id is not None
            else ""
        )
        items.append(
            """
            <li class="activity-item">
              <span class="activity-dot" aria-hidden="true"></span>
              <div class="activity-body">
                <div class="activity-meta">
                  <span>{time}</span>
                  <span>{kind}</span>
                  {task}
                </div>
                <div class="activity-summary">{summary}</div>
              </div>
            </li>
            """.format(
                time=_text(event.occurred_at),
                kind=_text(event.kind),
                task=task,
                summary=_text(event.summary),
            )
        )
    return '<ol class="activity-list">' + "".join(items) + "</ol>"


def _planning_card(snapshot: MissionControlSnapshot) -> str:
    planning = snapshot.planning
    if planning is None:
        return '<p class="empty">No autonomous planning status.</p>'
    return """<dl class="detail-grid">
      <div><dt>Request</dt><dd>{request_id}</dd></div>
      <div><dt>State</dt><dd>{state}</dd></div>
      <div><dt>Attempt</dt><dd>{attempt}</dd></div>
      <div><dt>Reason</dt><dd>{reason}</dd></div>
      <div><dt>Updated</dt><dd>{updated_at}</dd></div>
    </dl>""".format(
        request_id=_text(planning.get("request_id")),
        state=_text(planning.get("state")),
        attempt=_text(planning.get("attempt")),
        reason=_text(planning.get("reason")),
        updated_at=_text(planning.get("updated_at")),
    )


def _campaign_card(snapshot: MissionControlSnapshot) -> str:
    campaign = snapshot.campaign
    if campaign is None:
        return '<p class="empty">No active campaign.</p>'
    return """<dl class="detail-grid">
      <div><dt>Campaign</dt><dd>{campaign_id}</dd></div>
      <div><dt>Goal</dt><dd>{goal}</dd></div>
      <div><dt>Status</dt><dd>{status}</dd></div>
      <div><dt>Progress</dt><dd>{completed} / {total}</dd></div>
    </dl>""".format(
        campaign_id=_text(campaign.get("campaign_id")),
        goal=_text(campaign.get("goal")),
        status=_text(campaign.get("status")),
        completed=_text(campaign.get("completed_tasks")),
        total=_text(campaign.get("total_tasks")),
    )


def _release_card(snapshot: MissionControlSnapshot) -> str:
    release = snapshot.release
    if release is None:
        return '<p class="empty">No release orchestration state.</p>'
    return """<dl class="detail-grid">
      <div><dt>Candidate</dt><dd>{candidate}</dd></div>
      <div><dt>Repository</dt><dd>{repository}</dd></div>
      <div><dt>Source SHA</dt><dd>{source_sha}</dd></div>
      <div><dt>Target</dt><dd>{target}</dd></div>
      <div><dt>Approval</dt><dd>{approval}</dd></div>
      <div><dt>Promotion</dt><dd>{promotion}</dd></div>
      <div><dt>Deployment</dt><dd>{deployment}</dd></div>
      <div><dt>Deployment identity</dt><dd>{deployment_identity}</dd></div>
      <div><dt>Runtime verification</dt><dd>{verification}</dd></div>
      <div><dt>Containment</dt><dd>{containment}</dd></div>
      <div><dt>Human action</dt><dd>{human_action}</dd></div>
    </dl>""".format(
        candidate=_text(release.release_candidate_id),
        repository=_text(release.repository),
        source_sha=_text(release.source_sha),
        target=_text(release.target_environment),
        approval=_text(release.approval_state),
        promotion=_text(release.promotion_state),
        deployment=_text(release.deployment_state),
        deployment_identity="present" if release.deployment_identity_present else "none",
        verification=_text(release.verification_state),
        containment=_text(release.containment_state),
        human_action=_text(release.next_required_human_action),
    )


def _improvement_card(snapshot: MissionControlSnapshot) -> str:
    improvement = snapshot.improvement
    if improvement is None:
        return '<p class="empty">No Continuous Improvement state.</p>'
    return """<dl class="detail-grid">
      <div><dt>Release candidate</dt><dd>{release_candidate}</dd></div>
      <div><dt>Repository</dt><dd>{repository}</dd></div>
      <div><dt>Source SHA</dt><dd>{source_sha}</dd></div>
      <div><dt>Environment</dt><dd>{environment}</dd></div>
      <div><dt>Signals</dt><dd>{signal_count}</dd></div>
      <div><dt>Observation only</dt><dd>{observation_only}</dd></div>
      <div><dt>Current</dt><dd>{current}</dd></div>
      <div><dt>Cooldown</dt><dd>{cooldown}</dd></div>
      <div><dt>Superseded</dt><dd>{superseded}</dd></div>
      <div><dt>Conflicted</dt><dd>{conflicted}</dd></div>
      <div><dt>Cycle limit</dt><dd>{cycle_limit}</dd></div>
      <div><dt>Retired</dt><dd>{retired}</dd></div>
      <div><dt>Current signal</dt><dd>{current_signal}</dd></div>
      <div><dt>Current kind</dt><dd>{current_kind}</dd></div>
      <div><dt>Cycle state</dt><dd>{cycle_state}</dd></div>
      <div><dt>Cycle index</dt><dd>{cycle_index}</dd></div>
      <div><dt>Handoff count</dt><dd>{handoff_count}</dd></div>
      <div><dt>Lineage retirements</dt><dd>{lineage_retirements}</dd></div>
      <div><dt>Latest retirement</dt><dd>{latest_retirement}</dd></div>
    </dl>""".format(
        release_candidate=_text(improvement.release_candidate_id),
        repository=_text(improvement.repository),
        source_sha=_text(improvement.source_sha),
        environment=_text(improvement.release_environment),
        signal_count=_text(improvement.signal_count),
        observation_only=_text(improvement.observation_only_count),
        current=_text(improvement.current_count),
        cooldown=_text(improvement.cooldown_count),
        superseded=_text(improvement.superseded_count),
        conflicted=_text(improvement.conflicted_count),
        cycle_limit=_text(improvement.cycle_limit_count),
        retired=_text(improvement.retired_count),
        current_signal=_text(improvement.current_signal_id),
        current_kind=_text(improvement.current_signal_kind),
        cycle_state=_text(improvement.cycle_state),
        cycle_index=_text(improvement.cycle_index),
        handoff_count=_text(improvement.handoff_count),
        lineage_retirements=_text(improvement.lineage_retirement_count),
        latest_retirement=_text(improvement.latest_retirement_id),
    )


def _zero_touch_start_card(snapshot: MissionControlSnapshot) -> str:
    start = snapshot.zero_touch_start
    if start is None:
        return '<p class="empty">No zero-touch start receipt.</p>'
    return """<dl class="detail-grid">
      <div><dt>Status</dt><dd>{status}</dd></div>
      <div><dt>Campaign</dt><dd>{campaign_id}</dd></div>
      <div><dt>Task</dt><dd>{task_id}</dd></div>
      <div><dt>Dispatched</dt><dd>{dispatched_at}</dd></div>
      <div><dt>Dispatch count</dt><dd>{dispatch_count}</dd></div>
      <div><dt>Source</dt><dd>{source}</dd></div>
    </dl>""".format(
        status=_text(start.get("status")),
        campaign_id=_text(start.get("campaign_id")),
        task_id=_text(start.get("task_id")),
        dispatched_at=_text(start.get("dispatched_at")),
        dispatch_count=_text(start.get("dispatch_count")),
        source=_text(start.get("source")),
    )


def _human_action(snapshot: MissionControlSnapshot) -> str:
    action = snapshot.next_required_human_action
    if action is None and not snapshot.open_decisions:
        return """
        <div class="action-state action-clear">
          <span class="action-icon" aria-hidden="true">✓</span>
          <div>
            <strong>No human action required</strong>
            <p>ADE can continue under its current trusted policy.</p>
          </div>
        </div>
        """
    return """
    <div class="action-state action-needed">
      <span class="action-icon" aria-hidden="true">!</span>
      <div>
        <strong>Human action required</strong>
        <p>{action}</p>
      </div>
    </div>
    """.format(action=_text(action, "Review the open decision below."))


def render_mission_control(snapshot: MissionControlSnapshot) -> str:
    if not isinstance(snapshot, MissionControlSnapshot):
        raise ValueError("snapshot must be a MissionControlSnapshot")

    telemetry = snapshot.telemetry
    completed_total = snapshot.completed_tasks + snapshot.failed_tasks
    progress_completed, progress_total, progress_percent = _campaign_progress(snapshot)
    lifecycle_class = _status_class(snapshot.lifecycle_status)
    checkpoint_state = snapshot.checkpoint.state if snapshot.checkpoint is not None else None
    checkpoint_class = _status_class(checkpoint_state)

    template = Template("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ADE Control Center · Mission Control</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
      --bg: #081018;
      --panel: #0d1722;
      --panel-strong: #111e2c;
      --panel-soft: #0a141e;
      --border: #203142;
      --text: #ecf4fb;
      --muted: #8fa4b7;
      --good: #5ee0a0;
      --warn: #f3c969;
      --attention: #ff7c89;
      --accent: #7bb8ff;
      --accent-strong: #a7d3ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(74, 139, 255, .12), transparent 34rem),
        var(--bg);
      color: var(--text);
    }
    a { color: inherit; }
    h1, h2, h3, p { margin-top: 0; }
    h1 { margin-bottom: 6px; font-size: clamp(1.65rem, 5vw, 2.35rem); letter-spacing: -.035em; }
    h2 { margin-bottom: 14px; font-size: 1rem; letter-spacing: -.01em; }
    h3 { margin-bottom: 8px; font-size: .98rem; }
    .shell {
      width: min(100%, 1180px);
      margin-inline: auto;
      padding: 18px 14px 32px;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 6px 2px 18px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 760;
      letter-spacing: -.02em;
    }
    .brand-mark {
      display: grid;
      place-items: center;
      width: 34px;
      height: 34px;
      border: 1px solid #36526f;
      border-radius: 10px;
      background: #11253a;
      color: var(--accent-strong);
      font-size: .75rem;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      padding: 4px 9px;
      border: 1px solid var(--border);
      border-radius: 999px;
      font-size: .72rem;
      font-weight: 700;
      letter-spacing: .02em;
      background: #101b26;
    }
    .badge-good { border-color: rgba(94,224,160,.38); color: var(--good); }
    .badge-attention { border-color: rgba(255,124,137,.38); color: var(--attention); }
    .hero {
      padding: 18px;
      border: 1px solid var(--border);
      border-radius: 20px;
      background: linear-gradient(145deg, rgba(19,35,51,.98), rgba(10,20,30,.98));
      box-shadow: 0 20px 70px rgba(0,0,0,.18);
    }
    .hero-top {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .eyebrow {
      margin-bottom: 6px;
      color: var(--muted);
      font-size: .69rem;
      font-weight: 800;
      letter-spacing: .1em;
      text-transform: uppercase;
    }
    .muted, .empty { color: var(--muted); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      width: fit-content;
      padding: 6px 10px;
      border: 1px solid var(--border);
      border-radius: 999px;
      font-size: .75rem;
      font-weight: 800;
    }
    .status-pill::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: currentColor;
      box-shadow: 0 0 14px currentColor;
    }
    .status-good { color: var(--good); }
    .status-warn { color: var(--warn); }
    .status-attention { color: var(--attention); }
    .status-neutral { color: var(--muted); }
    .progress-wrap { margin-top: 18px; }
    .progress-copy {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: .76rem;
    }
    .progress-track {
      height: 9px;
      overflow: hidden;
      border: 1px solid #22374a;
      border-radius: 999px;
      background: #08111a;
    }
    .progress-fill {
      width: $progress_percent%;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, #4e9cff, #6ee7b7);
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .metric {
      min-width: 0;
      padding: 13px;
      border: 1px solid var(--border);
      border-radius: 14px;
      background: rgba(8,17,26,.62);
    }
    .metric strong {
      display: block;
      overflow-wrap: anywhere;
      font-size: 1.16rem;
      line-height: 1.2;
    }
    .metric span { display: block; margin-top: 5px; color: var(--muted); font-size: .7rem; }
    .layout {
      display: grid;
      gap: 12px;
      margin-top: 12px;
    }
    .card {
      min-width: 0;
      padding: 16px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: rgba(13,23,34,.92);
    }
    .card-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 14px;
    }
    .card-head h2 { margin-bottom: 0; }
    .card-head small { color: var(--muted); }
    .action-state {
      display: flex;
      gap: 12px;
      align-items: flex-start;
      padding: 14px;
      border: 1px solid var(--border);
      border-radius: 14px;
    }
    .action-state p { margin: 4px 0 0; color: var(--muted); font-size: .84rem; }
    .action-icon {
      display: grid;
      flex: 0 0 28px;
      place-items: center;
      width: 28px;
      height: 28px;
      border-radius: 9px;
      font-weight: 900;
    }
    .action-clear { border-color: rgba(94,224,160,.24); background: rgba(94,224,160,.055); }
    .action-clear .action-icon { background: rgba(94,224,160,.13); color: var(--good); }
    .action-needed { border-color: rgba(255,124,137,.28); background: rgba(255,124,137,.055); }
    .action-needed .action-icon { background: rgba(255,124,137,.14); color: var(--attention); }
    .execution-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }
    .execution-block {
      padding: 12px;
      border: 1px solid #1c2d3d;
      border-radius: 12px;
      background: var(--panel-soft);
    }
    .execution-label { margin-bottom: 5px; color: var(--muted); font-size: .69rem; text-transform: uppercase; letter-spacing: .07em; }
    .execution-value { overflow-wrap: anywhere; font-weight: 700; }
    .detail-grid {
      display: grid;
      gap: 0;
      margin: 0;
    }
    .detail-grid > div {
      display: grid;
      grid-template-columns: minmax(112px, .72fr) minmax(0, 1.28fr);
      gap: 12px;
      padding: 8px 0;
      border-bottom: 1px solid #192a39;
    }
    .detail-grid > div:last-child { border-bottom: 0; }
    dt { color: var(--muted); font-size: .72rem; }
    dd { margin: 0; overflow-wrap: anywhere; font-size: .82rem; }
    .output-card {
      display: flex;
      flex-direction: column;
      gap: 12px;
      justify-content: space-between;
      padding: 13px;
      border: 1px solid #20364a;
      border-radius: 13px;
      background: #0a1621;
    }
    .output-card p { margin: 6px 0 0; font-size: .78rem; }
    .button-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 36px;
      width: fit-content;
      padding: 7px 11px;
      border: 1px solid #345878;
      border-radius: 9px;
      background: #102841;
      color: var(--accent-strong);
      font-size: .78rem;
      font-weight: 750;
      text-decoration: none;
    }
    .activity-list {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .activity-item {
      position: relative;
      display: grid;
      grid-template-columns: 16px 1fr;
      gap: 8px;
      padding: 0 0 15px;
    }
    .activity-item:not(:last-child)::before {
      content: "";
      position: absolute;
      left: 5px;
      top: 13px;
      bottom: 1px;
      width: 1px;
      background: #26394a;
    }
    .activity-dot {
      position: relative;
      z-index: 1;
      width: 11px;
      height: 11px;
      margin-top: 4px;
      border: 2px solid #6aaef6;
      border-radius: 999px;
      background: var(--panel);
    }
    .activity-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 3px;
      color: var(--muted);
      font-size: .68rem;
    }
    .activity-summary { overflow-wrap: anywhere; font-size: .84rem; }
    .decision-list { display: grid; gap: 10px; }
    .decision-card {
      padding: 13px;
      border: 1px solid rgba(255,124,137,.24);
      border-radius: 13px;
      background: rgba(255,124,137,.045);
    }
    .decision-topline {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 10px;
      color: var(--muted);
      font-size: .68rem;
    }
    .decision-card p { margin-bottom: 8px; font-size: .76rem; }
    .options, .warning-list { margin: 8px 0 0; padding-left: 19px; }
    .options li, .warning-list li { margin-block: 4px; font-size: .82rem; }
    .ok-message { margin-bottom: 0; color: var(--good); font-size: .82rem; }
    details {
      border-top: 1px solid #1b2b39;
      padding-top: 10px;
      margin-top: 10px;
    }
    summary {
      cursor: pointer;
      color: var(--muted);
      font-size: .78rem;
      font-weight: 700;
    }
    details > div { padding-top: 12px; }
    footer {
      padding: 18px 2px 0;
      color: var(--muted);
      font-size: .72rem;
      text-align: center;
    }
    @media (min-width: 700px) {
      .shell { padding: 24px 20px 38px; }
      .hero { padding: 22px; }
      .hero-top { flex-direction: row; align-items: flex-start; justify-content: space-between; }
      .metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      .layout { grid-template-columns: minmax(0, 1.18fr) minmax(300px, .82fr); }
      .span-2 { grid-column: 1 / -1; }
      .execution-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .output-card { flex-direction: row; align-items: center; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand"><span class="brand-mark">ADE</span><span>Control Center</span></div>
      <span class="badge">Read-only · Mission Control</span>
    </header>

    <section class="hero" aria-labelledby="project-title">
      <div class="hero-top">
        <div>
          <div class="eyebrow">Autonomous Development Engine</div>
          <h1 id="project-title">$project_id</h1>
          <p class="muted">$phase · $milestone</p>
        </div>
        <span class="status-pill $lifecycle_class">$lifecycle_status</span>
      </div>

      <div class="progress-wrap" aria-label="Campaign progress">
        <div class="progress-copy">
          <span>Goal progress</span>
          <span>$progress_completed / $progress_total tasks · $progress_percent%</span>
        </div>
        <div class="progress-track">
          <div class="progress-fill"></div>
        </div>
      </div>

      <div class="metrics" aria-label="Project summary">
        <div class="metric"><strong>$current_task</strong><span>Current task</span></div>
        <div class="metric"><strong>$completed</strong><span>Completed tasks</span></div>
        <div class="metric"><strong>$queue_depth</strong><span>Queued tasks</span></div>
        <div class="metric"><strong>$failed</strong><span>Failed tasks</span></div>
      </div>
    </section>

    <main class="layout">
      <section class="card" aria-labelledby="human-heading">
        <div class="card-head">
          <h2 id="human-heading">Human action</h2>
          <small>$decision_count open decision(s)</small>
        </div>
        $human_action
      </section>

      <section class="card" aria-labelledby="execution-heading">
        <div class="card-head">
          <h2 id="execution-heading">Live execution</h2>
          <span class="status-pill $checkpoint_class">$checkpoint_state</span>
        </div>
        <div class="execution-grid">
          <div class="execution-block">
            <div class="execution-label">Next system action</div>
            <div class="execution-value">$next_system_action</div>
          </div>
          <div class="execution-block">
            <div class="execution-label">Resume after</div>
            <div class="execution-value">$resume_after</div>
          </div>
          <div class="execution-block">
            <div class="execution-label">Project status</div>
            <div class="execution-value">$project_status</div>
          </div>
          <div class="execution-block">
            <div class="execution-label">State updated</div>
            <div class="execution-value">$state_updated</div>
          </div>
        </div>
      </section>

      <section class="card" aria-labelledby="campaign-heading">
        <div class="card-head"><h2 id="campaign-heading">Goal & campaign</h2><small>Trusted state</small></div>
        $campaign
        <details>
          <summary>Planner details</summary>
          <div>$planning</div>
        </details>
      </section>

      <section class="card" aria-labelledby="output-heading">
        <div class="card-head"><h2 id="output-heading">Latest output</h2><small>Review surface</small></div>
        $preview
      </section>

      <section class="card span-2" aria-labelledby="activity-heading">
        <div class="card-head"><h2 id="activity-heading">Recent activity</h2><small>Newest first</small></div>
        $activity
      </section>

      <section class="card" aria-labelledby="decisions-heading">
        <div class="card-head"><h2 id="decisions-heading">Open human decisions</h2><small>Trusted boundary</small></div>
        <div class="decision-list">$decisions</div>
      </section>

      <section class="card" aria-labelledby="health-heading">
        <div class="card-head"><h2 id="health-heading">System health</h2><small>Operational signals</small></div>
        <dl class="detail-grid">
          <div><dt>Lifecycle</dt><dd>$lifecycle_status</dd></div>
          <div><dt>Iteration</dt><dd>$iteration</dd></div>
          <div><dt>Queue exhausted</dt><dd>$queue_exhausted</dd></div>
          <div><dt>Failure ledger</dt><dd>$failure_ledger</dd></div>
          <div><dt>Cycles</dt><dd>$cycles_completed / $cycles_started completed</dd></div>
          <div><dt>Repair attempts</dt><dd>$repair_attempts</dd></div>
          <div><dt>Human interrupts</dt><dd>$human_interrupts</dd></div>
          <div><dt>Quota pauses</dt><dd>$quota_pauses</dd></div>
        </dl>
      </section>

      <section class="card" aria-labelledby="warnings-heading">
        <div class="card-head"><h2 id="warnings-heading">Warnings</h2><small>Needs attention</small></div>
        $warnings
      </section>

      <section class="card" aria-labelledby="checkpoint-heading">
        <div class="card-head"><h2 id="checkpoint-heading">Checkpoint</h2><small>Resume state</small></div>
        $checkpoint
      </section>

      <section class="card span-2" aria-labelledby="advanced-heading">
        <div class="card-head"><h2 id="advanced-heading">Advanced orchestration</h2><small>Read-only details</small></div>
        <details open>
          <summary>Release</summary>
          <div>$release</div>
        </details>
        <details>
          <summary>Continuous Improvement</summary>
          <div>$improvement</div>
        </details>
        <details>
          <summary>Zero-touch start</summary>
          <div>$zero_touch_start</div>
        </details>
      </section>
    </main>

    <footer>
      ADE Control Center v0.1 · Read-only Mission Control · $completed_total terminal task outcomes recorded
    </footer>
  </div>
</body>
</html>
""")
    return template.substitute(
        project_id=_text(snapshot.project_id),
        project_status=_text(snapshot.project_status),
        lifecycle_status=_text(snapshot.lifecycle_status),
        lifecycle_class=lifecycle_class,
        checkpoint_state=_text(checkpoint_state, "IDLE"),
        checkpoint_class=checkpoint_class,
        progress_completed=_text(progress_completed),
        progress_total=_text(progress_total),
        progress_percent=_text(progress_percent),
        phase=_text(snapshot.phase, "ADE"),
        milestone=_text(snapshot.milestone, "Mission Control"),
        current_task=_text(snapshot.current_task_id, "Idle"),
        completed=_text(snapshot.completed_tasks),
        queue_depth=_text(snapshot.queue_depth),
        failed=_text(snapshot.failed_tasks),
        iteration=_text(snapshot.iteration),
        next_system_action=_text(snapshot.next_system_action, "No pending system action"),
        next_required_human_action=_text(snapshot.next_required_human_action),
        resume_after=_text(snapshot.resume_after, "Not scheduled"),
        state_updated=_text(snapshot.state_updated_at),
        queue_exhausted="yes" if snapshot.queue_exhausted else "no",
        failure_ledger=_text(snapshot.failure_ledger_count),
        decision_count=_text(len(snapshot.open_decisions)),
        human_action=_human_action(snapshot),
        planning=_planning_card(snapshot),
        campaign=_campaign_card(snapshot),
        release=_release_card(snapshot),
        improvement=_improvement_card(snapshot),
        zero_touch_start=_zero_touch_start_card(snapshot),
        checkpoint=_checkpoint_card(snapshot),
        cycles_started=_text(telemetry.cycles_started),
        cycles_completed=_text(telemetry.cycles_completed),
        repair_attempts=_text(telemetry.repair_attempts),
        human_interrupts=_text(telemetry.human_interrupts),
        quota_pauses=_text(telemetry.quota_pauses),
        warnings=_warnings(snapshot),
        decisions=_decision_cards(snapshot),
        preview=_preview_card(snapshot),
        activity=_activity_feed(snapshot),
        completed_total=_text(completed_total),
    )
