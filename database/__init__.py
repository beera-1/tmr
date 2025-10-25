import os
import re
import asyncio
import logging
from pyrogram import Client
from configs import *
from db_instance import db

os.makedirs("downloads", exist_ok=True)

User = Client("User", session_string=USER_SESSION_STRING, api_hash=API_HASH, api_id=API_ID)

# ------------------ DOWNLOAD FILE ------------------ #
async def download_file(url, local_filename):
    max_retries = 5
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Status code {resp.status}")
                    with open(local_filename, "wb") as f:
                        while True:
                            chunk = await resp.content.read(1024*64)
                            if not chunk:
                                break
                            f.write(chunk)
            logging.info(f"Downloaded {local_filename} successfully.")
            return True
        except Exception as e:
            logging.error(f"Download attempt {attempt+1} failed for {url}: {e}")
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
            local_filename = f"downloads/{safe_name}.torrent"

            full_url = link["link"]
            if not full_url.startswith("http"):
                full_url = BASE_URL.rstrip("/") + link["link"]

            if await download_file(full_url, local_filename):
                try:
                    sent_msg = await User.send_document(
                        chat_id=GROUP_ID,
                        document=local_filename,
                        thumb="database/thumb.jpg",
                        caption=f"<b>@MadxBotz {link['name']}\n<blockquote>〽️ Powered by @MadxBotz</blockquote></b>",
                    )
                    await User.send_message(
                        chat_id=GROUP_ID,
                        text="/qbleech",
                        reply_to_message_id=sent_msg.id,
                    )

                    await User.send_document(
                        chat_id=RSS_CHAT,
                        document=local_filename,
                        thumb="database/thumb.jpg",
                        caption=f"<b>@MadxBotz {link['name']}\n<blockquote>〽️ Powered by @MadxBotz</blockquote></b>",
                    )
                except Exception as e:
                    logging.error(f"Failed to send document: {e}")
                finally:
                    if os.path.exists(local_filename):
                        os.remove(local_filename)
            else:
                logging.warning(f"Failed to download file for link: {full_url}")
