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

            if (!host || !host.shadowRoot)
                return 'no-host';

            const inp = host.shadowRoot.getElementById(fid);

            if (!inp)
                return 'no-input:' + fid;

            const nativeSet = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                'value'
            ).set;

            nativeSet.call(inp, val);

            inp.dispatchEvent(new Event('input',  {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            inp.dispatchEvent(new Event('blur',   {bubbles: true}));

            return 'ok:' + inp.value;

        }""",
        [field_id, iso_date]
    )

    log.info(f"set_shadow_date({field_id}, {iso_date}) -> {ok}")

    return str(ok).startswith('ok')


async def set_shadow_field(page, field_id, value):

    ok = await page.evaluate(
        """([fid, val]) => {

            const host = document.getElementById('spv-quote-latest-home');

            if (!host || !host.shadowRoot)
                return 'no-host';

            const inp = host.shadowRoot.getElementById(fid);

            if (!inp)
                return 'no-input:' + fid;

            inp.focus();

            const nativeSet = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                'value'
            ).set;

            nativeSet.call(inp, val);

            inp.dispatchEvent(new Event('input',  {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            inp.dispatchEvent(new Event('blur',   {bubbles: true}));

            return 'ok:' + inp.value;

        }""",
        [field_id, value]
    )

    log.info(f"set_shadow_field({field_id}) -> {ok}")

    return str(ok).startswith('ok')


async def fill_ages_and_close(page):

    log.info("fill_ages: abrir dropdown")

    opened = await page.evaluate("""() => {

        const host = document.getElementById('spv-quote-latest-home');

        if (!host || !host.shadowRoot)
            return 'no-host';

        const inp = host.shadowRoot.getElementById('ages');

        if (!inp)
            return 'no-ages';

        inp.click();

        return 'clicked';

    }""")

    log.info(f"fill_ages open -> {opened}")

    await page.wait_for_timeout(1000)

    continuar_ok = await page.evaluate("""() => {

        const host = document.getElementById('spv-quote-latest-home');

        if (!host || !host.shadowRoot)
            return 'no-host';

        const btns = host.shadowRoot.querySelectorAll('button');

        for (const btn of btns) {

            if (
                btn.offsetParent !== null &&
                btn.textContent.includes('Continuar')
            ) {

                btn.click();

                return 'continuar-clicked';

            }
        }

        return 'no-continuar';

    }""")

    log.info(f"fill_ages continuar -> {continuar_ok}")

    await page.wait_for_timeout(800)

    return True


async def fill_phone_js(page, number):

    ok = await page.evaluate("""(number) => {

        const host = document.getElementById('spv-quote-latest-home');

        if (!host || !host.shadowRoot)
            return 'no-host';

        const inp = host.shadowRoot.getElementById('phone');

        if (!inp)
            return 'no-phone';

        inp.focus();

        const nativeSet = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype,
            'value'
        ).set;

        nativeSet.call(inp, '');

        inp.dispatchEvent(new Event('input', {bubbles: true}));

        for (const char of number) {

            nativeSet.call(inp, inp.value + char);

            inp.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                cancelable: true,
                data: char,
                inputType: 'insertText'
            }));
        }

        inp.dispatchEvent(new Event('change', {bubbles: true}));
        inp.dispatchEvent(new Event('blur',   {bubbles: true}));

        return 'ok:' + inp.value;

    }""", number)

    log.info(f"fill_phone_js -> {ok}")

    return str(ok).startswith('ok')


async def fill_form(page, dep, ret):

    # ── fechas ────────────────────────────────────────────────
    await set_shadow_date(page, 'departureDate', dep)

    await human_pause(page, 500, 1000)

    await set_shadow_date(page, 'arrivalDate', ret)

    await human_pause(page, 500, 1000)

    # ── pasajeros ─────────────────────────────────────────────
    await fill_ages_and_close(page)

    await page.wait_for_timeout(800)

    # ── nombre ────────────────────────────────────────────────
    await set_shadow_field(
        page,
        'fullName',
        FORM_CONFIG['nombre']
    )

    await page.wait_for_timeout(400)

    # ── email ─────────────────────────────────────────────────
    await set_shadow_field(
        page,
        'email',
        FORM_CONFIG['email']
    )

    await page.wait_for_timeout(400)

    # ── prefijo ───────────────────────────────────────────────
    await page.evaluate("""() => {

        const host = document.getElementById('spv-quote-latest-home');

        if (!host || !host.shadowRoot)
            return;

        const sel = host.shadowRoot.getElementById('intl');

        if (!sel)
            return;

        sel.value = '57';

        sel.dispatchEvent(new Event('change', {bubbles: true}));

    }""")

    await page.wait_for_timeout(400)

    # ── celular ───────────────────────────────────────────────
    await fill_phone_js(
        page,
        FORM_CONFIG['cel']
    )

    await page.wait_for_timeout(600)

    # ── validación ────────────────────────────────────────────
    estado = await page.evaluate("""() => {

        const host = document.getElementById('spv-quote-latest-home');

        if (!host || !host.shadowRoot)
            return {valid: true};

        const inputs = host.shadowRoot.querySelectorAll(
            'input, select'
        );

        const invalidos = Array.from(inputs)
            .filter(el => el.willValidate && !el.checkValidity())
            .map(el => ({
                id: el.id,
                msg: el.validationMessage
            }));

        return {
            valid: invalidos.length === 0,
            invalidos
        };

    }""")

    log.info(
        f"Formulario válido: {estado['valid']} | "
        f"Inválidos: {estado.get('invalidos', [])}"
    )

    return estado.get('valid', True)


async def click_cotizar(page):

    try:

        btn = page.locator(
            '#spv-quote-latest-home'
        ).locator('#btn-quote')

        await btn.click(timeout=10000)

        log.info("click_cotizar -> clicked via locator")

        return True

    except Exception as e:

        log.error(f"click_cotizar failed: {e}")

        return False


# ── extraction ──────────────────────────────────────────────────────────────

async def extract_plans(page, days):

    plans = []

    try:

        await page.wait_for_selector(
            "text=Precio hoy",
            timeout=30000
        )

    except PWTimeout:

        log.error(
            f"'Precio hoy' never appeared for {days}d. URL={page.url}"
        )

        return [{
            'plan': 'NO_RESULTS',
            'price': '',
            'original_price': '',
            'discount': '',
            'days': days
        }]

    await human_pause(page, 1500, 3000)

    cards = await page.locator(
        "div"
    ).filter(
        has_text="Precio hoy"
    ).all()

    log.info(f"Found {len(cards)} cards for {days}d")

    for card in cards:

        try:
            text = await card.inner_text()
        except Exception:
            continue

        plan_m = re.search(
            r'(Esencial|Estándar|Ideal)',
            text
        )

        price_m = re.search(
            r'\$([\d,.]+)\s*COP',
            text
        )

        disc_m = re.search(
            r'-(\d+)%',
            text
        )

        if not plan_m or not price_m:
            continue

        plan_name = plan_m.group(1)

        price_raw = re.sub(
            r'[^\d]',
            '',
            price_m.group(1)
        )

        discount = (
            f"-{disc_m.group(1)}%"
            if disc_m else ''
        )

        prices_all = re.findall(
            r'\$([\d,.]+)\s*COP',
            text
        )

        orig_raw = (
            re.sub(r'[^\d]', '', prices_all[1])
            if len(prices_all) > 1 else ''
        )

        plans.append({
            'plan': plan_name,
            'price': price_raw,
            'original_price': orig_raw,
            'discount': discount,
            'days': days,
        })

        log.info(
            f"{days}d | {plan_name} | "
            f"{price_raw} COP | {discount}"
        )

    if not plans:

        log.error(f"No valid cards parsed for {days}d")

        plans.append({
            'plan': 'NO_RESULTS',
            'price': '',
            'original_price': '',
            'discount': '',
            'days': days
        })

    return plans


# ── quote ───────────────────────────────────────────────────────────────────

async def quote_one(page, days):

    dep = (
        datetime.now() + timedelta(days=30)
    ).strftime('%Y-%m-%d')

    ret = (
        datetime.now() + timedelta(days=30 + days)
    ).strftime('%Y-%m-%d')

    log.info(f"=== Quote {days}d | {dep} -> {ret} ===")

    # ── abrir home ────────────────────────────────────────────
    await page.goto(
        URL_HOME,
        wait_until='domcontentloaded',
        timeout=30000
    )

    await human_pause(page, 2000, 4000)

    # ── esperar shadow host ───────────────────────────────────
    await page.wait_for_selector(
        "#spv-quote-latest-home",
        timeout=30000
    )

    await page.wait_for_timeout(5000)

    # ── llenar formulario ─────────────────────────────────────
    await fill_form(page, dep, ret)

    await human_pause(page, 800, 1500)

    # ── screenshot debug ──────────────────────────────────────
    await page.screenshot(
        path=f"debug_pre_{days}d.png",
        full_page=False
    )

    # ── click cotizar ─────────────────────────────────────────
    await click_cotizar(page)

    # ── esperar render SPA/AJAX ───────────────────────────────
    await page.wait_for_timeout(8000)

    html = await page.content()

    if "Precio hoy" in html:

        log.info(f"Resultados detectados para {days}d ✅")

    else:

        log.error(
            f"'Precio hoy' never appeared for {days}d. URL={page.url}"
        )

        await page.screenshot(
            path=f"debug_post_{days}d.png",
            full_page=True
        )

    cards = await page.locator("text=Precio hoy").all()

    log.info(f"Cards encontradas: {len(cards)}")

    await human_pause(page, 2000, 4000)

    return await extract_plans(page, days)


# ── main ────────────────────────────────────────────────────────────────────

async def run():

    log.info(
        "SPV scraper start — single session, "
        "10/20/30 days, Europa"
    )

    all_plans = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled'
            ],
        )

        ctx = await browser.new_context(
            user_agent=UA,
            viewport={
                'width': 1280,
                'height': 800
            },
            locale='es-CO',
            timezone_id='America/Bogota',
        )

        page = await ctx.new_page()

        await page.add_init_script(
            "Object.defineProperty("
            "navigator,"
            "'webdriver',"
            "{get:()=>undefined}"
            ");"
        )

        for days in [10, 20, 30]:

            try:

                plans = await quote_one(page, days)

                all_plans.extend(plans)

            except Exception as exc:

                log.error(
                    f"quote_one({days}) crashed: {exc}"
                )

                all_plans.append({
                    'plan': 'ERROR',
                    'price': '',
                    'original_price': '',
                    'discount': '',
                    'days': days
                })

            await human_pause(page, 3000, 6000)

        await ctx.close()

        await browser.close()

    log.info(f"Done. {len(all_plans)} records collected.")

    for r in all_plans:

        log.info(
            f"{r['days']}d | "
            f"{r['plan']} | "
            f"{r.get('price','')} COP"
        )

    return all_plans


if __name__ == '__main__':
    asyncio.run(run())
