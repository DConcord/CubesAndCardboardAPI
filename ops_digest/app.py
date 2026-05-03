"""
Daily ops digest Lambda.

Queries CloudWatch Logs Insights for errors/warnings across all Lambda log groups,
then:
  - Any day: if errors found, sends a digest email with details.
  - Friday: if no errors, sends a brief "All clear" weekly summary.
  - Other days, no errors: sends nothing.

Schedule: daily at noon Mountain Time (EventBridge ScheduleV2,
ScheduleExpressionTimezone: America/Denver handles DST automatically).
"""

import os
import time
from datetime import datetime, timezone, timedelta

import boto3

MODE = os.environ["MODE"]
ALERT_EMAIL_PARAM = os.environ["ALERT_EMAIL_PARAM"]

# Lambda log groups to monitor
LOG_GROUPS = [
    f"/aws/lambda/manage_events_{MODE}",
    f"/aws/lambda/BggSearch_{MODE}",
    f"/aws/lambda/RetrieveBGGImage_{MODE}",
    f"/aws/lambda/rsvp_alerts_{MODE}",
]

FROM_DOMAIN = "mail.cubesandcardboard.net" if MODE == "prod" else "mail.dissonantconcord.com"
FROM_EMAIL = f"Ops Digest <alert@{FROM_DOMAIN}>"

_ssm = boto3.client("ssm", region_name="us-east-1")
_logs = boto3.client("logs", region_name="us-east-1")
_ses = boto3.client("sesv2", region_name="us-east-1")

# Read alert email at cold start
_alert_email = _ssm.get_parameter(Name=ALERT_EMAIL_PARAM)["Parameter"]["Value"]


def query_log_group(log_group, start_epoch_sec, end_epoch_sec):
    """Run a Logs Insights query on one log group. Returns list of matched lines."""
    query = (
        "fields @timestamp, @message"
        " | filter @message like /(?i)(ERROR|Exception|Traceback|Failed|WARN)/"
        " | sort @timestamp desc"
        " | limit 20"
    )
    try:
        response = _logs.start_query(
            logGroupName=log_group,
            startTime=start_epoch_sec,
            endTime=end_epoch_sec,
            queryString=query,
        )
    except _logs.exceptions.ResourceNotFoundException:
        # Log group doesn't exist yet (Lambda never invoked in this environment)
        return []

    query_id = response["queryId"]

    # Poll until complete (up to 30s)
    result = {}
    for _ in range(30):
        result = _logs.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled"):
            break
        time.sleep(1)

    if result.get("status") != "Complete":
        return []

    lines = []
    for record in result.get("results", []):
        ts = next((f["value"] for f in record if f["field"] == "@timestamp"), "")
        msg = next((f["value"] for f in record if f["field"] == "@message"), "")
        if msg.strip():
            lines.append(f"[{ts}] {msg.strip()}")
    return lines


def build_html_digest(findings, date_str):
    """Build an HTML email body for an error digest."""
    rows = ""
    for log_group, lines in findings.items():
        fn_name = log_group.split("/")[-1]
        count = len(lines)
        samples = "".join(
            f"<li><code style='word-break:break-all'>{line[:300]}</code></li>"
            for line in lines[:5]
        )
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;white-space:nowrap">{fn_name}</td>
          <td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{count}</td>
          <td style="padding:8px;border-bottom:1px solid #eee"><ul style="margin:0;padding-left:16px">{samples}</ul></td>
        </tr>"""

    total = sum(len(v) for v in findings.values())
    return f"""<html><body style="font-family:sans-serif;color:#333;max-width:820px;margin:0 auto;padding:16px">
<h2 style="color:#c0392b">&#9888; [{MODE}] Daily Ops Digest &mdash; {date_str}</h2>
<p>Errors/warnings detected in the last 24 hours ({total} total matches across {len(findings)} function(s)):</p>
<table style="border-collapse:collapse;width:100%">
  <thead>
    <tr style="background:#f5f5f5">
      <th style="padding:8px;text-align:left">Function</th>
      <th style="padding:8px;text-align:center">Count</th>
      <th style="padding:8px;text-align:left">Samples (up to 5, most recent first)</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>
<p style="color:#999;font-size:12px;margin-top:24px">
  Sent by OpsDigest_{MODE} &mdash; daily at noon MT &mdash; CloudWatch Logs Insights query window: last 24 hours
</p>
</body></html>"""


def build_html_allclear(date_str):
    """Build an HTML email body for the Friday weekly all-clear."""
    fn_list = "".join(f"<li>{lg.split('/')[-1]}</li>" for lg in LOG_GROUPS)
    return f"""<html><body style="font-family:sans-serif;color:#333;max-width:600px;margin:0 auto;padding:16px">
<h2 style="color:#27ae60">&#10003; [{MODE}] Weekly All Clear &mdash; {date_str}</h2>
<p>No errors or warnings detected in any Lambda log group in the past 24 hours.</p>
<p><strong>Functions monitored:</strong></p>
<ul>{fn_list}</ul>
<p style="color:#999;font-size:12px;margin-top:24px">
  Sent by OpsDigest_{MODE} &mdash; weekly summary (Fridays at noon MT)
</p>
</body></html>"""


def send_email(subject, html_body):
    _ses.send_email(
        FromEmailAddress=FROM_EMAIL,
        Destination={"ToAddresses": [_alert_email]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
            }
        },
    )


def lambda_handler(event, context):
    now = datetime.now(timezone.utc)
    end_sec = int(now.timestamp())
    start_sec = int((now - timedelta(hours=24)).timestamp())

    date_str = now.strftime("%Y-%m-%d")
    is_friday = now.weekday() == 4  # Monday=0, Friday=4

    # Query all log groups
    findings = {}
    for lg in LOG_GROUPS:
        lines = query_log_group(lg, start_sec, end_sec)
        if lines:
            findings[lg] = lines

    if findings:
        total = sum(len(v) for v in findings.values())
        subject = f"[{MODE}] Daily Ops Digest \u2014 {date_str} ({total} issue{'s' if total != 1 else ''})"
        html = build_html_digest(findings, date_str)
        send_email(subject, html)
        print(f"Sent error digest: {len(findings)} log group(s) with {total} total matches")
    elif is_friday:
        subject = f"[{MODE}] Weekly All Clear \u2014 {date_str}"
        html = build_html_allclear(date_str)
        send_email(subject, html)
        print("Sent weekly all-clear email")
    else:
        print(f"No errors found and today is not Friday — nothing to send")

    return {"statusCode": 200}
