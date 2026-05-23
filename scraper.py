import asyncio
import random
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import URL_HOME, HEADLESS, UA
from logger import log


# ── helpers ────────────────────────────────────────────────────────────────

async def human_pause(page, lo=2000, hi=5000):
    await page.wait_for_timeout(random.randint(lo, hi))


async def set_shadow_date(page, field_id, iso_date):
    """Set #departureDate / #arrivalDate inside SPV-QUOTE shadow DOM."""
    ok = await page.evaluate(
        """([fid, val]) => {
            const host = document.getElementById('spv-quote-latest-home');
            if (!host || !host.shadowRoot) return 'no-host';
            const inp = host.shadowRoot.getElementById(fid);
            if (!inp) return 'no-input:' + fid;
            inp.value = val;
            inp.dispatchEvent(new Event('input',  {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            return 'ok:' + inp.value;
        }""",
        [field_id, iso_date]
    )
    log.info(f"set_shadow_date({field_id}, {iso_date}) -> {ok}")
    return ok.startswith('ok')


async def click_shadow_btn(page, btn_id):
    """Click a button by id inside the SPV-QUOTE shadow DOM."""
    ok = await page.evaluate(
        """([bid]) => {
            const host = document.getElementById('spv-quote-latest-home');
            if (!host || !host.shadowRoot) return 'no-host';
            const btn = host.shadowRoot.getElementById(bid);
            if (!btn) return 'no-btn:' + bid;
            btn.click();
            return 'clicked';
        }""",
        [btn_id]
    )
    log.info(f"click_shadow_btn({btn_id}) -> {ok}")
    return ok == 'clicked'


# ── extraction ─────────────────────────────────────────────────────────────

async def extract_plans(page, days):
    """
    On the /cotizar/ results page:
    - wait for 'Precio hoy' text to appear
    - grab every div that contains 'Precio hoy'
    - regex-extract plan name, price, discount
    Returns list of dicts.
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

        plan_name  = plan_m.group(1)
        price_raw  = re.sub(r'[^\d]', '', price_m.group(1))
        discount   = f"-{disc_m.group(1)}%" if disc_m else ''

        # second COP price = original (strikethrough)
        prices_all = re.findall(r'\$([\d,.]+)\s*COP', text)
        orig_raw = re.sub(r'[^\d]', '', prices_all[1]) if len(prices_all) > 1 else ''

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


# ── single-session quoting ─────────────────────────────────────────────────

async def quote_one(page, days):
    """Navigate to home, set dates, submit, extract. Same browser session."""
    dep = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    ret = (datetime.now() + timedelta(days=30 + days)).strftime('%Y-%m-%d')
    log.info(f"=== Quote {days}d | {dep} -> {ret} ===")

    await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
    await human_pause(page, 2000, 4000)

    await set_shadow_date(page, 'departureDate', dep)
    await human_pause(page, 500, 1200)
    await set_shadow_date(page, 'arrivalDate', ret)
    await human_pause(page, 800, 1800)

    await click_shadow_btn(page, 'btn-quote')

    # Wait for navigation to /cotizar/ page
    try:
        await page.wait_for_url('**/cotizar/**', timeout=20000)
    except PWTimeout:
        log.error(f"No /cotizar/ navigation for {days}d. URL={page.url}")

    await page.wait_for_load_state('networkidle', timeout=20000)
    await human_pause(page, 2000, 4000)

    return await extract_plans(page, days)


# ── main entry ─────────────────────────────────────────────────────────────

async def run():
    log.info("SPV scraper start — single session, 10 / 20 / 30 days, Europa")
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
            # human pause between quotes
            await human_pause(page, 3000, 6000)

        await ctx.close()
        await browser.close()

    log.info(f"Done. {len(all_plans)} records collected.")
    for r in all_plans:
        log.info(f"  {r['days']}d | {r['plan']} | {r.get('price','')} COP")
    return all_plans


if __name__ == '__main__':
    asyncio.run(run())
