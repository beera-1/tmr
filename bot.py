import os
import asyncio
from aiohttp import web
from pyrogram import Client, utils
from configs import *
from logger import logger
from utilities import web_server, ping_server, stop_user, ping_main_server

# Fix Pyrogram internal IDs for safety
utils.MIN_CHAT_ID = -999999999999
utils.MIN_CHANNEL_ID = -10099999999999900


class ScrapperBot(Client):
    def __init__(self):
        super().__init__(
            "Scrapper",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins=dict(root="plugins"),
            workers=50,  # set appropriate workers
        )

    async def start(self):
        # Start Web server for health checks
        web_app = await web_server()
        runner = web.AppRunner(web_app)
        await runner.setup()
        host = "0.0.0.0"
        port = int(os.getenv("PORT", 8080))
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f"Web server running on {host}:{port}")

        # Start Pyrogram client
        await super().start()
        logger.info("Bot session started successfully.")

        # Send startup messages
        try:
            await self.send_message(GROUP_ID, "Bot Started")
            msg = await self.send_message(RSS_CHAT, "Bot Started")
            await msg.delete()
        except Exception as e:
            logger.error(f"Error sending startup messages: {e}")

        # Start background tasks
        asyncio.create_task(ping_server())
        asyncio.create_task(ping_main_server())

    async def stop(self, *args):
        # Stop Pyrogram User session and bot
        await stop_user()
        try:
            await self.send_message(GROUP_ID, "Bot Stopped")
            msg = await self.send_message(RSS_CHAT, "Bot Stopped")
            await msg.delete()
        except Exception as e:
            logger.error(f"Error sending stop messages: {e}")
        await super().stop()
        logger.info("Bot stopped successfully.")


if __name__ == "__main__":
    ScrapperBot().run()
