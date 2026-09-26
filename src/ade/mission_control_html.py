from __future__ import annotations

from html import escape
from string import Template

from .mission_control import MissionControlSnapshot


def _text(value: object | None, fallback: str = "—") -> str:
    if value is None:
        return fallback
    return escape(str(value), quote=True)


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
              <div class="eyebrow">{priority}</div>
              <h3>{question}</h3>
              <dl class="meta-list">
                <div><dt>Decision ID</dt><dd>{decision_id}</dd></div>
                <div><dt>Blocking task</dt><dd>{blocking_task}</dd></div>
              </dl>
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
    <dl class="detail-grid">
      <div><dt>Type</dt><dd>{kind}</dd></div>
      <div><dt>Task</dt><dd>{task}</dd></div>
      <div><dt>Updated</dt><dd>{updated}</dd></div>
    </dl>
    <p class="preview-action">
      <a class="preview-link" href="{url}" target="_blank" rel="noopener noreferrer">
        {title}
      </a>
    </p>
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
            f'<span class="activity-task">{_text(event.task_id)}</span>'
            if event.task_id is not None
            else ""
        )
        items.append(
            """
            <li class="activity-item">
              <div class="activity-meta">
                <span>{time}</span>
                <span>{kind}</span>
                {task}
              </div>
              <div class="activity-summary">{summary}</div>
            </li>
            """.format(
                time=_text(event.occurred_at),
                kind=_text(event.kind),
                task=task,
                summary=_text(event.summary),
            )
        )
    return '<ol class="activity-list">' + "".join(items) + "</ol>"


def render_mission_control(snapshot: MissionControlSnapshot) -> str:
    if not isinstance(snapshot, MissionControlSnapshot):
        raise ValueError("snapshot must be a MissionControlSnapshot")

    telemetry = snapshot.telemetry
    completed_total = snapshot.completed_tasks + snapshot.failed_tasks
    template = Template("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ADE Mission Control</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: Canvas;
      color: CanvasText;
    }
    header, main, footer {
      width: min(100%, 880px);
      margin-inline: auto;
      padding-inline: 16px;
    }
    header {
      padding-block: 24px 12px;
    }
    h1, h2, h3, p { margin-top: 0; }
    h1 { font-size: clamp(1.7rem, 7vw, 2.4rem); margin-bottom: 6px; }
    h2 { font-size: 1.15rem; margin-bottom: 12px; }
    h3 { font-size: 1rem; margin-bottom: 10px; }
    .subtitle, .empty { opacity: .72; }
    .status-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-block: 16px;
    }
    .card, .decision-card {
      border: 1px solid color-mix(in srgb, CanvasText 18%, transparent);
      border-radius: 14px;
      padding: 14px;
      background: color-mix(in srgb, Canvas 96%, CanvasText 4%);
    }
    section { margin-block: 16px; }
    .stat strong { display: block; font-size: 1.35rem; }
    .stat span { font-size: .78rem; opacity: .68; }
    .detail-grid, .meta-list {
      display: grid;
      gap: 8px;
      margin: 0;
    }
    .detail-grid > div, .meta-list > div {
      display: grid;
      grid-template-columns: minmax(110px, .8fr) minmax(0, 1.2fr);
      gap: 10px;
      border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent);
      padding-block: 7px;
    }
    dt { font-size: .78rem; opacity: .68; }
    dd { margin: 0; overflow-wrap: anywhere; }
    .decision-list { display: grid; gap: 10px; }
    .eyebrow {
      font-size: .72rem;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
      opacity: .7;
      margin-bottom: 6px;
    }
    .options, .warning-list { padding-left: 20px; margin-bottom: 0; }
    .warning-list { margin-top: 0; }
    .ok-message { margin-bottom: 0; }
    .preview-action { margin: 14px 0 0; }
    .preview-link { overflow-wrap: anywhere; }
    .activity-list {
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 10px;
    }
    .activity-item {
      border-bottom: 1px solid color-mix(in srgb, CanvasText 10%, transparent);
      padding-bottom: 10px;
    }
    .activity-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      font-size: .72rem;
      opacity: .68;
      margin-bottom: 4px;
    }
    .activity-summary { overflow-wrap: anywhere; }
    footer { padding-block: 16px 28px; opacity: .62; font-size: .8rem; }
    @media (min-width: 680px) {
      .status-row { grid-template-columns: repeat(4, minmax(0, 1fr)); }
      main { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
      .wide { grid-column: 1 / -1; }
    }
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">Autonomous Development Engine</div>
    <h1>Mission Control</h1>
    <p class="subtitle">$project_id</p>
    <div class="status-row" aria-label="Project summary">
      <div class="card stat"><strong>$status</strong><span>Status</span></div>
      <div class="card stat"><strong>$iteration</strong><span>Iteration</span></div>
      <div class="card stat"><strong>$completed</strong><span>Completed tasks</span></div>
      <div class="card stat"><strong>$queue_depth</strong><span>Queued tasks</span></div>
    </div>
  </header>

  <main>
    <section class="card" aria-labelledby="project-heading">
      <h2 id="project-heading">Project</h2>
      <dl class="detail-grid">
        <div><dt>Phase</dt><dd>$phase</dd></div>
        <div><dt>Milestone</dt><dd>$milestone</dd></div>
        <div><dt>Current task</dt><dd>$current_task</dd></div>
        <div><dt>State updated</dt><dd>$state_updated</dd></div>
        <div><dt>Queue exhausted</dt><dd>$queue_exhausted</dd></div>
        <div><dt>Failed tasks</dt><dd>$failed</dd></div>
      </dl>
    </section>

    <section class="card" aria-labelledby="checkpoint-heading">
      <h2 id="checkpoint-heading">Checkpoint</h2>
      $checkpoint
    </section>

    <section class="card" aria-labelledby="preview-heading">
      <h2 id="preview-heading">Latest output</h2>
      $preview
    </section>

    <section class="card" aria-labelledby="telemetry-heading">
      <h2 id="telemetry-heading">Telemetry</h2>
      <dl class="detail-grid">
        <div><dt>Cycles started</dt><dd>$cycles_started</dd></div>
        <div><dt>Cycles completed</dt><dd>$cycles_completed</dd></div>
        <div><dt>Repair attempts</dt><dd>$repair_attempts</dd></div>
        <div><dt>Human interrupts</dt><dd>$human_interrupts</dd></div>
        <div><dt>Quota pauses</dt><dd>$quota_pauses</dd></div>
        <div><dt>Failure ledger</dt><dd>$failure_ledger</dd></div>
      </dl>
    </section>

    <section class="card" aria-labelledby="warnings-heading">
      <h2 id="warnings-heading">Warnings</h2>
      $warnings
    </section>

    <section class="wide" aria-labelledby="decisions-heading">
      <h2 id="decisions-heading">Open human decisions</h2>
      <div class="decision-list">
        $decisions
      </div>
    </section>

    <section class="wide card" aria-labelledby="activity-heading">
      <h2 id="activity-heading">Activity</h2>
      $activity
    </section>
  </main>

  <footer>
    Read-only snapshot · $completed_total terminal task outcomes recorded
  </footer>
</body>
</html>
""")
    return template.substitute(
        project_id=_text(snapshot.project_id),
        status=_text(snapshot.project_status),
        iteration=_text(snapshot.iteration),
        completed=_text(snapshot.completed_tasks),
        queue_depth=_text(snapshot.queue_depth),
        phase=_text(snapshot.phase),
        milestone=_text(snapshot.milestone),
        current_task=_text(snapshot.current_task_id),
        state_updated=_text(snapshot.state_updated_at),
        queue_exhausted="yes" if snapshot.queue_exhausted else "no",
        failed=_text(snapshot.failed_tasks),
        checkpoint=_checkpoint_card(snapshot),
        cycles_started=_text(telemetry.cycles_started),
        cycles_completed=_text(telemetry.cycles_completed),
        repair_attempts=_text(telemetry.repair_attempts),
        human_interrupts=_text(telemetry.human_interrupts),
        quota_pauses=_text(telemetry.quota_pauses),
        failure_ledger=_text(snapshot.failure_ledger_count),
        warnings=_warnings(snapshot),
        decisions=_decision_cards(snapshot),
        preview=_preview_card(snapshot),
        activity=_activity_feed(snapshot),
        completed_total=_text(completed_total),
    )
