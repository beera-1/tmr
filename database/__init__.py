import asyncio
import logging
import aiohttp
import cloudscraper
from bs4 import BeautifulSoup
import re
from datetime import datetime
from database import db
from configs import *
from aiohttp import web
from pyrogram import Client, enums
import traceback
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)

message_lock = asyncio.Lock()
executor = ThreadPoolExecutor(max_workers=10)

# Initialize cloudscraper for Cloudflare bypass
scraper = cloudscraper.create_scraper()

# Telegram Client
bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- SCRAPER FUNCTION -------------------
async def fetch_html(url):
    """Fetch page HTML with retry and Cloudflare bypass."""
    for attempt in range(3):
        try:
            response = scraper.get(url, timeout=15)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            logging.warning(f"[Retry {attempt+1}] Failed fetching {url}: {e}")
            await asyncio.sleep(2)
    return None


async def parse_links(url):
    """Parse and extract links from given URL."""
    html = await fetch_html(url)
    if not html:
        logging.error(f"Failed to fetch {url}")
        return []

    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.find_all("a", href=True):
        link = a["href"]
        if "magnet:?" in link or "torrent" in link:
            title = a.get_text(strip=True)
            links.append({"title": title, "link": link})
    return links


# ------------------- TELEGRAM POSTER -------------------
async def post_to_telegram(client, chat_id, title, link):
    """Send formatted message to Telegram group/channel."""
    try:
        msg_text = f"<b>{title}</b>\n<code>{link}</code>"
        await client.send_message(
            chat_id=chat_id,
            text=msg_text,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logging.info(f"✅ Posted: {title}")
    except Exception as e:
        logging.error(f"❌ Telegram post failed: {e}")


# ------------------- MAIN TASK -------------------
async def scrape_and_post():
    """Main loop to scrape and post new links."""
    urls = [
        "https://www.1tamilmv.kim/",
        "https://1tamilblasters.fi/",
    ]

    async with bot:
        for url in urls:
            try:
                domain = urlparse(url).netloc
                results = await parse_links(url)

                for item in results:
                    title, link = item["title"], item["link"]

                    # Check if already posted
                    if await db.exists(link):
                        continue

                    await db.save(link)
                    await post_to_telegram(bot, TARGET_CHAT, title, link)
            except Exception as e:
                logging.error(f"Error processing {url}: {traceback.format_exc()}")


# ------------------- FLASK WEBHOOK -------------------
async def handle_health(request):
    return web.Response(text="OK")

async def start_web_app():
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"🌐 Web server running on port {PORT}")


# ------------------- ENTRY POINT -------------------
async def main():
    await asyncio.gather(scrape_and_post(), start_web_app())

if __name__ == "__main__":
    asyncio.run(main())
