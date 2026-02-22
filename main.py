import asyncio
import html
import httpx
from collections import defaultdict

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

from config import BOT_TOKEN
from loader import get_all_sources


# =========================
# CONFIG GOD
# =========================

DELETE_DELAY = 25
MAX_USER_JOBS = 2

job_queue = asyncio.Queue()
user_jobs = defaultdict(int)
anilist_cache = {}


# =========================
# AUTO DELETE
# =========================

async def auto_delete(context, chat_id, msg_id):
    await asyncio.sleep(DELETE_DELAY)
    try:
        await context.bot.delete_message(chat_id, msg_id)
    except:
        pass


# =========================
# RESUMO + TRADUÇÃO
# =========================

def resumir(texto, limit=450):
    if not texto:
        return "Sem sinopse."

    texto = html.unescape(texto).replace("<br>", "\n")

    if len(texto) <= limit:
        return texto

    return texto[:limit].rsplit(".", 1)[0] + "..."


async def traduzir_pt(texto):
    """Tradução leve gratuita"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://libretranslate.de/translate",
                json={
                    "q": texto,
                    "source": "en",
                    "target": "pt",
                    "format": "text"
                }
            )
        return r.json()["translatedText"]
    except:
        return texto


# =========================
# ANILIST (COM CACHE)
# =========================

async def buscar_anilist(nome):

    if nome in anilist_cache:
        return anilist_cache[nome]

    query = """
    query ($search: String) {
      Media(search: $search, type: MANGA) {
        title { romaji english }
        description(asHtml:false)
        genres
        coverImage { extraLarge }
      }
    }
    """

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"search": nome}}
        )

    media = r.json()["data"]["Media"]

    titulo = media["title"]["english"] or media["title"]["romaji"]
    sinopse = resumir(media.get("description"))
    sinopse = await traduzir_pt(sinopse)

    data = (
        titulo,
        sinopse,
        ", ".join(media["genres"]),
        media["coverImage"]["extraLarge"]
    )

    anilist_cache[nome] = data
    return data


# =========================
# WORKER GOD
# =========================

async def worker(app):

    while True:
        job = await job_queue.get()

        try:
            bot = app.bot
            chat_id = job["chat_id"]
            source = job["source"]
            chapter = job["chapter"]

            images = await source.pages(chapter["url"])

            # envia em blocos (evita flood)
            for i in range(0, len(images), 8):
                media = [InputMediaPhoto(img) for img in images[i:i+8]]
                msgs = await bot.send_media_group(chat_id, media)

                for m in msgs:
                    asyncio.create_task(
                        auto_delete(app, m.chat_id, m.message_id)
                    )

        except Exception as e:
            print("Worker erro:", e)

        finally:
            user_jobs[job["user"]] -= 1
            job_queue.task_done()


# =========================
# /bb BUSCAR
# =========================

async def bb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        return

    nome = " ".join(context.args)

    titulo, sinopse, generos, capa = await buscar_anilist(nome)

    sources = get_all_sources()
    keyboard = []

    for source_name, source in sources.items():
        try:
            results = await source.search(nome)

            for manga in results[:4]:
                keyboard.append([
                    InlineKeyboardButton(
                        f"{source_name} • {manga['title']}",
                        callback_data=f"select|{source_name}|{manga['url']}|{manga['title']}"
                    )
                ])
        except:
            pass

    texto = f"""
<b>{html.escape(titulo)}</b>

📚 <b>Gêneros:</b> {generos}

📝 <b>Sinopse:</b>
{html.escape(sinopse)}
"""

    msg = await update.message.reply_photo(
        capa,
        caption=texto,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    asyncio.create_task(auto_delete(context, msg.chat_id, msg.message_id))


# =========================
# SELECIONAR MANGÁ
# =========================

async def selecionar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    _, source_name, url, title = q.data.split("|", 3)
    source = get_all_sources()[source_name]

    chapters = await source.chapters(url)

    buttons = [
        [InlineKeyboardButton(
            f"Cap {c['chapter_number']}",
            callback_data=f"download|{source_name}|{c['url']}|{title}"
        )]
        for c in chapters[:25]
    ]

    msg = await q.message.reply_text(
        f"📖 {title}\nEscolha capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    asyncio.create_task(auto_delete(context, msg.chat_id, msg.message_id))


# =========================
# DOWNLOAD (QUEUE GOD)
# =========================

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    user = q.from_user.id

    if user_jobs[user] >= MAX_USER_JOBS:
        return await q.message.reply_text(
            "⚠️ Aguarde terminar seus downloads atuais."
        )

    _, source_name, url, title = q.data.split("|", 3)
    source = get_all_sources()[source_name]

    user_jobs[user] += 1

    await job_queue.put({
        "chat_id": q.message.chat_id,
        "source": source,
        "chapter": {"url": url},
        "user": user
    })

    await q.message.reply_text("✅ Adicionado à fila.")


# =========================
# MAIN
# =========================

def main():

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("bb", bb))
    app.add_handler(CallbackQueryHandler(selecionar, pattern="^select"))
    app.add_handler(CallbackQueryHandler(download, pattern="^download"))

    # inicia worker infinito
    app.create_task(worker(app))

    print("👑 BOT GOD ONLINE")
    app.run_polling()


if __name__ == "__main__":
    main()
