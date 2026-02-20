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
from utils.cbz import create_volume_cbz

logging.basicConfig(level=logging.INFO)

CHAPTERS_PER_PAGE = 10


# ================= UTIL =================

def chunk_chapters(chapters, size=50):
    for i in range(0, len(chapters), size):
        yield chapters[i:i + size]


# ================= START =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Manga Bot Online!\n\nUse:\n/buscar nome_do_manga"
    )


# ================= BUSCAR =================

async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("COMANDO BUSCAR RECEBIDO")

    if not context.args:
        return await update.message.reply_text("Use:\n/buscar nome_do_manga")

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
        except Exception as e:
            print("Erro search:", e)

    if not buttons:
        return await update.message.reply_text("❌ Nenhum resultado encontrado.")

    await update.message.reply_text(
        f"🔎 Resultados para: {query_text}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ================= LISTAR CAPÍTULOS =================

async def manga_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, source_name, manga_id, page_str = query.data.split("|")
    page = int(page_str)

    source = get_all_sources()[source_name]
    chapters = await source.chapters(manga_id)

    # salva capítulos na sessão do usuário
    context.user_data["chapters"] = chapters
    context.user_data["source_name"] = source_name

    total = len(chapters)
    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE
    subset = chapters[start:end]

    buttons = []
    for i, ch in enumerate(subset, start=start):
        num = ch.get("chapter_number")
        buttons.append([
            InlineKeyboardButton(
                f"Cap {num}",
                callback_data=f"c|{i}"
            )
        ])

    nav = []
    if start > 0:
        nav.append(
            InlineKeyboardButton("«", callback_data=f"m|{source_name}|{manga_id}|{page-1}")
        )
    if end < total:
        nav.append(
            InlineKeyboardButton("»", callback_data=f"m|{source_name}|{manga_id}|{page+1}")
        )
    if nav:
        buttons.append(nav)

    await query.edit_message_text(
        "📖 Selecione o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ================= ESCOLHER PONTO =================

async def chapter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, index_str = query.data.split("|")
    context.user_data["selected_index"] = int(index_str)

    buttons = [
        [InlineKeyboardButton("📥 Baixar deste até o fim", callback_data="d|from")],
        [InlineKeyboardButton("📥 Baixar até aqui", callback_data="d|to")],
    ]

    await query.edit_message_text(
        "Escolha o tipo de download:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ================= DOWNLOAD =================

async def download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chapters = context.user_data.get("chapters")
    index = context.user_data.get("selected_index")
    source_name = context.user_data.get("source_name")

    if not chapters:
        return await query.message.reply_text("Sessão expirada. Faça /buscar novamente.")

    _, mode = query.data.split("|")

    if mode == "from":
        selected = chapters[index:]
    else:
        selected = chapters[: index + 1]

    source = get_all_sources()[source_name]
    manga_title = selected[0].get("manga_title", "Manga")

    volumes = list(chunk_chapters(selected, 50))

    for idx, volume in enumerate(volumes, start=1):
        start_cap = volume[0].get("chapter_number")
        end_cap = volume[-1].get("chapter_number")

        status = await query.message.reply_text(
            f"📦 Gerando Volume {idx} ({start_cap}-{end_cap})..."
        )

        try:
            cbz_path, cbz_name = await create_volume_cbz(
                source,
                volume,
                manga_title,
                f"Vol_{start_cap}-{end_cap}"
            )

            await query.message.reply_document(
                document=open(cbz_path, "rb"),
                filename=cbz_name
            )

            os.remove(cbz_path)

        except Exception as e:
            await query.message.reply_text(f"Erro ao gerar volume: {e}")
            print("Erro volume:", e)

        await status.delete()


# ================= MAIN =================

def main():
    print("BOT INICIADO")

    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buscar", buscar))

    app.add_handler(CallbackQueryHandler(manga_callback, pattern="^m\\|"))
    app.add_handler(CallbackQueryHandler(chapter_callback, pattern="^c\\|"))
    app.add_handler(CallbackQueryHandler(download_callback, pattern="^d\\|"))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
