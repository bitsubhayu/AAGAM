"""Email Templates for AAGAM Alert Notifications & Daily Summaries (PRD §6.12, §10.4)."""

from __future__ import annotations

from typing import Any, Dict, List


def format_lifecycle_email(
    alert_event: Dict[str, Any],
    lifecycle_state: str,
    location_name: str,
    previous_severity: str | None = None,
) -> tuple[str, str, str]:
    """Generates (subject, html_content, text_content) for an alert lifecycle transition."""
    hazard = alert_event.get("hazard", "extreme weather").replace("_", " ").title()
    severity = alert_event.get("severity_peak", "alert").upper()
    start_date = str(alert_event.get("start_date", ""))
    end_date = str(alert_event.get("end_date", ""))
    date_range = f"{start_date} to {end_date}" if start_date != end_date else start_date
    value_peak = alert_event.get("value_peak")
    value_str = f"{value_peak:.1f}" if value_peak is not None else "N/A"

    state_desc = {
        "new": "Newly Detected Threat",
        "upgraded": f"Severity Upgraded (Previous: {previous_severity.upper() if previous_severity else 'N/A'})",
        "downgraded": f"Severity Downgraded (Previous: {previous_severity.upper() if previous_severity else 'N/A'})",
        "cancelled": "Threat Cancelled (Forecast shifted prior to arrival)",
        "expired": "Threat Expired",
    }.get(lifecycle_state, lifecycle_state.capitalize())

    subject = f"[AAGAM {severity}] {hazard} for {location_name} — {state_desc}"

    text_content = f"""AAGAM WEATHER ALERT NOTIFICATION
----------------------------------------
Location: {location_name}
Hazard: {hazard}
Severity: {severity}
Status: {state_desc}
Valid Window: {date_range}
Peak Expected Value: {value_str}

Summary: An alert condition has been updated based on the latest 4-model ensemble blend (GFS, ECMWF-IFS, ICON, AIFS).

View active details and models on the dashboard:
https://aagam.vercel.app/alerts/events/{alert_event.get('id', '')}

----------------------------------------
Notice: AAGAM provides experimental AI-assimilated decision support, not an official IMD meteorological warning.
"""

    sev_color = {
        "ALERT": "#EF5B5B",
        "WATCH": "#F28C3D",
        "ADVISORY": "#F2C14E",
    }.get(severity, "#3FD0B4")

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0B1016; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #E7EDF3;">
  <div style="max-width: 580px; margin: 24px auto; background-color: #111922; border: 1px solid #1E2A37; border-radius: 8px; overflow: hidden;">
    <div style="padding: 20px 24px; border-bottom: 1px solid #1E2A37; background-color: #17212C;">
      <span style="font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: #3FD0B4; text-transform: uppercase;">AAGAM Notification</span>
      <h1 style="margin: 6px 0 0 0; font-size: 20px; color: #E7EDF3;">{hazard} in {location_name}</h1>
    </div>
    <div style="padding: 24px;">
      <div style="display: inline-block; padding: 4px 10px; border-radius: 4px; background-color: {sev_color}22; border: 1px solid {sev_color}66; color: {sev_color}; font-weight: 700; font-size: 12px; margin-bottom: 16px;">
        {severity} &bull; {state_desc}
      </div>
      <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 14px;">
        <tr>
          <td style="padding: 8px 0; color: #A3B0BD; width: 140px;">Valid Period:</td>
          <td style="padding: 8px 0; font-weight: 600;">{date_range}</td>
        </tr>
        <tr>
          <td style="padding: 8px 0; color: #A3B0BD;">Peak Intensity:</td>
          <td style="padding: 8px 0; font-weight: 600;">{value_str}</td>
        </tr>
      </table>
      <div style="margin: 24px 0 16px 0;">
        <a href="https://aagam.vercel.app/alerts/events/{alert_event.get('id', '')}" style="display: inline-block; background-color: #3FD0B4; color: #0B1016; font-weight: 600; padding: 10px 18px; border-radius: 6px; text-decoration: none; font-size: 13px;">View Event Details &rarr;</a>
      </div>
    </div>
    <div style="padding: 16px 24px; border-top: 1px solid #1E2A37; background-color: #0B1016; font-size: 11px; color: #70808F;">
      Decision support calibrated to IMD thresholds. Not an official IMD warning.
    </div>
  </div>
</body>
</html>
"""
    return subject, html_content, text_content


def format_daily_summary_email(
    user_email: str,
    date_str: str,
    active_events: List[Dict[str, Any]],
) -> tuple[str, str, str]:
    """Generates (subject, html_content, text_content) for a subscriber's daily briefing."""
    subject = f"[AAGAM Daily Briefing] Active Alerts for Your Locations — {date_str}"

    count = len(active_events)
    events_text_list = []
    for evt in active_events:
        h = evt.get("hazard", "").replace("_", " ").title()
        loc = evt.get("location_name", f"Loc #{evt.get('location_id')}")
        sev = evt.get("severity_peak", "alert").upper()
        events_text_list.append(f"- [{sev}] {h} at {loc} ({evt.get('start_date')} to {evt.get('end_date')})")

    events_summary_txt = "\n".join(events_text_list) if events_text_list else "No active severe weather alerts today."

    text_content = f"""AAGAM DAILY WEATHER BRIEFING — {date_str}
--------------------------------------------------
Recipient: {user_email}
Active severe weather alerts for your saved locations: {count}

{events_summary_txt}

View your interactive weather dashboard:
https://aagam.vercel.app/overview

--------------------------------------------------
Notice: AAGAM provides AI-assimilated multi-model guidance, not an official IMD warning.
"""

    rows_html = ""
    for evt in active_events:
        h = evt.get("hazard", "").replace("_", " ").title()
        loc = evt.get("location_name", f"Location #{evt.get('location_id')}")
        sev = evt.get("severity_peak", "alert").upper()
        sev_color = {"ALERT": "#EF5B5B", "WATCH": "#F28C3D", "ADVISORY": "#F2C14E"}.get(sev, "#3FD0B4")
        rows_html += f"""
        <tr style="border-bottom: 1px solid #1E2A37;">
          <td style="padding: 10px 0;"><span style="color: {sev_color}; font-weight: 700; font-size: 11px;">{sev}</span></td>
          <td style="padding: 10px 0; font-weight: 600;">{loc}</td>
          <td style="padding: 10px 0;">{h}</td>
          <td style="padding: 10px 0; color: #A3B0BD; font-size: 12px;">{evt.get('start_date')} &ndash; {evt.get('end_date')}</td>
        </tr>
        """

    if not rows_html:
        rows_html = '<tr><td colspan="4" style="padding: 16px 0; color: #A3B0BD;">No active weather alerts today for your saved locations.</td></tr>'

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0B1016; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #E7EDF3;">
  <div style="max-width: 600px; margin: 24px auto; background-color: #111922; border: 1px solid #1E2A37; border-radius: 8px; overflow: hidden;">
    <div style="padding: 20px 24px; border-bottom: 1px solid #1E2A37; background-color: #17212C;">
      <span style="font-size: 11px; font-weight: 700; letter-spacing: 0.05em; color: #3FD0B4; text-transform: uppercase;">AAGAM Daily Briefing</span>
      <h1 style="margin: 6px 0 0 0; font-size: 20px; color: #E7EDF3;">Active Weather Alerts &bull; {date_str}</h1>
    </div>
    <div style="padding: 24px;">
      <p style="margin-top: 0; color: #A3B0BD; font-size: 13px;">Showing active hazard events matching your subscription preferences:</p>
      <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
        <thead>
          <tr style="border-bottom: 1px solid #1E2A37; color: #70808F; font-size: 11px; text-transform: uppercase;">
            <th style="padding-bottom: 8px;">Severity</th>
            <th style="padding-bottom: 8px;">Location</th>
            <th style="padding-bottom: 8px;">Hazard</th>
            <th style="padding-bottom: 8px;">Dates</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
      <div style="margin: 28px 0 16px 0;">
        <a href="https://aagam.vercel.app/overview" style="display: inline-block; background-color: #3FD0B4; color: #0B1016; font-weight: 600; padding: 10px 18px; border-radius: 6px; text-decoration: none; font-size: 13px;">Open Forecast Explorer &rarr;</a>
      </div>
    </div>
    <div style="padding: 16px 24px; border-top: 1px solid #1E2A37; background-color: #0B1016; font-size: 11px; color: #70808F;">
      Decision support calibrated to IMD thresholds. Not an official IMD warning.
    </div>
  </div>
</body>
</html>
"""
    return subject, html_content, text_content
