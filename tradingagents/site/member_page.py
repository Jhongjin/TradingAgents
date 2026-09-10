"""Member area (`/member`, `/mypage`): login/signup landing and the signed-in workspace.

Markup keeps every element id, ``data-member-*`` attribute and form name the
member JavaScript (``web_pages.MEMBER_PAGE_JS``) binds to; only the shell,
layout and styling moved to the shared design system.
"""

from __future__ import annotations

from .design_system import badge, h, icon, icon_tile, render_shell

MEMBER_CSS = """
/* ---- session gate / auth landing ---- */
.member-page .member-session-gate { padding: 48px 0; text-align: center; }
.member-page .member-session-gate h1 { font-size: 22px; margin-top: 8px; }
.member-page .member-session-meter { width: 220px; height: 4px; margin: 16px auto 0; border-radius: 999px; background: var(--line); overflow: hidden; }
.member-page .member-session-meter span { display: block; width: 40%; height: 100%; background: var(--accent); border-radius: 999px; animation: memberMeter 1.2s ease-in-out infinite alternate; }
@keyframes memberMeter { from { transform: translateX(-20%); } to { transform: translateX(220%); } }
@media (prefers-reduced-motion: reduce) { .member-page .member-session-meter span { animation: none; width: 100%; } }
.member-page .member-auth-landing { display: grid; grid-template-columns: minmax(0, 1fr) 460px; min-height: 640px; }
.member-page .member-auth-copy { padding: 48px 48px 40px; display: flex; flex-direction: column; }
.member-page .member-auth-copy h1 { font-size: 34px; color: #fff; margin-top: 14px; max-width: 560px; }
.member-page .member-auth-lead { margin-top: 12px; max-width: 520px; font-size: 15px; color: rgba(255,255,255,.78); }
.member-page .member-auth-points { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 28px; max-width: 600px; }
.member-page .member-auth-points article { display: grid; gap: 4px; font-size: 13px; color: #fff; }
.member-page .member-auth-points article > span { display: inline-flex; width: 28px; height: 28px; border-radius: 8px; background: rgba(255,255,255,.16); align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
.member-page .member-auth-points strong { font-weight: 700; }
.member-page .member-auth-points small { color: rgba(255,255,255,.72); font-size: 12px; }
.member-page .member-auth-preview { margin-top: auto; padding-top: 28px; font-size: 12px; color: rgba(255,255,255,.72); }
.member-page .auth-panel { padding: 48px 44px; display: flex; flex-direction: column; justify-content: center; background: var(--panel); }
.member-page .auth-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.member-page .auth-heading h2 { font-size: 22px; margin-top: 4px; }
.member-page .auth-form { display: grid; gap: 14px; margin-top: 22px; }
.member-page .auth-form label { display: grid; gap: 6px; font-size: 12px; color: var(--muted); }
.member-page .auth-form input { height: 44px; border: 1px solid var(--line-strong); border-radius: 9px; background: var(--panel); padding: 0 12px; color: var(--ink); font: inherit; width: 100%; }
.member-page .auth-form input:focus { outline: 2px solid var(--accent); outline-offset: 1px; border-color: var(--accent); }
.member-page .password-row { position: relative; display: block; }
.member-page .auth-form .password-toggle { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); height: 30px; padding: 0 10px; font-size: 11px; background: transparent; border: 1px solid var(--line); border-radius: 6px; color: var(--ink2); cursor: pointer; font-family: inherit; }
.member-page .button-row.auth-button-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.member-page .auth-button-row button { height: 46px; border-radius: 9px; font: inherit; font-size: 15px; font-weight: 600; cursor: pointer; border: 1px solid var(--line-strong); background: var(--panel); color: var(--ink); }
.member-page .auth-button-row button[data-auth-action="signin"], .member-page .auth-button-row button.auth-suggested { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.member-page .auth-button-row button.auth-suggested ~ button[data-auth-action="signin"] { background: var(--panel); color: var(--ink); border-color: var(--line-strong); }
.member-page .auth-form-note { font-size: 12px; color: var(--muted); margin: -8px 0 0; }
.member-page .auth-status { font-size: 13px; color: var(--ink2); background: var(--bg2); border-radius: 9px; padding: 10px 12px; }
.member-page .auth-status.member-error { color: var(--gain); background: var(--gain-soft); }
/* ---- workspace ---- */
.member-page .member-summary-band { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
.member-page .member-summary-band h1 { font-size: 24px; }
.member-page .member-workspace-lede { font-size: 13px; color: var(--ink2); margin-top: 4px; }
.member-page .member-side { display: grid; gap: 10px; width: min(100%, 380px); }
.member-page .member-signed-in { display: grid; gap: 10px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); box-shadow: var(--shadow); }
.member-page .member-signed-in-head { display: flex; align-items: center; gap: 10px; min-width: 0; }
.member-page .member-signed-in-id { display: grid; gap: 4px; min-width: 0; }
.member-page .member-signed-in-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; justify-self: start; }
.member-page .status-pill.is-admin { background: var(--violet-soft); color: var(--violet); }
.member-page .member-alert-card { display: grid; gap: 8px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); box-shadow: var(--shadow); }
.member-page .member-alert-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.member-page .member-alert-head strong { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 700; }
.member-page .member-alert-head svg { width: 14px; height: 14px; }
.member-page .member-alert-copy { margin: 0; font-size: 12px; color: var(--ink2); line-height: 1.6; }
.member-page .member-alert-steps { margin: 0; padding-left: 18px; display: grid; gap: 4px; font-size: 12px; color: var(--ink2); line-height: 1.6; }
.member-page .member-alert-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.member-page .member-alert-actions .btn, .member-page .member-alert-actions .ghost-button { height: 32px; display: inline-flex; align-items: center; white-space: nowrap; }
.member-page .member-alert-code { justify-self: start; font-size: 18px; letter-spacing: .12em; padding: 6px 12px; border: 1px dashed var(--line-strong); border-radius: 8px; font-variant-numeric: tabular-nums; }
.member-page .member-alert-msg { font-size: 12px; color: var(--ink2); line-height: 1.5; }
.member-page .member-alert-msg.is-error { color: var(--gain); }
.member-page .member-signed-in strong { font-weight: 700; font-size: 14px; overflow-wrap: anywhere; }
.member-page .member-signed-in small { font-size: 12px; color: var(--ink2); line-height: 1.5; }
.member-page .member-signed-in-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.member-page .member-signed-in-actions .ghost-button, .member-page .member-signed-in-actions .btn { height: 32px; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.member-page .member-signed-in-actions svg { display: inline-block; width: 14px; height: 14px; }
.member-page .member-signed-in small { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.member-page .portfolio-manage-form { margin-top: 2px; }
.member-page .member-sublist-label { margin-top: 4px; }
.member-page .member-tab-strip { display: flex; gap: 4px; padding: 4px; background: var(--bg2); border-radius: 10px; margin-top: 18px; width: fit-content; max-width: 100%; overflow-x: auto; }
.member-page .member-tab-strip a { padding: 7px 14px; font-size: 13px; font-weight: 500; color: var(--ink2); border-radius: 8px; white-space: nowrap; display: inline-flex; gap: 6px; align-items: center; }
.member-page .member-tab-strip a:hover { text-decoration: none; color: var(--ink); }
.member-page .member-tab-strip a.is-active, .member-page .member-tab-strip a[aria-selected="true"] { color: var(--ink); background: var(--panel); font-weight: 600; box-shadow: var(--shadow); }
.member-page .member-tab-strip a span { display: inline-flex; align-items: center; height: 18px; padding: 0 6px; border-radius: 999px; background: var(--bg2); font-size: 11px; font-weight: 600; color: var(--ink2); }
.member-page .member-tab-strip a.is-active span { background: var(--accent-soft); color: var(--accent-ink); }
.member-page .member-grid { display: grid; gap: 20px; margin-top: 20px; }
.member-page .member-panel { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow); padding: 18px; }
.member-page .panel-heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; padding-bottom: 14px; border-bottom: 1px solid var(--line); margin-bottom: 16px; }
.member-page .panel-heading h2 { font-size: 16px; }
.member-page .panel-copy { font-size: 13px; color: var(--ink2); margin-top: 2px; }
.member-page .eyebrow { font-size: 12px; font-weight: 500; color: var(--muted); }
.member-page .status-pill { display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 999px; font-size: 12px; font-weight: 600; background: var(--bg2); color: var(--ink2); white-space: nowrap; }
.member-page .status-pill.analysis-status-completed { background: var(--accent-soft); color: var(--accent-ink); }
.member-page .status-pill.analysis-status-running, .member-page .status-pill.analysis-status-queued { background: var(--blue-soft); color: var(--blue); }
.member-page .status-pill.analysis-status-failed { background: var(--gain-soft); color: var(--gain); }
/* home panel */
.member-page .member-overview-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.member-page .member-overview-strip article { display: grid; gap: 2px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--bg); }
.member-page .member-overview-strip span { font-size: 12px; color: var(--muted); }
.member-page .member-overview-strip strong { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.member-page .member-overview-strip small { font-size: 12px; color: var(--muted); }
.member-page .member-home-state-note { font-size: 13px; color: var(--ink2); margin-top: 12px; }
.member-page .member-primary-action { display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap; margin-top: 14px; padding: 18px 20px; border-radius: 12px; background: linear-gradient(135deg, #0f766e 0%, #115e59 60%, #134e4a 100%); color: #fff; }
.member-page .member-primary-action > div { display: grid; gap: 4px; }
.member-page .member-primary-action span { font-size: 12px; color: rgba(255,255,255,.72); }
.member-page .member-primary-action strong { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; }
.member-page .member-primary-action small { font-size: 13px; color: rgba(255,255,255,.8); max-width: 640px; }
.member-page .home-primary-link { height: 40px; padding: 0 18px; border-radius: 9px; border: 0; background: #fff; color: #115e59; font: inherit; font-size: 14px; font-weight: 700; cursor: pointer; white-space: nowrap; }
.member-page .member-home-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.member-page .member-home-card { display: grid; gap: 6px; padding: 14px; border-radius: 12px; background: var(--bg2); align-content: start; }
.member-page .member-home-card > span { display: inline-flex; width: 28px; height: 28px; border-radius: 8px; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; background: var(--blue-soft); color: var(--blue); }
.member-page .member-home-card:nth-child(2) > span { background: var(--amber-soft); color: var(--amber); }
.member-page .member-home-card:nth-child(3) > span { background: var(--violet-soft); color: var(--violet); }
.member-page .member-home-card.member-paper-card > span { background: var(--accent-soft); color: var(--accent-ink); }
.member-page .member-home-card strong { font-weight: 700; }
.member-page .member-home-card small { font-size: 12px; color: var(--ink2); }
.member-page .member-home-card .ghost-button { margin-top: 4px; justify-self: start; }
.member-page .member-home-links { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
.member-page .member-home-links a { display: inline-flex; align-items: center; height: 32px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--line-strong); font-size: 13px; font-weight: 600; background: var(--panel); }
.member-page .member-home-links a:hover { text-decoration: none; border-color: var(--accent); }
.member-page .member-admin-link { border-color: var(--navy) !important; color: var(--navy); }
/* forms */
.member-page .member-form-stack { display: grid; gap: 14px; }
.member-page .member-form-block { display: grid; gap: 6px; padding: 14px; border-radius: 12px; background: var(--bg2); }
.member-page .member-form-block > strong { font-weight: 700; font-size: 14px; }
.member-page .member-form-hint { font-size: 12px; color: var(--muted); }
.member-page .member-form { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.member-page .member-form input, .member-page .member-form select { height: 40px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--panel); padding: 0 10px; color: var(--ink); font: inherit; font-size: 13px; min-width: 0; flex: 1 1 140px; }
.member-page .member-form select option { color: var(--ink); background: var(--panel); }
.member-page .member-form input:focus, .member-page .member-form select:focus { outline: 2px solid var(--accent); outline-offset: 1px; border-color: var(--accent); }
.member-page .member-form button, .member-page .ghost-button { height: 36px; padding: 0 14px; border-radius: 8px; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid var(--line-strong); background: var(--panel); color: var(--ink); white-space: nowrap; }
.member-page .member-form button[type="submit"] { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.member-page .ghost-button:hover, .member-page .member-form button:hover { filter: brightness(.97); }
.member-page .member-form input:disabled, .member-page .member-form select:disabled, .member-page .member-form button:disabled, .member-page .member-action-item input:disabled, .member-page .member-action-item button:disabled, .member-page .watchlist-rename-form input:disabled, .member-page .watchlist-rename-form button:disabled { opacity: 0.6; cursor: not-allowed; }
.member-page .member-form.is-busy button[type="submit"], .member-page .member-action-item button[aria-busy="true"], .member-page .watchlist-rename-form button[aria-busy="true"] { opacity: 0.6; }
.member-page .compact-form input { flex: 1 1 200px; }
.member-page .trade-form input[name="price"], .member-page .trade-form input[name="quantity"], .member-page .trade-form input[name="fee"], .member-page .trade-form input[name="tax"] { flex: 1 1 90px; }
.member-page .target-form input[name="memo"], .member-page .analysis-request-form input[name="reason"] { flex: 2 1 220px; }
.member-page .member-request-hint { margin-bottom: 8px; }
.member-page .danger-button { color: var(--gain); border-color: var(--gain-soft); }
/* auth form overrides (declared after the generic member-form rules on purpose) */
.member-page .member-form.auth-form { display: grid; gap: 14px; margin-top: 22px; }
.member-page .auth-form label { width: 100%; }
.member-page .auth-form input { flex: none; width: 100%; height: 44px; font-size: 14px; }
.member-page .auth-form .auth-button-row button { height: 46px; font-size: 15px; }
.member-page .auth-form .password-toggle { height: 30px; font-size: 11px; padding: 0 10px; }
/* lists & cards generated by the member JS */
.member-page .member-list { display: grid; gap: 12px; margin-top: 16px; }
.member-page .member-item { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--bg); }
.member-page .member-item > strong { font-weight: 700; }
.member-page .member-item > small, .member-page .member-empty { font-size: 13px; color: var(--ink2); }
.member-page .member-card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.member-page .member-card-header > div { display: grid; gap: 2px; }
.member-page .member-card-header strong { font-weight: 700; font-size: 15px; }
.member-page .member-card-header small { font-size: 12px; color: var(--muted); }
.member-page .member-metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.member-page .member-metric-grid div { display: grid; gap: 2px; padding: 10px 12px; border-radius: 10px; background: var(--panel); border: 1px solid var(--line); }
.member-page .member-metric-grid small { font-size: 11px; color: var(--muted); }
.member-page .member-metric-grid strong { font-size: 16px; font-weight: 700; letter-spacing: -0.01em; font-variant-numeric: tabular-nums; }
.member-page .member-metric-grid span { font-size: 11px; color: var(--ink2); }
.member-page .member-sublist { margin: 0; padding: 0 0 0 16px; font-size: 13px; color: var(--ink2); display: grid; gap: 4px; }
.member-page .member-sublist-label { font-size: 12px; font-weight: 600; color: var(--muted); }
.member-page .member-action-list { display: grid; gap: 8px; }
.member-page .member-action-item { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 10px; background: var(--panel); border: 1px solid var(--line); }
.member-page .member-action-item strong, .member-page .member-action-item a { font-weight: 600; font-size: 13px; }
.member-page .member-action-item a { color: var(--accent-ink); }
.member-page .member-action-item small { font-size: 12px; color: var(--muted); flex: 1 1 140px; }
.member-page .member-action-item input { height: 34px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--panel); padding: 0 10px; color: var(--ink); font: inherit; font-size: 13px; flex: 2 1 160px; }
.member-page .member-action-item button { height: 32px; padding: 0 12px; font-size: 12px; }
.member-page .watchlist-rename-form { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.member-page .watchlist-rename-form label { font-size: 12px; color: var(--muted); display: flex; gap: 8px; align-items: center; flex: 1 1 240px; }
.member-page .watchlist-rename-form input { height: 34px; border: 1px solid var(--line-strong); border-radius: 8px; background: var(--panel); padding: 0 10px; color: var(--ink); font: inherit; font-size: 13px; flex: 1; }
.member-page .watchlist-rename-form button { height: 32px; padding: 0 12px; font-size: 12px; }
.member-page .member-status-strip { display: flex; flex-wrap: wrap; gap: 6px; }
.member-page .member-action-item.is-target-hit { border-left: 4px solid var(--gain); background: var(--gain-soft); }
.member-page .member-action-item.is-stop-hit { border-left: 4px solid var(--loss); background: var(--loss-soft); }
.member-page .status-pill.hit-target { background: var(--gain); color: #fff; }
.member-page .status-pill.hit-stop { background: var(--loss); color: #fff; }
.member-page .member-empty { padding: 12px 14px; border-radius: 10px; background: var(--bg2); }
.member-page .member-empty-action { display: grid; gap: 6px; padding: 18px; border-radius: 12px; background: var(--bg2); justify-items: start; }
.member-page .member-empty-action strong { font-weight: 700; }
.member-page .member-empty-action small { font-size: 13px; color: var(--ink2); }
.member-page .member-error { color: var(--gain); }
.member-page .analysis-queue-overview { display: grid; gap: 10px; padding: 14px; border-radius: 12px; background: var(--bg2); margin-bottom: 12px; }
.member-page .analysis-queue-meters { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.member-page .analysis-queue-meters div { display: grid; gap: 2px; padding: 10px 12px; border-radius: 10px; background: var(--panel); border: 1px solid var(--line); }
.member-page .analysis-queue-meters small, .member-page .analysis-queue-meters span { font-size: 11px; color: var(--muted); }
.member-page .analysis-queue-meters strong { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.member-page .analysis-queue-note { font-size: 12px; color: var(--ink2); }
.member-page .analysis-request-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.member-page .analysis-request-header > div { display: grid; gap: 2px; }
.member-page .analysis-request-header strong { font-weight: 700; }
.member-page .analysis-request-header small { font-size: 12px; color: var(--muted); }
.member-page .analysis-request-hint { font-size: 13px; color: var(--ink2); }
.member-page .analysis-request-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.member-page .member-inline-link { text-decoration: none; display: inline-flex; align-items: center; }
.member-page .paper-simulation-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; list-style: none; margin: 0 0 12px; padding: 0; }
.member-page .paper-simulation-flow li { display: grid; gap: 2px; padding: 12px; border-radius: 10px; background: var(--bg2); }
.member-page .paper-simulation-flow span { font-size: 11px; font-weight: 700; color: var(--accent-ink); }
.member-page .paper-simulation-flow strong { font-weight: 700; }
.member-page .paper-simulation-flow small { font-size: 12px; color: var(--muted); }
.member-page .paper-simulation-overview { border-color: var(--accent); }
.member-page .paper-learning-note { display: grid; gap: 4px; padding: 12px 14px; border-radius: 10px; background: var(--accent-soft); color: var(--accent-ink); font-size: 13px; }
.member-page .paper-learning-note span { font-size: 11px; font-weight: 700; }
.member-page .paper-learning-buckets { display: flex; flex-wrap: wrap; gap: 6px; }
.member-page .paper-learning-buckets span { display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 999px; background: var(--bg2); color: var(--ink2); font-size: 12px; font-weight: 600; }
.member-page .paper-event-section { display: grid; gap: 10px; }
.member-page .paper-event-section-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.member-page .paper-event-section-heading strong { font-weight: 700; }
.member-page .paper-event-section-heading small { font-size: 12px; color: var(--muted); }
.member-page .decision-box { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 12px; border-radius: 10px; background: var(--bg2); }
@media (max-width: 960px) { .member-page .member-side { width: 100%; } }
@media (max-width: 960px) {
  .member-page .member-auth-landing { grid-template-columns: 1fr; }
  .member-page .member-auth-copy { padding: 32px 24px; }
  .member-page .member-auth-copy h1 { font-size: 26px; }
  .member-page .member-auth-points { grid-template-columns: 1fr; }
  .member-page .auth-panel { padding: 28px 24px; }
  .member-page .member-overview-strip, .member-page .member-home-grid, .member-page .member-metric-grid, .member-page .paper-simulation-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .member-page .analysis-queue-meters { grid-template-columns: 1fr; }
}
"""


AUTH_ENTER_JS = """
(function(){
  var form = document.getElementById('authForm');
  if(!form) return;
  form.addEventListener('keydown', function(event){
    if(event.key !== 'Enter' || event.isComposing) return;
    var target = event.target;
    if(!(target && target.tagName === 'INPUT')) return;
    event.preventDefault();
    var button = form.querySelector('button.auth-suggested') || form.querySelector('button[data-auth-action="signin"]');
    if(button && !button.disabled) button.click();
  });
})();
"""


def render_member_dashboard_page(*, site_base_url: str | None = None, canonical_path: str = "/member") -> str:
    """Render the authenticated member dashboard shell (login landing + workspace)."""

    from .web_pages import MEMBER_PAGE_JS, _public_supabase_config, _script_json

    config_json = _script_json(_public_supabase_config())
    body = f"""
<section class="member-session-gate" id="memberSessionGate" aria-live="polite" aria-label="회원 세션 확인">
  <div class="shell">
    {badge("세션 확인", "b-grey", icon_name="clock")}
    <h1 id="memberSessionTitle">세션을 확인하고 있습니다</h1>
    <p class="small ink2" id="memberSessionMessage" style="margin-top: 6px;">로그인 상태가 남아 있으면 바로 마이페이지로 이동하고, 없으면 로그인/가입 화면을 엽니다.</p>
    <div class="member-session-meter" aria-hidden="true"><span></span></div>
  </div>
</section>

<section class="member-auth-landing" id="memberAuthLanding" aria-labelledby="member-auth-title">
  <div class="member-auth-copy grad">
    <div>{badge("회원 전용 공간 · 조회 전용", "b-grey").replace('class="badge b-grey"', 'class="badge" style="background: rgba(255,255,255,.16); color: #fff;"')}</div>
    <h1 id="member-auth-title">나만의 AI 리서치 공간을 시작하세요</h1>
    <p class="member-auth-lead">매매 일지, 관심그룹, AI 분석 요청, 모의매매 복기를 마이페이지에서 한곳에 모아 봅니다.</p>
    <div class="member-auth-points" aria-label="회원 영역 원칙">
      <article><span>01</span><strong>주문 없음 원칙</strong><small>실거래 주문 기능은 차단하고 기록과 조회 흐름만 제공합니다.</small></article>
      <article><span>02</span><strong>공식 출처 기준</strong><small>KRX, DART, 공개 뉴스 흐름을 분리해 분석 근거를 남깁니다.</small></article>
      <article><span>03</span><strong>마이페이지</strong><small>로그인한 사용자에게만 저장 기록과 분석 요청 상태를 보여줍니다.</small></article>
    </div>
    <p class="member-auth-preview">가입 즉시 무료 플랜으로 전일 종목 선별과 토론 발췌를 볼 수 있고, 14일 체험으로 당일 전문까지 열립니다.</p>
  </div>
  <section class="member-panel auth-panel" aria-labelledby="auth-panel-title">
    <div class="auth-heading">
      <div><p class="eyebrow">보안 로그인</p><h2 id="auth-panel-title">로그인 / 가입</h2></div>
      <span class="status-pill">조회 전용</span>
    </div>
    <form class="member-form auth-form" id="authForm">
      <label><span>이메일</span><input name="email" type="email" autocomplete="email" placeholder="name@example.com" required></label>
      <label><span>비밀번호</span><span class="password-row"><input name="password" type="password" autocomplete="current-password" required><button class="ghost-button password-toggle" id="passwordToggle" type="button" aria-pressed="false" aria-label="비밀번호 표시">비밀번호 표시</button></span></label>
      <div class="button-row auth-button-row" aria-label="인증 작업">
        <button type="button" data-auth-action="signin">로그인</button>
        <button type="button" data-auth-action="signup">가입하기</button>
      </div>
      <p class="auth-form-note">처음이라면 가입하기로 마이페이지를 열 수 있습니다.</p>
      <div class="member-empty auth-status" id="authStatus" role="status" aria-live="polite">마이페이지 진입을 위해 인증이 필요합니다.</div>
    </form>
    <p class="tiny muted" style="margin-top: 16px;">계속하면 <a class="link" href="/terms">이용약관</a>과 <a class="link" href="/privacy">개인정보 처리방침</a>에 동의하게 됩니다. AI 의견은 연구 자료이며 투자 판단의 책임은 이용자에게 있습니다.</p>
  </section>
</section>

<section class="member-workspace" id="memberWorkspace" hidden>
  <div class="hero" style="padding: 26px 0 18px;">
    <div class="shell">
      <section class="member-summary-band" aria-labelledby="member-title">
        <div>
          <p class="eyebrow">회원 공간</p>
          <h1 id="member-title">마이페이지</h1>
          <p class="small ink2" id="memberStatus" style="margin-top: 4px;">로그인 상태 확인 중</p>
          <p class="member-workspace-lede">오늘의 선정 종목을 보고, 기록과 요청을 이어갑니다.</p>
        </div>
        <div class="member-side">
          <div class="member-signed-in" id="memberSignedIn" hidden>
            <div class="member-signed-in-head">
              <span class="avatar" style="background: var(--accent); color: var(--on-accent);">M</span>
              <div class="member-signed-in-id"><strong id="memberSignedInUser">회원 세션</strong><span class="member-signed-in-tags"><span class="status-pill" id="memberSignedInState">대시보드 확인 중</span><span class="status-pill is-admin" data-admin-only hidden>관리자</span></span></div>
            </div>
            <small id="memberSignedInMeta">대시보드를 불러오고 있습니다.</small>
            <div class="member-signed-in-actions"><a class="btn sm" href="/billing">구독 관리</a><a class="btn sm" href="/admin/members" data-admin-only hidden>회원 관리</a><button class="ghost-button" id="signOutButton" type="button">{icon("logout", 14)} 로그아웃</button></div>
          </div>
          <div class="member-alert-card" id="memberTelegramCard" hidden>
            <div class="member-alert-head"><strong>{icon("send", 14)} 텔레그램 알림</strong><span class="status-pill" id="memberTelegramState">확인 중</span></div>
            <p class="member-alert-copy">등록한 목표가·손절가에 도달하면 바로 알려드립니다. 아침 종목 선별 발행 알림도 같은 채널로 받습니다.</p>
            <ol class="member-alert-steps">
              <li>아래 <b>연결 코드 받기</b>를 누릅니다.</li>
              <li><b>텔레그램에서 열기</b>로 봇을 연 뒤 시작을 누르거나 코드를 보냅니다.</li>
              <li>연결 완료 표시가 뜨면 끝입니다. 코드는 30분간 유효합니다.</li>
            </ol>
            <div class="member-alert-actions">
              <button class="btn primary sm" id="memberTelegramLink" type="button">연결 코드 받기</button>
              <a class="btn sm" id="memberTelegramOpen" href="#" target="_blank" rel="noopener" hidden>텔레그램에서 열기</a>
              <button class="ghost-button" id="memberTelegramUnlink" type="button" hidden>연결 해제</button>
            </div>
            <span class="member-alert-code" id="memberTelegramCode" hidden>------</span>
            <small class="member-alert-msg" id="memberTelegramMsg">가입 후 한 번만 연결하면 됩니다.</small>
          </div>
          <div class="decision-box"><span class="badge b-grey">{icon("shield", 12)}실계좌 주문 없음</span><span class="tiny muted">조회·기록 전용 공간입니다.</span></div>
        </div>
      </section>
      <nav class="member-tab-strip" role="tablist" aria-label="마이페이지 섹션">
        <a id="home-tab" class="is-active" href="#member-home-section" role="tab" data-member-tab="home" aria-controls="member-home-section" aria-selected="true">홈 <span id="memberHomeStatus">준비됨</span></a>
        <a id="portfolio-tab" href="#portfolio-section" role="tab" data-member-tab="portfolio" aria-controls="portfolio-section" aria-selected="false">매매 일지 <span id="portfolioTabCount">0</span></a>
        <a id="watchlist-tab" href="#watchlist-section" role="tab" data-member-tab="watchlist" aria-controls="watchlist-section" aria-selected="false">관심그룹 <span id="watchlistTabCount">0</span></a>
        <a id="analysis-tab" href="#analysis-request-section" role="tab" data-member-tab="analysis" aria-controls="analysis-request-section" aria-selected="false">분석 요청 <span id="analysisTabCount">0</span></a>
        <a id="paper-simulation-tab" href="#paper-simulation-section" role="tab" data-member-tab="paper" aria-controls="paper-simulation-section" aria-selected="false">AI 가상매매 <span id="paperSimulationTabCount">0</span></a>
        <a id="billing-link" href="/billing" data-member-link="billing" aria-label="구독 관리로 이동">구독 관리 <span id="memberPlanBadge">플랜 확인 중</span></a>
        <a id="admin-members-link" href="/admin/members" data-member-link="admin" data-admin-only hidden aria-label="회원 관리로 이동">회원 관리 <span>운영</span></a>
      </nav>
    </div>
  </div>
  <script>
  (function(){{
    var key='tradingagents.member.access_token';
    var token='';try{{token=localStorage.getItem(key)||sessionStorage.getItem(key)||'';}}catch(e){{}}
    var badge=document.getElementById('memberPlanBadge');
    if(!badge)return;
    if(!token){{badge.textContent='무료';return;}}
    fetch('/api/billing/me',{{headers:{{'Authorization':'Bearer '+token}}}}).then(function(r){{return r.ok?r.json():null}}).then(function(d){{
      if(!d||!d.access){{badge.textContent='무료';return;}}
      var s=d.access.status;var name=d.access.plan.name;
      var label=s==='trialing'?name+' 체험':(s==='active'?name:'무료');
      badge.textContent=d.is_admin?('관리자 · '+label):label;
      if(d.is_admin){{document.querySelectorAll('[data-admin-only]').forEach(function(n){{n.hidden=false;}});}}
    }}).catch(function(){{badge.textContent='무료';}});
  }})();
  </script>

  <div class="shell">
  <section class="member-grid" aria-label="회원 기능">
    <section class="member-panel member-home-panel" id="member-home-section" role="tabpanel" data-member-panel="home" aria-labelledby="home-tab">
      <div class="panel-heading">
        <div><p class="eyebrow">마이페이지</p><h2>홈</h2><p class="panel-copy">오늘 이어갈 항목입니다.</p></div>
        <span class="status-pill">조회/기록 전용</span>
      </div>
      <section class="member-overview-strip" id="memberOverview" aria-label="마이페이지 요약">
        <article><span>매매 일지</span><strong id="memberOverviewPortfolios">0</strong><small>일지</small></article>
        <article><span>관심그룹</span><strong id="memberOverviewWatchlists">0</strong><small>종목 목록</small></article>
        <article><span>대기 중 요청</span><strong id="memberOverviewActiveRequests">0</strong><small>대기/처리 중</small></article>
        <article><span>리포트</span><strong id="memberOverviewCompletedReports">0</strong><small>완료 리포트</small></article>
        <article><span>AI 가상매매</span><strong id="memberOverviewPaperSimulations">0</strong><small>가상매매 기록</small></article>
      </section>
      <p class="member-home-state-note" id="memberHomeStateNote" aria-live="polite">저장된 항목을 불러오고 있습니다.</p>
      <section class="member-primary-action" id="memberPrimaryAction" data-member-primary-action="portfolio" aria-live="polite">
        <div>
          <span>다음 작업</span>
          <strong id="memberPrimaryActionTitle">첫 매매 일지를 만들어 보세요</strong>
          <small id="memberPrimaryActionCopy">실제 계좌 주문과 연결되지 않는 조회 전용 기록 공간입니다. 평단, 목표가, 손절선을 직접 남겨 투자 시나리오를 점검하세요.</small>
        </div>
        <button class="home-primary-link" type="button" id="memberPrimaryActionButton" data-member-jump="portfolio">매매 일지 시작</button>
      </section>
      <div class="member-home-grid" aria-label="다음 작업">
        <article class="member-home-card"><span>01</span><strong>매매 일지</strong><small>평단, 수수료, 목표가를 직접 남깁니다.</small><button class="ghost-button" type="button" data-member-jump="portfolio">일지 쓰기</button></article>
        <article class="member-home-card"><span>02</span><strong>관심그룹</strong><small>자주 보는 종목을 그룹으로 묶습니다.</small><button class="ghost-button" type="button" data-member-jump="watchlist">그룹 만들기</button></article>
        <article class="member-home-card"><span>03</span><strong>분석 요청</strong><small>요청 가능 횟수와 진행 상태를 확인합니다.</small><button class="ghost-button" type="button" data-member-jump="analysis">요청하기</button></article>
        <article class="member-home-card member-paper-card"><span>04</span><strong>AI 가상매매</strong><small>AI의 가상 매수·매도 기록을 봅니다.</small><button class="ghost-button" type="button" data-member-jump="paper">가상매매 보기</button></article>
      </div>
      <div class="member-home-links" aria-label="보조 이동">
        <a class="member-report-link" href="/harness">오늘의 선별 기록</a>
        <a class="member-report-link" href="/analyses">AI 리포트 보기</a>
        <a class="member-report-link" href="/outcomes">검증 결과 보기</a>
        <a class="member-report-link" href="/billing">구독 관리</a>
        <a class="member-admin-link" href="/admin" data-admin-only hidden>운영 콘솔</a>
        <a class="member-admin-link" href="/admin/members" data-admin-only hidden>회원 관리</a>
      </div>
    </section>

    <section class="member-panel" id="portfolio-section" role="tabpanel" data-member-panel="portfolio" aria-labelledby="portfolio-tab" hidden>
      <div class="panel-heading">
        <div><p class="eyebrow">매매 일지</p><h2>매매 일지</h2><p class="panel-copy">종목, 단가, 수량, 목표가를 직접 기록합니다.</p></div>
        <button class="ghost-button" id="refreshMemberData" type="button">새로고침</button>
      </div>
      <div class="member-form-stack">
        <div class="member-form-block">
          <strong>새 매매 일지</strong>
          <small class="member-form-hint">먼저 일지 이름을 만듭니다.</small>
          <form class="member-form compact-form" id="portfolioForm">
            <input name="name" maxlength="80" placeholder="예: 장기 관심주" aria-label="매매 일지 이름" required>
            <button type="submit">추가</button>
          </form>
        </div>
        <div class="member-form-block">
          <strong>매수/매도 기록</strong>
          <small class="member-form-hint">종목명이나 6자리 코드, 날짜, 단가, 수량을 입력하면 평균단가와 손익을 계산합니다.</small>
          <form class="member-form trade-form" id="tradeForm">
            <select name="portfolio_id" aria-label="매매 일지 선택" required></select>
            <input name="ticker_code" list="memberTickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" aria-label="종목코드 또는 종목명" autocomplete="off" data-member-ticker-lookup required>
            <select name="side" aria-label="매수 또는 매도" required><option value="buy">매수</option><option value="sell">매도</option></select>
            <input name="trade_date" type="date" aria-label="거래일" required>
            <input name="price" type="number" min="1" step="1" placeholder="단가" aria-label="거래 단가" inputmode="numeric" required>
            <input name="quantity" type="number" min="1" step="1" placeholder="수량" aria-label="거래 수량" inputmode="numeric" required>
            <input name="fee" type="number" min="0" step="1" placeholder="수수료" aria-label="수수료" inputmode="numeric">
            <input name="tax" type="number" min="0" step="1" placeholder="세금" aria-label="세금" inputmode="numeric">
            <button type="submit">기록</button>
          </form>
        </div>
        <div class="member-form-block">
          <strong>목표/손절 메모</strong>
          <small class="member-form-hint">목표가와 손절가는 주문으로 연결되지 않는 개인 메모입니다.</small>
          <form class="member-form target-form" id="targetForm">
            <select name="portfolio_id" aria-label="매매 일지 선택" required></select>
            <input name="ticker_code" list="memberTickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" aria-label="종목코드 또는 종목명" autocomplete="off" data-member-ticker-lookup required>
            <input name="target_price" type="number" min="1" step="1" placeholder="목표가" aria-label="목표가" inputmode="numeric">
            <input name="stop_price" type="number" min="1" step="1" placeholder="손절가" aria-label="손절가" inputmode="numeric">
            <input name="memo" maxlength="500" placeholder="목표 메모" aria-label="목표 메모">
            <button type="submit">저장</button>
          </form>
        </div>
      </div>
      <div class="member-list" id="portfolioList"></div>
    </section>

    <section class="member-panel" id="watchlist-section" role="tabpanel" data-member-panel="watchlist" aria-labelledby="watchlist-tab" hidden>
      <div class="panel-heading">
        <div><p class="eyebrow">관심그룹</p><h2>관심그룹</h2></div>
        <span class="status-pill">KR</span>
      </div>
      <div class="member-form-stack">
        <div class="member-form-block">
          <strong>새 관심그룹</strong>
          <small class="member-form-hint">예: 반도체, 2차전지처럼 자주 보는 종목을 묶습니다.</small>
          <form class="member-form compact-form" id="watchlistForm">
            <input name="name" maxlength="80" placeholder="예: 반도체 관심그룹" aria-label="관심그룹 이름" required>
            <button type="submit">그룹 만들기</button>
          </form>
        </div>
        <div class="member-form-block">
          <strong>종목 담기</strong>
          <small class="member-form-hint">종목명이나 6자리 코드와 메모를 남기면 목록에서 현재가 상태를 함께 확인합니다.</small>
          <form class="member-form compact-form" id="watchlistItemForm">
            <select name="watchlist_id" aria-label="관심그룹 선택" required></select>
            <input name="ticker_code" list="memberTickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" aria-label="종목코드 또는 종목명" autocomplete="off" data-member-ticker-lookup required>
            <input name="memo" maxlength="500" placeholder="메모" aria-label="관심그룹 종목 메모">
            <button type="submit">종목 담기</button>
          </form>
        </div>
      </div>
      <div class="member-list" id="watchlistList"></div>
    </section>

    <section class="member-panel" id="analysis-request-section" role="tabpanel" data-member-panel="analysis" aria-labelledby="analysis-tab" hidden>
      <div class="panel-heading">
        <div><p class="eyebrow">분석 요청</p><h2>새 분석 요청</h2><p class="panel-copy">요청 상태, 가능 횟수, 완료 리포트를 확인합니다.</p></div>
        <span class="status-pill">요청 대기열</span>
      </div>
      <p class="member-form-hint member-request-hint">종목명이나 6자리 코드만 입력하면 최근 기준일로 요청합니다. 특정 날짜로 보고 싶을 때만 날짜를 선택하세요.</p>
      <form class="member-form analysis-request-form" id="analysisRequestForm">
        <select name="watchlist_ticker" id="analysisWatchlistTickerSelect" aria-label="관심그룹 종목 선택"></select>
        <input name="ticker" list="memberTickerSuggestions" maxlength="80" placeholder="005930 또는 삼성전자" aria-label="분석 요청 종목코드 또는 종목명" autocomplete="off" data-member-ticker-lookup required>
        <input name="requested_trade_date" type="date" aria-label="분석 기준일">
        <input name="reason" maxlength="500" placeholder="궁금한 점 메모" aria-label="요청 메모">
        <button type="submit">요청</button>
      </form>
      <div class="member-list" id="analysisRequestList"></div>
    </section>

    <section class="member-panel" id="paper-simulation-section" role="tabpanel" data-member-panel="paper" aria-labelledby="paper-simulation-tab" hidden>
      <div class="panel-heading">
        <div><p class="eyebrow">AI 가상매매</p><h2>가상매매 기록</h2><p class="panel-copy">완료된 AI 리포트 기준으로 모의 매수·매도 기록을 보여줍니다.</p></div>
        <span class="status-pill">주문 없음</span>
      </div>
      <ol class="paper-simulation-flow" aria-label="AI 가상매매 흐름">
        <li><span>01</span><strong>리포트</strong><small>AI 의견 저장</small></li>
        <li><span>02</span><strong>매수</strong><small>모의 매수 기록</small></li>
        <li><span>03</span><strong>평가</strong><small>보유·청산 추적</small></li>
        <li><span>04</span><strong>복기</strong><small>승률과 손익 확인</small></li>
      </ol>
      <div class="member-list" id="paperSimulationList"></div>
    </section>
  </section>
  </div>
</section>
<datalist id="memberTickerSuggestions"></datalist>
<script id="member-config" type="application/json">{config_json}</script>
"""
    return render_shell(
        title="회원 대시보드 | TradingAgents Korea",
        description="매매 일지, 관심그룹, 한국 주식 분석 요청, AI 가상매매 기록을 관리합니다.",
        body=body,
        active=None,
        canonical_path=canonical_path,
        site_base_url=site_base_url,
        noindex=True,
        extra_css=MEMBER_CSS,
        extra_js=MEMBER_PAGE_JS + AUTH_ENTER_JS,
        body_class="member-page is-member-checking",
    )
