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

# ===== IMPORTA DIRETO AS FONTES =====
from sources.toonbr import ToonBrSource
from sources.mangaflix import MangaFlixSource


# =========================
# FONTES
# =========================
SOURCES = {
    "ToonBr": ToonBrSource(),
    "MangaFlix": MangaFlixSource()
}

def get_all_sources():
    return SOURCES


# =========================
# CONFIG
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
# RESUMIR TEXTO
# =========================
def resumir(texto, limit=450):
    if not texto:
        return "Sem sinopse."

    texto = html.unescape(texto).replace("<br>", "\n")

    if len(texto) <= limit:
        return texto

    return texto[:limit].rsplit(".", 1)[0] + "..."


# =========================
# TRADUÇÃO PT
# =========================
async def traduzir_pt(texto):
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
# ANILIST API + CACHE
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

    async with httpx.AsyncClient(timeout=20) as client:
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
# WORKER (FILA)
# =========================
async def worker(app: Application):

    while True:
        job = await job_queue.get()

        try:
            bot = app.bot
            chat_id = job["chat_id"]
            source = job["source"]
            chapter_url = job["chapter_url"]

            images = await source.pages(chapter_url)

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

    keyboard = []

    for source_name, source in get_all_sources().items():
        try:
            results = await source.search(nome)

            for manga in results[:4]:
                keyboard.append([
                    InlineKeyboardButton(
                        f"{source_name} • {manga['title']}",
                        callback_data=f"select|{source_name}|{manga['url']}|{manga['title']}"
                    )
                ])
        except Exception as e:
            print("Erro fonte:", e)

    texto = f"""
<b>{html.escape(titulo)}</b>

📚 <b>Gêneros:</b> {generos}

📝 <b>Sinopse:</b>
{html.escape(sinopse)}
"""

    msg = await update.message.reply_photo(
        photo=capa,
        caption=texto,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    asyncio.create_task(auto_delete(context, msg.chat_id, msg.message_id))


# =========================
# ESCOLHER MANGÁ
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
# DOWNLOAD
# =========================
async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    await q.answer()

    user = q.from_user.id

    if user_jobs[user] >= MAX_USER_JOBS:
        await q.message.reply_text("⚠️ Aguarde terminar seus downloads.")
        return

    _, source_name, url, title = q.data.split("|", 3)
    source = get_all_sources()[source_name]

    user_jobs[user] += 1

    await job_queue.put({
        "chat_id": q.message.chat_id,
        "source": source,
        "chapter_url": url,
        "user": user
    })

    await q.message.reply_text("✅ Adicionado à fila.")


# =========================
# INICIAR WORKER CORRETAMENTE
# =========================
async def post_init(app: Application):
    asyncio.create_task(worker(app))


# =========================
# MAIN
# =========================
def main():

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("bb", bb))
    app.add_handler(CallbackQueryHandler(selecionar, pattern="^select"))
    app.add_handler(CallbackQueryHandler(download, pattern="^download"))

    print("👑 BOT GOD ONLINE")

    app.run_polling()


if __name__ == "__main__":
    main()
