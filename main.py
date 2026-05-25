import asyncio
import os
from datetime import datetime

from logger import log


def main():
    log.info('=' * 55)
    log.info('Segurosfly Bot - inicio')
    log.info('=' * 55)

    # 1. Scraping
    from scraper import run as scrape
    raw_plans = asyncio.run(scrape())

    if not raw_plans:
        log.error('Sin registros - abortando')
        return

    # 2. Convert to sheet-compatible records
    # COLUMNS: fecha, hora, duracion_dias, plan, precio_cop, descuento,
    #          precio_original, cambio_vs_ayer, status, screenshot
    now = datetime.now()
    records = []
    for p in raw_plans:
        record = {
            'fecha': now.strftime('%Y-%m-%d'),
            'hora': now.strftime('%H:%M:%S'),
            'duracion_dias': str(p.get('days', '')),
            'plan': p.get('plan', ''),
            'precio_cop': p.get('price', ''),
            'descuento': p.get('discount', ''),
            'precio_original': p.get('original_price', ''),
            'cambio_vs_ayer': '',
            'status': 'ok' if p.get('plan', 'ERROR') not in ('ERROR', 'NO_RESULTS') else 'error',
            'screenshot': '',
        }
        records.append(record)

    log.info(str(len(records)) + ' records converted for storage')

    # 3. Save to Sheets and CSV
    from sheets_writer import save_all
    save_all(records)

    log.info('=' * 55)
    log.info('Bot finalizado correctamente')
    log.info('=' * 55)


if __name__ == '__main__':
    main()
