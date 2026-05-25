import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

from config import EMAIL_TO, EMAIL_USER, EMAIL_PASSWORD, SMTP_SERVER, SMTP_PORT
from logger import log


def _price_table(records):
    rows = ''
    for r in records:
        if r.get('status') != 'ok':
            continue
        cambio = r.get('cambio_vs_ayer', '')
        if 'up' in cambio or cambio.startswith('up'):
            color = 'red'
        elif cambio.startswith('down') or 'down' in cambio:
            color = 'green'
        else:
            color = '#555'
        cambio_html = '<span style="color:' + color + '">' + cambio + '</span>' if cambio else '-'
        rows += (
            '<tr>'
            '<td style="padding:8px;border:1px solid #ddd;">' + str(r['duracion_dias']) + ' dias</td>'
            '<td style="padding:8px;border:1px solid #ddd;">' + str(r['plan']) + '</td>'
            '<td style="padding:8px;border:1px solid #ddd;font-weight:bold;">$' + str(r['precio_cop']) + ' COP</td>'
            '<td style="padding:8px;border:1px solid #ddd;">' + str(r.get('descuento','')) + '</td>'
            '<td style="padding:8px;border:1px solid #ddd;">' + cambio_html + '</td>'
            '</tr>'
        )
    return rows


def send_report(records, changes):
    """Envia resumen ejecutivo diario."""
    if not EMAIL_USER or not EMAIL_PASSWORD:
        log.warning('EMAIL_USER / EMAIL_PASSWORD no configurados — omitiendo email')
        return

    fecha   = datetime.now().strftime('%Y-%m-%d')
    ok      = sum(1 for r in records if r.get('status') == 'ok')
    errors  = len(records) - ok
    status  = 'Sin errores' if errors == 0 else str(errors) + ' error(es)'
    
    changes_html = ''
    for c in changes:
        changes_html += '<li>' + c + '</li>'
    if not changes_html:
        changes_html = '<li>Sin cambios detectados hoy</li>'

    table_rows = _price_table(records)

    html = (
        '<html><body style="font-family:Arial,sans-serif;max-width:700px;">'
        '<div style="background:#1a365d;color:white;padding:16px;border-radius:6px 6px 0 0;">'
        '<h2 style="margin:0">Segurosfly Bot — ' + fecha + '</h2>'
        '<p style="margin:4px 0 0">Colombia -> Europa y Mediterraneo | ' + str(ok) + ' planes | ' + status + '</p>'
        '</div>'
        '<h3 style="color:#1a365d">Precios del dia</h3>'
        '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        '<tr style="background:#1a365d;color:white;">'
        '<th style="padding:8px">Duracion</th>'
        '<th style="padding:8px">Plan</th>'
        '<th style="padding:8px">Precio</th>'
        '<th style="padding:8px">Descuento</th>'
        '<th style="padding:8px">Cambio</th>'
        '</tr>'
        + table_rows +
        '</table>'
        '<h3 style="color:#1a365d">Cambios detectados</h3>'
        '<ul>' + changes_html + '</ul>'
        '<p style="color:#888;font-size:12px;margin-top:24px">'
        'Generado automaticamente por Segurosfly Bot via GitHub Actions'
        '</p>'
        '</body></html>'
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = '[Segurosfly Bot] Reporte ' + fecha + ' | ' + str(ok) + ' planes | ' + status
    msg['From']    = EMAIL_USER
    msg['To']      = EMAIL_TO
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as s:
            s.starttls()
            s.login(EMAIL_USER, EMAIL_PASSWORD)
            s.send_message(msg)
        log.info('Email enviado a ' + EMAIL_TO)
    except Exception as e:
        log.error('Error enviando email: ' + str(e))

