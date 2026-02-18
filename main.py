import os
import logging
import traceback
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from sources import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
sources = get_all_sources()


# ================= ERROR HANDLER =================
async def error_handler(update, context):
    print("========== ERRO GLOBAL ==========")
    traceback.print_exception(None, context.error, context.error.__traceback__)
    print("==================================")


# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Olá! Sou Yuki, um Bot de download de mangás online!\n\n"
        "Use:\n/buscar nome_do_manga"
    )


# ================= BUSCAR =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /buscar nome")

    query = " ".join(context.args)
    results = []

    # Busca em todas as fontes
    for src_name, src in sources.items():
        try:
            mangas = await src.search(query)
            for manga in mangas:
                manga["source"] = src_name
            results.extend(mangas)
        except Exception as e:
            print(f"Erro ao buscar em {src_name}: {e}")

    if not results:
        return await update.message.reply_text("❌ Nenhum resultado encontrado.")

    buttons = []
    for manga in results[:10]:
        buttons.append([
            InlineKeyboardButton(
                f"[{manga['source']}] {manga['title']}",
                callback_data=f"m|{manga['source']}|{manga['url']}|0"
            )
        ])

    await update.message.reply_text(
        f"🔎 Resultados para: {query}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= LISTA CAPÍTULOS =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, src_name, slug, page_str = query.data.split("|")
    page = int(page_str)
    source_obj = sources[src_name]

    chapters = await source_obj.chapters(slug)

    context.user_data["chapters"] = chapters
    context.user_data["slug"] = slug
    context.user_data["source"] = src_name

    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []
    for i, ch in enumerate(subset, start=start):
        chap_num = ch.get("chapter_number") or "?"
        buttons.append([
            InlineKeyboardButton(
                f"Cap {chap_num}",
                callback_data=f"c|{i}"
            )
        ])

    # Navegação
    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton("«", callback_data=f"m|{src_name}|{slug}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("»", callback_data=f"m|{src_name}|{slug}|{page+1}")
        )
    if nav:
        buttons.append(nav)

    await query.edit_message_text(
        "📖 Selecione o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= OPÇÕES DE DOWNLOAD =================
async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, index_str = query.data.split("|")
    index = int(index_str)

    context.user_data["selected_index"] = index

    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data="d|single")],
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data="d|from")],
        [InlineKeyboardButton("📥 Baixar até cap X", callback_data="d|to_input")]
    ]

    await query.edit_message_text(
        "Escolha o tipo de download:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= DOWNLOAD =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, mode = query.data.split("|")
    chapters = context.user_data.get("chapters")
    index = context.user_data.get("selected_index")
    src_name = context.user_data.get("source")
    source_obj = sources[src_name]

    if chapters is None or index is None:
        await query.message.reply_text("❌ Sessão expirada. Busque novamente.")
        return

    if mode == "single":
        selected = [chapters[index]]
    elif mode == "from":
        selected = chapters[index:]
    elif mode == "to_input":
        await query.message.reply_text("Digite o número do capítulo final que deseja baixar:")
        return
    else:
        selected = [chapters[index]]

    await download_chapters(selected, source_obj, query)


# ================= INPUT DO CAPÍTULO FINAL =================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "chapters" not in context.user_data or "source" not in context.user_data:
        return

    try:
        final_cap = float(update.message.text)
    except:
        return await update.message.reply_text("❌ Número de capítulo inválido.")

    chapters = context.user_data["chapters"]
    source_obj = sources[context.user_data["source"]]
    index = context.user_data["selected_index"]

    # Seleciona capítulos do index até final_cap
    selected = [
        ch for ch in chapters[index:]
        if (ch.get("chapter_number") or 0) <= final_cap
    ]

    if not selected:
        return await update.message.reply_text("❌ Nenhum capítulo encontrado nesse intervalo.")

    class DummyQuery:
        message = update.message
    dummy_query = DummyQuery()
    await download_chapters(selected, source_obj, dummy_query)


# ================= FUNÇÃO DE DOWNLOAD =================
async def download_chapters(chapters, source_obj, query):
    status = await query.message.reply_text(f"📦 Gerando {len(chapters)} capítulo(s)...")

    for chapter in chapters:
        imgs = await source_obj.pages(chapter["url"])

        if not imgs:
            await query.message.reply_text(
                f"❌ Cap {chapter.get('chapter_number')} vazio ou bloqueado."
            )
            continue

        cbz_path, cbz_name = await create_cbz(
            imgs,
            chapter["manga_title"],
            f"Cap {chapter.get('chapter_number')}"
        )

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
    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^m\\|"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^c\\|"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^d\\|"))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters=None, callback=handle_text))

    app.add_error_handler(error_handler)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
