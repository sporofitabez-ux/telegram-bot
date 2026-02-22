import aiohttp
import re
import asyncio
from googletrans import Translator

ANILIST_URL = "https://graphql.anilist.co"

# Remove HTML da sinopse
def clean_html(text):
    return re.sub("<.*?>", "", text or "")

# Resumo simples automático
def summarize(text, max_sentences=3):
    sentences = text.split(". ")
    if len(sentences) > max_sentences:
        return ". ".join(sentences[:max_sentences]).strip() + "..."
    return text.strip()

# Formata a saída de forma bonita
def format_manga_info(data):
    return (
        f"🎌 **{data['title']}**\n"
        f"📚 Gêneros: {data['genres']}\n"
        f"📝 Sinopse: {data['synopsis']}\n"
        f"🖼️ Capa: {data['cover']}"
    )

# Função para traduzir para PT-BR usando googletrans
def translate_to_ptbr(text):
    translator = Translator()
    translation = translator.translate(text, src="en", dest="pt")
    return translation.text

async def search_anilist(title):

    query = """
    query ($search: String) {
      Media(search: $search, type: MANGA) {
        title {
          romaji
          english
        }
        description(asHtml:false)
        genres
        coverImage {
          extraLarge
        }
      }
    }
    """

    async with aiohttp.ClientSession() as session:
        async with session.post(
            ANILIST_URL,
            json={"query": query, "variables": {"search": title}},
        ) as resp:
            data = await resp.json()

    if not data.get("data") or not data["data"].get("Media"):
        return "❌ Mangá não encontrado."

    media = data["data"]["Media"]

    synopsis = clean_html(media.get("description"))
    synopsis = summarize(synopsis)
    
    # Traduz a sinopse para PT-BR
    translated_synopsis = translate_to_ptbr(synopsis)

    manga_info = {
        "title": media["title"].get("romaji") or media["title"].get("english"),
        "genres": ", ".join(media.get("genres", [])) or "Não disponível",
        "cover": media["coverImage"].get("extraLarge"),
        "synopsis": translated_synopsis or "Sem sinopse disponível.",
    }

    return format_manga_info(manga_info)


# Exemplo de uso
if __name__ == "__main__":
    title = "One Piece"
    result = asyncio.run(search_anilist(title))
    print(result)
