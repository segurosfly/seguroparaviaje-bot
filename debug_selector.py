"""
Diagnóstico: abre segurosfly.com/es, espera que cargue,
toma screenshot y vuelca TODOS los elementos visibles del searchbar.
Corre con: python debug_selector.py
"""
import asyncio
from playwright.async_api import async_playwright

URL = "https://segurosfly.com/es"
UA  = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 800},
            locale="es-CO",
        )
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        await page.screenshot(path="debug_A_home.png")
        print("📸 debug_A_home.png guardado")

        # ── 1. Listar todos los segmentos ──────────────────────────────────
        segments = await page.locator(".sf-searchbar__segment").all()
        print(f"\n🔍 Segmentos encontrados: {len(segments)}")
        for i, seg in enumerate(segments):
            try:
                txt = (await seg.inner_text()).strip().replace("\n", " ")[:80]
                cls = await seg.get_attribute("class") or ""
                print(f"  [{i}] class='{cls}' | texto='{txt}'")
            except Exception as e:
                print(f"  [{i}] ERROR: {e}")

        # ── 2. Click en índice 2 (DESTINO) ────────────────────────────────
        print("\n🖱  Clickeando segmento índice 2 (destino)...")
        await segments[2].click()
        await page.wait_for_timeout(2000)
        await page.screenshot(path="debug_B_after_click_seg2.png")
        print("📸 debug_B_after_click_seg2.png")

        # ── 3. Buscar inputs visibles ──────────────────────────────────────
        inputs = await page.locator("input:visible").all()
        print(f"\n📋 Inputs visibles después del click: {len(inputs)}")
        for inp in inputs:
            try:
                ph    = await inp.get_attribute("placeholder") or ""
                cls   = await inp.get_attribute("class") or ""
                itype = await inp.get_attribute("type") or ""
                print(f"  type='{itype}' placeholder='{ph}' class='{cls[:60]}'")
            except Exception as e:
                print(f"  ERROR: {e}")

        # ── 4. Buscar react-select específicamente ─────────────────────────
        rs_containers = await page.locator("[class*='react-select']").all()
        print(f"\n⚛️  Elementos react-select encontrados: {len(rs_containers)}")
        for el in rs_containers[:10]:
            try:
                cls = await el.get_attribute("class") or ""
                tag = await el.evaluate("el => el.tagName")
                print(f"  <{tag}> class='{cls[:80]}'")
            except Exception:
                pass

        # ── 5. Buscar inputs dentro de cualquier dropdown abierto ──────────
        print("\n🔎 Buscando input dentro de dropdown/popover abierto...")
        all_inputs = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('input')).map(el => ({
                placeholder: el.placeholder,
                className: el.className,
                visible: el.offsetParent !== null,
                type: el.type,
                parentClass: el.parentElement ? el.parentElement.className : ''
            }));
        }""")
        for inp in all_inputs:
            if inp['visible']:
                print(f"  VISIBLE | placeholder='{inp['placeholder']}' | class='{inp['className'][:60]}' | parent='{inp['parentClass'][:60]}'")

        await page.wait_for_timeout(2000)
        await browser.close()
        print("\n✅ Diagnóstico completo. Revisa los screenshots y este output.")

asyncio.run(main())
