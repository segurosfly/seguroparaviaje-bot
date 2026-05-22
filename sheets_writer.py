import csv
import json
import os
import gspread
from google.oauth2.service_account import Credentials

from config import SHEET_ID, SHEET_TAB, COLUMNS, CSV_FILE, DIR_DATA
from logger import log

os.makedirs(DIR_DATA, exist_ok=True)

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def _client():
    creds_raw = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
    if not creds_raw:
        raise EnvironmentError('Falta GOOGLE_SHEETS_CREDENTIALS en Secrets')
    info = json.loads(creds_raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def save_to_sheet(records):
    """Agrega filas al Sheet. Nunca sobrescribe el historico."""
    if not records or not SHEET_ID:
        log.warning('Sin registros o SHEET_ID vacio — omitiendo Sheets')
        return False
    try:
        ws = _client().open_by_key(SHEET_ID).worksheet(SHEET_TAB)
        # Crear encabezados si la hoja esta vacia
        existing = ws.row_values(1)
        if not existing or existing[0] != COLUMNS[0]:
            ws.append_row(COLUMNS)
        rows = [[str(r.get(c, '')) for c in COLUMNS] for r in records]
        ws.append_rows(rows, value_input_option='RAW')
        log.info(str(len(rows)) + ' filas guardadas en Google Sheets')
        return True
    except Exception as e:
        log.error('Error en Sheets: ' + str(e))
        return False


def save_to_csv(records):
    """Backup CSV acumulativo — nunca sobrescribe."""
    if not records:
        return False
    new_file = not os.path.exists(CSV_FILE)
    try:
        with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
            if new_file:
                w.writeheader()
            w.writerows(records)
        log.info('CSV guardado: ' + CSV_FILE)
        return True
    except Exception as e:
        log.error('Error en CSV: ' + str(e))
        return False


def save_all(records):
    """Guarda en Sheets Y CSV."""
    s = save_to_sheet(records)
    c = save_to_csv(records)
    return s, c

