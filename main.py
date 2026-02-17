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

from sources.toonbr import ToonBr
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

source = ToonBr()
CHAPTERS_PER_PAGE = 10


# ================= ERROR HANDLER =================
async def error_handler(update, context):
    print("========== ERRO GLOBAL ==========")
    traceback.print_exception(None, context.error, context.error.__traceback__)
    print("==================================")


# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 ToonBr Bot Online!\n\nUse:\n/buscar nome_do_manga"
    )


# ================= BUSCAR =================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Use: /buscar nome")

    query = " ".join(context.args)
    results = await source.search(query)

    if not results:
        return await update.message.reply_text("Nenhum resultado encontrado.")

    buttons = []
    for manga in results[:10]:
        buttons.append([
            InlineKeyboardButton(
                manga["title"],
                callback_data=f"m|{manga['url']}|0"
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

    _, slug, page_str = query.data.split("|")
    page = int(page_str)

    chapters = await source.chapters(slug)

    # salva na sessão do usuário
    context.user_data["chapters"] = chapters
    context.user_data["slug"] = slug

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
            InlineKeyboardButton("«", callback_data=f"m|{slug}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("»", callback_data=f"m|{slug}|{page+1}")
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
        [InlineKeyboardButton("📥 Baixar até aqui", callback_data="d|to")]
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

    if chapters is None or index is None:
        await query.message.reply_text("❌ Sessão expirada. Busque novamente.")
        return

    if mode == "single":
        selected = [chapters[index]]
    elif mode == "from":
        selected = chapters[index:]
    elif mode == "to":
        selected = chapters[:index+1]
    else:
        selected = [chapters[index]]

    status = await query.message.reply_text(
        f"📦 Gerando {len(selected)} capítulo(s)..."
    )

    for chapter in selected:
        imgs = await source.pages(chapter["url"])

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

    app.add_error_handler(error_handler)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
