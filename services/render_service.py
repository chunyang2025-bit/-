import base64
import hashlib
import hmac
import json
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from app.models import DesignPlan, GenerateRequest, RenderedAsset


class RenderService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate(self, request: GenerateRequest, plan: DesignPlan) -> RenderedAsset:
        prompt = self._build_prompt(request, plan)
        filename = f"home_design_render_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        output = self.settings.renders_dir / filename
        if self.settings.render_provider.lower() == "kling" and self.settings.render_api_key and self.settings.render_api_secret:
            try:
                await self._generate_with_kling(prompt, output)
                return RenderedAsset(
                    render_url=f"/renders/{filename}",
                    render_path=str(output),
                    prompt=prompt,
                    provider="kling",
                    is_demo=False,
                )
            except Exception:
                pass
        self._draw_demo_render(output, request, plan, prompt)
        return RenderedAsset(
            render_url=f"/renders/{filename}",
            render_path=str(output),
            prompt=prompt,
            provider=self.settings.render_provider,
            is_demo=self.settings.render_provider == "demo",
        )

    async def _generate_with_kling(self, prompt: str, output: Path) -> None:
        base_url = (self.settings.render_api_url or "https://api.klingai.com").rstrip("/")
        headers = {
            "Authorization": f"Bearer {self._kling_jwt()}",
            "Content-Type": "application/json",
        }
        payload = {
            "model_name": self.settings.render_model,
            "prompt": prompt,
            "negative_prompt": "low quality, blurry, distorted furniture, unreadable text, watermark, logo, people",
            "n": 1,
            "aspect_ratio": self.settings.render_aspect_ratio,
        }
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(f"{base_url}/v1/images/generations", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            task_id = self._extract_task_id(data)
            if not task_id:
                image_url = self._extract_image_url(data)
                if not image_url:
                    raise RuntimeError(f"Kling did not return task_id or image url: {data}")
                await self._download_render(client, image_url, output)
                return

            deadline = time.time() + self.settings.render_poll_seconds
            while time.time() < deadline:
                await self._sleep(3)
                poll = await client.get(f"{base_url}/v1/images/generations/{task_id}", headers=headers)
                poll.raise_for_status()
                poll_data = poll.json()
                status = self._extract_status(poll_data)
                if status in {"succeed", "success", "completed"}:
                    image_url = self._extract_image_url(poll_data)
                    if not image_url:
                        raise RuntimeError(f"Kling task succeeded without image url: {poll_data}")
                    await self._download_render(client, image_url, output)
                    return
                if status in {"failed", "failure"}:
                    raise RuntimeError(f"Kling task failed: {poll_data}")
        raise TimeoutError("Kling render timed out")

    async def _download_render(self, client: httpx.AsyncClient, image_url: str, output: Path) -> None:
        response = await client.get(image_url, timeout=60, follow_redirects=True)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGB")
        image.save(output, format="JPEG", quality=92)

    def _kling_jwt(self) -> str:
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self.settings.render_api_key,
            "exp": now + 1800,
            "nbf": now - 5,
        }
        signing_input = ".".join([self._b64_json(header), self._b64_json(payload)])
        signature = hmac.new(
            (self.settings.render_api_secret or "").encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return f"{signing_input}.{self._b64(signature)}"

    @staticmethod
    def _b64_json(payload: dict[str, Any]) -> str:
        return RenderService._b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

    @staticmethod
    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    @staticmethod
    async def _sleep(seconds: int) -> None:
        import asyncio

        await asyncio.sleep(seconds)

    @staticmethod
    def _extract_task_id(data: dict[str, Any]) -> Optional[str]:
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        return payload.get("task_id") or payload.get("id") or payload.get("taskId")

    @staticmethod
    def _extract_status(data: dict[str, Any]) -> str:
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        return str(payload.get("task_status") or payload.get("status") or "").lower()

    @staticmethod
    def _extract_image_url(data: dict[str, Any]) -> Optional[str]:
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        task_result = payload.get("task_result") if isinstance(payload, dict) else None
        if isinstance(task_result, dict):
            images = task_result.get("images") or []
            if images:
                return images[0].get("url") or images[0].get("image_url")
        images = payload.get("images") or payload.get("result") or []
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                return first.get("url") or first.get("image_url")
            if isinstance(first, str):
                return first
        return payload.get("url") or payload.get("image_url")

    @staticmethod
    def _build_prompt(request: GenerateRequest, plan: DesignPlan) -> str:
        item_names = "、".join(item.name for item in plan.items[:6])
        return (
            f"{request.area_sqm:g}平方米{request.space_type.value}，{request.decor_style.value}，"
            f"{request.house_property.value}，重点{request.video_focus.value}，包含{item_names}，"
            "温暖自然光，真实家装效果图，适合短视频开场。"
        )

    def _draw_demo_render(self, output: Path, request: GenerateRequest, plan: DesignPlan, prompt: str) -> None:
        width, height = 1600, 1200
        palettes = {
            "奶油风": ("#F2E8D8", "#D7C0A0", "#A77A58", "#F7F2EA"),
            "极简": ("#ECEDEA", "#C9CDC8", "#5F6862", "#FFFFFF"),
            "原木": ("#EFE1C8", "#C79B63", "#7B5634", "#FFF8EA"),
            "法式": ("#EFEAF0", "#CBB8C8", "#7F6384", "#FFF9FB"),
            "现代": ("#E8ECEF", "#AEB8BF", "#344451", "#FFFFFF"),
        }
        wall, wood, dark, panel = palettes.get(request.decor_style.value, palettes["奶油风"])
        image = Image.new("RGB", (width, height), wall)
        draw = ImageDraw.Draw(image)
        title_font = self._font(76)
        body_font = self._font(38)
        small_font = self._font(28)

        draw.rectangle([0, 760, width, height], fill="#D8C4A4")
        draw.polygon([(0, 760), (1600, 760), (1380, 1200), (220, 1200)], fill=wood)
        for x in range(-100, 1700, 160):
            draw.line([(x, 770), (x - 210, 1200)], fill="#B88D5F", width=5)

        draw.rectangle([120, 150, 540, 690], fill="#F8F4ED", outline="#C7B89F", width=8)
        draw.rectangle([150, 180, 510, 660], fill="#DCE7EA")
        for x in [230, 330, 430]:
            draw.line([(x, 180), (x, 660)], fill="#EEF5F7", width=10)
        draw.rounded_rectangle([115, 145, 545, 705], radius=28, outline=dark, width=5)

        draw.rounded_rectangle([620, 450, 1300, 690], radius=60, fill="#C98A65")
        draw.rounded_rectangle([540, 610, 1390, 840], radius=50, fill="#E0AD84")
        for x in [640, 1150]:
            draw.rectangle([x, 830, x + 80, 980], fill=dark)
        draw.rounded_rectangle([690, 510, 880, 640], radius=28, fill="#F4D6B9")
        draw.rounded_rectangle([940, 510, 1130, 640], radius=28, fill="#F6E5D2")

        draw.ellipse([430, 820, 1160, 1050], fill="#E7D7C4", outline="#C59B78", width=10)
        draw.rounded_rectangle([1080, 360, 1160, 810], radius=18, fill=dark)
        draw.ellipse([960, 250, 1270, 455], fill="#F9D889", outline="#8C6A3F", width=8)
        draw.ellipse([1010, 785, 1240, 875], fill=dark)

        draw.rounded_rectangle([1180, 210, 1420, 700], radius=18, fill="#CDA77C")
        for y in [330, 455, 580]:
            draw.rectangle([1210, y, 1390, y + 18], fill=dark)
        draw.ellipse([1250, 260, 1310, 320], fill="#7F9B7B")
        draw.rectangle([1268, 315, 1292, 380], fill="#5F7A56")

        draw.rounded_rectangle([70, 40, 1530, 150], radius=28, fill=panel)
        draw.text((110, 62), plan.title, font=title_font, fill=dark)
        draw.rounded_rectangle([90, 1015, 1510, 1145], radius=26, fill="#FFFFFF")
        draw.text((125, 1042), prompt[:56], font=body_font, fill=dark)
        draw.text((125, 1100), "AI 家装效果示意图｜权限审核期间用于流程演示", font=small_font, fill="#8A6A2A")
        image.save(output, format="JPEG", quality=90)

    @staticmethod
    def _font(size: int):
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        return ImageFont.load_default()
