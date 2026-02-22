import os
import asyncio
import logging
import time
import httpx

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
)

from utils.loader import get_all_sources
from utils.cbz import create_cbz
from utils.queue_manager import (
    DOWNLOAD_QUEUE,
    add_job,
    remove_job,
    queue_size,
)

logging.basicConfig(level=logging.INFO)

DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
CHAPTERS_PER_PAGE = 10
USER_COOLDOWN = {}
COOLDOWN_TIME = 4


# =====================================================
# TRADUÇÃO SIMPLES PARA PT-BR
# =====================================================
async def translate_to_pt(text):
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://translate.googleapis.com/translate_a/single",
                params={
                    "client": "gtx",
                    "sl": "auto",
                    "tl": "pt",
                    "dt": "t",
                    "q": text
                }
            )
        result = r.json()
        return "".join([item[0] for item in result[0]])
    except:
        return text


# =====================================================
# ANI LIST
# =====================================================
async def fetch_anilist_info(title):

    query = """
    query ($search: String) {
      Media(search: $search, type: MANGA) {
        description(asHtml: false)
        status
        genres
        coverImage {
          extraLarge
        }
      }
    }
    """

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"search": title}},
        )

    data = response.json().get("data", {}).get("Media")
    if not data:
        return None

    status_map = {
        "FINISHED": "Finalizado",
        "RELEASING": "Em lançamento",
        "NOT_YET_RELEASED": "Não lançado",
        "CANCELLED": "Cancelado",
    }

    synopsis = data.get("description") or "Sem descrição."
    synopsis = synopsis[:1200]

    # TRADUZ
    synopsis_pt = await translate_to_pt(synopsis)

    return {
        "cover": data["coverImage"]["extraLarge"],
        "status": status_map.get(data["status"], "Desconhecido"),
        "genres": ", ".join(data["genres"]),
        "synopsis": synopsis_pt
    }


# =====================================================
# ENVIO DO CAPÍTULO
# =====================================================
async def send_chapter(message, source, chapter):

    async with DOWNLOAD_SEMAPHORE:

        cid = chapter.get("url")
        num = chapter.get("chapter_number")
        manga_title = chapter.get("manga_title", "Manga")

        try:
            imgs = await source.pages(cid)
            if not imgs:
                return

            cbz_buffer, cbz_name = await create_cbz(
                imgs,
                manga_title,
                f"Cap_{num}"
            )

            await message.reply_document(
                document=cbz_buffer,
                filename=cbz_name
            )

        except Exception as e:
            print("Erro envio:", e)

        finally:
            try:
                cbz_buffer.close()
            except:
                pass


# =====================================================
# WORKER
# =====================================================
async def download_worker():
    while True:
        job = await DOWNLOAD_QUEUE.get()

        try:
            await send_chapter(
                job["message"],
                job["source"],
                job["chapter"],
            )
            await asyncio.sleep(1.5)
        except Exception as e:
            print("Erro worker:", e)

        remove_job()
        DOWNLOAD_QUEUE.task_done()


# =====================================================
# BUSCAR
# =====================================================
async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        return await update.message.reply_text("Use: /buscar nome")

    query_text = " ".join(context.args)
    sources = get_all_sources()

    await update.message.reply_text(f"🔎 Buscando «{query_text}»")

    for source_name, source in sources.items():
        try:
            results = await source.search(query_text)
            if not results:
                continue

            manga = results[0]
            title = manga.get("title")
            url = manga.get("url")

            chapters = await source.chapters(url)
            chapters.sort(key=lambda x: float(x.get("chapter_number", 0)))

            context.user_data["chapters"] = chapters
            context.user_data["source"] = source
            context.user_data["page"] = 0

            info = await fetch_anilist_info(title)

            if info:
                caption = f"""📚 «{title}»

Status » {info['status']}
Gênero: {info['genres']}

Sinopse:
{info['synopsis']}

🔗 @animesmangas308"""

                await update.message.reply_photo(
                    photo=info["cover"],
                    caption=caption
                )

            await send_chapter_list(update.message, context)
            return

        except Exception as e:
            print("Erro:", e)

    await update.message.reply_text("❌ Nenhum resultado encontrado.")


# =====================================================
# LISTA PAGINADA (SEM DELETAR)
# =====================================================
async def send_chapter_list(message, context):

    chapters = context.user_data["chapters"]
    page = context.user_data["page"]

    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE

    keyboard = []

    for ch in chapters[start:end]:
        num = ch.get("chapter_number")
        keyboard.append([
            InlineKeyboardButton(
                f"📖 Capítulo {num}",
                callback_data=f"select_{num}"
            )
        ])

    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data="prev"))
    if end < len(chapters):
        nav.append(InlineKeyboardButton("➡️", callback_data="next"))

    if nav:
        keyboard.append(nav)

    await message.reply_text(
        "Escolha o capítulo:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =====================================================
# CALLBACKS
# =====================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    chapters = context.user_data["chapters"]
    source = context.user_data["source"]

    # PAGINAÇÃO ESTÁVEL
    if query.data == "next":
        context.user_data["page"] += 1
        await query.message.edit_reply_markup(None)
        await send_chapter_list(query.message, context)
        return

    if query.data == "prev":
        context.user_data["page"] -= 1
        await query.message.edit_reply_markup(None)
        await send_chapter_list(query.message, context)
        return

    # SELEÇÃO
    if query.data.startswith("select_"):
        number = query.data.split("_")[1]
        context.user_data["selected"] = float(number)

        keyboard = [
            [InlineKeyboardButton("🔥 Baixar este", callback_data="one")],
            [InlineKeyboardButton("⬇️ Baixar até aqui", callback_data="upto")],
            [InlineKeyboardButton("📥 Baixar todos", callback_data="all")]
        ]

        await query.message.reply_text(
            f"Capítulo {number} selecionado:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # BAIXAR UM
    if query.data == "one":
        number = context.user_data["selected"]

        for ch in chapters:
            if float(ch.get("chapter_number", 0)) == number:
                await add_job({
                    "message": query.message,
                    "source": source,
                    "chapter": ch,
                })
                break

        await query.message.reply_text("✅ Adicionado à fila.")
        return

    # BAIXAR ATÉ
    if query.data == "upto":
        number = context.user_data["selected"]

        for ch in chapters:
            if float(ch.get("chapter_number", 0)) <= number:
                await add_job({
                    "message": query.message,
                    "source": source,
                    "chapter": ch,
                })

        await query.message.reply_text("⬇️ Capítulos adicionados até aqui.")
        return

    # BAIXAR TODOS (AGORA CORRETO)
    if query.data == "all":
        for ch in chapters:
            await add_job({
                "message": query.message,
                "source": source,
                "chapter": ch,
            })

        await query.message.reply_text("📥 Todos capítulos adicionados na fila.")
        return


# =====================================================
# MAIN
# =====================================================
def main():

    app = ApplicationBuilder().token(
        os.getenv("BOT_TOKEN")
    ).build()

    app.add_handler(CommandHandler("buscar", buscar))
    app.add_handler(CallbackQueryHandler(button_handler))

    async def startup(app):
        asyncio.create_task(download_worker())

    app.post_init = startup

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
