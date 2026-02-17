import logging
import os
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
    for ch in chapters:
        ch_id = ch.get("url") or ch.get("id")
        cap_number = ch.get("chapter_number") or ch.get("name")
        buttons.append([InlineKeyboardButton(str(cap_number), callback_data=f"chapter|{source_name}|{ch_id}")])

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

    chapters = await source.chapters(chapter_id)
    chapter_info = next((ch for ch in chapters if ch.get("url") == chapter_id or ch.get("id") == chapter_id), None)

    if chapter_info:
        chapter_number = chapter_info.get("chapter_number") or chapter_info.get("name")
        chapter_name = f"Cap {chapter_number}"
        manga_title = chapter_info.get("manga_title", "Manga")
    else:
        chapter_name = "Capítulo"
        manga_title = "Manga"

    # Botões de download
    buttons = [
        [
            InlineKeyboardButton("📥 Baixar apenas este", callback_data=f"download|{source_name}|{chapter_id}|single"),
            InlineKeyboardButton("📥 Baixar deste até o fim", callback_data=f"download|{source_name}|{chapter_id}|from_here")
        ],
        [
            InlineKeyboardButton("📥 Baixar até capítulo X", callback_data=f"download|{source_name}|{chapter_id}|to_here")
        ]
    ]

    await query.edit_message_text(
        f"{chapter_name} - selecione uma opção de download:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= DOWNLOAD CALLBACK =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, source_name, chapter_id, mode = query.data.split("|", 3)
    source = get_all_sources()[source_name]

    chapters = await source.chapters(chapter_id)
    chapter_index = next((i for i, ch in enumerate(chapters) if ch.get("url") == chapter_id or ch.get("id") == chapter_id), 0)

    if mode == "single":
        selected_chapters = [chapters[chapter_index]]
    elif mode == "from_here":
        selected_chapters = chapters[chapter_index:]
    elif mode == "to_here":
        selected_chapters = chapters[:chapter_index+1]
    else:
        selected_chapters = [chapters[chapter_index]]

    status = await query.message.reply_text(f"📦 Gerando CBZ(s) para {len(selected_chapters)} capítulo(s)...")

    for ch in selected_chapters:
        ch_id = ch.get("url") or ch.get("id")
        chapter_number = ch.get("chapter_number") or ch.get("name")
        chapter_name = f"Cap {chapter_number}"
        manga_title = ch.get("manga_title", "Manga")

        try:
            images = await source.pages(ch_id)
        except Exception:
            await query.message.reply_text(f"❌ Falha ao baixar {chapter_name}")
            continue

        if not images:
            await query.message.reply_text(f"❌ {chapter_name} vazio")
            continue

        cbz_path, cbz_name = await create_cbz(images, manga_title, chapter_name)
        await query.message.reply_document(
            document=open(cbz_path, "rb"),
            filename=cbz_name
        )
        os.remove(cbz_path)

    await status.delete()


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^manga"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^chapter"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^download"))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
