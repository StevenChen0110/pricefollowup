import asyncio
import re
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


@dataclass
class ScrapeResult:
    name: str
    price: float
    image_url: Optional[str]
    url: str
    in_stock: bool = True
    error: Optional[str] = None


async def _scrape_momo(page, url: str) -> ScrapeResult:
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)

    # price selector — Momo uses class patterns that change; try multiple
    price_selectors = [
        "span.price",
        "[class*='goodsPrice'] b",
        "[class*='price'] b",
        "b.price",
    ]
    price_text = None
    for sel in price_selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=5000)
            price_text = await el.inner_text()
            break
        except PlaywrightTimeout:
            continue

    if price_text is None:
        return ScrapeResult(name="", price=0, image_url=None, url=url,
                            error="找不到價格元素，Momo 頁面結構可能已更新")

    price = float(re.sub(r"[^\d.]", "", price_text))

    # product name
    name = await page.title()
    name = re.sub(r"\s*[-|]\s*momo.*$", "", name, flags=re.IGNORECASE).strip()

    # image
    image_url = None
    try:
        img = await page.query_selector("img#goodsImg, [class*='goodsImg'] img")
        if img:
            image_url = await img.get_attribute("src")
    except Exception:
        pass

    return ScrapeResult(name=name, price=price, image_url=image_url, url=url)


async def _search_momo(page, keyword: str) -> list[ScrapeResult]:
    search_url = f"https://www.momoshop.com.tw/search/searchShop.jsp?keyword={keyword}&searchType=1&ctype=1&ent=k"
    await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

    results = []
    items = await page.query_selector_all("li.listArea")
    for item in items[:8]:
        try:
            name_el = await item.query_selector("[class*='goodsName']")
            price_el = await item.query_selector("b.price, [class*='price'] b")
            link_el = await item.query_selector("a")
            img_el = await item.query_selector("img")

            if not (name_el and price_el and link_el):
                continue

            name = (await name_el.inner_text()).strip()
            price_text = (await price_el.inner_text()).strip()
            price = float(re.sub(r"[^\d.]", "", price_text))
            href = await link_el.get_attribute("href")
            url = href if href.startswith("http") else f"https://www.momoshop.com.tw{href}"
            image_url = await img_el.get_attribute("src") if img_el else None

            results.append(ScrapeResult(name=name, price=price, image_url=image_url, url=url))
        except Exception:
            continue

    return results


async def scrape(query: str) -> list[ScrapeResult]:
    """
    query: Momo URL → scrape single product
           keyword   → search and return list
    """
    is_url = query.startswith("http")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        try:
            if is_url:
                result = await _scrape_momo(page, query)
                return [result]
            else:
                return await _search_momo(page, query)
        finally:
            await browser.close()


def scrape_sync(query: str) -> list[ScrapeResult]:
    return asyncio.run(scrape(query))
