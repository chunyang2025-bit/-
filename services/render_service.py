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
from app.models import DesignItem, DesignPlan, GenerateRequest, RenderedAsset, RenderedClip


class RenderService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate(self, request: GenerateRequest, plan: DesignPlan) -> RenderedAsset:
        prompt = self._build_prompt(request, plan)
        filename = f"home_design_render_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        output = self.settings.renders_dir / filename
        render_provider = (self.settings.render_provider or "demo").lower()
        if render_provider == "kling" and self.settings.render_api_key:
            try:
                if self._wants_video_render():
                    self._draw_demo_render(output, request, plan, f"{prompt}｜Kling text-to-video preview")
                    clips = await self._generate_kling_clip_set(request, plan, filename, prompt)
                    first_clip = clips[0] if clips else None
                    return RenderedAsset(
                        render_url=self.settings.public_url(f"/renders/{filename}"),
                        render_path=str(output),
                        prompt=prompt,
                        provider="kling-video",
                        is_demo=False,
                        render_type="video",
                        render_video_url=first_clip.video_url if first_clip else None,
                        render_video_path=first_clip.video_path if first_clip else None,
                        render_task_id=first_clip.task_id if first_clip else None,
                        render_video_duration_seconds=float(self.settings.render_duration),
                        render_clips=clips,
                    )
                await self._generate_image_with_kling(prompt, output)
                return RenderedAsset(
                    render_url=self.settings.public_url(f"/renders/{filename}"),
                    render_path=str(output),
                    prompt=prompt,
                    provider="kling",
                    is_demo=False,
                )
            except Exception as exc:
                self._draw_demo_render(output, request, plan, f"{prompt}｜Kling failed: {exc}")
                return RenderedAsset(
                    render_url=self.settings.public_url(f"/renders/{filename}"),
                    render_path=str(output),
                    prompt=f"{prompt}｜Kling failed: {exc}",
                    provider="kling-fallback",
                    is_demo=True,
                )
        self._draw_demo_render(output, request, plan, prompt)
        return RenderedAsset(
            render_url=self.settings.public_url(f"/renders/{filename}"),
            render_path=str(output),
            prompt=prompt,
            provider=render_provider,
            is_demo=render_provider == "demo",
        )

    def _wants_video_render(self) -> bool:
        render_kind = (self.settings.render_kind or "").lower()
        endpoint = (self.settings.render_endpoint or "").lower()
        return render_kind in {"video", "text-to-video", "kling-video"} or "text-to-video" in endpoint

    async def _generate_kling_clip_set(
        self,
        request: GenerateRequest,
        plan: DesignPlan,
        image_filename: str,
        cover_prompt: str,
    ) -> list[RenderedClip]:
        base_name = image_filename.replace(".jpg", "")
        clip_specs: list[tuple[str, str, str]] = [
            (
                "overall",
                "整体方案",
                self._build_video_prompt(cover_prompt, self.settings.render_duration),
            )
        ]
        if self.settings.render_product_clips:
            for item in plan.items[: self.settings.render_product_clip_count]:
                clip_specs.append(("product", item.name, self._build_item_video_prompt(request, item)))

        clips: list[RenderedClip] = []
        for index, (kind, title, clip_prompt) in enumerate(clip_specs):
            video_filename = f"{base_name}_{index:02d}_{kind}.mp4"
            video_output = self.settings.renders_dir / video_filename
            task_id = await self._generate_video_with_kling(clip_prompt, video_output)
            clips.append(
                RenderedClip(
                    title=title,
                    kind=kind,
                    video_url=self.settings.public_url(f"/renders/{video_filename}"),
                    video_path=str(video_output),
                    task_id=task_id,
                    duration_seconds=float(self.settings.render_duration),
                )
            )
        return clips

    async def _generate_image_with_kling(self, prompt: str, output: Path) -> None:
        base_url = (self.settings.render_api_url or "https://api.klingai.com").rstrip("/")
        endpoint = "/" + (self.settings.render_endpoint or "/v1/images/generations").lstrip("/")
        headers = self._auth_headers()
        payload = {
            "model_name": self.settings.render_model,
            "prompt": prompt,
            "negative_prompt": "low quality, blurry, distorted furniture, unreadable text, watermark, logo, people",
            "n": 1,
            "aspect_ratio": self.settings.render_aspect_ratio,
        }
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(f"{base_url}{endpoint}", headers=headers, json=payload)
            self._raise_render_error(response)
            data = response.json()
            self._raise_kling_api_error(data)
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
                poll = await client.get(f"{base_url}{endpoint}/{task_id}", headers=headers)
                self._raise_render_error(poll)
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

    async def _generate_video_with_kling(self, prompt: str, output: Path) -> str:
        base_url = (self.settings.render_api_url or "https://api-beijing.klingai.com").rstrip("/")
        endpoint = "/" + (self.settings.render_video_endpoint or "/text-to-video/kling-3.0-turbo").lstrip("/")
        task_endpoint = "/" + (self.settings.render_task_endpoint or "/tasks").lstrip("/")
        headers = self._auth_headers()
        external_task_id = f"ai_home_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        payload = {
            "prompt": prompt,
            "options": {
                "watermark_info": {"enabled": False},
                "external_task_id": external_task_id,
            },
            "settings": {
                "duration": self.settings.render_duration,
                "resolution": self.settings.render_resolution,
                "aspect_ratio": self.settings.render_aspect_ratio,
            },
        }
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.post(f"{base_url}{endpoint}", headers=headers, json=payload)
            self._raise_render_error(response)
            data = response.json()
            self._raise_kling_api_error(data)
            task_id = self._extract_task_id(data)
            if not task_id:
                raise RuntimeError(f"Kling text-to-video did not return task id: {data}")

            deadline = time.time() + self.settings.render_poll_seconds
            last_status = "submitted"
            while time.time() < deadline:
                await self._sleep(5)
                poll = await client.get(f"{base_url}{task_endpoint}", headers=headers, params={"task_ids": task_id})
                self._raise_render_error(poll)
                poll_data = poll.json()
                self._raise_kling_api_error(poll_data)
                task = self._extract_first_task(poll_data)
                last_status = self._extract_status(task)
                if last_status == "succeeded":
                    video_url = self._extract_video_url(task)
                    if not video_url:
                        raise RuntimeError(f"Kling task succeeded without video url: {poll_data}")
                    await self._download_video(client, video_url, output)
                    return task_id
                if last_status == "failed":
                    message = task.get("message") if isinstance(task, dict) else ""
                    raise RuntimeError(f"Kling text-to-video task failed: {message or poll_data}")
            raise TimeoutError(f"Kling text-to-video timed out, last_status={last_status}, task_id={task_id}")

    @staticmethod
    def _raise_render_error(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text[:1200]
            raise RuntimeError(f"{response.status_code} {response.reason_phrase}: {body}") from exc

    @staticmethod
    def _raise_kling_api_error(data: dict[str, Any]) -> None:
        code = data.get("code")
        if code in (None, 0, "0"):
            return
        message = data.get("message") or data.get("msg") or data
        raise RuntimeError(f"Kling API error {code}: {message}")

    def _auth_headers(self) -> dict[str, str]:
        token = self._kling_token()
        auth_prefix = (self.settings.render_auth_prefix or "").strip()
        return {
            "Content-Type": "application/json",
            self.settings.render_auth_header or "Authorization": f"{auth_prefix} {token}".strip(),
        }

    async def _download_render(self, client: httpx.AsyncClient, image_url: str, output: Path) -> None:
        response = await client.get(image_url, timeout=60, follow_redirects=True)
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGB")
        image.save(output, format="JPEG", quality=92)

    @staticmethod
    async def _download_video(client: httpx.AsyncClient, video_url: str, output: Path) -> None:
        response = await client.get(video_url, timeout=180, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        output.write_bytes(response.content)
        if output.stat().st_size == 0:
            raise RuntimeError("Downloaded Kling video is empty")

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

    def _kling_token(self) -> str:
        if self.settings.render_api_secret:
            return self._kling_jwt()
        return self.settings.render_api_key or ""

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
    def _extract_first_task(data: dict[str, Any]) -> dict[str, Any]:
        payload = data.get("data")
        if isinstance(payload, list) and payload:
            return payload[0] if isinstance(payload[0], dict) else {}
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, list) and result:
                return result[0] if isinstance(result[0], dict) else {}
            return payload
        return data

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
    def _extract_video_url(data: dict[str, Any]) -> Optional[str]:
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        outputs = payload.get("outputs") or []
        if isinstance(outputs, list):
            for item in outputs:
                if isinstance(item, dict) and item.get("type") == "video":
                    return item.get("url") or item.get("watermark_url")
        task_result = payload.get("task_result") if isinstance(payload, dict) else None
        if isinstance(task_result, dict):
            videos = task_result.get("videos") or []
            if videos and isinstance(videos[0], dict):
                return videos[0].get("url") or videos[0].get("video_url")
        return payload.get("url") or payload.get("video_url")

    @staticmethod
    def _build_prompt(request: GenerateRequest, plan: DesignPlan) -> str:
        item_names = "、".join(item.name for item in plan.items[:6])
        return (
            f"{request.area_sqm:g}平方米{request.space_type.value}，{request.decor_style.value}，"
            f"{request.house_property.value}，重点{request.video_focus.value}，包含{item_names}，"
            "温暖自然光，真实家装效果图，适合短视频开场。"
        )

    @staticmethod
    def _build_video_prompt(prompt: str, duration: int) -> str:
        first_duration = max(1, min(2, duration - 1))
        second_duration = max(1, duration - first_duration)
        first = f"{prompt}，真实家装全景，竖屏短视频，镜头缓慢推进，无人物，无文字，无水印"
        second = "家具软装商品细节展示，沙发、茶几、灯具、窗帘、地毯依次出现，真实材质，电商种草质感，温暖自然光"
        return f"镜头 1, {first_duration}, {first}; 镜头 2, {second_duration}, {second};"

    @staticmethod
    def _build_item_video_prompt(request: GenerateRequest, item: DesignItem) -> str:
        return (
            f"镜头 1, 2, {request.decor_style.value}{request.space_type.value}真实家装场景，镜头缓慢靠近{item.name}，"
            f"{item.material}材质，{item.size}规格，无人物，无文字，无水印;"
            f"镜头 2, 3, {item.name}软装商品细节特写，展示材质纹理、尺寸比例和摆放位置，"
            f"适合{item.scene}，{item.role}，真实电商种草短视频质感，温暖自然光;"
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
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/arphic/ukai.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
        return ImageFont.load_default()
