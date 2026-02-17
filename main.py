import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)
from sources.toonbr import ToonBrSource
from sources.mangaflix import MangaFlixSource
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
GET_CAP_INPUT = range(1)

# ================= SOURCES =================
def get_all_sources():
    return {
        "ToonBr": ToonBrSource(),
        "MangaFlix": MangaFlixSource()
    }

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
                url = manga.get("url") or manga.get("slug")
                buttons.append([
                    InlineKeyboardButton(
                        f"{title} ({source_name})",
                        callback_data=f"manga|{source_name}|{url}|0"
                    )
                ])
        except Exception as e:
            logging.error(f"Erro buscando {source_name}: {e}")
            continue

    if not buttons:
        return await update.message.reply_text("Nenhum resultado encontrado.")

    await update.message.reply_text(
        f"🔎 Resultados para: {query}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= MANGA CALLBACK =================
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
        buttons.append([
            InlineKeyboardButton(
                str(chap_num),
                callback_data=f"chapter|{source_name}|{manga_url}|{ch.get('url')}|{chap_num}"
            )
        ])

    # Navegação de páginas
    nav = []
    if start > 0:
        nav.append([
            InlineKeyboardButton("« Anterior", callback_data=f"manga|{source_name}|{manga_url}|{page-1}")
        ])
    if end < total:
        nav.append([
            InlineKeyboardButton("Próxima »", callback_data=f"manga|{source_name}|{manga_url}|{page+1}")
        ])
    buttons.extend(nav)

    await query.edit_message_text(
        "📖 Selecione o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= CHAPTER CALLBACK =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_id, chapter_id, chap_num = query.data.split("|")
    source = get_all_sources()[source_name]

    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data=f"download|{source_name}|{manga_id}|{chapter_id}|single")],
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data=f"download|{source_name}|{manga_id}|{chapter_id}|from_here")],
        [InlineKeyboardButton("📥 Baixar até Cap X", callback_data=f"capinput|{source_name}|{manga_id}|{chapter_id}|{chap_num}")]
    ]

    await query.edit_message_text(
        f"📦 Cap {chap_num} — escolha o tipo de download:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= CAP INPUT HANDLER =================
async def cap_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    cap_number_str = update.message.text
    data = context.user_data.get("cap_input_data")
    if not data:
        return

    try:
        cap_number = int(cap_number_str)
    except ValueError:
        await update.message.reply_text("Digite apenas números do capítulo.")
        return

    source_name, manga_id, chapter_id, current_num = data
    source = get_all_sources()[source_name]

    chapters = await source.chapters(manga_id)
    # Seleciona capítulos até o número digitado
    sel = [c for c in chapters if int(c.get("chapter_number") or 0) <= cap_number]

    status = await update.message.reply_text(f"📦 Gerando {len(sel)} CBZ(s)...")
    for c in sel:
        cid = c.get("url")
        num = c.get("chapter_number") or c.get("name")
        manga_title = c.get("manga_title","Manga")
        imgs = await source.pages(cid)
        if not imgs:
            await update.message.reply_text(f"❌ Cap {num} vazio")
            continue
        cbz_path, cbz_name = await create_cbz(imgs, manga_title, f"Cap {num}")
        await update.message.reply_document(document=open(cbz_path,"rb"), filename=cbz_name)
        os.remove(cbz_path)
    await status.delete()
    context.user_data["cap_input_data"] = None

# ================= DOWNLOAD CALLBACK =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_id, chapter_id, mode = query.data.split("|")
    source = get_all_sources()[source_name]

    chapters = await source.chapters(manga_id)
    index = next((i for i,c in enumerate(chapters) if c.get('url')==chapter_id), 0)

    if mode == "single":
        sel = [chapters[index]]
    elif mode == "from_here":
        sel = chapters[index:]
    else:
        sel = [chapters[index]]

    status = await query.message.reply_text(f"📦 Gerando {len(sel)} CBZ(s)...")
    for c in sel:
        cid = c.get("url")
        num = c.get("chapter_number") or c.get("name")
        manga_title = c.get("manga_title","Manga")
        imgs = await source.pages(cid)
        if not imgs:
            await query.message.reply_text(f"❌ Cap {num} vazio")
            continue
        cbz_path, cbz_name = await create_cbz(imgs, manga_title, f"Cap {num}")
        await query.message.reply_document(document=open(cbz_path,"rb"), filename=cbz_name)
        os.remove(cbz_path)
    await status.delete()

# ================= CALLBACK HANDLER =================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data.startswith("manga"):
        await manga_callback(update, context)
    elif data.startswith("chapter"):
        await chapter_callback(update, context)
    elif data.startswith("download"):
        await download_callback(update, context)
    elif data.startswith("capinput"):
        _, source_name, manga_id, chapter_id, chap_num = data.split("|")
        context.user_data["cap_input_data"] = [source_name, manga_id, chapter_id, chap_num]
        await query.message.reply_text("Digite o número do capítulo até onde deseja baixar:")
    await query.answer()

# ================= MAIN =================
def main():
    token = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cap_input))

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
