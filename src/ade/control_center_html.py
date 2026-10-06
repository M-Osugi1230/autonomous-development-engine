from __future__ import annotations

from html import escape
from string import Template

from .control_center import (
    ControlCenterPortfolioSnapshot,
    ControlCenterProjectSummary,
)


def _text(value: object | None, fallback: str = "—") -> str:
    if value is None:
        return fallback
    return escape(str(value), quote=True)


def _status_class(status: str) -> str:
    normalized = status.upper()
    if normalized in {"RUNNING", "READY", "COMPLETED", "VERIFIED"}:
        return "good"
    if normalized in {"RECOVERING", "PAUSED_QUOTA", "WAITING", "PENDING"}:
        return "warn"
    if normalized in {"HUMAN_WAIT", "FAILED", "BLOCKED"}:
        return "attention"
    return "neutral"


def _project_card(project: ControlCenterProjectSummary) -> str:
    human = (
        '<span class="human human-needed">Human action required</span>'
        if project.human_action_required
        else '<span class="human human-clear">No human action</span>'
    )
    current = _text(project.current_task_id, "Idle")
    next_action = _text(project.next_system_action, "No pending system action")
    resume = _text(project.resume_after, "Not scheduled")
    return """
    <article class="project-card {status_class}">
      <div class="project-top">
        <div>
          <div class="project-id">{project_id}</div>
          <div class="project-meta">{phase} · {milestone}</div>
        </div>
        <span class="status {status_class}">{status}</span>
      </div>
      <div class="progress-copy"><span>Progress</span><strong>{percent}%</strong></div>
      <div class="progress-track"><div class="progress-fill" style="width:{percent}%"></div></div>
      <div class="stats">
        <div><strong>{current}</strong><span>Current task</span></div>
        <div><strong>{completed}/{total}</strong><span>Tasks</span></div>
        <div><strong>{queue}</strong><span>Queued</span></div>
        <div><strong>{failed}</strong><span>Failed</span></div>
      </div>
      <div class="human-row">{human}</div>
      <dl class="details">
        <div><dt>Next system action</dt><dd>{next_action}</dd></div>
        <div><dt>Resume after</dt><dd>{resume}</dd></div>
        <div><dt>Warnings</dt><dd>{warnings}</dd></div>
        <div><dt>Updated</dt><dd>{updated}</dd></div>
      </dl>
    </article>
    """.format(
        status_class=_status_class(project.lifecycle_status),
        project_id=_text(project.project_id),
        phase=_text(project.phase, "ADE"),
        milestone=_text(project.milestone, "—"),
        status=_text(project.lifecycle_status),
        percent=project.progress_percent,
        current=current,
        completed=project.completed_tasks,
        total=project.total_tasks,
        queue=project.queue_depth,
        failed=project.failed_tasks,
        human=human,
        next_action=next_action,
        resume=resume,
        warnings=project.warning_count,
        updated=_text(project.state_updated_at),
    )


def render_control_center(snapshot: ControlCenterPortfolioSnapshot) -> str:
    if not isinstance(snapshot, ControlCenterPortfolioSnapshot):
        raise ValueError("snapshot must be a ControlCenterPortfolioSnapshot")

    project_cards = "".join(_project_card(project) for project in snapshot.projects)
    if not project_cards:
        project_cards = '<p class="empty">No ADE-managed projects are available.</p>'

    template = Template("""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ADE Control Center</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --bg:#071019; --panel:#0d1823; --border:#213244; --text:#eef5fb;
      --muted:#8da2b5; --accent:#76b7ff; --good:#5ee0a0; --warn:#f3c969;
      --attention:#ff7c89;
    }
    * { box-sizing:border-box; }
    body { margin:0; background:radial-gradient(circle at top left,rgba(74,139,255,.12),transparent 34rem),var(--bg); color:var(--text); }
    .shell { width:min(100%,1200px); margin:auto; padding:18px 14px 36px; }
    header { display:flex; gap:14px; align-items:flex-start; justify-content:space-between; margin-bottom:16px; }
    h1 { margin:0 0 4px; font-size:clamp(1.6rem,5vw,2.4rem); letter-spacing:-.04em; }
    p { margin:0; }
    .muted,.empty { color:var(--muted); }
    .brand { display:flex; gap:11px; align-items:center; }
    .mark { display:grid; place-items:center; width:36px; height:36px; border:1px solid #36526f; border-radius:11px; background:#11253a; color:#acd5ff; font-size:.72rem; font-weight:800; }
    .summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; margin-bottom:14px; }
    .summary > div { padding:13px; border:1px solid var(--border); border-radius:14px; background:rgba(13,24,35,.92); }
    .summary strong { display:block; font-size:1.25rem; }
    .summary span { display:block; margin-top:4px; color:var(--muted); font-size:.69rem; }
    .projects { display:grid; gap:12px; }
    .project-card { min-width:0; padding:16px; border:1px solid var(--border); border-radius:17px; background:rgba(13,24,35,.95); box-shadow:0 18px 54px rgba(0,0,0,.14); }
    .project-card.attention { border-color:rgba(255,124,137,.38); }
    .project-card.warn { border-color:rgba(243,201,105,.30); }
    .project-top { display:flex; gap:12px; justify-content:space-between; align-items:flex-start; }
    .project-id { font-size:1.05rem; font-weight:800; overflow-wrap:anywhere; }
    .project-meta { margin-top:3px; color:var(--muted); font-size:.7rem; overflow-wrap:anywhere; }
    .status { display:inline-flex; align-items:center; gap:6px; padding:5px 8px; border:1px solid var(--border); border-radius:999px; font-size:.68rem; font-weight:800; white-space:nowrap; }
    .status::before { content:""; width:6px; height:6px; border-radius:999px; background:currentColor; }
    .good { color:var(--good); } .warn { color:var(--warn); } .attention { color:var(--attention); } .neutral { color:var(--muted); }
    .progress-copy { display:flex; justify-content:space-between; margin:15px 0 6px; color:var(--muted); font-size:.7rem; }
    .progress-copy strong { color:var(--text); }
    .progress-track { height:8px; overflow:hidden; border:1px solid #23374a; border-radius:999px; background:#08121b; }
    .progress-fill { height:100%; border-radius:inherit; background:linear-gradient(90deg,#4e9cff,#6ee7b7); }
    .stats { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin-top:12px; }
    .stats > div { padding:10px; border:1px solid #1c2d3d; border-radius:11px; background:#09141e; min-width:0; }
    .stats strong { display:block; font-size:.92rem; overflow-wrap:anywhere; }
    .stats span { display:block; margin-top:4px; color:var(--muted); font-size:.65rem; }
    .human-row { margin-top:10px; }
    .human { display:inline-flex; padding:5px 8px; border-radius:8px; font-size:.7rem; font-weight:750; }
    .human-clear { color:var(--good); background:rgba(94,224,160,.09); }
    .human-needed { color:var(--attention); background:rgba(255,124,137,.10); }
    .details { margin:12px 0 0; }
    .details > div { display:grid; grid-template-columns:minmax(110px,.75fr) minmax(0,1.25fr); gap:10px; padding:7px 0; border-top:1px solid #192a39; }
    dt { color:var(--muted); font-size:.67rem; } dd { margin:0; font-size:.74rem; overflow-wrap:anywhere; }
    footer { margin-top:16px; color:var(--muted); text-align:center; font-size:.68rem; }
    @media (min-width:760px) {
      .shell { padding:26px 20px 42px; }
      .projects { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .stats { grid-template-columns:repeat(4,minmax(0,1fr)); }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="brand"><span class="mark">ADE</span><div><h1>Control Center</h1><p class="muted">Portfolio overview · read-only</p></div></div>
    </header>
    <section class="summary" aria-label="Portfolio summary">
      <div><strong>$project_count</strong><span>Projects</span></div>
      <div><strong>$active_count</strong><span>Active / non-terminal</span></div>
      <div><strong>$attention_count</strong><span>Human action required</span></div>
    </section>
    <main class="projects">$project_cards</main>
    <footer>ADE Control Center v0.2 · trusted Mission Control aggregation</footer>
  </div>
</body>
</html>
""")
    return template.substitute(
        project_count=len(snapshot.projects),
        active_count=snapshot.active_count,
        attention_count=snapshot.attention_required_count,
        project_cards=project_cards,
    )
