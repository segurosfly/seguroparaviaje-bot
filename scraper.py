import asyncio
import random
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import URL_HOME, HEADLESS, UA
from logger import log


# ── Datos fijos de cotización ───────────────────────────────────────────────
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
    """Llena un campo dentro del shadow DOM disparando todos los eventos."""
    ok = await page.evaluate(
        """([fid, val, ftype]) => {
            const host = document.getElementById('spv-quote-latest-home');
            if (!host || !host.shadowRoot) return 'no-host';
            let el = host.shadowRoot.getElementById(fid);
            if (!el) return 'no-field:' + fid;
            if (ftype === 'select') {
                const opts = Array.from(el.options);
                const target = opts.find(o =>
                    o.text.toLowerCase().includes(val.toLowerCase())
                );
                if (target) el.value = target.value;
                else el.selectedIndex = 1;
            } else {
                el.focus();
                const nativeSet = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                nativeSet.call(el, val);
            }
            ['focus', 'input', 'change', 'blur'].forEach(evName => {
                el.dispatchEvent(new Event(evName, {bubbles: true, cancelable: true}));
            });
            el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
            return 'ok:' + el.value;
        }""",
        [field_id, value, field_type]
    )
    log.info(f"set_shadow_field({field_id}) -> {ok}")
    return str(ok).startswith('ok')


async def fill_ages_and_close(page):
    """
    Abre dropdown de pasajeros con Playwright locator (pierce shadow DOM),
    clickea el primer botón + activo (grupo 0-69 años), luego Continuar.
    """
    log.info("  fill_ages: abriendo dropdown de pasajeros...")

    # 1. Click en ages via Playwright locator (pierce shadow DOM real)
    ages_loc = page.locator('#spv-quote-latest-home').locator('#ages')
    await ages_loc.click()
    log.info("  fill_ages click ages -> clicked via locator")
    await page.wait_for_timeout(1200)
    await page.screenshot(path="debug_01_ages_clicked.png")
    log.info("  screenshot: debug_01_ages_clicked.png")

    # 2. Click en el primer botón + con class="active"
    #    Confirmado por consola DevTools: los botones activos tienen class="active"
    #    y text="+". El primero es siempre el del grupo 0-69 años.
    plus_ok = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return 'no-host';
        const btns = Array.from(host.shadowRoot.querySelectorAll('button'));

        // Buscar por class="active" y texto "+"
        const plusBtn = btns.find(b =>
            b.className === 'active' &&
            b.textContent.trim() === '+'
        );
        if (plusBtn) {
            plusBtn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
            return 'plus-active:ok';
        }

        // Fallback: cualquier botón con texto "+"
        const anyPlus = btns.find(b => b.textContent.trim() === '+');
        if (anyPlus) {
            anyPlus.dispatchEvent(new MouseEvent('click', {bubbles: true}));
            return 'plus-fallback:ok';
        }

        const info = btns.map(b => b.textContent.trim() + '|' + b.className);
        return 'no-plus:' + JSON.stringify(info);
    }""")
    log.info(f"  fill_ages plus -> {plus_ok}")
    await page.wait_for_timeout(800)
    await page.screenshot(path="debug_02_after_plus.png")
    log.info("  screenshot: debug_02_after_plus.png")

    # 3. Click en Continuar (class="select-ages" confirmado por consola)
    continuar_ok = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return 'no-host';
        const btn = host.shadowRoot.querySelector('button.select-ages');
        if (btn) { btn.dispatchEvent(new MouseEvent('click', {bubbles: true})); return 'continuar-clicked'; }
        // fallback texto
        for (const b of host.shadowRoot.querySelectorAll('button')) {
            if (b.textContent.includes('Continuar')) {
                b.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                return 'continuar-fallback';
            }
        }
        return 'no-continuar-found';
    }""")
    log.info(f"  fill_ages continuar -> {continuar_ok}")
    await page.wait_for_timeout(800)
    await page.screenshot(path="debug_03_after_continuar.png")
    log.info("  screenshot: debug_03_after_continuar.png")

    # 4. Verificar cierre
    dropdown_open = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return false;
        const btn = host.shadowRoot.querySelector('button.select-ages');
        return btn ? btn.offsetParent !== null : false;
    }""")

    if dropdown_open:
        log.warning("  fill_ages: dropdown todavía abierto — intentando Escape")
        await page.keyboard.press('Escape')
        await page.wait_for_timeout(500)
    else:
        log.info("  fill_ages: dropdown cerrado correctamente ✓")

    return 'continuar' in str(continuar_ok)


async def fill_phone_real(page, number):
    """
    Llena id=phone via JS con secuencia completa de eventos.
    El prefijo intl debe estar seleccionado ANTES de llamar esta función.
    Usa dispatchEvent nativo para que el framework reactive detecte el cambio.
    """
    ok = await page.evaluate("""(number) => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return 'no-host';
        const inp = host.shadowRoot.getElementById('phone');
        if (!inp) return 'no-phone';
        const nativeSet = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
        inp.focus();
        nativeSet.call(inp, '');
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        for (const char of number) {
            nativeSet.call(inp, inp.value + char);
            inp.dispatchEvent(new InputEvent('input', {
                bubbles: true, cancelable: true,
                data: char, inputType: 'insertText'
            }));
        }
        inp.dispatchEvent(new Event('change', {bubbles: true}));
        inp.dispatchEvent(new FocusEvent('blur', {bubbles: true}));
        return 'ok:' + inp.value;
    }""", number)
    log.info(f"fill_phone_real -> {ok}")
    return str(ok).startswith('ok')


async def dump_shadow_fields(page):
    """Diagnóstico: lista todos los campos del shadow DOM."""
    fields = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return [];
        const els = host.shadowRoot.querySelectorAll('input, select, textarea, button');
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
    """Llena todos los campos en el orden correcto."""

    # ── 1. Fechas (funciona) ─────────────────────────────────────────────
    await set_shadow_date(page, 'departureDate', dep)
    await human_pause(page, 500, 1000)
    await set_shadow_date(page, 'arrivalDate', ret)
    await human_pause(page, 500, 1000)

    # ── 2. Ages: abrir dropdown → click Continuar → cerrar ───────────────
    await fill_ages_and_close(page)
    await page.wait_for_timeout(800)

    # ── 3. Nombre (id=fullName — funciona) ───────────────────────────────
    ok = await set_shadow_field(page, 'fullName', FORM_CONFIG['nombre'], 'input')
    log.info(f"  nombre -> {'OK' if ok else 'FAIL'}")
    await page.wait_for_timeout(400)

    # ── 4. Email (id=email — funciona) ───────────────────────────────────
    ok = await set_shadow_field(page, 'email', FORM_CONFIG['email'], 'input')
    log.info(f"  email  -> {'OK' if ok else 'FAIL'}")
    await page.wait_for_timeout(400)

    # ── 5. Prefijo +57 ───────────────────────────────────────────────────
    ok_intl = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return 'no-host';
        const sel = host.shadowRoot.getElementById('intl');
        if (!sel) return 'no-intl';
        const opts = Array.from(sel.options);
        const target = opts.find(o =>
            o.value === '57' || o.value === '+57' ||
            o.text.includes('57') || o.text.toLowerCase().includes('colombia')
        );
        if (target) sel.value = target.value;
        else sel.selectedIndex = 1;
        sel.dispatchEvent(new Event('change', {bubbles: true}));
        sel.dispatchEvent(new Event('blur',   {bubbles: true}));
        return 'ok:' + sel.value;
    }""")
    log.info(f"  intl prefix -> {ok_intl}")
    await page.wait_for_timeout(400)

    # ── 6. Phone: JS directo (evita problema del dropdown encima) ────────
    await fill_phone_real(page, FORM_CONFIG['cel'])
    await page.wait_for_timeout(600)

    # ── 7. Verificar validez ─────────────────────────────────────────────
    estado = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return {valid: true, invalidos: []};
        const inputs = host.shadowRoot.querySelectorAll('input, select');
        const inv = Array.from(inputs)
            .filter(el => el.willValidate && !el.checkValidity())
            .map(el => ({id: el.id, msg: el.validationMessage, value: el.value}));
        return {valid: inv.length === 0, invalidos: inv};
    }""")
    log.info(f"  Formulario válido: {estado['valid']} | "
             f"Inválidos: {estado['invalidos']}")
    await page.screenshot(path="debug_04_form_complete.png")
    log.info("  screenshot: debug_04_form_complete.png")
    return estado.get('valid', True)


async def click_cotizar(page):
    """Click 'Cotiza Gratis' — pierce shadow DOM."""
    try:
        btn = page.locator('#spv-quote-latest-home').locator('#btn-quote')
        await btn.click(timeout=10000)
        log.info("click_cotizar -> clicked via locator")
        return True
    except Exception as e:
        log.error(f"click_cotizar locator failed: {e}")

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
    """Espera 'Precio hoy' y extrae planes de la página /cotizar/."""
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
            'plan': plan_name, 'price': price_raw,
            'original_price': orig_raw, 'discount': discount, 'days': days,
        })
        log.info(f"  {days}d | {plan_name} | {price_raw} COP | {discount}")

    if not plans:
        log.error(f"No valid cards parsed for {days}d")
        plans.append({'plan': 'NO_RESULTS', 'price': '', 'original_price': '',
                      'discount': '', 'days': days})
    return plans


# ── single quote ────────────────────────────────────────────────────────────

async def quote_one(page, days):
    """Navega al home, llena todo el formulario, cotiza y extrae."""
    dep = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    ret = (datetime.now() + timedelta(days=30 + days)).strftime('%Y-%m-%d')
    log.info(f"=== Quote {days}d | {dep} -> {ret} ===")

    await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
    await human_pause(page, 2000, 4000)
    await page.wait_for_selector("#spv-quote-latest-home", timeout=30000)
    await page.wait_for_timeout(5000)

    if days == 10:
        await dump_shadow_fields(page)

    await fill_form(page, dep, ret)
    await human_pause(page, 800, 1500)

    await page.screenshot(path=f"debug_pre_{days}d.png", full_page=False)
    await click_cotizar(page)

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
