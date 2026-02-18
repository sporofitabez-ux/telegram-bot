# sources/mangaflix.py
import aiohttp
import asyncio

class MangaFlixSource:
    BASE_URL = "https://api.mangaflix.net/v1"

    def __init__(self):
        self.session = None

    async def _get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session

    # ================= SEARCH =================
    async def search(self, query: str):
        session = await self._get_session()
        url = f"{self.BASE_URL}/search/mangas?query={query}&selected_language=pt-br"
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                results = []
                for item in data.get("data", []):
                    results.append({
                        "title": item.get("name"),
                        "url": f"/br/manga/{item.get('_id')}"
                    })
                return results
        except Exception:
            return []

    # ================= CHAPTERS =================
    async def chapters(self, manga_id: str):
        session = await self._get_session()
        mid = manga_id.split("/")[-1]
        url = f"{self.BASE_URL}/mangas/{mid}"
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                chapters = []
                for ch in data.get("data", {}).get("chapters", []):
                    chapters.append({
                        "chapter_number": ch.get("number"),
                        "url": f"/br/manga/{ch.get('_id')}",
                        "manga_title": data.get("data", {}).get("name", "Manga")
                    })
                return chapters
        except Exception:
            return []

    # ================= PAGES =================
    async def pages(self, chapter_id: str):
        session = await self._get_session()
        cid = chapter_id.split("/")[-1]
        url = f"{self.BASE_URL}/chapters/{cid}?selected_language=pt-br"
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                images = [img.get("default_url") for img in data.get("data", {}).get("images", [])]
                return images
        except Exception:
            return []

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
