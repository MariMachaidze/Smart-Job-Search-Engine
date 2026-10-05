import asyncio
from playwright.async_api import async_playwright

# 3 test URLs from Anthropic
TEST_URLS = [
    "https://job-boards.greenhouse.io/anthropic/jobs/5208193008",
    "https://job-boards.greenhouse.io/anthropic/jobs/5234538008",
    "https://job-boards.greenhouse.io/anthropic/jobs/5239733008",
]


async def extract_job_details(page, url: str, company: str) -> dict:
    """
    Visit a job listing URL and extract structured data.
    Returns a dict with title, location, description.
    """
    print(f"  Extracting: {url}")

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(1.0)

        # --- TITLE ---
        title = None
        title_selectors = [
            "h1",
            "[class*='title']",
            "[class*='job-title']",
            "[class*='position']",
        ]
        for selector in title_selectors:
            el = await page.query_selector(selector)
            if el:
                text = await el.inner_text()
                if text.strip():
                    title = text.strip()
                    break

        # --- LOCATION ---
        location = None
        location_selectors = [
            "[class*='location']",
            "[class*='office']",
            "[data-qa='job-location']",
            "[class*='city']",
        ]
        for selector in location_selectors:
            el = await page.query_selector(selector)
            if el:
                text = await el.inner_text()
                if text.strip():
                    location = text.strip()
                    break

        # --- FULL DESCRIPTION ---
        # grab the largest text block on the page
        description = None
        description_selectors = [
            "[class*='content']",
            "[class*='description']",
            "[class*='job-detail']",
            "[class*='details']",
            "main",
            "article",
        ]
        for selector in description_selectors:
            el = await page.query_selector(selector)
            if el:
                text = await el.inner_text()
                if len(text.strip()) > 200:  # must be substantial
                    description = text.strip()
                    break

        # fallback — grab all body text
        if not description:
            body = await page.query_selector("body")
            if body:
                description = await body.inner_text()

        return {
            "company": company,
            "url": url,
            "title": title or "Unknown",
            "location": location or "Unknown",
            "description": description or "",
            "description_length": len(description) if description else 0
        }

    except Exception as e:
        print(f"  Failed: {e}")
        return {
            "company": company,
            "url": url,
            "title": "Error",
            "location": "Error",
            "description": "",
            "description_length": 0
        }


async def main():
    print("Phase 2 — Job Detail Extractor")
    print("=" * 50)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )

        context = await browser.new_context()

        # block images and fonts to save memory
        await context.route(
            "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf}",
            lambda route: route.abort()
        )

        page = await context.new_page()

        results = []
        for url in TEST_URLS:
            job = await extract_job_details(page, url, "Anthropic")
            results.append(job)
            await asyncio.sleep(1.5)  # polite delay

        await browser.close()

    # print results
    print("\n" + "=" * 50)
    print("RESULTS")
    print("=" * 50)

    for job in results:
        print(f"\nCompany:     {job['company']}")
        print(f"Title:       {job['title']}")
        print(f"Location:    {job['location']}")
        print(f"URL:         {job['url']}")
        print(f"Description: {job['description_length']} chars")
        print(f"Preview:     {job['description'][:200]}...")
        print("-" * 50)


if __name__ == "__main__":
    asyncio.run(main())