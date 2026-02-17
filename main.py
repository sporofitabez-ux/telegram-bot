import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from utils.loader import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
WAITING_FOR_CAP = {}  # Armazena quando o usuário digita o número do capítulo

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
            for manga in results[:6]:
                title = manga.get("title") or manga.get("name")
                url = manga.get("url") or manga.get("slug")
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

# ================= MANGA (paginação) =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_slug, page_str = query.data.split("|")
    page = int(page_str)
    source = get_all_sources()[source_name]

    chapters = await source.chapters(manga_slug)
    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []
    for ch in subset:
        chap_num = ch.get("chapter_number") or ch.get("name")
        buttons.append([
            InlineKeyboardButton(
                f"Cap {chap_num}",
                callback_data=f"chapter|{source_name}|{manga_slug}|{ch.get('url')}"
            )
        ])

    # Navegação de páginas
    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton("« Anterior", callback_data=f"manga|{source_name}|{manga_slug}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("Próxima »", callback_data=f"manga|{source_name}|{manga_slug}|{page+1}")
        )
    if nav:
        buttons.append(nav)

    await query.edit_message_text(
        "📖 Selecione o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= CHAPTER (opções) =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_slug, chapter_slug = query.data.split("|")
    source = get_all_sources()[source_name]

    # Busca info do capítulo
    chapters = await source.chapters(manga_slug)
    info = next((c for c in chapters if c.get("url") == chapter_slug), None)
    if not info:
        return await query.message.reply_text("❌ Erro ao abrir capítulo")

    chap_num = info.get("chapter_number") or info.get("name")
    manga_title = info.get("manga_title", "Manga")

    # Botões de download (um embaixo do outro)
    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data=f"download|{source_name}|{manga_slug}|{chapter_slug}|single")],
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data=f"download|{source_name}|{manga_slug}|{chapter_slug}|from_here")],
        [InlineKeyboardButton("📥 Baixar até Cap X", callback_data=f"download|{source_name}|{manga_slug}|{chapter_slug}|to_here")]
    ]

    await query.edit_message_text(
        f"📦 Cap {chap_num} — escolha o tipo de download:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= DOWNLOAD =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_slug, chapter_slug, mode = query.data.split("|")
    source = get_all_sources()[source_name]

    chapters = await source.chapters(manga_slug)
    index = next((i for i,c in enumerate(chapters) if c.get("url")==chapter_slug), 0)

    if mode == "single":
        sel = [chapters[index]]
    elif mode == "from_here":
        sel = chapters[index:]
    elif mode == "to_here":
        # Pergunta ao usuário o número do capítulo
        user_id = query.from_user.id
        WAITING_FOR_CAP[user_id] = (source_name, manga_slug, index)
        return await query.message.reply_text("Digite o número do capítulo até onde deseja baixar:")
    else:
        sel = [chapters[index]]

    await start_cbz_download(query, source, sel)

# ================= PROCESSA CBZ =================
async def start_cbz_download(query, source, sel):
    status = await query.message.reply_text(f"📦 Gerando {len(sel)} CBZ(s)...")

    for c in sel:
        cid = c.get("url")
        num = c.get("chapter_number") or c.get("name")
        name = f"Cap {num}"
        manga_title = c.get("manga_title","Manga")

        imgs = await source.pages(cid)
        if not imgs:
            await query.message.reply_text(f"❌ Cap {num} vazio")
            continue

        cbz_path, cbz_name = await create_cbz(imgs, manga_title, name)
        await query.message.reply_document(
            document=open(cbz_path,"rb"),
            filename=cbz_name
        )
        os.remove(cbz_path)

    await status.delete()

# ================= MENSAGEM (para baixar até cap X) =================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in WAITING_FOR_CAP:
        return
    try:
        end_cap = int(update.message.text)
    except ValueError:
        return await update.message.reply_text("Digite apenas números válidos.")

    source_name, manga_slug, start_index = WAITING_FOR_CAP.pop(user_id)
    source = get_all_sources()[source_name]
    chapters = await source.chapters(manga_slug)
    if end_cap > len(chapters):
        end_cap = len(chapters)
    sel = chapters[start_index:end_cap]
    await start_cbz_download(update.message, source, sel)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^manga"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^chapter"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^download"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
