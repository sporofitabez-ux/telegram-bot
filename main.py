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
from utils.loader import get_all_sources

logging.basicConfig(level=logging.INFO)


# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Manga Bot Online!\n\n"
        "Use:\n"
        "/buscar nome_do_manga"
    )


# ================= BUSCAR =================

async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /buscar nome")

    query = " ".join(context.args)
    sources = get_all_sources()

    buttons = []

    for source_name, source in sources.items():
        try:
            results = await source.search(query)

            for manga in results[:3]:  # limita 3 por fonte
                title = manga.get("title") or manga.get("name")
                url = manga.get("url") or manga.get("slug")

                if "slug" in manga:
                    url = f"https://toonbr.com/manga/{manga['slug']}"

                buttons.append([
                    InlineKeyboardButton(
                        f"{title} ({source_name})",
                        callback_data=f"manga|{source_name}|{url}"
                    )
                ])

        except Exception as e:
            print(f"Erro na fonte {source_name}: {e}")

    if not buttons:
        return await update.message.reply_text("Nenhum resultado encontrado.")

    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        f"Resultados para: {query}",
        reply_markup=reply_markup
    )


# ================= MANGA =================

async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, url = query.data.split("|", 2)

    source = get_all_sources()[source_name]

    try:
        chapters = await source.chapters(url)
    except Exception:
        return await query.message.reply_text("Erro ao carregar capítulos.")

    buttons = []

    for ch in chapters[:10]:
        name = ch.get("name") or f"Cap {ch.get('chapter_number')}"
        ch_url = ch.get("url") or ch.get("id")

        if "id" in ch:
            ch_url = f"https://toonbr.com/read/{ch['id']}"

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

    source = get_all_sources()[source_name]

    try:
        images = await source.pages(url)
    except Exception:
        return await query.message.reply_text("Erro ao carregar páginas.")

    if not images:
        return await query.message.reply_text("Capítulo vazio.")

    media = [InputMediaPhoto(img) for img in images[:10]]

    await query.message.reply_media_group(media)


# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^manga"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^chapter"))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
