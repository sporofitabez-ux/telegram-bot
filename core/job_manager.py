import os
import shutil
import asyncio


class MangaJob:
    def __init__(self, user_id, message, source, chapters):
        self.user_id = user_id
        self.message = message
        self.source = source
        self.chapters = chapters
        self.total = len(chapters)
        self.progress = 0

    async def run(self):
        await self.message.reply_text(
            f"📥 Iniciando download\nTotal: {self.total} capítulos"
        )

        for index, chapter in enumerate(self.chapters, start=1):
            self.progress = index

            try:
                file_path = await self.source.download_chapter(chapter)

                await self.message.reply_document(
                    document=open(file_path, "rb")
                )

                # 🔥 Apaga após enviar (economiza Railway)
                try:
                    os.remove(file_path)
                except:
                    pass

            except Exception as e:
                print("Erro no capítulo:", e)
                continue

        await self.message.reply_text("✅ Download finalizado.")
