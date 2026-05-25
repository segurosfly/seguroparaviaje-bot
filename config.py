import os
from datetime import datetime, timedelta

# Sitio
URL_HOME    = "https://segurosfly.com/es"
ORIGIN      = "Colombia"
DESTINATION = "Europa y Mediterraneo"
DURATIONS   = list(range(1, 31))  # 1 a 30 días

# Datos del formulario (obligatorios)
USER_NAME   = "Nirvia"
USER_EMAIL  = "Nirviagonza@hotmail.com"
USER_PHONE  = "3022500760"

# Google Sheets
SHEET_ID  = os.getenv("GOOGLE_SHEET_ID", "1-jBJ7c1cIHcwIplAHU1fH0ETZRm0GEdy7jvGewF5cKU")
SHEET_TAB = "Hoja 1"
COLUMNS   = [
      "fecha", "hora", "duracion_dias", "plan",
      "precio_cop", "descuento", "precio_original",
      "cambio_vs_ayer", "status", "screenshot"
]

# Email
EMAIL_TO       = "info@segurosfly.com"
SMTP_SERVER    = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT") or "587")
EMAIL_USER     = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")

# Paths
DIR_SCREENSHOTS = "screenshots"
DIR_DATA        = "data"
DIR_LOGS        = "logs"
CSV_FILE        = os.path.join(DIR_DATA, "historico.csv")

# Browser
HEADLESS = True
UA        = (
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36"
)

def get_trip_dates(duration_days):
      dep = datetime.now() + timedelta(days=1)
      ret = dep + timedelta(days=duration_days)
      return dep.strftime("%Y-%m-%d"), ret.strftime("%Y-%m-%d")
