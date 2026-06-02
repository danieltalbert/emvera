"""
Exportable analytics report (CSV always; PDF when reportlab is installed).

Assembles the key numbers from the insight layers into a flat, tidy structure
that serializes cleanly to CSV, and — if the optional `reportlab` package is
present — a formatted PDF. PDF follows the project's gated-optional-dependency
pattern (like Plaid/Alpaca): the button is always there; without the package the
export endpoint explains how to enable it instead of erroring.
"""
from __future__ import annotations

import csv
import io

from . import insights
from . import product_analytics as pa
from . import experiments as exp_runtime


def report_sections(days: int = 30) -> list[dict]:
    """Build the report as a list of titled sections of (label, value) rows.

    One structure drives both CSV and PDF so they never disagree. Everything
    here is already-computed insight output — no new aggregation logic.
    """
    k = insights.kpis(days)
    peak = insights.peak_activity(days)
    sess = pa.sessionize(days)
    churn = pa.churn_model(days)
    traffic = insights.daily_traffic(days)

    overview = [
        ('Window (days)', days),
        ('Total page views', k['total_views']),
        ('Distinct visitors', k['distinct_visitors']),
        ('Signed-in visitors', k['signed_in_visitors']),
        ('Avg response (ms)', k['avg_response_ms']),
        ('Busiest hour', peak['busiest_hour']),
        ('Busiest day', peak['busiest_day']),
        ('Traffic trend', f"{traffic['trend_direction']} ({traffic['trend_per_day']}/day)"),
        ('Trend r²', traffic['r_squared']),
    ]
    sessions_rows = [
        ('Sessions', sess['sessions']),
        ('Avg pages / session', sess['avg_pages']),
        ('Avg duration (min)', sess['avg_duration_min']),
        ('Bounce rate', sess['bounce_rate']),
    ]
    top_rows = [(p['path'], f"{p['count']} views, {p['avg_dwell_s']}s avg")
                for p in insights.top_pages(days)]
    funnel_rows = [(s['label'], f"{s['count']} ({s['conversion_from_top']:.0%} of top)")
                   for s in pa.funnel(days)['steps']]

    sections = [
        {'title': 'Overview', 'rows': overview},
        {'title': 'Sessions', 'rows': sessions_rows},
        {'title': 'Top pages', 'rows': top_rows},
        {'title': 'Activation funnel', 'rows': funnel_rows},
    ]

    if churn.get('available'):
        r = churn['report']
        sections.append({'title': 'Churn model (held-out)', 'rows': [
            ('Churn rate', churn['churn_rate']),
            ('ROC-AUC', r['roc_auc']),
            ('Precision', r['precision']),
            ('Recall', r['recall']),
            ('F1', r['f1']),
            ('Top driver', churn['importances'][0]['feature'] if churn['importances'] else '—'),
        ]})

    exps = exp_runtime.all_results()
    if exps:
        rows = []
        for e in exps:
            verdict = 'significant' if e['significant'] else ('collecting' if not e['enough_data'] else 'not significant')
            rows.append((e['experiment'].name,
                         f"A {e['control']['rate']:.1%} vs B {e['variant']['rate']:.1%} "
                         f"| p={e['p_value']} | {verdict}"))
        sections.append({'title': 'A/B experiments', 'rows': rows})

    return sections


def report_csv(days: int = 30) -> str:
    """Serialize the report to CSV text (section, label, value per row)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Section', 'Metric', 'Value'])
    for sec in report_sections(days):
        for label, value in sec['rows']:
            writer.writerow([sec['title'], label, value])
    return buf.getvalue()


def pdf_available() -> bool:
    """True when reportlab is importable (enables the PDF export)."""
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


def build_pdf(days: int = 30) -> bytes:
    """Render the report to a PDF (requires reportlab). Raises RuntimeError if
    the package isn't installed — callers should check pdf_available() first."""
    if not pdf_available():
        raise RuntimeError('reportlab is not installed; cannot render PDF.')

    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title='Emvera Analytics Report')
    styles = getSampleStyleSheet()
    story = [Paragraph('Emvera — Analytics Report', styles['Title']),
             Paragraph(f'Last {days} days', styles['Normal']), Spacer(1, 0.25 * inch)]

    for sec in report_sections(days):
        story.append(Paragraph(sec['title'], styles['Heading2']))
        data = [['Metric', 'Value']] + [[str(a), str(b)] for a, b in sec['rows']]
        table = Table(data, colWidths=[2.6 * inch, 3.4 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B3A2D')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#C8DDD5')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F8F6')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.2 * inch))

    doc.build(story)
    return buf.getvalue()
