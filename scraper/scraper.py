import asyncio
import pandas as pd
from playwright.async_api import async_playwright

REQUEST_DELAY = 1.5  # seconds between requests


async def get_job_links(page, base_url: str) -> list[str]:
    """
    Given a careers page, find all individual job listing links.
    Handles pagination and infinite scroll.
    """
    job_links = set()

    # keywords that suggest a link is a job listing
    job_keywords = [
        "job", "career", "position", "role", "opening",
        "vacancy", "apply", "opportunity", "hire"
    ]

    async def extract_links():
        anchors = await page.query_selector_all("a[href]")
        for anchor in anchors:
            href = await anchor.get_attribute("href")
            if not href:
                continue

            # make relative URLs absolute
            if href.startswith("/"):
                from urllib.parse import urlparse
                parsed = urlparse(base_url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"

            # check if URL looks like a job listing
            href_lower = href.lower()
            if any(keyword in href_lower for keyword in job_keywords):
                job_links.add(href)

    # initial extract
    await extract_links()

    # handle infinite scroll — scroll down repeatedly
    previous_count = 0
    max_scrolls = 10
    scroll_attempts = 0

    while scroll_attempts < max_scrolls:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1.5)
        await extract_links()

        if len(job_links) == previous_count:
            break  # nothing new loaded, stop scrolling

        previous_count = len(job_links)
        scroll_attempts += 1

    # handle "load more" button
    load_more_selectors = [
        "button:has-text('Load more')",
        "button:has-text('Show more')",
        "button:has-text('See more')",
        "button:has-text('View more')",
        "a:has-text('Load more')",
        "a:has-text('Next')",
    ]

    for selector in load_more_selectors:
        while True:
            try:
                button = await page.query_selector(selector)
                if not button:
                    break
                await button.click()
                await asyncio.sleep(1.5)
                await extract_links()
            except Exception:
                break

    return list(job_links)


async def scrape_company(playwright, company: str, careers_url: str) -> list[dict]:
    """
    Scrape all job links from a company careers page.
    Returns list of {company, url} dicts.
    """
    print(f"\n[{company}] Starting scrape: {careers_url}")

    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-images",        # skip images — faster, less memory
            "--disable-javascript",    # will re-enable if needed
        ]
    )

    # re-launch with JS enabled (most careers pages need it)
    await browser.close()
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
    )

    context = await browser.new_context(
        # block images and fonts to save memory
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"}
    )

    # block images, fonts, stylesheets to save memory
    await context.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,css}", 
                        lambda route: route.abort())

    page = await context.new_page()

    try:
        await page.goto(careers_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(REQUEST_DELAY)

        job_links = await get_job_links(page, careers_url)
        print(f"[{company}] Found {len(job_links)} job links")

        return [{"company": company, "url": link} for link in job_links]

    except Exception as e:
        print(f"[{company}] Failed: {e}")
        return []

    finally:
        await browser.close()


async def main():
    # load companies from CSV
    try:
        df = pd.read_csv("/input/companies.csv")
    except FileNotFoundError:
        print("ERROR: /input/companies.csv not found")
        print("Create it with columns: company, careers_url")
        return

    print(f"Loaded {len(df)} companies from CSV")
    print("=" * 50)

    all_jobs = []

    async with async_playwright() as playwright:
        for _, row in df.iterrows():
            company = row["company"]
            careers_url = row["careers_url"]

            jobs = await scrape_company(playwright, company, careers_url)
            all_jobs.extend(jobs)

            await asyncio.sleep(REQUEST_DELAY)  # polite delay between companies

    print("\n" + "=" * 50)
    print(f"DONE — {len(all_jobs)} job links found across {len(df)} companies")
    print("=" * 50)

    # print results
    for job in all_jobs:
        print(f"  [{job['company']}] {job['url']}")


if __name__ == "__main__":
    asyncio.run(main())