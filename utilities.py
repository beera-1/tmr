import asyncio, logging, aiohttp
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

message_lock = asyncio.Lock()
executor = ThreadPoolExecutor()

BASE_URL = "https://www.1tamilblasters.date"

# ---------------- Fetch HTML with error handling ---------------- #
async def fetch(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/113.0.0.0 Safari/537.36"
    }
    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(executor, requests.get, url, headers)
        response.raise_for_status()
        return response.text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logging.warning(f"Topic not found (404): {url}")
        else:
            logging.error(f"HTTP error fetching {url}: {str(e)}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching {url}: {str(e)}")
        return None

# ---------------- Parse topic links from main page ---------------- #
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

# ---------------- Convert size string to bytes ---------------- #
def get_size_in_bytes(size_str):
    size_str = size_str.strip().lower()
    size_match = re.search(r"(\d+(?:\.\d+)?)(gb|mb)", size_str)
    if size_match:
        value, unit = float(size_match.group(1)), size_match.group(2).lower()
        if unit == "gb":
            return value * 1024 * 1024 * 1024
        elif unit == "mb":
            return value * 1024 * 1024
    return None

# ---------------- Fetch attachments from topic ---------------- #
async def fetch_attachments(page_url):
    html = await fetch(page_url)
    if not html:
        return None

    episode_pattern = re.compile(r"E(?:P)?(\d{1,2})", re.IGNORECASE)
    season_pattern = re.compile(r"S(\d{1,2})\s*(?:E|EP)?\s*\(?(\d+(?:-\d+)?)\)?", re.IGNORECASE)
    domain_removal_regex = re.compile(r"\b(www\.[^\s/$.?#].[^\s]*)\b")
    mkv_torrent_removal_regex = re.compile(r"\.mkv\.torrent$")

    soup = BeautifulSoup(html, "html.parser")
    content_div = soup.find("div", class_="cPost_contentWrap ipsPad")

    img_url = None
    if content_div:
        inner_div = content_div.find("div", class_="ipsType_normal ipsType_richText ipsContained")
        if inner_div:
            img_tag = inner_div.find("img")
            if img_tag and img_tag.get("data-src"):
                img_url = img_tag["data-src"]

    links, highest_episode_links, season_links = [], [], []
    highest_episode_number = 0
    highest_season = 0
    highest_episode_range = (0, 0)

    for link in soup.find_all("a", href=True):
        if "attachment.php" not in link["href"]:
            continue

        attachment_url = link["href"]
        link_text = link.get_text(strip=True)
        clean_text = domain_removal_regex.sub("", link_text)
        clean_text = mkv_torrent_removal_regex.sub("", clean_text).strip()
        size_in_bytes = get_size_in_bytes(link_text)

        # Season-based
        season_match = season_pattern.search(link_text)
        if season_match:
            season_number = int(season_match.group(1))
            ep_range = season_match.group(2)
            ep_start, ep_end = (int(ep_range.split("-")[0]), int(ep_range.split("-")[-1])) if "-" in ep_range else (int(ep_range), int(ep_range))

            if season_number > highest_season or (season_number == highest_season and ep_end > highest_episode_range[1]):
                highest_season = season_number
                highest_episode_range = (ep_start, ep_end)
                season_links = [{"name": clean_text, "link": attachment_url}]
            elif season_number == highest_season:
                season_links.append({"name": clean_text, "link": attachment_url})

        # Episode-based
        episode_matches = episode_pattern.findall(link_text)
        if episode_matches and size_in_bytes and size_in_bytes < 4*1024*1024*1024:
            current_episode = max(int(ep) for ep in episode_matches)
            if current_episode > highest_episode_number:
                highest_episode_number = current_episode
                highest_episode_links = [{"name": clean_text, "link": attachment_url}]
            elif current_episode == highest_episode_number:
                highest_episode_links.append({"name": clean_text, "link": attachment_url})

        elif size_in_bytes and size_in_bytes < 4*1024*1024*1024:
            links.append({"name": clean_text, "link": attachment_url, "size": size_in_bytes})

    final_links = season_links if season_links else (highest_episode_links if highest_episode_links else links)
    document = {"img_url": img_url, "links": final_links, "added_on": datetime.utcnow()}

    await db.add_document(document)
    return document

# ---------------- Main processing loop ---------------- #
async def start_processing():
    html = await fetch(BASE_URL)
    if not html:
        logging.warning("Main page not found!")
        return

    topic_links = await parse_links(html)
    for topic in topic_links:
        logging.info(f"Fetching attachments from {topic}")
        try:
            doc = await fetch_attachments(topic)
            if not doc:
                logging.warning(f"No attachments found: {topic}")
        except Exception as e:
            logging.error(f"Error processing {topic}: {str(e)}")

# ---------------- Web server ---------------- #
routes = web.RouteTableDef()
@routes.get("/", allow_head=True)
async def root_handler(request):
    return web.json_response({"status": "MadxBotz"})

async def web_server():
    app = web.Application(client_max_size=30000000)
    app.add_routes(routes)
    return app
