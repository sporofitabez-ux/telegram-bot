import asyncio
import html
import httpx

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


# ===============================
# CONFIG
# ===============================

DELETE_DELAY = 25  # segundos para apagar mensagens do bot


# ===============================
# UTILIDADES
# ===============================

async def auto_delete(context, chat_id, message_id):
    await asyncio.sleep(DELETE_DELAY)
    try:
        await context.bot.delete_message(chat_id, message_id)
    except:
        pass


def resumir(texto: str, max_chars=500):
    """Resumo simples da sinopse"""
    if not texto:
        return "Sem sinopse disponível."

    texto = html.unescape(texto)
    texto = texto.replace("<br>", "\n")

    if len(texto) <= max_chars:
        return texto

    return texto[:max_chars].rsplit(".", 1)[0] + "..."


# ===============================
# ANILIST API
# ===============================

async def buscar_anilist(nome):
    url = "https://graphql.anilist.co"

    query = """
    query ($search: String) {
      Media(search: $search, type: MANGA) {
        title {
          romaji
          english
          native
        }
        description(asHtml:false)
        genres
        coverImage {
          extraLarge
        }
      }
    }
    """

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json={
            "query": query,
            "variables": {"search": nome}
        })

    data = r.json()["data"]["Media"]

    titulo = (
        data["title"]["english"]
        or data["title"]["romaji"]
        or data["title"]["native"]
    )

    descricao = resumir(data.get("description"))
    generos = ", ".join(data.get("genres", []))
    capa = data["coverImage"]["extraLarge"]

    return titulo, descricao, generos, capa


# ===============================
# COMANDO /bb (BUSCAR)
# ===============================

async def bb(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        msg = await update.message.reply_text("Use: /bb nome_do_manga")
        asyncio.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return

    nome = " ".join(context.args)

    loading = await update.message.reply_text("🔎 Buscando informações...")
    asyncio.create_task(auto_delete(context, loading.chat_id, loading.message_id))

    # ===== AniList =====
    try:
        titulo, sinopse, generos, capa = await buscar_anilist(nome)
    except:
        titulo, sinopse, generos, capa = nome, "Sem dados.", "-", None

    sources = get_all_sources()

    keyboard = []

    # ===== busca nas fontes =====
    for source_name, source in sources.items():
        try:
            results = await source.search(nome)

            for manga in results[:5]:
                keyboard.append([
                    InlineKeyboardButton(
                        f"{source_name} • {manga['title']}",
                        callback_data=f"select|{source_name}|{manga['url']}|{manga['title']}"
                    )
                ])

        except Exception as e:
            print("Erro fonte:", source_name, e)

    if not keyboard:
        msg = await update.message.reply_text("❌ Nenhum resultado encontrado.")
        asyncio.create_task(auto_delete(context, msg.chat_id, msg.message_id))
        return

    texto = f"""
<b>{html.escape(titulo)}</b>

📚 <b>Gêneros:</b> {generos}

📝 <b>Sinopse resumida:</b>
{html.escape(sinopse)}
"""

    sent = await update.message.reply_photo(
        photo=capa,
        caption=texto,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    asyncio.create_task(auto_delete(context, sent.chat_id, sent.message_id))


# ===============================
# ESCOLHER MANGÁ
# ===============================

async def selecionar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    _, source_name, url, title = query.data.split("|", 3)

    source = get_all_sources()[source_name]

    msg = await query.message.reply_text("📥 Carregando capítulos...")
    asyncio.create_task(auto_delete(context, msg.chat_id, msg.message_id))

    chapters = await source.chapters(url)

    buttons = []

    for ch in chapters[:20]:  # limite visual
        buttons.append([
            InlineKeyboardButton(
                f"Capítulo {ch['chapter_number']}",
                callback_data=f"download|{source_name}|{ch['url']}|{title}|{ch['chapter_number']}"
            )
        ])

    sent = await query.message.reply_text(
        f"📖 {title}\nEscolha o capítulo:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    asyncio.create_task(auto_delete(context, sent.chat_id, sent.message_id))


# ===============================
# DOWNLOAD
# ===============================

async def download(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    _, source_name, url, title, chapter = query.data.split("|", 4)

    source = get_all_sources()[source_name]

    loading = await query.message.reply_text(
        f"⬇️ Baixando {title} - Cap {chapter}"
    )

    asyncio.create_task(auto_delete(context, loading.chat_id, loading.message_id))

    images = await source.pages(url)

    media = [InputMediaPhoto(img) for img in images[:10]]

    sent = await query.message.reply_media_group(media)

    # apagar também as páginas depois
    for m in sent:
        asyncio.create_task(auto_delete(context, m.chat_id, m.message_id))


# ===============================
# MAIN
# ===============================

def main():

    app = Application.builder().token(BOT_TOKEN).build()

    # NÃO adicionamos /start → ele não responde
    app.add_handler(CommandHandler("bb", bb))
    app.add_handler(CallbackQueryHandler(selecionar, pattern="^select"))
    app.add_handler(CallbackQueryHandler(download, pattern="^download"))

    print("✅ Bot profissional iniciado")
    app.run_polling()


if __name__ == "__main__":
    main()
