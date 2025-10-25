import re
import asyncio
import logging
from datetime import datetime
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from pyrogram import Client
from db_instance import db          # Use the singleton DB instance
from configs import *

message_lock = asyncio.Lock()

# ------------------ FETCH URL ------------------ #
async def fetch(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/113.0.0.0 Safari/537.36"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                resp.raise_for_status()
                return await resp.text()
    except Exception as e:
        logging.error(f"Error fetching {url}: {str(e)}")
        return None

# ------------------ PARSE MAIN PAGE LINKS ------------------ #
async def parse_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/index.php?/forums/topic/" in href and href not in links:
            links.append(href)
            if len(links) >= 60:
                break
    return links

# ------------------ CONVERT SIZE STRING TO BYTES ------------------ #
def get_size_in_bytes(size_str):
    size_str = size_str.strip().lower()
    match = re.search(r"(\d+(?:\.\d+)?)(gb|mb)", size_str)
    if match:
        size, unit = float(match.group(1)), match.group(2)
        return size * (1024 ** 3) if unit == "gb" else size * (1024 ** 2)
    return None

# ------------------ FETCH ATTACHMENTS ------------------ #
async def fetch_attachments(page_url):
    html = await fetch(page_url)
    if not html:
        return None

    mkv_torrent_removal_regex = re.compile(r"\.mkv\.torrent$", re.IGNORECASE)

    soup = BeautifulSoup(html, "html.parser")
    links = []

    content_div = soup.find("div", class_="cPost_contentWrap ipsPad")
    img_url = None
    if content_div:
        inner_div = content_div.find("div", class_="ipsType_normal ipsType_richText ipsContained")
        if inner_div:
            img_tag = inner_div.find("img")
            if img_tag and img_tag.get("data-src"):
                img_url = img_tag["data-src"]

    for link_tag in soup.find_all("a", href=True):
        if "attachment.php" in link_tag["href"]:
            attachment_url = urljoin(BASE_URL, link_tag["href"])
            link_text = link_tag.get_text(strip=True)
            size_in_bytes = get_size_in_bytes(link_text)
            clean_name = mkv_torrent_removal_regex.sub("", link_text).strip()

            if size_in_bytes and size_in_bytes < 4 * 1024 ** 3:
                links.append({"name": clean_name, "link": attachment_url, "size": size_in_bytes})

    document = {"img_url": img_url, "links": links, "added_on": datetime.utcnow()}
    await db.add_document(document)
    return document

# ------------------ MAIN LOOP ------------------ #
async def start_processing():
    main_page_html = await fetch(BASE_URL)
    if main_page_html:
        fetched_links = await parse_links(main_page_html)
        for link in fetched_links:
            logging.info(f"Fetching attachments from {link}")
            await fetch_attachments(link)
    else:
        logging.warning("No content found on the main page!")

# ------------------ WEB SERVER ------------------ #
from aiohttp import web

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("MadxBotz")

async def web_server():
    web_app = web.Application(client_max_size=30_000_000)
    web_app.add_routes(routes)
    return web_app

# ------------------ PYROGRAM USER SESSION ------------------ #
User = Client("User", session_string=USER_SESSION_STRING, api_hash=API_HASH, api_id=API_ID)

async def ping_server():
    while True:
        try:
            await start_processing()
        except Exception as e:
            logging.error(f"Unexpected error: {str(e)}")
        await asyncio.sleep(180)

async def ping_main_server():
    try:
        await User.start()
        logging.info("User Session started.")
        await User.send_message(GROUP_ID, "User Session Started")
    except Exception as e:
        logging.error(f"Error Starting User: {str(e)}")

    while True:
        await asyncio.sleep(250)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(SERVER_URL) as resp:
                    logging.info(f"Pinged server with response: {resp.status}")
        except Exception:
            logging.warning("Couldn't connect to the site URL.")
            pass

async def stop_user():
    await User.send_message(GROUP_ID, "User Session Stopped")
    await User.stop()
    logging.info("User Session Stopped.")
