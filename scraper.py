import asyncio
import random
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import URL_HOME, HEADLESS, UA, USER_EMAIL, USER_PHONE
from logger import log

# ── Configuración ────────────────────────────────────────────────────────────
RESULTS_URL_PATTERN = "**/cotizar/plans/**"

from config import USER_EMAIL, USER_PHONE

FORM_CONFIG = {
    "email": USER_EMAIL,
    "cel":   USER_PHONE,
}


# ── helpers ──────────────────────────────────────────────────────────────────

async def human_pause(page, lo=2000, hi=5000):
    await page.wait_for_timeout(random.randint(lo, hi))


# ── Pasos del formulario ──────────────────────────────────────────────────────

async def select_destination(page):
    """Índice 2 = DESTINO. Escribe 'Europa' y elige 'Europa y Mediterraneo'."""
    log.info("  destino: abriendo selector...")

    segments = page.locator(".sf-searchbar__segment")
    await segments.nth(2).click()
    await page.wait_for_timeout(1000)

    inp = page.locator(".react-select__input input")
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


async def set_dates(page, dep: str, ret: str):
    """Abre FECHAS y selecciona el preset que coincide con los días."""
    dep_dt = datetime.strptime(dep, '%Y-%m-%d')
    ret_dt = datetime.strptime(ret, '%Y-%m-%d')
    days   = (ret_dt - dep_dt).days
    log.info(f"  fechas: {dep} -> {ret} ({days}d)")

    dates_seg = page.locator(".sf-searchbar__segment--dates")
    await dates_seg.click()
    await page.wait_for_timeout(800)

    # Buscar preset exacto por texto
    preset_btn = page.locator(".sf-preset-btn", has_text=str(days))
    if await preset_btn.count() > 0:
        await preset_btn.first.click(timeout=5000)
        log.info(f"  fechas: preset {days}d ✓")
    else:
        # Sin preset exacto: intentar inputs de fecha directos
        log.info(f"  fechas: sin preset exacto — usando inputs directos")
        date_inputs = await page.locator("input[type='date']").all()
        if len(date_inputs) >= 2:
            await date_inputs[0].fill(dep)
            await date_inputs[1].fill(ret)
            log.info(f"  fechas: inputs llenados ✓")
        else:
            log.error(f"  fechas: no se encontró preset ni inputs para {days}d")

    await page.wait_for_timeout(600)


async def set_passengers(page):
    """Abre VIAJEROS y agrega 1 pasajero con el botón +."""
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
    # Cerrar dropdown
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)


async def fill_contact(page):
    """Llena EMAIL y TELÉFONO — ambos visibles en la barra antes de cotizar."""
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
    """Click en el botón CTA de la barra."""
    log.info("  cotizar: buscando botón...")

    try:
        cta = page.locator(".sf-searchbar__cta")
        await cta.first.click(timeout=10000)
        log.info("  cotizar -> .sf-searchbar__cta clickeado ✓")
        return True
    except PWTimeout:
        log.error("  cotizar -> .sf-searchbar__cta no encontrado")
        return False


# ── Extracción de planes ──────────────────────────────────────────────────────

async def extract_plans(page, days):
    """Espera 'Precio hoy' y extrae nombre, precio, precio original y descuento."""
    plans = []
    try:
        await page.wait_for_selector("text=Precio hoy", timeout=30000)
    except PWTimeout:
        log.error(f"'Precio hoy' no apareció para {days}d. URL={page.url}")
        return [{'plan': 'NO_RESULTS', 'price': '', 'original_price': '',
                 'discount': '', 'days': days}]

    await page.wait_for_load_state("networkidle")
    await human_pause(page, 1500, 3000)

    cards = await page.locator("div").filter(has_text="Precio hoy").all()
    log.info(f"  {len(cards)} tarjetas encontradas para {days}d")

    for card in cards:
        try:
            text = await card.inner_text()
        except Exception:
            continue

        plan_m  = re.search(r'(Esencial|Est\u00e1ndar|Ideal)', text)
        price_m = re.search(r'\$([\d,.]+)\s*COP', text)
        disc_m  = re.search(r'-(\d+)%', text)

        if not plan_m or not price_m:
            continue

        plan_name  = plan_m.group(1)
        price_raw  = re.sub(r'[^\d]', '', price_m.group(1))
        discount   = f"-{disc_m.group(1)}%" if disc_m else ''
        prices_all = re.findall(r'\$([\d,.]+)\s*COP', text)
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


# ── Cotización individual ─────────────────────────────────────────────────────

async def quote_one(page, days):
    """Navega al home, llena la barra completa y extrae los planes."""
    dep = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    ret = (datetime.now() + timedelta(days=30 + days)).strftime('%Y-%m-%d')
    log.info(f"=== Cotización {days}d | {dep} -> {ret} ===")

    await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
    await human_pause(page, 2000, 4000)

    try:
        await page.wait_for_selector(".sf-searchbar__segment", timeout=20000)
    except PWTimeout:
        log.error(f"  Searchbar no cargó para {days}d")
        return [{'plan': 'ERROR', 'price': '', 'original_price': '', 'discount': '', 'days': days}]

    await page.wait_for_timeout(1500)

    # Orden exacto de la barra: Destino → Fechas → Viajeros → Email → Tel → Cotizar
    await select_destination(page)
    await human_pause(page, 800, 1400)

    await set_dates(page, dep, ret)
    await human_pause(page, 800, 1400)

    await set_passengers(page)
    await human_pause(page, 800, 1400)

    await fill_contact(page)
    await human_pause(page, 600, 1000)

    await page.screenshot(path=f"debug_pre_{days}d.png", full_page=False)
    await click_cotizar(page)

    try:
        await page.wait_for_url(RESULTS_URL_PATTERN, timeout=20000)
        log.info(f"  → {page.url}")
    except PWTimeout:
        log.error(f"  Sin redirección a /cotizar/plans/ para {days}d. URL={page.url}")
        await page.screenshot(path=f"debug_fail_{days}d.png", full_page=True)
        return [{'plan': 'ERROR', 'price': '', 'original_price': '', 'discount': '', 'days': days}]

    await page.wait_for_load_state('networkidle', timeout=20000)
    await human_pause(page, 2000, 4000)
    return await extract_plans(page, days)


# ── Entry point ───────────────────────────────────────────────────────────────

async def run():
    log.info("Segurosfly Bot — scraping 1 a 30 días — Europa y Mediterraneo")
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

        for days in range(1, 31):
            try:
                plans = await quote_one(page, days)
                all_plans.extend(plans)
                log.info(f"  ✓ {days}d completado ({len(plans)} planes)")
            except Exception as exc:
                log.error(f"  ✗ quote_one({days}d) falló: {exc}")
                all_plans.append({'plan': 'ERROR', 'price': '', 'original_price': '',
                                   'discount': '', 'days': days})

            await human_pause(page, 3000, 6000)

        await ctx.close()
        await browser.close()

    log.info(f"Finalizado. {len(all_plans)} registros totales.")
    for r in all_plans:
        log.info(f"  {r['days']}d | {r['plan']} | {r.get('price','')} COP | {r.get('discount','')}")
    return all_plans


if __name__ == '__main__':
    asyncio.run(run())
