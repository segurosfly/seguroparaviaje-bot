import asyncio
import random
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import URL_HOME, HEADLESS, UA
from logger import log

FORM_CONFIG = {
    "nombre": "Nirvia",
    "email":  "Nirviagonza@hotmail.com",
    "cel":    "3022500760",
}

async def human_pause(page, lo=2000, hi=5000):
    await page.wait_for_timeout(random.randint(lo, hi))

async def set_shadow_date(page, field_id, iso_date):

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

# ✅ NUEVO FIX TELÉFONO
async def fill_phone_real(page, number):

    phone = page.locator(
        '#spv-quote-latest-home'
    ).locator('#phone')

    await phone.click()

    await page.wait_for_timeout(500)

    await phone.clear()

    await page.wait_for_timeout(300)

    await phone.type(number, delay=150)

    await page.wait_for_timeout(1000)

    value = await phone.input_value()

    log.info(f"fill_phone_real -> {value}")

    return value == number

async def fill_form(page, dep, ret):

    await set_shadow_date(page, 'departureDate', dep)

    await human_pause(page, 500, 1000)

    await set_shadow_date(page, 'arrivalDate', ret)

    await human_pause(page, 500, 1000)

    await fill_ages_and_close(page)

    await page.wait_for_timeout(800)

    await set_shadow_field(
        page,
        'fullName',
        FORM_CONFIG['nombre']
    )

    await page.wait_for_timeout(400)

    await set_shadow_field(
        page,
        'email',
        FORM_CONFIG['email']
    )

    await page.wait_for_timeout(400)

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

    # ✅ FIX NUEVO
    await fill_phone_real(
        page,
        FORM_CONFIG['cel']
    )

    await page.wait_for_timeout(600)

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
