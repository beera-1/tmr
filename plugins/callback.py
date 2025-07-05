from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from configs import *
from plugins.commands import user_pagination, show_document

@Client.on_callback_query()
async def callback(bot, query):
    me = await bot.get_me()
    data = query.data
    msg = query.message

    if data == "delete":
        await msg.delete()
        try:
            await msg.reply_to_message.delete()
        except:
            pass
                    
    elif data.startswith("prev_") or data.startswith("next_"):
        _, user_id, current_index = data.split("_")
        current_index = int(current_index)

        await show_document(bot, msg, int(user_id), current_index)
            
            
    elif data == "help":
        await msg.edit(
            HELP_TXT.format(me.mention),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Aʙᴏᴜᴛ ★", callback_data="about"),
                        InlineKeyboardButton(
                            "Sᴜᴘᴘᴏʀᴛ Gʀᴏᴜᴘ ⌘", url="https://t.me/MadxBotzSupport"
                        ),
                    ],
                    [InlineKeyboardButton("Bᴀᴄᴋ ✰", callback_data="start")],
                ]
            ),
        )

    elif data == "about":
        await msg.edit(
            ABOUT_TXT.format(me.mention),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Uᴘᴅᴀᴛᴇs 🙌", url="https://t.me/MadxBotz"
                        ),
                        InlineKeyboardButton(
                            "Dᴇᴠᴇʟᴏᴘᴇʀ ⚡", url="https://t.me/ruban9124"
                        ),
                    ],
                    [InlineKeyboardButton("Bᴀᴄᴋ 𖦹", callback_data="start")],
                ]
            ),
        )


    elif data == "start":
        await msg.edit(
            START_TXT.format(query.from_user.mention),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Hᴇʟᴩ Mᴇɴᴜ", callback_data="help"),
                    ],
                    [
                        InlineKeyboardButton(
                            "Cʜᴀɴɴᴇʟ", url=f"https://t.me/MadxBotz"
                        ),
                        InlineKeyboardButton(
                            "Sᴜᴩᴩᴏʀᴛ", url=f"https://t.me/MadxBotzSupport"
                        ),
                    ],
                    [InlineKeyboardButton("Cʟᴏsᴇ ❌", callback_data="delete")],
                ]
            ),
        )
