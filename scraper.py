import asyncio
import random
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import URL_HOME, HEADLESS, UA
from logger import log


async def pause(lo=1.0, hi=3.0):
    await asyncio.sleep(random.uniform(lo, hi))


async def set_date_shadow(page, field_id, date_value):
    """Set a date input value inside shadow DOM of #spv-quote-latest-home.
    date_value should be YYYY-MM-DD format.
    """
    result = await page.evaluate(f"""() => {{
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return 'no host or shadow';
        const inp = host.shadowRoot.getElementById('{field_id}');
        if (!inp) return 'input not found: {field_id}';
        inp.value = '{date_value}';
        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
        return 'ok:' + inp.value;
    }}""")
    log(f"set_date_shadow({field_id}, {date_value}): {result}")
    return 'ok' in str(result)


async def click_cotizar_shadow(page):
    """Click the #btn-quote submit button inside shadow DOM."""
    result = await page.evaluate("""() => {
        const host = document.getElementById('spv-quote-latest-home');
        if (!host || !host.shadowRoot) return 'no host or shadow';
        const btn = host.shadowRoot.getElementById('btn-quote');
        if (!btn) return 'btn not found';
        btn.click();
        return 'clicked';
    }""")
    log(f"click_cotizar_shadow: {result}")
    return 'clicked' in str(result)


async def extract_plans_from_text(page_text, days):
    """
    Parse plan names and prices from the cotizar results page text.
    
    Expected pattern in page text:
        Esencial
        Precio hoy
        -30%
        $99,952 COP
        $142,788 COP
        ...
        Estándar
        ...
    """
    plans = []
    
    # Plan names from the site
    plan_names = ['Esencial', 'Estándar', 'Ideal', 'Premium', 'Elite', 'Básico', 'Completo', 'Plus']
    
    lines = page_text.split('\n')
    lines = [l.strip() for l in lines if l.strip()]
    
    for i, line in enumerate(lines):
        if line in plan_names:
            plan_name = line
            price = None
            original_price = None
            discount = None
            
            # Look ahead up to 10 lines for price pattern
            for j in range(i+1, min(i+12, len(lines))):
                # Price pattern: $99,952 COP or $119,364 COP
                price_match = re.search(r'\$([\d,]+)\s*COP', lines[j])
                if price_match and price is None:
                    price = lines[j]
                    # Clean: "99952"
                    price_clean = re.sub(r'[^\d]', '', price_match.group(1))
                elif price_match and original_price is None and price is not None:
                    original_price = lines[j]
                    
                # Discount pattern: -30% or -35%
                disc_match = re.search(r'-(\d+)%', lines[j])
                if disc_match and discount is None:
                    discount = '-' + disc_match.group(1) + '%'
                
                # Stop if we hit another plan name
                if lines[j] in plan_names and lines[j] != plan_name:
                    break
            
            if price:
                price_clean = re.sub(r'[^\d]', '', re.search(r'\$([\d,]+)\s*COP', price).group(1)) if re.search(r'\$([\d,]+)\s*COP', price) else price
                orig_clean = re.sub(r'[^\d]', '', re.search(r'\$([\d,]+)\s*COP', original_price).group(1)) if original_price and re.search(r'\$([\d,]+)\s*COP', original_price) else ''
                
                plans.append({
                    'plan': plan_name,
                    'price': price_clean,
                    'original_price': orig_clean,
                    'discount': discount or '',
                    'currency': 'COP',
                    'days': days,
                })
                log(f"  Found plan: {plan_name} = {price_clean} COP (orig: {orig_clean}, disc: {discount})")
    
    if not plans:
        log(f"WARNING: No plans found in text for {days} days. Text sample: {page_text[:300]}")
        plans.append({
            'plan': 'NO_RESULTS',
            'price': '',
            'original_price': '',
            'discount': '',
            'currency': '',
            'days': days,
        })
    
    return plans


async def quote_duration(page, days):
    """
    Starting from the homepage, set dates for a given duration and submit.
    Returns list of plan dicts.
    """
    log(f"=== Quote: {days} days ===")
    
    dep_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    ret_date = (datetime.now() + timedelta(days=30 + days)).strftime('%Y-%m-%d')
    log(f"  Dates: {dep_date} -> {ret_date}")
    
    # Navigate to homepage
    await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
    await pause(2.0, 3.5)
    
    # Set departure date in shadow DOM
    ok1 = await set_date_shadow(page, 'departureDate', dep_date)
    await pause(0.5, 1.0)
    
    # Set return date in shadow DOM
    ok2 = await set_date_shadow(page, 'arrivalDate', ret_date)
    await pause(0.8, 1.5)
    
    if not (ok1 and ok2):
        log(f"WARNING: Date setting may have failed: dep={ok1}, ret={ok2}")
    
    # Click the quote button
    clicked = await click_cotizar_shadow(page)
    if not clicked:
        log("WARNING: Quote button click may have failed")
    
    # Wait for navigation to /cotizar/ page
    try:
        await page.wait_for_url('**/cotizar/**', timeout=20000)
        log(f"  Navigated to: {page.url}")
    except PWTimeout:
        log(f"  Navigation timeout. Current URL: {page.url}")
    
    await pause(2.0, 4.0)
    await page.wait_for_load_state('networkidle', timeout=20000)
    await pause(1.0, 2.0)
    
    # Extract text from results page
    page_text = await page.evaluate("""() => {
        return document.body.innerText || document.body.textContent || '';
    }""")
    
    log(f"  Page text length: {len(page_text)} chars")
    log(f"  URL: {page.url}")
    
    plans = await extract_plans_from_text(page_text, days)
    log(f"  Extracted {len(plans)} plans for {days} days")
    return plans


async def run():
    """
    Single browser session: quote for 10, 20, 30 days for Europe.
    Human-like behavior throughout.
    """
    log("Starting SPV scraper - single session, 3 durations (Europa)")
    all_plans = []
    durations = [10, 20, 30]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=['--no-sandbox', '--disable-setuid-sandbox',
                  '--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent=UA,
            viewport={'width': 1280, 'height': 800},
            locale='es-CO',
            timezone_id='America/Bogota'
        )
        page = await context.new_page()
        
        # Mask automation signals
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        
        for days in durations:
            try:
                plans = await quote_duration(page, days)
                all_plans.extend(plans)
                # Human pause between quotes
                await pause(3.0, 6.0)
            except Exception as e:
                log(f"Error quoting {days} days: {e}")
                all_plans.append({
                    'plan': 'ERROR',
                    'price': '',
                    'original_price': '',
                    'discount': '',
                    'currency': '',
                    'days': days,
                })
        
        await context.close()
        await browser.close()
    
    log(f"Scraping complete. Total plans: {len(all_plans)}")
    for p in all_plans:
        log(f"  {p['days']}d | {p['plan']} | {p['price']} COP")
    return all_plans


if __name__ == '__main__':
    asyncio.run(run())
