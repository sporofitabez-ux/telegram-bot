import httpx


class ToonBr:
    name = "ToonBr"
    base_url = "https://beta.toonbr.com"
    api_url = "https://api.toonbr.com"
    cdn_url = "https://cdn2.toonbr.com"

    # ================= SEARCH =================
    async def search(self, query: str):
        url = f"{self.api_url}/api/manga?page=1&limit=20&search={query}"

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        results = []
        for manga in data.get("data", []):
            results.append({
                "title": manga.get("title"),
                "url": manga.get("slug"),  # slug do mangá
            })

        return results

    # ================= CHAPTERS =================
    async def chapters(self, manga_slug: str):
        url = f"{self.api_url}/api/manga/{manga_slug}"

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        chapters = []
        manga_title = data.get("title", "Manga")

        for ch in data.get("chapters", []):
            chapters.append({
                "name": ch.get("name"),
                "chapter_number": ch.get("chapterNumber"),
                "url": ch.get("id"),  # ID do capítulo
                "manga_title": manga_title,
            })

        # Ordena com segurança (evita crash se vier None)
        def safe_float(x):
            try:
                return float(x)
            except:
                return 0.0

        chapters.sort(
            key=lambda x: safe_float(x.get("chapter_number")),
            reverse=True
        )

        return chapters

    # ================= PAGES =================
    async def pages(self, chapter_id: str):
        url = f"{self.api_url}/api/chapter/{chapter_id}"

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()

        pages = []
        for p in data.get("pages", []):
            image = p.get("imageUrl")
            if image:
                pages.append(f"{self.cdn_url}{image}")

        return pages
