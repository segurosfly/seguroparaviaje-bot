import asyncio
import random
import os
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import (
    URL_HOME, USER_NAME, USER_EMAIL, USER_PHONE,
    DURATIONS, DIR_SCREENSHOTS, HEADLESS, UA, get_trip_dates
)
from logger import log

os.makedirs(DIR_SCREENSHOTS, exist_ok=True)


async def pause(lo=0.4, hi=1.2):
    await asyncio.sleep(random.uniform(lo, hi))


async def shot(page, label):
    ts = datetime.now().strftime('%H%M%S')
    path = os.path.join(DIR_SCREENSHOTS, ts + '_' + label + '.png')
    await page.screenshot(path=path, full_page=False)
    log.info('Screenshot: ' + path)
    return path


async def shadow_eval(page, js):
    script = (
        '(function(){'
        'var host=document.getElementById("spv-quote-latest-home");'
        'if(!host||!host.shadowRoot)return null;'
        'var shadow=host.shadowRoot;' + js + '})()'
    )
    return await page.evaluate(script)


async def wait_shadow(page, retries=8):
    check_js = (
        "(function(){"
        "var h=document.getElementById('spv-quote-latest-home');"
        "return !!(h&&h.shadowRoot&&h.shadowRoot.querySelector('#btn-quote'));"
        "})()"
    )
    for i in range(retries):
        ready = await page.evaluate(check_js)
        if ready:
            log.info('Shadow DOM listo')
            return True
        log.info('Esperando Shadow DOM... intento ' + str(i + 1))
        await asyncio.sleep(2)
    return False

async def fill_shadow_form(page, departure, arrival):
    dep_js = (
        "var dep=shadow.querySelector('#departureDate');"
        "dep.value='" + departure + "';"
        "dep.dispatchEvent(new Event('input',{bubbles:true}));"
        "dep.dispatchEvent(new Event('change',{bubbles:true}));"
    )
    await shadow_eval(page, dep_js)
    await pause(0.3, 0.6)

    arr_js = (
        "var arr=shadow.querySelector('#arrivalDate');"
        "arr.value='" + arrival + "';"
        "arr.dispatchEvent(new Event('input',{bubbles:true}));"
        "arr.dispatchEvent(new Event('change',{bubbles:true}));"
    )
    await shadow_eval(page, arr_js)
    await pause(0.3, 0.6)

    for fid, val in [('#fullName', USER_NAME), ('#email', USER_EMAIL), ('#phone', USER_PHONE)]:
        field_js = (
            "var el=shadow.querySelector('" + fid + "');"
            "if(el){el.value='" + val + "';"
            "el.dispatchEvent(new Event('input',{bubbles:true}));"
            "el.dispatchEvent(new Event('change',{bubbles:true}));}"
        )
        await shadow_eval(page, field_js)
        await pause(0.2, 0.5)

    log.info('Fechas: ' + departure + ' -> ' + arrival)


async def click_cotizar(page):
    await shadow_eval(page, "shadow.querySelector('#btn-quote').click();")
    log.info('Click en Cotiza Gratis')


async def wait_results(page):
    try:
        await page.wait_for_load_state('networkidle', timeout=30000)
        log.info('Resultados cargados')
        return True
    except PWTimeout:
        log.warning('Timeout esperando resultados')
        html_snap = await page.inner_text('body') if await page.query_selector('body') else ''
        log.warning('Body text (400c): ' + html_snap[:400])
        return False


async def extract_plans(page):
    js = """
    (function(){
        var cards = document.querySelectorAll('.h-90.cursor-pointer');
        var result = [];
        cards.forEach(function(card){
            var text = card.textContent;
            var nameEl = card.querySelector('.plan-name');
            var name = nameEl ? nameEl.textContent.trim() : 'Desconocido';
            var pm = text.match(/\$([\d,]+)\s*COP/);
            var precio = pm ? pm[1].replace(/,/g,'') : '';
            var all = text.match(/\$[\d,]+\s*COP/g) || [];
            var orig = all.length > 1 ? all[1].replace(/[\$\sCOP,]/g,'') : '';
            var dm = text.match(/-?(\d+)%/);
            var desc = dm ? dm[1] + '%' : '';
            result.push({
                plan: name,
                precio_cop: precio,
                descuento: desc,
                precio_original: orig
            });
        });
        return result;
    })()
    """
    plans = await page.evaluate(js)
    log.info('Planes extraidos: ' + str(len(plans)))
    for p in plans:
        log.info('  ' + p['plan'] + '  $' + p['precio_cop'] + ' COP  ' + p['descuento'])
    return plans


async def modify_dates(page, departure, arrival):
    sel = 'input.form-control.input-form-traveler.b-input-quote'
    inputs = await page.query_selector_all(sel)
    if len(inputs) < 2:
        log.warning('No se encontraron inputs de fecha para modificar')
        return False
    for i, value in enumerate([departure, arrival]):
        await inputs[i].triple_click()
        await pause(0.1, 0.3)
        await inputs[i].type(value, delay=50)
        await pause(0.2, 0.4)
    btn = page.locator('button', has_text='Modificar')
    await btn.first.click()
    log.info('Modificando fechas: ' + departure + ' -> ' + arrival)
    await pause(1.5, 3.0)
    return True

async def run():
    all_records = []
    today = datetime.now().strftime('%Y-%m-%d')
    now   = datetime.now().strftime('%H:%M:%S')

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        ctx = await browser.new_context(
            viewport={'width': 1366, 'height': 768},
            user_agent=UA,
            locale='es-CO',
            timezone_id='America/Bogota',
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        page = await ctx.new_page()

        try:
            log.info('Abriendo ' + URL_HOME)
            await page.goto(URL_HOME, wait_until='networkidle', timeout=60000)
            await pause(2, 4)

            if not await wait_shadow(page):
                log.error('Shadow DOM no disponible — abortando')
                await shot(page, 'error_shadow')
                return all_records

            # Primera cotizacion
            dep0, arr0 = get_trip_dates(DURATIONS[0])
            await fill_shadow_form(page, dep0, arr0)
            await pause(0.8, 1.5)
            await shot(page, 'form_' + str(DURATIONS[0]) + 'd')
            await click_cotizar(page)
            await page.wait_for_load_state('networkidle', timeout=60000)
            await pause(2, 4)

            ok = await wait_results(page)
            await shot(page, 'results_' + str(DURATIONS[0]) + 'd')

            if ok:
                for p in await extract_plans(page):
                    rec = {'fecha': today, 'hora': now,
                           'duracion_dias': DURATIONS[0], **p,
                           'cambio_vs_ayer': '', 'status': 'ok',
                           'screenshot': 'results_' + str(DURATIONS[0]) + 'd.png'}
                    all_records.append(rec)
            else:
                all_records.append({
                    'fecha': today, 'hora': now,
                    'duracion_dias': DURATIONS[0], 'plan': 'ERROR',
                    'precio_cop': '', 'descuento': '', 'precio_original': '',
                    'cambio_vs_ayer': '', 'status': 'error', 'screenshot': ''
                })

            # Duraciones restantes — reusar sesion
            for duration in DURATIONS[1:]:
                dep, arr = get_trip_dates(duration)
                log.info('Cotizando ' + str(duration) + ' dias  (' + dep + ' -> ' + arr + ')')

                if not await modify_dates(page, dep, arr):
                    log.error('No se pudo modificar fechas para ' + str(duration) + 'd')
                    continue

                await page.wait_for_load_state('networkidle', timeout=45000)
                await pause(2, 4)

                ok = await wait_results(page)
                await shot(page, 'results_' + str(duration) + 'd')

                if ok:
                    for p in await extract_plans(page):
                        rec = {'fecha': today, 'hora': now,
                               'duracion_dias': duration, **p,
                               'cambio_vs_ayer': '', 'status': 'ok',
                               'screenshot': 'results_' + str(duration) + 'd.png'}
                        all_records.append(rec)
                else:
                    all_records.append({
                        'fecha': today, 'hora': now,
                        'duracion_dias': duration, 'plan': 'ERROR',
                        'precio_cop': '', 'descuento': '', 'precio_original': '',
                        'cambio_vs_ayer': '', 'status': 'error', 'screenshot': ''
                    })

                await pause(3, 6)

        except Exception as e:
            log.error('Error critico: ' + str(e), exc_info=True)
            try:
                await shot(page, 'error_critico')
            except Exception:
                pass
        finally:
            await browser.close()

    log.info('Scraping terminado. ' + str(len(all_records)) + ' registros.')
    return all_records


if __name__ == '__main__':
    records = asyncio.run(run())
    for r in records:
        print(r)
