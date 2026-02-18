import os
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from utils.loader import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10
WAITING_FOR_CAP = 1


# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📚 Manga Bot Online!\nUse:\n/buscar nome_do_manga"
    )


# ================= BUSCAR =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.effective_message.reply_text(
            "Use:\n/buscar nome_do_manga"
        )

    query_text = " ".join(context.args)
    sources = get_all_sources()
    buttons = []

    for source_name, source in sources.items():
        try:
            results = await source.search(query_text)
            for manga in results[:6]:
                title = manga.get("title")
                url = manga.get("url")

                buttons.append([
                    InlineKeyboardButton(
                        f"{title} ({source_name})",
                        callback_data=f"m|{source_name}|{url}|0"
                    )
                ])
        except Exception:
            continue

    if not buttons:
        return await update.effective_message.reply_text(
            "❌ Nenhum resultado encontrado."
        )

    await update.effective_message.reply_text(
        f"🔎 Resultados para: {query_text}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= LISTAR CAPÍTULOS =================
async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_id, page_str = query.data.split("|")
    page = int(page_str)

    source = get_all_sources()[source_name]
    chapters = await source.chapters(manga_id)

    context.user_data["chapters"] = chapters
    context.user_data["source_name"] = source_name

    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []

    for i, ch in enumerate(subset, start=start):
        num = ch.get("chapter_number") or ch.get("name")
        buttons.append([
            InlineKeyboardButton(
                f"Cap {num}",
                callback_data=f"c|{i}"
            )
        ])

    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton(
                "«",
                callback_data=f"m|{source_name}|{manga_id}|{page-1}"
            )
        )
    if end < total:
        nav.append(
            InlineKeyboardButton(
                "»",
                callback_data=f"m|{source_name}|{manga_id}|{page+1}"
            )
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
    context.user_data["selected_index"] = int(index_str)

    buttons = [
        [InlineKeyboardButton("📥 Baixar este", callback_data="d|single")],
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data="d|from")],
        [InlineKeyboardButton("📥 Baixar até aqui", callback_data="d|to")],
        [InlineKeyboardButton("📥 Baixar até cap X", callback_data="input_cap")],
    ]

    await query.edit_message_text(
        "Escolha o tipo de download:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= DOWNLOAD NORMAL =================
async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, mode = query.data.split("|")

    chapters = context.user_data.get("chapters")
    index = context.user_data.get("selected_index")
    source_name = context.user_data.get("source_name")

    if not chapters:
        return await query.message.reply_text("Sessão expirada.")

    source = get_all_sources()[source_name]

    if mode == "single":
        selected = [chapters[index]]
    elif mode == "from":
        selected = chapters[index:]
    elif mode == "to":
        selected = chapters[: index + 1]
    else:
        selected = []

    status = await query.message.reply_text(
        f"📦 Gerando {len(selected)} capítulo(s)..."
    )

    for chapter in selected:
        await send_chapter(query.message, source, chapter)

    await status.delete()


# ================= BAIXAR ATÉ CAP X =================
async def input_cap_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "Digite o número do capítulo até onde deseja baixar:"
    )

    return WAITING_FOR_CAP


async def receive_cap_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cap_text = update.message.text.strip()

    if not cap_text.replace(".", "", 1).isdigit():
        await update.message.reply_text("Digite um número válido.")
        return WAITING_FOR_CAP

    cap_number = float(cap_text)

    chapters = context.user_data.get("chapters")
    source_name = context.user_data.get("source_name")

    if not chapters:
        await update.message.reply_text("Sessão expirada.")
        return ConversationHandler.END

    source = get_all_sources()[source_name]

    selected = [
        c for c in chapters
        if float(c.get("chapter_number") or 0) <= cap_number
    ]

    if not selected:
        await update.message.reply_text("Nenhum capítulo encontrado.")
        return ConversationHandler.END

    status = await update.message.reply_text(
        f"📦 Gerando {len(selected)} capítulo(s)..."
    )

    for chapter in selected:
        await send_chapter(update.message, source, chapter)

    await status.delete()
    return ConversationHandler.END


# ================= FUNÇÃO AUXILIAR =================
async def send_chapter(message, source, chapter):
    cid = chapter.get("url")
    num = chapter.get("chapter_number")
    manga_title = chapter.get("manga_title", "Manga")

    imgs = await source.pages(cid)

    if not imgs:
        return

    cbz_path, cbz_name = await create_cbz(
        imgs,
        manga_title,
        f"Cap_{num}"
    )

    await message.reply_document(
        document=open(cbz_path, "rb"),
        filename=cbz_name
    )

    os.remove(cbz_path)


# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(
        os.getenv("BOT_TOKEN")
    ).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))

    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^m\\|"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^c\\|"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^d\\|"))

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(input_cap_callback, pattern="^input_cap$")
        ],
        states={
            WAITING_FOR_CAP: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_cap_number
                )
            ],
        },
        fallbacks=[],
    )

    app.add_handler(conv_handler)

    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
