import os
import logging
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

CHAPTERS_PER_PAGE = 10

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
        except Exception as e:
            logging.warning(f"Erro na busca {source_name}: {e}")
            continue

    if not buttons:
        return await update.message.reply_text("Nenhum resultado encontrado.")

    await update.message.reply_text(
        f"🔎 Resultados para: {query}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= MANGA (paginação capítulos) =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_id, page_str = query.data.split("|")
    page = int(page_str)
    source = get_all_sources()[source_name]

    try:
        chapters = await source.chapters(manga_id)
    except Exception:
        return await query.edit_message_text("❌ Erro ao abrir capítulos.")

    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []
    for ch in subset:
        chap_num = ch.get("chapter_number") or ch.get("name") or "?"
        buttons.append([
            InlineKeyboardButton(
                f"Cap {chap_num}",
                callback_data=f"chapter|{source_name}|{ch.get('url')}"
            )
        ])

    # Paginação
    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton("« Anterior", callback_data=f"manga|{source_name}|{manga_id}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("Próxima »", callback_data=f"manga|{source_name}|{manga_id}|{page+1}")
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

    _, source_name, chapter_id = query.data.split("|")
    source = get_all_sources()[source_name]

    # Busca capítulo
    chapters = await source.chapters_for_id(chapter_id)
    info = next((c for c in chapters if c.get("url") == chapter_id or c.get("id") == chapter_id), None)
    if not info:
        return await query.edit_message_text("❌ Capítulo não encontrado.")

    chap_num = info.get("chapter_number") or info.get("name") or "?"
    manga_title = info.get("manga_title", "Manga")

    # Botões um embaixo do outro
    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data=f"download|{source_name}|{chapter_id}|single")],
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data=f"download|{source_name}|{chapter_id}|from_here")],
        [InlineKeyboardButton("📥 Baixar até Cap X", callback_data=f"download|{source_name}|{chapter_id}|to_here")]
    ]

    await query.edit_message_text(
        f"📦 Cap {chap_num} — escolha o tipo de download:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# ================= DOWNLOAD =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, chapter_id, mode = query.data.split("|")
    source = get_all_sources()[source_name]

    # Lista de capítulos do manga
    chapters = await source.chapters_for_id(chapter_id)
    index = next((i for i, c in enumerate(chapters) if c.get('url') == chapter_id or c.get('id') == chapter_id), 0)

    if mode == "single":
        sel = [chapters[index]]
    elif mode == "from_here":
        sel = chapters[index:]
    elif mode == "to_here":
        # Pede ao usuário o número do capítulo final
        await query.message.reply_text("Digite o número do capítulo final:")
        context.user_data["download_mode"] = {"source": source_name, "chapters": chapters[:index+1]}
        return
    else:
        sel = [chapters[index]]

    status = await query.message.reply_text(f"📦 Gerando {len(sel)} CBZ(s)...")

    for c in sel:
        cid = c.get("url") or c.get("id")
        num = c.get("chapter_number") or c.get("name") or "?"
        name = f"Cap {num}"
        manga_title = c.get("manga_title", "Manga")

        imgs = await source.pages(cid)
        if not imgs:
            await query.message.reply_text(f"❌ Cap {num} vazio")
            continue

        cbz_path, cbz_name = await create_cbz(imgs, manga_title, name)
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
