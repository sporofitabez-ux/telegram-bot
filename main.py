import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import BOT_TOKEN
from utils.loader import get_source

logging.basicConfig(level=logging.INFO)


# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📚 Manga Bot Online!\n\n"
        "Use:\n"
        "/search toonbr nome\n"
        "/search mangaonline nome\n"
    )
    await update.message.reply_text(text)


# ================= SEARCH =================

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        return await update.message.reply_text("Uso: /search fonte nome")

    source_name = context.args[0]
    query = " ".join(context.args[1:])

    source = get_source(source_name)

    if not source:
        return await update.message.reply_text("Fonte não encontrada.")

    results = await source.search(query)

    if not results:
        return await update.message.reply_text("Nenhum resultado.")

    buttons = []

    for manga in results[:10]:
        title = manga.get("title") or manga.get("name")
        url = manga.get("url") or manga.get("slug")

        if "slug" in manga:
            url = f"https://beta.toonbr.com/manga/{manga['slug']}"

        buttons.append([
            InlineKeyboardButton(
                title,
                callback_data=f"manga|{source_name}|{url}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text("Resultados:", reply_markup=reply_markup)


# ================= MANGA =================

async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, url = query.data.split("|", 2)

    source = get_source(source_name)
    chapters = await source.chapters(url)

    buttons = []

    for ch in chapters[:10]:
        name = ch.get("name") or f"Cap {ch.get('chapter_number')}"
        ch_url = ch.get("url")

        if not ch_url:
            ch_url = f"https://beta.toonbr.com/read/{ch['id']}"

        buttons.append([
            InlineKeyboardButton(
                name,
                callback_data=f"chapter|{source_name}|{ch_url}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text("Capítulos:", reply_markup=reply_markup)


# ================= CHAPTER =================

async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, url = query.data.split("|", 2)

    source = get_source(source_name)
    images = await source.pages(url)

    if not images:
        return await query.message.reply_text("Capítulo vazio.")

    media = [InputMediaPhoto(img) for img in images[:10]]

    await query.message.reply_media_group(media)


# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^manga"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^chapter"))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
