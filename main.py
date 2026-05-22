import asyncio
import csv
import os
from datetime import datetime, timedelta

from config import CSV_FILE, COLUMNS
from logger import log


def load_yesterday(duration, plan):
    """Busca el precio de ayer para el mismo plan y duracion."""
    if not os.path.exists(CSV_FILE):
        return ''
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if (row.get('fecha') == yesterday
                        and str(row.get('duracion_dias')) == str(duration)
                        and row.get('plan') == plan):
                    return row.get('precio_cop', '')
    except Exception:
        pass
    return ''


def add_changes(records):
    """Agrega columna cambio_vs_ayer y construye lista de cambios."""
    changes = []
    for r in records:
        if r.get('status') != 'ok':
            continue
        ayer = load_yesterday(r['duracion_dias'], r['plan'])
        if not ayer:
            r['cambio_vs_ayer'] = 'NUEVO'
            continue
        try:
            hoy_val  = int(r['precio_cop'])
            ayer_val = int(ayer)
            diff = hoy_val - ayer_val
            pct  = round(diff / ayer_val * 100, 1)
            if diff == 0:
                r['cambio_vs_ayer'] = '='
            elif diff > 0:
                r['cambio_vs_ayer'] = 'up +' + str(pct) + '%'
                changes.append(
                    str(r['duracion_dias']) + 'd ' + r['plan'] + ': '
                    + '$' + str(ayer_val) + ' -> $' + str(hoy_val) + ' COP (up +' + str(pct) + '%)'
                )
            else:
                r['cambio_vs_ayer'] = 'down ' + str(pct) + '%'
                changes.append(
                    str(r['duracion_dias']) + 'd ' + r['plan'] + ': '
                    + '$' + str(ayer_val) + ' -> $' + str(hoy_val) + ' COP (down ' + str(pct) + '%)'
                )
        except (ValueError, ZeroDivisionError):
            r['cambio_vs_ayer'] = ''
    return records, changes


def main():
    log.info('=' * 55)
    log.info('SPV Intelligence Bot — inicio')
    log.info('=' * 55)

    # 1. Scraping
    from scraper import run as scrape
    records = asyncio.run(scrape())

    if not records:
        log.error('Sin registros — abortando')
        return

    # 2. Comparar con historico
    records, changes = add_changes(records)
    if changes:
        log.info(str(len(changes)) + ' cambio(s) detectado(s):')
        for c in changes:
            log.info('  ' + c)
    else:
        log.info('Sin cambios vs ayer')

    # 3. Guardar
    from sheets_writer import save_all
    save_all(records)

    # 4. Email
    from email_sender import send_report
    send_report(records, changes)

    log.info('=' * 55)
    log.info('Bot finalizado correctamente')
    log.info('=' * 55)


if __name__ == '__main__':
    main()

