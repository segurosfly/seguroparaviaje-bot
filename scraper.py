import asyncio
import random
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import URL_HOME, HEADLESS, UA
from logger import log


# ── Datos fijos de cotización ───────────────────────────────────────────────
# Ajusta estos valores según tu cotización estándar
FORM_CONFIG = {
    "nombre": "Nirvia",
    "email":  "Nirviagonza@hotmail.com",
    "cel":    "3022500760",
}


# ── helpers ─────────────────────────────────────────────────────────────────

async def human_pause(page, lo=2000, hi=5000):
    await page.wait_for_timeout(random.randint(lo, hi))


async def set_shadow_date(page, field_id, iso_date):
    """Set #departureDate / #arrivalDate inside SPV-QUOTE shadow DOM via JS."""
    ok = await page.evaluate(
        """([fid, val]) => {
            const host = document.getElementById('spv-quote-latest-home');
            if (!host || !host.shadowRoot) return 'no-host';
            const inp = host.shadowRoot.getElementById(fid);
            if (!inp) return 'no-input:' + fid;
            const nativeSet = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            nativeSet.call(inp, val);
            inp.dispatchEvent(new Event('input',  {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            return 'ok:' + inp.value;
        }""",
        [field_id, iso_date]
    )
    log.info(f"set_shadow_date({field_id}, {iso_date}) -> {ok}")
    return str(ok).startswith('ok')


async def set_shadow_field(page, field_id, value, field_type='input'):
    """
    Llena un campo de texto dentro del shadow DOM de #spv-quote-latest-home.
    field_type: 'input' | 'select'
    """
    ok = await page.evaluate(
        """([fid, val, ftype]) => {
            const host = document.getElementById('spv-quote-latest-home');
            if (!host || !host.shadowRoot) return 'no-host';
            const el = host.shadowRoot.getElementById(fid);
            if (!el) {
                // Intentar por name o por tipo
                const byName = host.shadowRoot.querySelector('[name="' + fid + '"]');
                if (!byName) return 'no-field:' + fid;
                el = byName;
            }
            if (ftype === 'select') {
                // Seleccionar opción por texto visible
                const opts = Array.from(el.options);
                const target = opts.find(o =>
                    o.text.toLowerCase().includes(val.toLowerCase())
                );
                if (target) {
                    el.value = target.value;
                } else {
                    el.selectedIndex = 1; // primera opción válida
                }
            } else {
                const nativeSet = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeSet.call(el, val);
            }
            el.dispatchEvent(new Event('input',  {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new Event('blur',   {bubbles: true}));
            return 'ok:' + el.value;
        }""",
        [field_id, value, field_type]
    )
    log.info(f"set_shadow_field({field_id}) -> {ok}")
    return str(ok).startswith('ok')


async def dump_shadow_fields(page):
    """
    Diagnóstico: lista todos los campos dentro del shadow DOM.
    Útil para identificar IDs exactos si algo falla.
    """
    fields = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return [];
        const els = host.shadowRoot.querySelectorAll(
            'input, select, textarea, button'
        );
        return Array.from(els).map(el => ({
            tag:         el.tagName,
            id:          el.id || '',
            name:        el.name || '',
            type:        el.type || '',
            placeholder: el.placeholder || '',
            value:       el.value || '',
            visible:     el.offsetParent !== null,
        }));
    }""")
    log.info("── Shadow DOM fields ──────────────────────────────")
    for f in fields:
        if f['visible']:
            log.info(f"  [{f['tag']}] id={f['id']} name={f['name']} "
                     f"type={f['type']} placeholder='{f['placeholder']}' "
                     f"value='{f['value']}'")
    log.info("───────────────────────────────────────────────────")
    return fields


async def fill_form(page, dep: str, ret: str):
    """
    Llena TODOS los campos del formulario de cotización.
    Estrategia: primero intenta por ID dentro del shadow DOM,
    luego fallback por selectores en el DOM principal.
    """

    # ── 1. Origen (select) ──────────────────────────────────────────────
    # IDs comunes del componente SPV: 'origin', 'origen', 'countryOrigin'
    for fid in ['origin', 'origen', 'countryOrigin', 'country-origin']:
        ok = await set_shadow_field(page, fid, 'Colombia', 'select')
        if ok:
            log.info("  [OK] origen -> Colombia")
            break
    else:
        # Fallback DOM principal
        for sel in ["select[name*='origin']", "select[id*='origin']",
                    "select[name*='origen']", "select[id*='origen']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.select_option(label='Colombia')
                    log.info(f"  [OK] origen DOM fallback -> {sel}")
                    break
            except Exception:
                continue
    await page.wait_for_timeout(500)

    # ── 2. Destino (select) ─────────────────────────────────────────────
    for fid in ['destination', 'destino', 'countryDest', 'country-dest']:
        ok = await set_shadow_field(page, fid, 'Europa', 'select')
        if ok:
            log.info("  [OK] destino -> Europa")
            break
    else:
        for sel in ["select[name*='dest']", "select[id*='dest']",
                    "select[name*='region']", "select[id*='region']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.select_option(label='Europa')
                    log.info(f"  [OK] destino DOM fallback -> {sel}")
                    break
            except Exception:
                continue
    await page.wait_for_timeout(500)

    # ── 3. Fechas (shadow DOM — ya funciona) ────────────────────────────
    await set_shadow_date(page, 'departureDate', dep)
    await human_pause(page, 500, 1200)
    await set_shadow_date(page, 'arrivalDate', ret)
    await human_pause(page, 800, 1500)

    # ── 4. Pasajeros (select) ───────────────────────────────────────────
    for fid in ['passengers', 'pasajeros', 'travelers', 'pax']:
        ok = await set_shadow_field(page, fid, '1', 'select')
        if ok:
            log.info("  [OK] pasajeros -> 1")
            break
    await page.wait_for_timeout(400)

    # ── 5. Nombre ───────────────────────────────────────────────────────
    nombre_ok = False
    for fid in ['nombre', 'name', 'firstName', 'first-name', 'fullName']:
        ok = await set_shadow_field(page, fid, FORM_CONFIG['nombre'], 'input')
        if ok:
            log.info(f"  [OK] nombre -> {FORM_CONFIG['nombre']}")
            nombre_ok = True
            break
    if not nombre_ok:
        for sel in ["input[name*='nombre']", "input[id*='nombre']",
                    "input[name*='name']", "input[placeholder*='Nombre']",
                    "input[placeholder*='nombre']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.fill(FORM_CONFIG['nombre'])
                    log.info(f"  [OK] nombre DOM fallback -> {sel}")
                    nombre_ok = True
                    break
            except Exception:
                continue
    await page.wait_for_timeout(400)

    # ── 6. Email ────────────────────────────────────────────────────────
    email_ok = False
    for fid in ['email', 'correo', 'mail', 'emailAddress']:
        ok = await set_shadow_field(page, fid, FORM_CONFIG['email'], 'input')
        if ok:
            log.info(f"  [OK] email -> {FORM_CONFIG['email']}")
            email_ok = True
            break
    if not email_ok:
        for sel in ["input[type='email']", "input[name*='email']",
                    "input[id*='email']", "input[placeholder*='mail']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.fill(FORM_CONFIG['email'])
                    log.info(f"  [OK] email DOM fallback -> {sel}")
                    email_ok = True
                    break
            except Exception:
                continue
    await page.wait_for_timeout(400)

    # ── 7. Celular ──────────────────────────────────────────────────────
    cel_ok = False
    for fid in ['cel', 'phone', 'telefono', 'celular', 'mobile', 'phoneNumber']:
        ok = await set_shadow_field(page, fid, FORM_CONFIG['cel'], 'input')
        if ok:
            log.info(f"  [OK] cel -> {FORM_CONFIG['cel']}")
            cel_ok = True
            break
    if not cel_ok:
        for sel in ["input[type='tel']", "input[name*='cel']",
                    "input[name*='phone']", "input[placeholder*='Cel']",
                    "input[placeholder*='celular']"]:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=2000):
                    await el.fill(FORM_CONFIG['cel'])
                    log.info(f"  [OK] cel DOM fallback -> {sel}")
                    cel_ok = True
                    break
            except Exception:
                continue
    await page.wait_for_timeout(400)

    # ── 8. Verificar validez del formulario ─────────────────────────────
    estado = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) {
            // Verificar formulario normal
            const form = document.querySelector('form');
            if (!form) return {valid: true, invalidos: []};
            const inv = Array.from(form.elements)
                .filter(el => el.willValidate && !el.checkValidity())
                .map(el => el.id || el.name || el.placeholder || el.type);
            return {valid: form.checkValidity(), invalidos: inv};
        }
        // Verificar dentro del shadow DOM
        const inputs = host.shadowRoot.querySelectorAll('input, select');
        const inv = Array.from(inputs)
            .filter(el => el.willValidate && !el.checkValidity())
            .map(el => ({
                id: el.id,
                name: el.name,
                msg: el.validationMessage,
                value: el.value,
            }));
        return {valid: inv.length === 0, invalidos: inv};
    }""")
    log.info(f"  Formulario válido: {estado['valid']} | "
             f"Campos inválidos: {estado['invalidos']}")

    return estado.get('valid', True)


async def click_cotizar(page):
    """Click 'Cotiza Gratis' button — pierce shadow DOM."""
    try:
        btn = page.locator('#spv-quote-latest-home').locator('#btn-quote')
        await btn.click(timeout=10000)
        log.info("click_cotizar -> clicked via locator")
        return True
    except Exception as e:
        log.error(f"click_cotizar locator failed: {e}")

    # Fallback JS
    ok = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return 'no-host';
        const btn = host.shadowRoot.getElementById('btn-quote');
        if (!btn) return 'no-btn';
        btn.click();
        return 'eval-clicked';
    }""")
    log.info(f"click_cotizar fallback -> {ok}")
    return True


# ── extraction ──────────────────────────────────────────────────────────────

async def extract_plans(page, days):
    """
    En la página /cotizar/ espera 'Precio hoy' y extrae planes.
    """
    plans = []

    try:
        await page.wait_for_selector("text=Precio hoy", timeout=30000)
    except PWTimeout:
        log.error(f"'Precio hoy' never appeared for {days}d. URL={page.url}")
        return [{'plan': 'NO_RESULTS', 'price': '', 'original_price': '',
                 'discount': '', 'days': days}]

    await page.wait_for_load_state("networkidle")
    await human_pause(page, 1500, 3000)

    cards = await page.locator("div").filter(has_text="Precio hoy").all()
    log.info(f"Found {len(cards)} 'Precio hoy' cards for {days}d")

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

        plan_name = plan_m.group(1)
        price_raw = re.sub(r'[^\d]', '', price_m.group(1))
        discount  = f"-{disc_m.group(1)}%" if disc_m else ''

        prices_all = re.findall(r'\$([\d,.]+)\s*COP', text)
        orig_raw   = re.sub(r'[^\d]', '', prices_all[1]) if len(prices_all) > 1 else ''

        plans.append({
            'plan':           plan_name,
            'price':          price_raw,
            'original_price': orig_raw,
            'discount':       discount,
            'days':           days,
        })
        log.info(f"  {days}d | {plan_name} | {price_raw} COP | {discount}")

    if not plans:
        log.error(f"No valid cards parsed for {days}d")
        plans.append({'plan': 'NO_RESULTS', 'price': '', 'original_price': '',
                      'discount': '', 'days': days})
    return plans


# ── single quote ────────────────────────────────────────────────────────────

async def quote_one(page, days):
    """Navega al home, llena TODO el formulario, cotiza y extrae."""
    dep = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    ret = (datetime.now() + timedelta(days=30 + days)).strftime('%Y-%m-%d')
    log.info(f"=== Quote {days}d | {dep} -> {ret} ===")

    # Reload limpio para cada cotización
    await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
    await human_pause(page, 2000, 4000)

    # Esperar que el componente shadow DOM esté listo
    await page.wait_for_selector("#spv-quote-latest-home", timeout=30000)
    await page.wait_for_timeout(5000)

    # Diagnóstico en primer run (opcional — comenta en producción)
    if days == 10:
        await dump_shadow_fields(page)

    # Llenar TODOS los campos del formulario
    form_valid = await fill_form(page, dep, ret)
    if not form_valid:
        log.warning(f"  Formulario con campos inválidos — igualmente intentando cotizar")

    await human_pause(page, 800, 1500)

    # Screenshot pre-click para debug
    await page.screenshot(path=f"debug_pre_{days}d.png", full_page=False)

    # Click cotizar
    await click_cotizar(page)

    # Esperar navegación a /cotizar/
    try:
        await page.wait_for_url('**/cotizar/**', timeout=20000)
        log.info(f"  Navegó a: {page.url}")
    except PWTimeout:
        log.error(f"No /cotizar/ navigation for {days}d. URL={page.url}")
        await page.screenshot(path=f"debug_post_{days}d.png", full_page=True)

    await page.wait_for_load_state('networkidle', timeout=20000)
    await human_pause(page, 2000, 4000)

    return await extract_plans(page, days)


# ── main entry ──────────────────────────────────────────────────────────────

async def run():
    log.info("SPV scraper start — single session, 10/20/30 days, Europa")
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

        for days in [10, 20, 30]:
            try:
                plans = await quote_one(page, days)
                all_plans.extend(plans)
            except Exception as exc:
                log.error(f"quote_one({days}) crashed: {exc}")
                all_plans.append({'plan': 'ERROR', 'price': '', 'original_price': '',
                                   'discount': '', 'days': days})
            await human_pause(page, 3000, 6000)

        await ctx.close()
        await browser.close()

    log.info(f"Done. {len(all_plans)} records collected.")
    for r in all_plans:
        log.info(f"  {r['days']}d | {r['plan']} | {r.get('price','')} COP")
    return all_plans


if __name__ == '__main__':
    asyncio.run(run())
