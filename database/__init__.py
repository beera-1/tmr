import os
import re
import asyncio
import logging
from datetime import datetime
from urllib.parse import urlparse

import cloudscraper
import requests
from pyrogram import Client
from motor.motor_asyncio import AsyncIOMotorClient

from configs import *

os.makedirs("downloads", exist_ok=True)
logging.basicConfig(level=logging.INFO)

scraper = cloudscraper.create_scraper(delay=10, browser="chrome")

User = Client("User", session_string=USER_SESSION_STRING, api_id=API_ID, api_hash=API_HASH)

async def fetch(url):
    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(None, lambda: scraper.get(url, timeout=20))
        response.raise_for_status()
        size = int(response.headers.get("Content-Length", 0))
        return response, size
    except Exception as e:
        logging.error(f"[fetch] Error fetching {url}: {e}", exc_info=True)
        return None, 0

async def is_valid_link(url):
    response, _ = await fetch(url)
    return response.status_code == 200 if response else False

# ✅ Fixed download_file — safe, retry-based, Cloudflare proof
async def download_file(url, local_filename):
    max_retries = 5
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Encoding": "identity"
    }
    loop = asyncio.get_event_loop()

    for attempt in range(max_retries):
        try:
            def do_request():
                with scraper.get(url, headers=headers, stream=True, timeout=60) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("Content-Length", 0))
                    size = 0

                    with open(local_filename, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                size += len(chunk)

                    if total and abs(size - total) > 1024:
                        logging.warning(f"⚠️ Size mismatch ({size}/{total}) for {url}")
                        return False
                    return True

            success = await loop.run_in_executor(None, do_request)
            if success:
                logging.info(f"✅ Downloaded {local_filename} successfully.")
                return True
            else:
                if os.path.exists(local_filename):
                    os.remove(local_filename)
                await asyncio.sleep(2)

        except Exception as e:
            logging.error(f"[download_file] Error: {e}")
            if os.path.exists(local_filename):
                os.remove(local_filename)
            await asyncio.sleep(2)

    logging.error(f"❌ Failed to download {url} after {max_retries} attempts.")
    return False

async def send_new_link_notification(links):
    async with User:
        if not links:
            await User.send_message(chat_id=GROUP_ID, text="Empty Array")
            return

        for link in links:
            local_filename = f"downloads/@MOVIES_ADDDDA {link['name']}.torrent"

            if await is_valid_link(link["link"]):
                if await download_file(link["link"], local_filename):
                    try:
                        sent_msg = await User.send_document(
                            chat_id=GROUP_ID,
                            document=local_filename,
                            thumb="database/thumb.jpg",
                            caption=f"<b>@MOVIES_ADDDDA {link['name']}\n\n<blockquote>〽️ Powered by @MOVIES_ADDDDA</blockquote></b>",
                        )
                        await User.send_message(
                            chat_id=GROUP_ID,
                            text="/qbleech1",
                            reply_to_message_id=sent_msg.id,
                        )
                        await User.send_document(
                            chat_id=RSS_CHAT,
                            document=local_filename,
                            thumb="database/thumb.jpg",
                            caption=f"<b>@MOVIES_ADDDDA {link['name']}\n\n<blockquote>〽️ Powered by @MOVIES_ADDDDA</blockquote></b>",
                        )
                    except Exception as e:
                        logging.error(f"[send_document] Error: {e}")
                    finally:
                        if os.path.exists(local_filename):
                            os.remove(local_filename)
                else:
                    logging.warning(f"⚠️ Failed to download: {link['link']}")
            else:
                logging.warning(f"⚠️ Invalid link skipped: {link['link']}")

class Database:
    def __init__(self, url, db_name):
        self.db = AsyncIOMotorClient(url)[db_name]
        self.users_coll = self.db.users
        self.links_coll = self.db.attachments

    async def add_user(self, user_id):
        if not await self.is_present(user_id):
            await self.users_coll.insert_one({"id": user_id})

    async def is_present(self, user_id):
        return bool(await self.users_coll.find_one({"id": int(user_id)}))

    async def total_users(self):
        return await self.users_coll.count_documents({})

    async def count_all_links(self):
        return await self.links_coll.count_documents({})

    async def search_movie(self, movie_name):
        regex_query = {
            "name": {
                "$regex": re.escape(movie_name).replace(r"\ ", r".*"),
                "$options": "i",
            }
        }
        return await self.links_coll.find(regex_query).to_list(length=None)

    async def get_last_documents(self, count):
        return await self.links_coll.find().sort("added_on", -1).limit(count).to_list(count)

    async def add_document(self, document):
        img_url = document.get("img_url")
        for link in document.get("links", []):
            parsed = urlparse(link["link"])
            link_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            if not await self.links_coll.find_one({"link": link_path}):
                new_doc = {
                    "img_url": img_url,
                    "name": link["name"],
                    "link": link_path,
                    "added_on": datetime.utcnow(),
                }
                await self.links_coll.insert_one(new_doc)
                logging.info(f"[DB] New document inserted: {new_doc['name']}")
                await send_new_link_notification([link])

db = Database(DATABASE_URL, "MadxBotz_Scrapper")
