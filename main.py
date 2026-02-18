import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from utils.loader import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
WAITING_FOR_CAP_NUMBER = range(1)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Manga Bot Online!\nUse: /buscar nome_do_manga"
    )

# ================= BUSCAR =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /buscar nome_do_manga")

    query = " ".join(context.args)
    sources = get_all_sources()
    buttons = []

    for source_name, source in sources.items():
        try:
            results = await source.search(query)
            for manga in results[:6]:
                title = manga.get("title") or manga.get("name")
                url = manga.get("url")
                buttons.append([
                    InlineKeyboardButton(
                        f"{title} ({source_name})",
                        callback_data=f"manga|{source_name}|{url}|0"
                    )
                ])
        except Exception:
            continue

    if not buttons:
        return await update.message.reply_text("Nenhum resultado encontrado.")

    await update.message.reply_text(
        f"🔎 Resultados para: {query}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= MANGA (capítulos com paginação) =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_url, page_str = query.data.split("|")
    page = int(page_str)
    source = get_all_sources()[source_name]

    chapters = await source.chapters(manga_url)
    context.user_data["chapters"] = chapters
    context.user_data["slug"] = manga_url
    context.user_data["source_name"] = source_name

    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []
    for i, ch in enumerate(subset, start=start):
        chap_num = ch.get("chapter_number") or ch.get("name") or "?"
        buttons.append([
            InlineKeyboardButton(
                f"Cap {chap_num}",
                callback_data=f"chapter|{i}"
            )
        ])

    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton("« Anterior", callback_data=f"manga|{source_name}|{manga_url}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("Próxima »", callback_data=f"manga|{source_name}|{manga_url}|{page+1}")
        )
    if nav:
        buttons.append(nav)

    await query.edit_message_text(
        "📖 Selecione o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= CHAPTER (opções de download) =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, index_str = query.data.split("|")
    index = int(index_str)
    context.user_data["selected_index"] = index

    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data="download|single")],
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data="download|from_here")],
        [InlineKeyboardButton("📥 Baixar até cap X", callback_data="input_cap")]
    ]

    chapters = context.user_data.get("chapters", [])
    chap_info = chapters[index]
    chap_num = chap_info.get("chapter_number") or chap_info.get("name") or "?"

    await query.edit_message_text(
        f"📦 Cap {chap_num} — escolha o tipo de download:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= DOWNLOAD =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, mode = query.data.split("|")
    chapters = context.user_data.get("chapters")
    index = context.user_data.get("selected_index")
    source_name = context.user_data.get("source_name")
    source = get_all_sources()[source_name]

    if chapters is None or index is None:
        return await query.message.reply_text("❌ Sessão expirada. Busque novamente.")

    if mode == "single":
        selected = [chapters[index]]
    elif mode == "from_here":
        selected = chapters[index:]
    else:
        selected = [chapters[index]]

    status = await query.message.reply_text(f"📦 Gerando {len(selected)} capítulo(s)...")

    for c in selected:
        cid = c.get("url")
        manga_title = c.get("manga_title", "Manga")
        chap_num = c.get("chapter_number") or c.get("name") or "?"

        imgs = await source.pages(cid)
        if not imgs:
            await query.message.reply_text(f"❌ Cap {chap_num} vazio")
            continue

        cbz_path, cbz_name = await create_cbz(imgs, manga_title, f"Cap {chap_num}")
        await query.message.reply_document(
            document=open(cbz_path, "rb"),
            filename=cbz_name
        )
        os.remove(cbz_path)

    await status.delete()

# ================= INPUT CAP PARA "até cap X" =================
async def input_cap_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Digite o número do capítulo até onde deseja baixar:")
    return WAITING_FOR_CAP_NUMBER

async def receive_cap_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cap_text = update.message.text
    if not cap_text.isdigit():
        return await update.message.reply_text("Digite um número válido de capítulo:")

    cap_number = int(cap_text)
    chapters = context.user_data.get("chapters")
    source_name = context.user_data.get("source_name")
    source = get_all_sources()[source_name]

    target_index = next((i for i, c in enumerate(chapters) if c.get("chapter_number") == cap_number), None)
    if target_index is None:
        return await update.message.reply_text(f"❌ Cap {cap_number} não encontrado.")

    chapters_to_download = chapters[:target_index+1]

    status = await update.message.reply_text(f"📦 Gerando {len(chapters_to_download)} CBZ(s)...")

    for c in chapters_to_download:
        cid = c.get("url")
        manga_title = c.get("manga_title", "Manga")
        chap_num = c.get("chapter_number") or c.get("name") or "?"

        imgs = await source.pages(cid)
        if not imgs:
            await update.message.reply_text(f"❌ Cap {chap_num} vazio")
            continue

        cbz_path, cbz_name = await create_cbz(imgs, manga_title, f"Cap {chap_num}")
        await update.message.reply_document(
            document=open(cbz_path, "rb"),
            filename=cbz_name
        )
        os.remove(cbz_path)

    await status.delete()
    return ConversationHandler.END

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))

    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^manga"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^chapter"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^download"))
    app.add_handler(CallbackQueryHandler(input_cap_callback, pattern="^input_cap"))

    app.add_handler(
        ConversationHandler(
            entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cap_number)],
            states={WAITING_FOR_CAP_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cap_number)]},
            fallbacks=[]
        )
    )

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
