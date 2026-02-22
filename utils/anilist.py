import aiohttp
import re

ANILIST_URL = "https://graphql.anilist.co"

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"

_translation_cache = {}


def clean_html(text):
    return re.sub("<.*?>", "", text or "")


def summarize(text, max_sentences=4):
    sentences = text.split(". ")
    return ". ".join(sentences[:max_sentences]).strip() + "."


def is_english(text):
    common_words = ["the ", " is ", " of ", " and ", " in ", " to "]
    text_lower = text.lower()
    return any(word in text_lower for word in common_words)


async def translate_to_pt(text):

    if text in _translation_cache:
        return _translation_cache[text]

    params = {
        "client": "gtx",
        "sl": "en",
        "tl": "pt",
        "dt": "t",
        "q": text,
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(TRANSLATE_URL, params=params) as resp:
            result = await resp.json()

    translated = "".join([item[0] for item in result[0]])

    _translation_cache[text] = translated
    return translated


async def search_anilist(title):

    query = """
    query ($search: String) {
      Media(search: $search, type: MANGA) {
        title {
          romaji
          english
          native
        }
        description(asHtml: false)
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

    media = data["data"]["Media"]

    synopsis = clean_html(media.get("description", ""))

    if not synopsis:
        synopsis = "Sem sinopse disponível."

    # 🔥 FALLBACK AUTOMÁTICO
    if is_english(synopsis):
        try:
            synopsis = await translate_to_pt(synopsis)
        except:
            pass

    synopsis = summarize(synopsis)

    return {
        "title": media["title"]["romaji"]
        or media["title"]["english"]
        or media["title"]["native"],
        "genres": ", ".join(media.get("genres", [])),
        "cover": media["coverImage"]["extraLarge"],
        "synopsis": synopsis,
    }
