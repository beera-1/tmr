import asyncio
import logging
import aiohttp
from bs4 import BeautifulSoup
import re
from datetime import datetime
from database import db
from configs import *
from aiohttp import web
from pyrogram import Client
import traceback
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

message_lock = asyncio.Lock()
executor = ThreadPoolExecutor()

# --------------------------- FETCH HTML ---------------------------
async def fetch(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
        )
    }
    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(executor, lambda: requests.get(url, headers=headers))
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching {url}: {e}")
        return None

# --------------------------- PARSE TOPIC LINKS ---------------------------
async def parse_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for link in soup.find_all("a", href=True):
        if "/index.php?/forums/topic/" in link["href"]:
            if link["href"] not in links:
                links.append(link["href"])
            if len(links) >= 60:
                break
    return links

# --------------------------- SIZE CONVERTER ---------------------------
def get_size_in_bytes(size_str):
    size_str = size_str.strip().lower()
    size_match = re.search(r"(\d+(?:\.\d+)?)(gb|mb)", size_str, re.IGNORECASE)
    if size_match:
        size_value = float(size_match.group(1))
        size_unit = size_match.group(2).lower()
        if size_unit == "gb":
            return size_value * 1024 * 1024 * 1024
        elif size_unit == "mb":
            return size_value * 1024 * 1024
    return None

# --------------------------- FETCH ATTACHMENTS ---------------------------
async def fetch_attachments(page_url):
    html = await fetch(page_url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # --------------------------- IMAGE EXTRACTION ---------------------------
    img_url = None
    # Primary: check inside content wrapper
    content_div = soup.find("div", class_="cPost_contentWrap ipsPad")
    if content_div:
        img_tag = content_div.find("img")
        if img_tag:
            img_url = img_tag.get("data-src") or img_tag.get("src")

    # Secondary: check richText container
    if not img_url:
        inner_div = soup.find("div", class_="ipsType_richText ipsContained")
        if inner_div:
            img_tag = inner_div.find("img")
            if img_tag:
                img_url = img_tag.get("data-src") or img_tag.get("src")

    # Fallback: first available image
    if not img_url:
        img_tag = soup.find("img")
        if img_tag:
            img_url = img_tag.get("data-src") or img_tag.get("src")

    # --------------------------- LINK EXTRACTION ---------------------------
    episode_pattern = re.compile(r"E(?:P)?(\d{1,2})", re.IGNORECASE)
    non_episode_regex = re.compile(r"S(\d{1,2})\s*(?:E|EP)?\s*\(?(\d+(?:-\d+))\)?", re.IGNORECASE)
    domain_removal_regex = re.compile(r"\b(www\.[^\s/$.?#].[^\s]*)\b")
    mkv_torrent_removal_regex = re.compile(r"\.mkv\.torrent$")

    links = []
    highest_episode_number = 0
    highest_episode_links = []
    season_based_links = []
    highest_season = 0
    highest_episode_range = (0, 0)

    for link in soup.find_all("a", href=True):
        if "attachment.php" not in link["href"]:
            continue

        attachment_url = link["href"]
        link_text = link.get_text(strip=True)
        size_in_bytes = get_size_in_bytes(link_text)
        clean_link_text = mkv_torrent_removal_regex.sub(domain_removal_regex.sub("", link_text), "").strip()

        # Season detection
        season_match = non_episode_regex.search(link_text)
        if season_match:
            season_number = int(season_match.group(1))
            episode_range = season_match.group(2)
            if "-" in episode_range:
                episode_start, episode_end = map(int, episode_range.split("-"))
            else:
                episode_start = episode_end = int(episode_range)

            if season_number > highest_season or (season_number == highest_season and episode_end > highest_episode_range[1]):
                highest_season = season_number
                highest_episode_range = (episode_start, episode_end)
                season_based_links = [{"name": clean_link_text, "link": attachment_url}]
            elif season_number == highest_season and episode_start <= highest_episode_range[1]:
                season_based_links.append({"name": clean_link_text, "link": attachment_url})

        # Episode detection
        episode_matches = episode_pattern.findall(link_text)
        if episode_matches and size_in_bytes and size_in_bytes < 4 * 1024 * 1024 * 1024:
            current_episode_number = max(int(ep) for ep in episode_matches)
            if current_episode_number > highest_episode_number:
                highest_episode_number = current_episode_number
                highest_episode_links = [{"name": clean_link_text, "link": attachment_url}]
            elif current_episode_number == highest_episode_number:
                highest_episode_links.append({"name": clean_link_text, "link": attachment_url})
        elif size_in_bytes and size_in_bytes < 4 * 1024 * 1024 * 1024:
            links.append({"name": clean_link_text, "link": attachment_url, "size": size_in_bytes})

    final_links = season_based_links or highest_episode_links or links

    document = {"img_url": img_url, "links": final_links, "added_on": datetime.utcnow()}
    await db.add_document(document)
    return document

# --------------------------- MAIN SCRAPER ---------------------------
async def start_processing():
    main_page_html = await fetch(BASE_URL)
    if not main_page_html:
        logging.warning("No content found on the main page!")
        return

    fetched_links = await parse_links(main_page_html)
    for li_link in fetched_links:
        logging.info(f"Fetching attachments from {li_link}")
        await fetch_attachments(li_link)

# --------------------------- WEB SERVER ---------------------------
routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("MadxBotz")

async def web_server():
    app = web.Application(client_max_size=30000000)
    app.add_routes(routes)
    return app

# --------------------------- USER CLIENT ---------------------------
User = Client("User", session_string=USER_SESSION_STRING, api_hash=API_HASH, api_id=API_ID)

# --------------------------- PING SERVER TASKS ---------------------------
async def ping_server():
    while True:
        try:
            await start_processing()
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
        await asyncio.sleep(180)

async def ping_main_server():
    try:
        await User.start()
        logging.info("User Session started.")
        await User.send_message(GROUP_ID, "User Session Started")
    except Exception as e:
        logging.error(f"Error Starting User: {e}")

    while True:
        await asyncio.sleep(250)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(SERVER_URL) as resp:
                    logging.info(f"Pinged server with response: {resp.status}")
        except Exception:
            logging.warning("Couldn't connect to the site URL.")
            traceback.print_exc()

async def stop_user():
    await User.send_message(GROUP_ID, "User Session Stopped")
    await User.stop()
    logging.info("User Session Stopped.")
