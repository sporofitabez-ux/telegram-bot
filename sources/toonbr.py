import httpx
from datetime import datetime

API_URL = "https://api.toonbr.com"
CDN_URL = "https://cdn2.toonbr.com"

PAGE_LIMIT = 150


class ToonBrSource:

    def __init__(self, email=None, password=None):
        self.email = email
        self.password = password
        self.token = None
        self.client = httpx.AsyncClient(timeout=30)

    # ================= LOGIN =================

    async def login(self):
        if not self.email or not self.password:
            return None

        payload = {
            "email": self.email,
            "password": self.password
        }

        r = await self.client.post(f"{API_URL}/api/auth/login", json=payload)

        if r.status_code == 200:
            self.token = r.json().get("token")
            return self.token
        else:
            return None

    def _headers(self):
        headers = {}
        if self.token:
            headers["Cookie"] = f"token={self.token}"
        return headers

    # ================= POPULAR =================

    async def popular(self):
        r = await self.client.get(
            f"{API_URL}/api/manga/popular?limit={PAGE_LIMIT}",
            headers=self._headers()
        )
        return r.json()

    # ================= LATEST =================

    async def latest(self):
        r = await self.client.get(
            f"{API_URL}/api/manga/latest?limit={PAGE_LIMIT}",
            headers=self._headers()
        )
        return r.json()

    # ================= SEARCH =================

    async def search(self, query="", page=1, category_id=None):
        url = f"{API_URL}/api/manga?page={page}&limit={PAGE_LIMIT}"

        if query:
            url += f"&search={query}"

        if category_id:
            url += f"&categoryId={category_id}"

        r = await self.client.get(url, headers=self._headers())
        return r.json()

    # ================= DETAILS =================

    async def details(self, slug):
        r = await self.client.get(
            f"{API_URL}/api/manga/{slug}",
            headers=self._headers()
        )
        return r.json()

    # ================= CHAPTERS =================

    async def chapters(self, slug):
        data = await self.details(slug)
        chapters = data.get("chapters", [])

        # Ordenar igual extensão
        chapters.sort(key=lambda x: x.get("chapter_number", 0), reverse=True)

        return chapters

    # ================= PAGES =================

    async def pages(self, chapter_id):
        r = await self.client.get(
            f"{API_URL}/api/chapter/{chapter_id}",
            headers=self._headers()
        )

        data = r.json()

        pages = []
        for page in data.get("pages", []):
            if page.get("imageUrl"):
                pages.append(CDN_URL + page["imageUrl"])

        return pages
