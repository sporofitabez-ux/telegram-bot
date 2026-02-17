import logging
import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from utils.loader import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)


# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Manga Bot Online!\nUse: /buscar nome_do_manga"
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
            for manga in results[:5]:
                title = manga.get("title") or manga.get("name")
                url = manga.get("url") or manga.get("slug")
                callback_id = f"manga|{source_name}|{url}"
                buttons.append([InlineKeyboardButton(f"{title} ({source_name})", callback_data=callback_id)])
        except Exception:
            continue

    if not buttons:
        return await update.message.reply_text("Nenhum resultado encontrado.")

    await update.message.reply_text(
        f"Resultados para: {query}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= MANGA =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, source_name, manga_url = query.data.split("|", 2)
    source = get_all_sources()[source_name]

    try:
        chapters = await source.chapters(manga_url)
    except Exception:
        return await query.message.reply_text("Erro ao carregar capítulos.")

    buttons = []
    for ch in chapters[:20]:
        ch_id = ch.get("url") or ch.get("id")
        cap_number = ch.get("chapter_number") or ch.get("name")
        buttons.append([InlineKeyboardButton(f"{cap_number}", callback_data=f"chapter|{source_name}|{ch_id}")])

    await query.edit_message_text(
        "Selecione o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= CHAPTER =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, source_name, chapter_id = query.data.split("|", 2)
    source = get_all_sources()[source_name]

    status = await query.message.reply_text("📦 Gerando CBZ...")

    try:
        # Buscar capítulo para pegar nome correto
        chapters = await source.chapters(chapter_id)
        chapter_info = next((ch for ch in chapters if ch.get("url") == chapter_id or ch.get("id") == chapter_id), None)

        if chapter_info:
            chapter_name = chapter_info.get("name", "Capítulo")
            manga_title = chapter_info.get("manga_title", "Manga")
        else:
            chapter_name = "Capítulo"
            manga_title = "Manga"

        # Busca imagens
        images = await source.pages(chapter_id)
    except Exception:
        return await status.edit_text("Erro ao carregar capítulo.")

    if not images:
        return await status.edit_text("Capítulo vazio.")

    # Barra de progresso simples
    total = len(images)
    message = await status.edit_text(f"📦 Baixando 0/{total} páginas...")
    cbz_path, cbz_name = await create_cbz(images, manga_title, chapter_name, progress_message=message)

    await query.message.reply_document(
        document=open(cbz_path, "rb"),
        filename=cbz_name
    )

    os.remove(cbz_path)
    await message.delete()


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^manga"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^chapter"))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
