import asyncio
import random
import os
import re
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

from config import (
    URL_HOME, USER_NAME, USER_EMAIL, USER_PHONE,
    HEADLESS, UA
)
from logger import log


async def pause(lo=1.0, hi=3.0):
    await asyncio.sleep(random.uniform(lo, hi))


async def human_type(page, selector, text, delay_lo=80, delay_hi=200):
    """Type text character by character with random delays (human simulation)."""
    await page.click(selector)
    await pause(0.3, 0.7)
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(delay_lo, delay_hi) / 1000.0)


async def scroll_smooth(page, pixels=300):
    """Smooth scroll to simulate human behavior."""
    steps = random.randint(3, 6)
    for _ in range(steps):
        await page.evaluate(f'window.scrollBy(0, {pixels // steps})')
        await asyncio.sleep(random.uniform(0.1, 0.3))


async def fill_form_shadow(page, origin, destination, dep_date, ret_date):
    """Fill the quote form handling Shadow DOM inputs."""
    log(f"Filling form: {origin} -> {destination}, {dep_date} to {ret_date}")

    # Wait for page to fully load
    await page.wait_for_load_state('networkidle', timeout=30000)
    await pause(1.5, 3.0)

    # Scroll gently to the form area
    await scroll_smooth(page, 200)
    await pause(0.5, 1.5)

    # Helper to evaluate inside shadow DOM
    async def shadow_fill(host_selector, input_selector, value):
        result = await page.evaluate(f"""() => {{
            const host = document.querySelector('{host_selector}');
            if (!host) return 'host not found: {host_selector}';
            const root = host.shadowRoot;
            if (!root) return 'no shadowRoot';
            const inp = root.querySelector('{input_selector}');
            if (!inp) return 'input not found: {input_selector}';
            inp.focus();
            inp.value = '';
            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
            inp.value = '{value}';
            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
            return 'ok';
        }}""")
        log(f"shadow_fill({host_selector}, {input_selector}): {result}")
        return result

    # Fill destination field - try multiple approaches
    filled = False

    # Approach 1: Direct page inputs
    try:
        inputs = await page.query_selector_all('input[type="text"], input[placeholder*="destino" i], input[placeholder*="destination" i]')
        for inp in inputs:
            placeholder = await inp.get_attribute('placeholder') or ''
            if 'destino' in placeholder.lower() or 'destination' in placeholder.lower():
                await inp.click()
                await pause(0.3, 0.6)
                await inp.fill(destination)
                filled = True
                log(f"Filled destination via direct input: {destination}")
                break
    except Exception as e:
        log(f"Direct input approach failed: {e}")

    # Fill dates using visible date inputs
    try:
        date_inputs = await page.query_selector_all('input[type="date"], input[placeholder*="fecha" i], input[placeholder*="date" i]')
        log(f"Found {len(date_inputs)} date inputs")
        if len(date_inputs) >= 2:
            await date_inputs[0].click()
            await date_inputs[0].fill(dep_date)
            await pause(0.5, 1.0)
            await date_inputs[1].click()
            await date_inputs[1].fill(ret_date)
            log(f"Filled dates: {dep_date} -> {ret_date}")
    except Exception as e:
        log(f"Date fill failed: {e}")

    await pause(1.0, 2.0)


async def click_cotizar(page):
    """Click the main quote button."""
    log("Clicking quote button...")
    await pause(0.8, 1.5)

    # Try different button selectors
    buttons_to_try = [
        'button:has-text("Cotiza")',
        'button:has-text("Cotizar")',
        'button:has-text("Buscar")',
        'button[type="submit"]',
        'input[type="submit"]',
    ]

    for selector in buttons_to_try:
        try:
            btn = await page.query_selector(selector)
            if btn:
                await btn.scroll_into_view_if_needed()
                await pause(0.3, 0.8)
                await btn.click()
                log(f"Clicked button: {selector}")
                return True
        except Exception as e:
            log(f"Button {selector} failed: {e}")

    # Last resort: evaluate to find and click button with "cotiza" text
    result = await page.evaluate("""() => {
        const buttons = Array.from(document.querySelectorAll('button, input[type="submit"], a'));
        const btn = buttons.find(b => /cotiz|buscar|quote/i.test(b.textContent || b.value || ''));
        if (btn) { btn.click(); return 'clicked: ' + (btn.textContent || btn.value).trim().substring(0, 40); }
        return 'no button found';
    }""")
    log(f"Fallback button click: {result}")
    return True


async def extract_text_plans(page, days):
    """Extract plan data using full text parsing - no fragile CSS selectors."""
    log(f"Extracting plans from page text (days={days})...")

    await pause(2.0, 4.0)

    # Get full visible text from page
    page_text = await page.evaluate("""() => {
        // Remove scripts and styles
        const clone = document.cloneNode(true);
        const scripts = clone.querySelectorAll('script, style, noscript');
        scripts.forEach(s => s.remove());
        return document.body.innerText || document.body.textContent;
    }""")

    log(f"Page text length: {len(page_text)} chars")
    log(f"Page text sample (first 500): {page_text[:500]}")

    plans = []

    # Strategy 1: Find prices with COP or USD patterns
    # Match patterns like "COP 1.234.567" or "$ 1,234" or "1.234.567 COP"
    price_patterns = [
        r'COP\s*[\$]?\s*([\d][\d.,]+)',
        r'USD\s*[\$]?\s*([\d][\d.,]+)',
        r'\$\s*([\d][\d.,]{4,})',
        r'([\d][\d.,]+)\s*COP',
        r'([\d][\d.,]+)\s*USD',
    ]

    all_prices = []
    for pattern in price_patterns:
        matches = re.findall(pattern, page_text, re.IGNORECASE)
        for m in matches:
            # Clean the price
            clean = re.sub(r'[^\d]', '', m)
            if len(clean) >= 4:  # At least 4 digits = meaningful price
                all_prices.append(clean)

    log(f"Found {len(all_prices)} price candidates: {all_prices[:10]}")

    # Strategy 2: Look for plan name keywords
    plan_keywords = [
        'básico', 'basic', 'esencial', 'essential', 'estándar', 'standard',
        'plus', 'premium', 'elite', 'gold', 'platinum', 'full', 'completo',
        'económico', 'económic', 'asistencia', 'protection', 'protección',
        'traveler', 'viajero', 'explorer', 'explorador'
    ]

    # Find lines that contain plan names near prices
    lines = page_text.split('\n')
    plan_lines = []
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if any(kw in line_lower for kw in plan_keywords) and len(line.strip()) > 3:
            # Check nearby lines for price
            context = ' '.join(lines[max(0,i-3):min(len(lines),i+4)])
            price_in_context = re.search(r'[\d][\d.,]{4,}', context)
            plan_lines.append({
                'name': line.strip(),
                'context': context[:200],
                'has_price': bool(price_in_context)
            })

    log(f"Found {len(plan_lines)} plan-named lines")
    for pl in plan_lines[:5]:
        log(f"  Plan line: {pl['name'][:60]} | has_price={pl['has_price']}")

    # Strategy 3: Try to find structured cards via evaluate
    cards_data = await page.evaluate("""() => {
        const results = [];

        // Try common result card patterns
        const cardSelectors = [
            '[class*="card"]', '[class*="plan"]', '[class*="result"]',
            '[class*="seguro"]', '[class*="producto"]', '[class*="oferta"]',
            '[class*="cotiz"]', '[class*="precio"]', 'article', '.item'
        ];

        let cards = [];
        for (const sel of cardSelectors) {
            const found = document.querySelectorAll(sel);
            if (found.length > 0 && found.length < 50) {
                cards = Array.from(found);
                break;
            }
        }

        // Also try shadow DOM
        const shadowHosts = document.querySelectorAll('*');
        shadowHosts.forEach(host => {
            if (host.shadowRoot) {
                const shadowText = host.shadowRoot.textContent || '';
                if (/COP|USD|\$[\d]/.test(shadowText)) {
                    results.push({
                        source: 'shadow:' + host.tagName + '.' + (host.className || '').substring(0, 30),
                        text: shadowText.substring(0, 500)
                    });
                }
            }
        });

        for (const card of cards.slice(0, 20)) {
            const text = card.innerText || card.textContent || '';
            if (/[\d]{4,}/.test(text) || /COP|USD/.test(text)) {
                results.push({
                    source: 'card:' + card.className.substring(0, 40),
                    text: text.substring(0, 300)
                });
            }
        }

        return results;
    }""")

    log(f"Card extraction found {len(cards_data)} items")
    for card in cards_data[:5]:
        log(f"  Card [{card['source']}]: {card['text'][:100]}")

    # Build final plans list from what we found
    if plan_lines:
        for i, pl in enumerate(plan_lines[:5]):
            # Find associated price
            price_match = re.search(r'([\d][\d.,]{4,})', pl['context'])
            price_val = price_match.group(1) if price_match else 'N/A'
            currency = 'COP'
            if 'USD' in pl['context'].upper():
                currency = 'USD'

            plans.append({
                'plan': pl['name'][:60],
                'price': price_val,
                'currency': currency,
                'days': days,
                'source': 'text_parse'
            })
    elif all_prices:
        # We have prices but no plan names - use generic names
        for i, price in enumerate(all_prices[:5]):
            plans.append({
                'plan': f'Plan_{i+1}',
                'price': price,
                'currency': 'COP',
                'days': days,
                'source': 'price_only'
            })
    elif cards_data:
        for card in cards_data[:3]:
            price_match = re.search(r'([\d][\d.,]{4,})', card['text'])
            price_val = price_match.group(1) if price_match else 'N/A'
            plans.append({
                'plan': card['source'][:40],
                'price': price_val,
                'currency': 'COP',
                'days': days,
                'source': 'card_extract'
            })

    if not plans:
        log("WARNING: No plans found - saving partial data")
        plans.append({
            'plan': 'NO_RESULTS',
            'price': 'N/A',
            'currency': 'N/A',
            'days': days,
            'source': 'empty'
        })

    log(f"Extracted {len(plans)} plans for {days} days")
    return plans


async def get_trip_dates(days_duration):
    """Generate departure and return dates for a trip."""
    dep = datetime.now() + timedelta(days=30)
    ret = dep + timedelta(days=days_duration)
    return dep.strftime('%Y-%m-%d'), ret.strftime('%Y-%m-%d')


async def run():
    """
    Single browser session: quote for 10, 20, 30 days for Europe.
    Human-like behavior throughout.
    """
    log("Starting SPV scraper - single session, 3 durations")
    all_plans = []

    durations = [10, 20, 30]
    origin = 'Colombia'
    destination = 'Europa'

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
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

        # --- First quote: 10 days ---
        log(f"=== Quote 1: {durations[0]} days ===")
        dep_date, ret_date = await get_trip_dates(durations[0])

        await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
        await pause(2.0, 4.0)

        await fill_form_shadow(page, origin, destination, dep_date, ret_date)
        await pause(1.0, 2.0)
        await click_cotizar(page)
        await page.wait_for_load_state('networkidle', timeout=30000)
        await pause(3.0, 5.0)

        plans_10 = await extract_text_plans(page, durations[0])
        all_plans.extend(plans_10)

        # --- Second quote: 20 days - modify dates only ---
        log(f"=== Quote 2: {durations[1]} days ===")
        dep_date2, ret_date2 = await get_trip_dates(durations[1])
        await pause(2.0, 4.0)

        # Go back to home to refill form
        await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
        await pause(2.0, 3.5)

        await fill_form_shadow(page, origin, destination, dep_date2, ret_date2)
        await pause(1.0, 2.0)
        await click_cotizar(page)
        await page.wait_for_load_state('networkidle', timeout=30000)
        await pause(3.0, 5.0)

        plans_20 = await extract_text_plans(page, durations[1])
        all_plans.extend(plans_20)

        # --- Third quote: 30 days ---
        log(f"=== Quote 3: {durations[2]} days ===")
        dep_date3, ret_date3 = await get_trip_dates(durations[2])
        await pause(2.0, 4.0)

        await page.goto(URL_HOME, wait_until='domcontentloaded', timeout=30000)
        await pause(2.0, 3.5)

        await fill_form_shadow(page, origin, destination, dep_date3, ret_date3)
        await pause(1.0, 2.0)
        await click_cotizar(page)
        await page.wait_for_load_state('networkidle', timeout=30000)
        await pause(3.0, 5.0)

        plans_30 = await extract_text_plans(page, durations[2])
        all_plans.extend(plans_30)

        await context.close()
        await browser.close()

    log(f"Scraping complete. Total plans collected: {len(all_plans)}")
    return all_plans


if __name__ == '__main__':
    asyncio.run(run())
