import httpx
from datetime import datetime

class MangaFlix:
    base_url = "https://mangaflix.net"
    api_url = "https://api.mangaflix.net/v1"
    
    async def search(self, query: str):
        """Busca mangás pelo nome"""
        if not query:
            return []

        url = f"{self.api_url}/search/mangas?query={query}&selected_language=pt-br"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json().get("data", [])

        results = []
        for item in data:
            results.append({
                "title": item.get("name"),
                "url": f"/br/manga/{item.get('_id')}",
                "manga_title": item.get("name")
            })
        return results

    async def chapters(self, slug: str):
        """Lista capítulos de um mangá"""
        manga_id = slug.split("/")[-1]
        url = f"{self.api_url}/mangas/{manga_id}"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json().get("data", {})
            chapters = data.get("chapters", [])

        result = []
        for ch in chapters:
            chapter_number = ch.get("number") or "?"
            iso_date = ch.get("iso_date")
            timestamp = 0
            if iso_date:
                try:
                    timestamp = int(datetime.fromisoformat(iso_date.replace("Z","+00:00")).timestamp())
                except:
                    timestamp = 0
            result.append({
                "chapter_number": chapter_number,
                "url": f"/br/manga/{ch.get('_id')}",
                "manga_title": data.get("name","Manga"),
                "date_upload": timestamp
            })
        # ordenar por número decrescente
        result.sort(key=lambda x: x.get("chapter_number") or 0, reverse=True)
        return result

    async def pages(self, chapter_url: str):
        """Lista URLs das páginas de um capítulo"""
        chapter_id = chapter_url.split("/")[-1]
        url = f"{self.api_url}/chapters/{chapter_id}?selected_language=pt-br"
        async with httpx.AsyncClient() as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json().get("data", {})
            images = data.get("images", [])

        return [img.get("default_url") for img in images if img.get("default_url")]
