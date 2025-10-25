import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

import aiohttp
import requests
from bs4 import BeautifulSoup
from pyrogram import Client
from database import db
from configs import *

message_lock = asyncio.Lock()
executor = ThreadPoolExecutor()


# ------------------ FETCH URL WITH HEADERS ------------------ #
async def fetch(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/113.0.0.0 Safari/537.36"
    }

    loop = asyncio.get_event_loop()
    try:
        # Correctly pass headers using lambda
        response = await loop.run_in_executor(executor, lambda: requests.get(url, headers=headers))
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
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
    size_match = re.search(r"(\d+(?:\.\d+)?)(gb|mb)", size_str)
    if size_match:
        size_value = float(size_match.group(1))
        size_unit = size_match.group(2)
        if size_unit == "gb":
            return size_value * 1024 * 1024 * 1024
        elif size_unit == "mb":
            return size_value * 1024 * 1024
    return None


# ------------------ FETCH ATTACHMENTS FROM TOPIC ------------------ #
async def fetch_attachments(page_url):
    html = await fetch(page_url)
    if not html:
        return None

    episode_pattern = re.compile(r"E(?:P)?(\d{1,2})", re.IGNORECASE)
    non_episode_regex = re.compile(r"S(\d{1,2})\s*(?:E|EP)?\s*\(?(\d+(?:-\d+))\)?", re.IGNORECASE)
    domain_removal_regex = re.compile(r"\b(www\.[^\s/$.?#].[^\s]*)\b")
    mkv_torrent_removal_regex = re.compile(r"\.mkv\.torrent$")

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

    highest_episode_number = 0
    highest_episode_links = []
    season_based_links = []
    highest_season = 0
    highest_episode_range = (0, 0)

    for link in soup.find_all("a", href=True):
        if "attachment.php" in link["href"]:
            attachment_url = link["href"]
            link_text = link.get_text(strip=True)
            size_in_bytes = get_size_in_bytes(link_text)

            clean_link_text = domain_removal_regex.sub("", link_text)
            clean_link_text = mkv_torrent_removal_regex.sub("", clean_link_text).strip()

            # Season/Episode detection
            season_match = non_episode_regex.search(link_text)
            if season_match:
                season_number = int(season_match.group(1))
                episode_range = season_match.group(2)
                if "-" in episode_range:
                    episode_start, episode_end = map(int, episode_range.split("-"))
                else:
                    episode_start = episode_end = int(episode_range)

                if season_number > highest_season or (
                    season_number == highest_season and episode_end > highest_episode_range[1]
                ):
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


# ------------------ MAIN PROCESSING LOOP ------------------ #
async def start_processing():
    main_page_html = await fetch(BASE_URL)
    if main_page_html:
        fetched_links = await parse_links(main_page_html)
        for li_link in fetched_links:
            logging.info(f"Fetching attachments from {li_link}")
            await fetch_attachments(li_link)
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
