import asyncio, logging, aiohttp, re, traceback
from bs4 import BeautifulSoup
from datetime import datetime
from aiohttp import web, ClientSession, ClientTimeout
from pyrogram import Client
from database import db
from configs import *
from concurrent.futures import ThreadPoolExecutor

# ---------------------------- CONFIG ----------------------------
MAX_CONCURRENT_REQUESTS = 6      # Control concurrency
MAX_RETRIES = 3                  # Retry limit for failed fetches
FETCH_DELAY = 1.2                # Delay between fetches to avoid ban
REFRESH_INTERVAL = 180           # Re-scrape interval (seconds)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
    )
}
# -----------------------------------------------------------------

executor = ThreadPoolExecutor()
message_lock = asyncio.Lock()
visited_links = set()  # cache of already processed URLs


# ---------- FETCH FUNCTION ----------
async def fetch(url, session: ClientSession):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, headers=HEADERS, timeout=ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    return await resp.text()
                logging.warning(f"[{resp.status}] Retrying {url} (Attempt {attempt})")
        except Exception as e:
            logging.warning(f"Attempt {attempt} failed for {url}: {e}")
        await asyncio.sleep(2)
    logging.error(f"❌ Failed to fetch {url} after {MAX_RETRIES} retries.")
    return None


# ---------- PARSE TOPIC LINKS ----------
async def parse_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for link in soup.find_all("a", href=True):
        if "/index.php?/forums/topic/" in link["href"]:
            full_url = link["href"]
            if full_url not in links:
                links.append(full_url)
            if len(links) >= 60:
                break
    return links


# ---------- FILE SIZE CONVERTER ----------
def get_size_in_bytes(size_str):
    match = re.search(r"(\d+(?:\.\d+)?)(gb|mb)", size_str, re.IGNORECASE)
    if not match:
        return None
    size = float(match.group(1))
    unit = match.group(2).lower()
    return size * 1024**3 if unit == "gb" else size * 1024**2


# ---------- FETCH ATTACHMENTS ----------
async def fetch_attachments(url, session: ClientSession):
    if url in visited_links:
        return
    visited_links.add(url)

    html = await fetch(url, session)
    if not html:
        return

    soup = BeautifulSoup(html, "html.parser")
    img_url, final_links = None, []

    try:
        content_div = soup.find("div", class_="cPost_contentWrap ipsPad")
        if content_div:
            inner_div = content_div.find("div", class_="ipsType_normal ipsType_richText ipsContained")
            if inner_div:
                img_tag = inner_div.find("img")
                if img_tag:
                    img_url = img_tag.get("data-src") or img_tag.get("src")

        for link in soup.find_all("a", href=True):
            if "attachment.php" not in link["href"]:
                continue
            link_text = link.get_text(strip=True)
            size_in_bytes = get_size_in_bytes(link_text)
            if size_in_bytes and size_in_bytes < 4 * 1024 * 1024 * 1024:  # <4GB filter
                final_links.append({"name": link_text, "link": link["href"], "size": size_in_bytes})

        if final_links:
            await db.add_document({
                "url": url,
                "img_url": img_url,
                "links": final_links,
                "added_on": datetime.utcnow(),
            })
            logging.info(f"✅ Added {len(final_links)} attachments from {url}")

    except Exception:
        logging.error(f"Error parsing {url}")
        traceback.print_exc()


# ---------- PROCESS ALL LINKS ----------
async def start_processing():
    async with aiohttp.ClientSession() as session:
        main_page_html = await fetch(BASE_URL, session)
        if not main_page_html:
            logging.warning("No main page HTML found.")
            return

        topic_links = await parse_links(main_page_html)
        sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        async def sem_task(link):
            async with sem:
                logging.info(f"Fetching attachments from {link}")
                await fetch_attachments(link, session)
                await asyncio.sleep(FETCH_DELAY)

        await asyncio.gather(*(sem_task(l) for l in topic_links))


# ---------- WEB SERVER ----------
routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_handler(request):
    return web.json_response({"status": "MadxBotz running"})


async def web_server():
    app = web.Application(client_max_size=30_000_000)
    app.add_routes(routes)
    return app


# ---------- PING SERVER LOOP ----------
User = Client("User", session_string=USER_SESSION_STRING, api_id=API_ID, api_hash=API_HASH)

async def ping_server():
    while True:
        try:
            await start_processing()
        except Exception as e:
            logging.error(f"Main loop error: {e}")
        await asyncio.sleep(REFRESH_INTERVAL)


async def ping_main_server():
    try:
        await User.start()
        logging.info("User session started.")
        await User.send_message(GROUP_ID, "User session started ✅")
    except Exception as e:
        logging.error(f"User start error: {e}")

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(SERVER_URL, timeout=10) as resp:
                    logging.info(f"Pinged main server: {resp.status}")
        except Exception as e:
            logging.warning(f"Ping failed: {e}")
        await asyncio.sleep(250)


async def stop_user():
    await User.send_message(GROUP_ID, "User session stopped ❌")
    await User.stop()
    logging.info("User session stopped.")
