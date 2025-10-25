import os
import re
import asyncio
import logging
from urllib.parse import urljoin

import aiohttp
from pyrogram import Client
from db_instance import db
from configs import *

os.makedirs("downloads", exist_ok=True)

User = Client("User", session_string=USER_SESSION_STRING, api_hash=API_HASH, api_id=API_ID)

# ------------------ DOWNLOAD FILE ------------------ #
async def download_file(url, local_filename):
    for attempt in range(5):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Status {resp.status}")
                    with open(local_filename, "wb") as f:
                        while chunk := await resp.content.read(1024*64):
                            f.write(chunk)
            logging.info(f"Downloaded {local_filename}")
            return True
        except Exception as e:
            logging.error(f"Attempt {attempt+1} failed for {url}: {e}")
            if os.path.exists(local_filename):
                os.remove(local_filename)
            await asyncio.sleep(1)
    return False

# ------------------ SEND DOCUMENTS ------------------ #
async def send_new_link_notification(links):
    async with User:
        if not links:
            await User.send_message(chat_id=GROUP_ID, text="Empty Array")
            return

        for link in links:
            safe_name = re.sub(r"[^\w\d-_. ]", "_", link['name'])
            local_file = f"downloads/{safe_name}.torrent"
            url = link["link"]
            if not url.startswith("http"):
                url = urljoin(BASE_URL, link["link"])

            if await download_file(url, local_file):
                try:
                    msg = await User.send_document(GROUP_ID, local_file, thumb="database/thumb.jpg",
                                                  caption=f"<b>@MadxBotz {link['name']}\n<blockquote>〽️ Powered by @MadxBotz</blockquote></b>")
                    await User.send_message(GROUP_ID, "/qbleech", reply_to_message_id=msg.id)
                except Exception as e:
                    logging.error(f"Failed to send document: {e}")
                finally:
                    if os.path.exists(local_file):
                        os.remove(local_file)
