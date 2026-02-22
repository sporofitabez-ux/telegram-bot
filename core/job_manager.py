import uuid

class MangaJob:
    def __init__(self, user_id, message, source, chapters):
        self.id = str(uuid.uuid4())[:8]
        self.user_id = user_id
        self.message = message
        self.source = source
        self.chapters = chapters
        self.total = len(chapters)
        self.progress = 0
        self.status = "queued"
        self.cancelled = False

    def update_progress(self):
        self.progress += 1

    def is_finished(self):
        return self.progress >= self.total
