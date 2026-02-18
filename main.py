import os
import logging
import traceback
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from sources.loader import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
MAX_CONCURRENT_DOWNLOADS = 3

# ================= FONTS / SOURCES =================
sources = get_all_sources()  # {'ToonBr': ToonBrSource(), 'MangaFlix': MangaFlixSource()}

# ================= FILA DE DOWNLOAD =================
download_queue = asyncio.Queue()

async def worker():
    while True:
        task = await download_queue.get()
        if task is None:
            break
        try:
            await process_download(*task)
        except Exception as e:
            print(f"Erro no download: {e}")
        finally:
            download_queue.task_done()

async def process_download(message, context, chapters, source):
    for chapter in chapters:
        imgs = await source.pages(chapter["url"])
        if not imgs:
            await message.reply_text(
                f"❌ Cap {chapter.get('chapter_number')} vazio ou bloqueado."
            )
            continue

        cbz_path, cbz_name = await create_cbz(
            imgs,
            chapter["manga_title"],
            f"Cap {chapter.get('chapter_number')}"
        )

        await message.reply_document(
            document=open(cbz_path, "rb"),
            filename=cbz_name
        )
        os.remove(cbz_path)

# ================= ERROR HANDLER =================
async def error_handler(update, context):
    print("========== ERRO GLOBAL ==========")
    traceback.print_exception(None, context.error, context.error.__traceback__)
    print("==================================")

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Olá! Sou Yuki, Bot de download de mangás Online!\n\nUse:\n/buscar nome_do_manga"
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
            res = await src.search(query)
            for manga in res:
                manga["source"] = src_name
            results.extend(res)
        except Exception as e:
            print(f"Erro ao buscar na fonte {src_name}: {e}")

    if not results:
        return await update.message.reply_text("❌ Nenhum resultado encontrado.")

    buttons = []
    for manga in results[:10]:
        buttons.append([
            InlineKeyboardButton(
                f"{manga['title']} ({manga['source']})",
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

    _, source_name, slug, page_str = query.data.split("|")
    page = int(page_str)
    source = sources[source_name]

    chapters = await source.chapters(slug)

    context.user_data["chapters"] = chapters
    context.user_data["slug"] = slug
    context.user_data["source_name"] = source_name

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

    # navegação
    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton("«", callback_data=f"m|{source_name}|{slug}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("»", callback_data=f"m|{source_name}|{slug}|{page+1}")
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

    data = query.data.split("|")
    mode = data[1]

    chapters = context.user_data.get("chapters")
    index = context.user_data.get("selected_index")
    source_name = context.user_data.get("source_name")
    source = sources[source_name]

    if chapters is None or index is None:
        await query.message.reply_text("❌ Sessão expirada. Busque novamente.")
        return

    if mode == "single":
        selected = [chapters[index]]
    elif mode == "from":
        selected = chapters[index:]
    elif mode == "to_input":
        await query.message.reply_text("Digite o número do capítulo até onde quer baixar:")
        context.user_data["waiting_for_cap_input"] = True
        return
    else:
        selected = [chapters[index]]

    await query.message.reply_text(
        f"✅ Sua solicitação foi adicionada à fila. {len(selected)} capítulo(s) serão enviados em breve..."
    )
    await download_queue.put((query.message, context, selected, source))

# ================= INPUT DE CAP X =================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_cap_input"):
        cap_str = update.message.text.strip()
        if not cap_str.isdigit():
            await update.message.reply_text("❌ Número inválido.")
            return
        cap_number = int(cap_str)
        chapters = context.user_data.get("chapters")
        index = context.user_data.get("selected_index")
        source_name = context.user_data.get("source_name")
        source = sources[source_name]

        if cap_number < 1 or cap_number > len(chapters):
            await update.message.reply_text("❌ Capítulo fora do intervalo.")
            return

        selected = chapters[:cap_number]
        await update.message.reply_text(
            f"✅ Sua solicitação foi adicionada à fila. {len(selected)} capítulo(s) serão enviados em breve..."
        )
        await download_queue.put((update.message, context, selected, source))
        context.user_data["waiting_for_cap_input"] = False

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^m\\|"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^c\\|"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^d\\|"))
    app.add_handler(CommandHandler("cancel", lambda u, c: u.message.reply_text("Cancelado")))
    app.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text("Use /buscar <nome do manga>")))
    app.add_handler(
        # Captura mensagens de texto para input de cap X
        CommandHandler("text", text_handler)  # ou MessageHandler(Filters.text & ~Filters.command, text_handler) se usar telegram.ext.filters
    )

    app.add_error_handler(error_handler)

    # Inicia os workers
    for _ in range(MAX_CONCURRENT_DOWNLOADS):
        asyncio.create_task(worker())

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
