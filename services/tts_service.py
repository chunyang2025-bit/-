from pathlib import Path
from typing import Optional

import httpx

from app.config import Settings


class TtsService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def synthesize(self, text: str, filename: str) -> Optional[Path]:
        if not self.settings.has_openai:
            return None
        model = self.settings.openai_tts_model or "gpt-4o-mini-tts"
        output = self.settings.tmp_dir / filename
        payload = {"model": model, "voice": "alloy", "input": text, "format": "mp3"}
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        try:
            async with httpx.AsyncClient(base_url=self.settings.openai_base_url, timeout=60) as client:
                response = await client.post("/audio/speech", headers=headers, json=payload)
                response.raise_for_status()
            output.write_bytes(response.content)
            return output
        except Exception:
            return None
