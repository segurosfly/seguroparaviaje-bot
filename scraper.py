import asyncio
import random
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import URL_HOME, HEADLESS, UA, USER_EMAIL, USER_PHONE
from logger import log

# ── Configuración ────────────────────────────────────────────────────────────
RESULTS_URL_PATTERN = "**/cotizar/plans/**"

FORM_CONFIG = {
    "email": USER_EMAIL,
    "cel":   USER_PHONE,
}

MESES_ES = [
    'enero','febrero','marzo','abril','mayo','junio',
    'julio','agosto','septiembre','octubre','noviembre','diciembre'
]


# ── helpers ──────────────────────────────────────────────────────────────────

async def human_pause(page, lo=2000, hi=5000):
    await page.wait_for_timeout(random.randint(lo, hi))


def get_dates_10d():
    """
    Calcula siempre desde HOY:
      salida  = hoy + 1 día
      retorno = hoy + 11 días (10 días de viaje)
    """
    hoy     = datetime.now()
    salida  = hoy + timedelta(days=1)
    retorno = hoy + timedelta(days=11)
    return salida, retorno


# ── Pasos del formulario ──────────────────────────────────────────────────────

async def select_origin(page):
    log.info("  origen: verificando...")
    segments = page.locator(".sf-searchbar__segment")
    origen_txt = await segments.nth(1).inner_text()
    if "Colombia" in origen_txt:
        log.info("  origen -> Colombia ya seleccionado ✓")
        return True
    await segments.nth(1).click()
    await page.wait_for_timeout(1000)
    inp = page.locator(".react-select__input")
    await inp.fill("Colombia")
    await page.wait_for_timeout(800)
    option = page.locator(".react-select__option", has_text="Colombia")
    try:
        await option.first.click(timeout=8000)
        log.info("  origen -> Colombia ✓")
        return True
    except PWTimeout:
        log.error("  origen -> Colombia no encontrado")
        return False


async def select_destination(page):
    log.info("  destino: abriendo selector...")
    segments = page.locator(".sf-searchbar__segment")
    await segments.nth(2).click()
    await page.wait_for_timeout(1000)
    inp = page.locator(".react-select__input")
    await inp.fill("Europa")
    await page.wait_for_timeout(800)
    option = page.locator(".react-select__option", has_text="Europa y Mediterraneo")
    try:
        await option.first.click(timeout=8000)
        log.info("  destino -> Europa y Mediterraneo ✓")
        return True
    except PWTimeout:
        opts = await page.locator(".react-select__option").all()
        if opts:
            await opts[0].click()
            log.info("  destino -> opción fallback ✓")
            return True
        log.error("  destino -> ninguna opción encontrada")
        return False


async def _get_calendar_months(page):
    """
    Lee SOLO los títulos de mes dentro del contenedor del calendario.
    Evita leer todo el texto de la página.
    """
    # El calendario tiene un contenedor específico — buscar por clase
    for cal_selector in [
        ".sf-datepicker",
        ".sf-calendar",
        "[class*='datepicker']",
        "[class*='calendar-container']",
        "[class*='DayPicker']",
        "[class*='react-datepicker']",
    ]:
        try:
            cal = page.locator(cal_selector).first
            if await cal.is_visible(timeout=1000):
                # Leer títulos de mes dentro del contenedor
                titles = await cal.locator(
                    "[class*='month-title'], [class*='month-caption'], "
                    "[class*='caption'], [class*='header'] span, "
                    "h2, h3, [class*='Month']"
                ).all_inner_texts()
                if titles:
                    log.info(f"  calendario ({cal_selector}): títulos = {titles}")
                    return titles
        except Exception:
            continue

    # Fallback: buscar cualquier texto que parezca "Mes Año"
    all_texts = await page.locator(
        "[class*='month']:not(script):not(style)"
    ).all_inner_texts()
    mes_año = [t.strip() for t in all_texts if any(m in t.lower() for m in MESES_ES) and len(t.strip()) < 30]
    log.info(f"  calendario fallback títulos = {mes_año}")
    return mes_año


async def _mes_visible(titulos, target: datetime):
    """Verifica si el mes/año objetivo está en los títulos del calendario."""
    mes_es  = MESES_ES[target.month - 1]
    mes_en  = target.strftime('%B').lower()
    anio    = str(target.year)
    for t in titulos:
        t_lower = t.lower()
        if anio in t and (mes_es in t_lower or mes_en in t_lower):
            return True
    return False


async def _click_day_in_calendar(page, target: datetime):
    """
    Hace click en el día correcto dentro del calendario visible.
    Busca el número exacto solo dentro del contenedor del calendario.
    """
    dia = str(target.day)

    # Selectores del contenedor del calendario (de más específico a menos)
    cal_containers = [
        ".sf-datepicker",
        ".sf-calendar",
        "[class*='datepicker']",
        "[class*='DayPicker']",
        "[class*='react-datepicker']",
        "[class*='calendar']",
    ]

    for container_sel in cal_containers:
        try:
            container = page.locator(container_sel).first
            if not await container.is_visible(timeout=1000):
                continue

            # Buscar días dentro del contenedor
            day_selectors = [
                f"[class*='day']:not([class*='disabled']):not([class*='past']):not([class*='outside'])",
                "td:not([class*='disabled'])",
                "button:not([disabled])",
            ]

            for day_sel in day_selectors:
                dias = await container.locator(day_sel).all()
                for btn in dias:
                    try:
                        txt = (await btn.inner_text()).strip()
                        if txt != dia:
                            continue
                        cls = (await btn.get_attribute('class') or '').lower()
                        if any(x in cls for x in ['disabled', 'past', 'outside', 'prev', 'next', 'other']):
                            continue
                        await btn.click(timeout=3000)
                        log.info(f"  calendario: día {dia} clickeado en {container_sel} ✓")
                        return True
                    except Exception:
                        continue
        except Exception:
            continue

    # Fallback final: click directo por evaluate en shadow/cualquier DOM
    result = await page.evaluate(f"""(dia) => {{
        // Buscar todos los elementos que muestren solo el número del día
        const all = document.querySelectorAll('[class*="day"], td, [class*="Day"]');
        for (const el of all) {{
            const txt = el.innerText?.trim();
            if (txt !== dia) continue;
            const cls = el.className?.toLowerCase() || '';
            if (cls.includes('disabled') || cls.includes('past') || cls.includes('outside')) continue;
            el.click();
            return 'ok:' + el.className;
        }}
        return 'not-found';
    }}""", dia)
    log.info(f"  calendario: evaluate click día {dia} -> {result}")
    return result.startswith('ok')


async def _navigate_calendar_to_month(page, target: datetime):
    """Navega el calendario hasta que el mes objetivo sea visible."""
    for intento in range(6):
        titulos = await _get_calendar_months(page)
        if await _mes_visible(titulos, target):
            log.info(f"  calendario: mes {MESES_ES[target.month-1]} {target.year} visible ✓")
            return True

        log.info(f"  calendario: mes no visible aún, avanzando... (intento {intento+1})")

        # Botón "siguiente mes"
        for nav_sel in [
            ".sf-calendar__arrow--right",
            "[class*='next-month']",
            "[class*='nextMonth']",
            "button[aria-label*='next']",
            "button[aria-label*='siguiente']",
            "[class*='nav--next']",
            "[class*='navigation'] button:last-child",
        ]:
            try:
                btn = page.locator(nav_sel).first
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    await page.wait_for_timeout(700)
                    break
            except Exception:
                continue

    log.error(f"  calendario: no se llegó al mes {MESES_ES[target.month-1]} {target.year}")
    return False


async def set_dates(page, dep_dt: datetime, ret_dt: datetime):
    """
    Abre el selector de fechas y hace click en salida y retorno
    directamente en el calendario. Fechas calculadas dinámicamente.
    """
    log.info(f"  fechas: {dep_dt.date()} -> {ret_dt.date()} (10 días desde hoy)")

    # Abrir selector de fechas
    dates_seg = page.locator(".sf-searchbar__segment--dates")
    await dates_seg.click()
    await page.wait_for_timeout(1500)

    # Screenshot para ver el estado del calendario
    await page.screenshot(path="debug_calendar.png", full_page=False)

    # ── SALIDA ──────────────────────────────────────────────────────────
    log.info(f"  fechas: seleccionando salida {dep_dt.day}/{dep_dt.month}/{dep_dt.year}")
    await _navigate_calendar_to_month(page, dep_dt)
    ok_dep = await _click_day_in_calendar(page, dep_dt)
    if not ok_dep:
        log.error("  fechas: falló click en salida")
    await page.wait_for_timeout(800)

    # ── RETORNO ─────────────────────────────────────────────────────────
    log.info(f"  fechas: seleccionando retorno {ret_dt.day}/{ret_dt.month}/{ret_dt.year}")
    await _navigate_calendar_to_month(page, ret_dt)
    ok_ret = await _click_day_in_calendar(page, ret_dt)
    if not ok_ret:
        log.error("  fechas: falló click en retorno")
    await page.wait_for_timeout(600)

    # Cerrar calendario
    await page.keyboard.press('Escape')
    await page.wait_for_timeout(500)


async def set_passengers(page):
    log.info("  viajeros: abriendo selector...")
    passengers_seg = page.locator(".sf-searchbar__segment--passengers")
    await passengers_seg.click()
    await page.wait_for_timeout(800)
    plus_btn = page.locator(".sf-counter-btn", has_text="+")
    try:
        await plus_btn.first.click(timeout=5000)
        log.info("  viajeros: +1 ✓")
    except PWTimeout:
        log.error("  viajeros: botón + no encontrado")
    await page.wait_for_timeout(600)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)


async def fill_contact(page):
    log.info("  contacto: llenando email y teléfono...")
    email_inp = page.locator("input[placeholder='tu@email.com']")
    await email_inp.fill(FORM_CONFIG["email"])
    log.info(f"  email -> {FORM_CONFIG['email']} ✓")
    await page.wait_for_timeout(300)
    phone_inp = page.locator("input[placeholder='+1 234 567 890']")
    await phone_inp.fill(FORM_CONFIG["cel"])
    log.info(f"  teléfono -> {FORM_CONFIG['cel']} ✓")
    await page.wait_for_timeout(300)


async def click_cotizar(page):
    log.info("  cotizar: buscando botón...")
    try:
        cta = page.locator(".sf-searchbar__cta")
        await cta.first.click(timeout=10000)
        log.info("  cotizar -> clickeado ✓")
        return True
    except PWTimeout:
        log.error("  cotizar -> .sf-searchbar__cta no encontrado")
        return False


# ── Extracción de planes ──────────────────────────────────────────────────────

async def extract_plans(page, days):
    """Espera 'TOTAL A PAGAR' y extrae planes únicos sin duplicados."""
    plans = []
    try:
        await page.wait_for_selector("text=TOTAL A PAGAR", timeout=30000)
    except PWTimeout:
        log.error(f"'TOTAL A PAGAR' no apareció para {days}d. URL={page.url}")
        return [{'plan': 'NO_RESULTS', 'price': '', 'original_price': '',
                 'discount': '', 'days': days}]

    await page.wait_for_load_state("networkidle")
    await human_pause(page, 1500, 3000)

    cards = await page.locator("div").filter(has_text="TOTAL A PAGAR").all()
    log.info(f"  {len(cards)} tarjetas encontradas para {days}d")

    seen = set()
    for card in cards:
        try:
            text = await card.inner_text()
        except Exception:
            continue

        plan_m  = re.search(r'(Plan Smart|Plan Plus|Plan Max|Plan Elite)', text)
        price_m = re.search(r'COP ([\d,.]+)', text)
        disc_m  = re.search(r'(\d+)%\s*OFF', text)

        if not plan_m or not price_m:
            continue

        plan_name = plan_m.group(1)
        price_raw = re.sub(r'[^\d]', '', price_m.group(1))
        key       = (plan_name, price_raw)
        if key in seen:
            continue
        seen.add(key)

        discount   = f"-{disc_m.group(1)}%" if disc_m else ''
        prices_all = re.findall(r'COP ([\d,.]+)', text)
        orig_raw   = re.sub(r'[^\d]', '', prices_all[1]) if len(prices_all) > 1 else ''

        plans.append({
            'plan': plan_name, 'price': price_raw,
            'original_price': orig_raw, 'discount': discount, 'days': days,
        })
        log.info(f"  {days}d | {plan_name} | {price_raw} COP | {discount}")

    if not plans:
        log.error(f"  Ningún plan válido para {days}d")
        plans.append({'plan': 'NO_RESULTS', 'price': '', 'original_price': '',
                      'discount': '', 'days': days})
    return plans


# ── Cotización ────────────────────────────────────────────────────────────────

async def quote_one(page):
    """Una sola cotización de 10 días desde HOY."""
    dep_dt, ret_dt = get_dates_10d()
    log.info(f"=== Cotización 10d | {dep_dt.date()} -> {ret_dt.date()} ===")
    log.info(f"    (calculado desde hoy: {datetime.now().strftime('%Y-%m-%d')})")

    await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
    await human_pause(page, 2000, 4000)

    try:
        await page.wait_for_selector(".sf-searchbar__segment", timeout=20000)
    except PWTimeout:
        log.error("  Searchbar no cargó")
        return [{'plan': 'ERROR', 'price': '', 'original_price': '', 'discount': '', 'days': 10}]

    await page.wait_for_timeout(1500)

    await select_origin(page)
    await human_pause(page, 600, 1000)
    await select_destination(page)
    await human_pause(page, 800, 1400)
    await set_dates(page, dep_dt, ret_dt)
    await human_pause(page, 800, 1400)
    await set_passengers(page)
    await human_pause(page, 800, 1400)
    await fill_contact(page)
    await human_pause(page, 600, 1000)

    await page.screenshot(path="debug_pre_10d.png", full_page=False)
    await click_cotizar(page)

    try:
        await page.wait_for_url(RESULTS_URL_PATTERN, timeout=20000)
        log.info(f"  → {page.url}")
    except PWTimeout:
        log.error(f"  Sin redirección. URL={page.url}")
        await page.screenshot(path="debug_fail_10d.png", full_page=True)
        return [{'plan': 'ERROR', 'price': '', 'original_price': '', 'discount': '', 'days': 10}]

    await page.wait_for_load_state('networkidle', timeout=20000)
    await human_pause(page, 2000, 4000)
    return await extract_plans(page, 10)


# ── Entry point ───────────────────────────────────────────────────────────────

async def run():
    log.info("Segurosfly Bot — cotización 10 días desde HOY — Europa y Mediterraneo")
    all_plans = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=['--no-sandbox', '--disable-setuid-sandbox',
                  '--disable-blink-features=AutomationControlled'],
        )
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={'width': 1280, 'height': 800},
            locale='es-CO',
            timezone_id='America/Bogota',
        )
        page = await ctx.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )

        try:
            plans = await quote_one(page)
            all_plans.extend(plans)
        except Exception as exc:
            log.error(f"  quote_one falló: {exc}")
            all_plans.append({'plan': 'ERROR', 'price': '', 'original_price': '',
                               'discount': '', 'days': 10})

        await ctx.close()
        await browser.close()

    log.info(f"Finalizado. {len(all_plans)} planes encontrados.")
    for r in all_plans:
        log.info(f"  {r['days']}d | {r['plan']} | {r.get('price','')} COP | {r.get('discount','')}")
    return all_plans


if __name__ == '__main__':
    asyncio.run(run())
