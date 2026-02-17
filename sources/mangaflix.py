import httpx
import asyncio

class MangaFlixSource:
    def __init__(self):
        self.api_url = "https://api.mangaflix.net/v1"
        self.client = httpx.AsyncClient(timeout=30)

    async def search(self, query: str):
        url = f"{self.api_url}/search/mangas?query={query}&selected_language=pt-br"
        resp = await self.client.get(url)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [
            {
                "title": item.get("name"),
                "url": item.get("_id"),
                "manga_title": item.get("name")
            } for item in data
        ]

    async def chapters(self, manga_id: str):
        url = f"{self.api_url}/mangas/{manga_id}"
        resp = await self.client.get(url)
        if resp.status_code != 200:
            return []
        manga = resp.json().get("data", {})
        chapters = manga.get("chapters", [])
        return [
            {
                "url": ch.get("_id"),
                "chapter_number": ch.get("number"),
                "name": f"Cap {ch.get('number')}",
                "manga_title": manga.get("name")
            } for ch in chapters
        ]

    async def pages(self, chapter_id: str):
        url = f"{self.api_url}/chapters/{chapter_id}?selected_language=pt-br"
        resp = await self.client.get(url)
        if resp.status_code != 200:
            return []
        chapter = resp.json().get("data", {})
        return [img.get("default_url") for img in chapter.get("images", []) if img.get("default_url")]
