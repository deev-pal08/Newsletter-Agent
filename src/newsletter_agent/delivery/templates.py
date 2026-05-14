"""Jinja2 HTML email template for the digest."""

from __future__ import annotations

from typing import TYPE_CHECKING

from jinja2 import Template

if TYPE_CHECKING:
    from newsletter_agent.models import Digest

DIGEST_TEMPLATE = Template("""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:20px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">

<!-- Header -->
<tr><td style="background:#1a1a2e;padding:24px 32px;">
  <h1 style="color:#ffffff;margin:0;font-size:22px;font-weight:600;">Security &amp; AI Intelligence Digest</h1>
  <p style="color:#a0a0b0;margin:8px 0 0;font-size:14px;">{{ date }} &middot; {{ total_fetched }} scanned &middot; {{ total_after_dedup }} new &middot; {{ article_count }} ranked</p>
</td></tr>

{% if critical %}
<!-- Critical -->
<tr><td style="padding:24px 32px 0;">
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr><td style="background:#dc2626;color:#ffffff;padding:6px 12px;border-radius:4px;font-size:13px;font-weight:600;letter-spacing:0.5px;">
    &#x1F6A8; CRITICAL &mdash; ACT NOW ({{ critical|length }})
  </td></tr>
  </table>
</td></tr>
{% for a in critical %}
<tr><td style="padding:12px 32px;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#fef2f2;border-left:4px solid #dc2626;border-radius:4px;padding:12px 16px;">
  <tr><td>
    <a href="{{ a.url }}" style="color:#1a1a2e;font-size:15px;font-weight:600;text-decoration:none;">{{ a.title }}</a>
    <p style="color:#6b7280;font-size:12px;margin:4px 0;">{{ a.source_name }}{% if a.published_at %} &middot; {{ a.published_at.strftime('%b %d') }}{% endif %}{% if a.score %} &middot; Score: {{ a.score }}{% endif %}</p>
    {% if a.ai_summary %}<p style="color:#374151;font-size:13px;margin:6px 0 0;">{{ a.ai_summary }}</p>{% endif %}
  </td></tr>
  </table>
</td></tr>
{% endfor %}
{% endif %}

{% if important %}
<!-- Important -->
<tr><td style="padding:24px 32px 0;">
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr><td style="background:#d97706;color:#ffffff;padding:6px 12px;border-radius:4px;font-size:13px;font-weight:600;letter-spacing:0.5px;">
    &#x26A0;&#xFE0F; IMPORTANT &mdash; READ THIS WEEK ({{ important|length }})
  </td></tr>
  </table>
</td></tr>
{% for a in important %}
<tr><td style="padding:12px 32px;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#fffbeb;border-left:4px solid #d97706;border-radius:4px;padding:12px 16px;">
  <tr><td>
    <a href="{{ a.url }}" style="color:#1a1a2e;font-size:15px;font-weight:600;text-decoration:none;">{{ a.title }}</a>
    <p style="color:#6b7280;font-size:12px;margin:4px 0;">{{ a.source_name }}{% if a.published_at %} &middot; {{ a.published_at.strftime('%b %d') }}{% endif %}{% if a.score %} &middot; Score: {{ a.score }}{% endif %}</p>
    {% if a.ai_summary %}<p style="color:#374151;font-size:13px;margin:6px 0 0;">{{ a.ai_summary }}</p>{% endif %}
  </td></tr>
  </table>
</td></tr>
{% endfor %}
{% endif %}

{% if interesting %}
<!-- Interesting -->
<tr><td style="padding:24px 32px 0;">
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr><td style="background:#2563eb;color:#ffffff;padding:6px 12px;border-radius:4px;font-size:13px;font-weight:600;letter-spacing:0.5px;">
    &#x1F4DA; INTERESTING &mdash; QUEUE FOR WEEKEND ({{ interesting|length }})
  </td></tr>
  </table>
</td></tr>
{% for a in interesting %}
<tr><td style="padding:8px 32px;">
  <a href="{{ a.url }}" style="color:#2563eb;font-size:14px;text-decoration:none;">{{ a.title }}</a>
  <span style="color:#9ca3af;font-size:12px;"> &mdash; {{ a.source_name }}</span>
  {% if a.ai_summary %}<p style="color:#6b7280;font-size:12px;margin:2px 0 0;">{{ a.ai_summary }}</p>{% endif %}
</td></tr>
{% endfor %}
{% endif %}

{% if reference %}
<!-- Reference -->
<tr><td style="padding:24px 32px 0;">
  <table width="100%" cellpadding="0" cellspacing="0">
  <tr><td style="background:#6b7280;color:#ffffff;padding:6px 12px;border-radius:4px;font-size:13px;font-weight:600;letter-spacing:0.5px;">
    &#x1F4C1; REFERENCE &mdash; SAVE FOR LATER ({{ reference|length }})
  </td></tr>
  </table>
</td></tr>
{% for a in reference %}
<tr><td style="padding:4px 32px;">
  <a href="{{ a.url }}" style="color:#6b7280;font-size:13px;text-decoration:none;">{{ a.title }}</a>
  <span style="color:#d1d5db;font-size:11px;"> &mdash; {{ a.source_name }}</span>
</td></tr>
{% endfor %}
{% endif %}

<!-- Footer -->
<tr><td style="padding:24px 32px;border-top:1px solid #e5e7eb;margin-top:16px;">
  <p style="color:#9ca3af;font-size:12px;margin:0;">
    Sources: {{ sources_used | join(', ') }}<br>
    Generated in {{ "%.1f"|format(generation_time) }}s &middot; Newsletter Agent v0.1.0
  </p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>
""")


def render_digest_html(digest: Digest) -> str:
    return DIGEST_TEMPLATE.render(
        date=digest.date.strftime("%B %d, %Y"),
        total_fetched=digest.total_fetched,
        total_after_dedup=digest.total_after_dedup,
        article_count=len(digest.articles),
        critical=digest.critical,
        important=digest.important,
        interesting=digest.interesting,
        reference=digest.reference,
        sources_used=digest.sources_used,
        generation_time=digest.generation_time_seconds,
    )
