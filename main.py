import os
import logging
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
from config import BOT_TOKEN, WEBHOOK_URL, PORT

logging.basicConfig(level=logging.INFO)
CHAPTERS_PER_PAGE = 10

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 Manga Bot Online!\nUse: /buscar nome_do_manga")

# ================= BUSCAR =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /buscar nome")

    query = " ".join(context.args)
    sources = get_all_sources()
    buttons = []

    for source_name, source in sources.items():
        results = await source.search(query)
        for manga in results[:6]:
            title = manga.get("title") or manga.get("name")
            url = manga.get("url") or manga.get("slug")
            buttons.append([InlineKeyboardButton(f"{title} ({source_name})",
                                                 callback_data=f"manga|{source_name}|{url}|0")])

    if not buttons:
        return await update.message.reply_text("Nenhum resultado encontrado.")

    await update.message.reply_text(f"🔎 Resultados para: {query}",
                                    reply_markup=InlineKeyboardMarkup(buttons))

# ================= MANGA (paginação) =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, source_name, manga_url, page_str = query.data.split("|")
    page = int(page_str)
    source = get_all_sources()[source_name]

    chapters = await source.chapters(manga_url)
    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []
    for ch in subset:
        chap_num = ch.get("chapter_number") or ch.get("name")
        buttons.append([InlineKeyboardButton(f"Cap {chap_num}", callback_data=f"chapter|{source_name}|{ch.get('url')}")])

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("« Anterior", callback_data=f"manga|{source_name}|{manga_url}|{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Próxima »", callback_data=f"manga|{source_name}|{manga_url}|{page+1}"))
    if nav:
        buttons.append(nav)

    await query.edit_message_text("📖 Selecione o capítulo:",
                                  reply_markup=InlineKeyboardMarkup(buttons))

# ================= CHAPTER =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, source_name, chapter_id = query.data.split("|")
    source = get_all_sources()[source_name]

    chapters = await source.chapters(chapter_id)
    chapter = next((c for c in chapters if str(c.get("url"))==chapter_id or str(c.get("id"))==chapter_id), None)
    if not chapter:
        return await query.message.reply_text("❌ Capítulo não encontrado.")

    chap_num = chapter.get("chapter_number")
    manga_title = chapter.get("manga_title","Manga")

    buttons = [
        [
            InlineKeyboardButton("📥 Baixar este", callback_data=f"download|{source_name}|{chapter_id}|single"),
            InlineKeyboardButton("📥 Baixar deste até o fim", callback_data=f"download|{source_name}|{chapter_id}|from_here")
        ],
        [
            InlineKeyboardButton("📥 Baixar até Cap X", callback_data=f"download|{source_name}|{chapter_id}|to_here")
        ]
    ]

    await query.edit_message_text(f"📦 {manga_title} — Cap {chap_num}\nEscolha o tipo de download:",
                                  reply_markup=InlineKeyboardMarkup(buttons))

# ================= DOWNLOAD =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, source_name, chapter_id, mode = query.data.split("|")
    source = get_all_sources()[source_name]

    chapters = await source.chapters(chapter_id)
    index = next((i for i,c in enumerate(chapters) if str(c.get("url"))==chapter_id or str(c.get("id"))==chapter_id), 0)

    if mode=="single":
        sel = [chapters[index]]
    elif mode=="from_here":
        sel = chapters[index:]
    elif mode=="to_here":
        sel = chapters[:index+1]
    else:
        sel = [chapters[index]]

    status = await query.message.reply_text(f"📦 Gerando {len(sel)} CBZ(s)...")

    for c in sel:
        cid = c.get("url") or c.get("id")
        num = c.get("chapter_number")
        name = f"Cap {num}"
        manga_title = c.get("manga_title","Manga")

        imgs = await source.pages(cid)
        if not imgs:
            await query.message.reply_text(f"❌ Cap {num} vazio")
            continue

        async def progress(i, total):
            await status.edit_text(f"📦 {manga_title} Cap {num}: {i}/{total} imagens baixadas")

        cbz_path, cbz_name = await create_cbz(imgs, manga_title, name, progress)
        await query.message.reply_document(document=open(cbz_path,"rb"), filename=cbz_name)

    await status.delete()

# ================= MAIN =================
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^manga"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^chapter"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^download"))

    # Webhook
    await app.bot.set_webhook(WEBHOOK_URL)
    await app.run_webhook(listen="0.0.0.0", port=PORT, webhook_path="/")

if __name__=="__main__":
    asyncio.run(main())
