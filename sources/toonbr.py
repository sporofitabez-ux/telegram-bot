# sources/toonbr.py
import aiohttp
import asyncio

class ToonBrSource:
    name = "ToonBr"
    apiUrl = "https://api.toonbr.com"
    cdnUrl = "https://cdn2.toonbr.com"

    async def _get_json(self, url):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()

    async def search(self, query: str):
        url = f"{self.apiUrl}/api/manga?search={query}"
        data = await self._get_json(url)
        results = []
        for m in data.get("data", []):
            results.append({
                "title": m.get("name"),
                "url": m.get("_id"),
            })
        return results

    async def chapters(self, manga_id: str):
        url = f"{self.apiUrl}/api/manga/{manga_id}"
        data = await self._get_json(url)
        chapters = []
        for ch in data.get("chapters", []):
            chapters.append({
                "name": f"Cap {ch.get('number')}",
                "url": ch.get("_id"),
                "chapter_number": ch.get("number"),
                "manga_title": data.get("name"),
            })
        return chapters

    async def pages(self, chapter_id: str):
        url = f"{self.apiUrl}/api/chapter/{chapter_id}"
        data = await self._get_json(url)
        pages = []
        for p in data.get("pages", []):
            pages.append(f"{self.cdnUrl}{p.get('imageUrl')}")
        return pages
