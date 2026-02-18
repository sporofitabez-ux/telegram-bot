import httpx

class Mangaflix:
    name = "Mangaflix"
    base_url = "https://mangaflix.net"
    api_url = "https://api.mangaflix.net/v1"

    # ================= SEARCH =================
    async def search(self, query: str):
        url = f"{self.api_url}/search/mangas?query={query}&selected_language=pt-br"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        results = []
        for item in data.get("data", []):
            results.append({
                "title": item.get("name"),
                "url": item.get("_id")
            })
        return results

    # ================= CHAPTERS =================
    async def chapters(self, manga_id: str):
        url = f"{self.api_url}/mangas/{manga_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        chapters = []
        for ch in data.get("data", {}).get("chapters", []):
            chapters.append({
                "name": f"Capítulo {ch.get('number')}",
                "chapter_number": ch.get("number"),
                "url": ch.get("_id")
            })

        # Ordena capítulos do mais recente
        chapters.sort(key=lambda x: float(x.get("chapter_number") or 0), reverse=True)
        return chapters

    # ================= PAGES =================
    async def pages(self, chapter_id: str):
        url = f"{self.api_url}/chapters/{chapter_id}?selected_language=pt-br"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        pages = []
        for img in data.get("data", {}).get("images", []):
            if img.get("default_url"):
                pages.append(img["default_url"])
        return pages
