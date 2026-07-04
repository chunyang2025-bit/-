import shutil
import subprocess
import textwrap
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Optional

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from app.models import BudgetResponse, DesignPlan, GenerateRequest, GeneratedVideo, ProductMatch
from services.tts_service import TtsService


class VideoService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tts = TtsService(settings)

    async def generate(
        self,
        request: GenerateRequest,
        plan: DesignPlan,
        matches: List[ProductMatch],
        budget: BudgetResponse,
    ) -> GeneratedVideo:
        filename = f"home_design_video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        output = self.settings.videos_dir / filename
        scenes = self._build_scenes(request, plan, matches, budget)
        self._attach_product_images(scenes, output.stem)
        narration = "。".join(scene["title"] + "，" + scene["body"] for scene in scenes)
        audio_path = await self.tts.synthesize(narration[:3600], filename.replace(".mp4", ".mp3"))
        self._render_movie(output, scenes, audio_path)
        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError(f"视频生成失败，未生成有效 MP4：{output}")
        return GeneratedVideo(
            video_url=f"/videos/{filename}",
            video_path=str(output),
            duration_seconds=round(sum(scene["duration"] for scene in scenes), 2),
            compliance_caption="AI 设计方案仅供参考｜商品来源：淘宝官方在售商品｜价格为实时券后价，以官网为准｜本内容由 AI 自动生成",
        )

    def _build_scenes(
        self,
        request: GenerateRequest,
        plan: DesignPlan,
        matches: List[ProductMatch],
        budget: BudgetResponse,
    ) -> list[dict]:
        scenes = [
            {
                "title": f"{request.area_sqm:g}㎡{request.decor_style.value}低成本改造",
                "body": "软装清单｜逐件商品视觉展示｜一键生成视频与采购表",
                "price": "TBK 未通过时使用虚拟商品演示",
                "duration": 4,
                "kind": "cover",
            },
            {
                "title": "整体方案",
                "body": plan.concept_summary,
                "price": request.video_focus.value,
                "duration": 8,
                "kind": "plan",
            },
        ]
        per_item = matches[:7]
        item_duration = 30 / max(len(per_item), 1)
        for match in per_item:
            product = match.products[0] if match.products else None
            scenes.append(
                {
                    "title": match.design_item.name,
                    "body": f"{match.design_item.material}｜{match.design_item.size}｜{match.design_item.role}",
                    "price": f"券后约 {product.final_price:.0f} 元" if product else "待匹配",
                    "shop": product.shop_name if product else "待匹配",
                    "sales": product.sales if product else 0,
                    "source": product.source if product else "无商品来源",
                    "is_realtime": bool(product and product.is_realtime),
                    "image_url": product.image_url if product else None,
                    "product_title": product.title if product else "未匹配到商品",
                    "duration": item_duration,
                    "kind": "product",
                }
            )
        scenes.append(
            {
                "title": "预算汇总",
                "body": f"低配 {budget.low_plan.total_price:.0f} 元｜高配 {budget.high_plan.total_price:.0f} 元",
                "price": "价格以淘宝实时页面为准",
                "duration": 8,
                "kind": "budget",
            }
        )
        scenes.append(
            {
                "title": "合规声明",
                "body": "AI 设计方案仅供参考。商品来源淘宝官方在售商品。本内容由 AI 自动生成。",
                "price": "可导出采购 Excel",
                "duration": 5,
                "kind": "compliance",
            }
        )
        return scenes

    def _attach_product_images(self, scenes: list[dict], run_id: str) -> None:
        asset_dir = self.settings.tmp_dir / run_id
        asset_dir.mkdir(parents=True, exist_ok=True)
        for index, scene in enumerate(scenes):
            image_url = scene.get("image_url")
            if not image_url:
                continue
            try:
                image_path = asset_dir / f"product_{index:02d}.jpg"
                image = self._download_image(image_url)
                image.save(image_path, format="JPEG", quality=88)
                scene["image_path"] = image_path
            except Exception:
                scene["image_path"] = None

    @staticmethod
    def _download_image(url: str) -> Image.Image:
        headers = {"User-Agent": "Mozilla/5.0"}
        with httpx.Client(timeout=12, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGB")

    def _render_movie(self, output: Path, scenes: list[dict], audio_path: Optional[Path]) -> None:
        try:
            self._render_with_ffmpeg(output, scenes, audio_path)
        except Exception as exc:
            self._render_storyboard_fallback(output, scenes)
            raise RuntimeError(
                "FFmpeg 无法生成 MP4，"
                f"已输出分镜文本：{output.with_suffix('.storyboard.txt')}，"
                f"错误日志：{output.with_suffix('.ffmpeg.log')}"
            ) from exc

    def _render_with_ffmpeg(self, output: Path, scenes: list[dict], audio_path: Optional[Path]) -> None:
        work_dir = self.settings.tmp_dir / output.stem
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            concat_file = work_dir / "concat.txt"
            frame_paths = []
            for index, scene in enumerate(scenes):
                frame_path = work_dir / f"scene_{index:02d}.png"
                self._draw_scene(scene, index).save(frame_path)
                frame_paths.append(frame_path)

            lines = []
            for frame_path, scene in zip(frame_paths, scenes):
                lines.append(f"file '{frame_path}'")
                lines.append(f"duration {scene['duration']}")
            lines.append(f"file '{frame_paths[-1]}'")
            concat_file.write_text("\n".join(lines), encoding="utf-8")

            silent_output = work_dir / "silent.mp4" if audio_path and audio_path.exists() else output
            self._run_ffmpeg(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-fps_mode",
                    "cfr",
                    str(silent_output),
                ],
                output.with_suffix(".ffmpeg.log"),
            )

            if audio_path and audio_path.exists():
                self._run_ffmpeg(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(silent_output),
                        "-i",
                        str(audio_path),
                        "-shortest",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        str(output),
                    ],
                    output.with_suffix(".ffmpeg.log"),
                )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    def _run_ffmpeg(command: list[str], log_path: Path) -> None:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        log_path.write_text(
            "COMMAND\n"
            + " ".join(command)
            + "\n\nSTDOUT\n"
            + result.stdout
            + "\n\nSTDERR\n"
            + result.stderr,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-1200:] or "ffmpeg failed")

    def _draw_scene(self, scene: dict, index: int) -> Image.Image:
        width, height = self.settings.video_width, self.settings.video_height
        palette = [("#F7F1E8", "#1E2328", "#D9633D"), ("#EAF3EF", "#17211C", "#2F7A68"), ("#F3EEF7", "#211827", "#8060A8")]
        bg, ink, accent = palette[index % len(palette)]
        image = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(image)
        title_font = self._font(74)
        body_font = self._font(42)
        price_font = self._font(58)
        small_font = self._font(28)

        draw.rectangle([0, 0, width, 18], fill=accent)
        if scene.get("kind") == "product":
            self._draw_product_scene(image, draw, scene, title_font, body_font, price_font, small_font, ink, accent)
        else:
            draw.rounded_rectangle([72, 170, width - 72, 430], radius=24, fill="#FFFFFF")
            self._multiline(draw, scene["title"], 112, 215, title_font, ink, 11, 88)
            self._multiline(draw, scene["body"], 92, 560, body_font, ink, 17, 62)
            draw.rounded_rectangle([92, 1210, width - 92, 1360], radius=18, fill=accent)
            self._multiline(draw, scene["price"], 132, 1248, price_font, "#FFFFFF", 13, 72)
        draw.text((92, height - 170), "商品来源・淘宝｜AI 自动生成｜价格以官网为准", font=small_font, fill=ink)
        draw.text((92, height - 115), "AI 设计方案仅供参考", font=small_font, fill=ink)
        return image

    def _draw_product_scene(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        scene: dict,
        title_font: ImageFont.FreeTypeFont,
        body_font: ImageFont.FreeTypeFont,
        price_font: ImageFont.FreeTypeFont,
        small_font: ImageFont.FreeTypeFont,
        ink: str,
        accent: str,
    ) -> None:
        width = self.settings.video_width
        draw.rounded_rectangle([66, 82, width - 66, 1550], radius=26, fill="#FFFFFF")
        image_path = scene.get("image_path")
        if image_path:
            product_image = Image.open(image_path).convert("RGB")
            product_image = self._fit_cover(product_image, (900, 900))
            image.paste(product_image, (90, 120))
            draw.rectangle([90, 120, 990, 1020], outline="#FFFFFF", width=4)
        else:
            self._draw_virtual_product(image, draw, scene, body_font, small_font, ink)

        badge = "淘宝实时商品" if scene.get("is_realtime") else "虚拟演示"
        badge_color = accent if scene.get("is_realtime") else "#8A6A2A"
        draw.rounded_rectangle([120, 1052, 410, 1116], radius=14, fill=badge_color)
        draw.text((146, 1065), badge, font=small_font, fill="#FFFFFF")

        self._multiline(draw, scene["title"], 112, 1160, title_font, ink, 10, 86)
        self._multiline(draw, scene["body"], 112, 1325, body_font, ink, 17, 58)
        product_title = scene.get("product_title") or ""
        self._multiline(draw, product_title, 112, 1450, small_font, "#4D4B45", 27, 40)

        draw.rounded_rectangle([88, 1580, width - 88, 1740], radius=18, fill=accent)
        self._multiline(draw, scene["price"], 126, 1618, price_font, "#FFFFFF", 12, 70)
        meta = f"{scene.get('shop', '')}｜销量 {scene.get('sales', 0)}｜{scene.get('source', '')}"
        self._multiline(draw, meta, 112, 1775, small_font, ink, 27, 40)

    def _draw_virtual_product(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        scene: dict,
        body_font: ImageFont.FreeTypeFont,
        small_font: ImageFont.FreeTypeFont,
        ink: str,
    ) -> None:
        draw.rounded_rectangle([90, 120, 990, 1020], radius=18, fill="#F4EFE6")
        draw.rectangle([120, 840, 960, 900], fill="#D7C7AD")
        draw.rectangle([140, 890, 940, 930], fill="#B99C78")
        draw.rectangle([120, 930, 960, 960], fill="#8D7558")
        title = scene.get("title", "")
        color = "#B97852"
        if "沙发" in title or "椅" in title:
            draw.rounded_rectangle([230, 520, 820, 720], radius=40, fill=color)
            draw.rounded_rectangle([180, 635, 870, 810], radius=34, fill="#D5A37C")
            draw.rectangle([250, 800, 310, 900], fill="#7B5A3B")
            draw.rectangle([740, 800, 800, 900], fill="#7B5A3B")
        elif "灯" in title:
            draw.rectangle([525, 440, 555, 835], fill="#6E5A43")
            draw.ellipse([390, 285, 690, 505], fill="#F6D98C", outline="#8E6B3A", width=6)
            draw.ellipse([450, 795, 630, 875], fill="#7B5A3B")
        elif "窗帘" in title:
            for x in range(210, 850, 90):
                draw.rounded_rectangle([x, 250, x + 70, 840], radius=28, fill="#D9C8AE")
            draw.rectangle([190, 235, 890, 260], fill="#7B5A3B")
        elif "地毯" in title:
            draw.rounded_rectangle([220, 560, 840, 810], radius=44, fill="#C96E4D")
            draw.rounded_rectangle([270, 600, 790, 770], radius=36, outline="#F5D0B5", width=8)
        elif "架" in title or "柜" in title:
            draw.rounded_rectangle([300, 300, 780, 835], radius=20, fill="#C6A47C")
            for y in [430, 560, 690]:
                draw.rectangle([330, y, 750, y + 18], fill="#7B5A3B")
            draw.rectangle([340, 835, 390, 920], fill="#7B5A3B")
            draw.rectangle([690, 835, 740, 920], fill="#7B5A3B")
        else:
            draw.rounded_rectangle([280, 370, 800, 790], radius=38, fill=color)
            draw.rounded_rectangle([330, 420, 750, 735], radius=30, fill="#E5B28A")

        draw.rounded_rectangle([130, 145, 490, 210], radius=14, fill="#8A6A2A")
        draw.text((154, 160), "虚拟商品演示图", font=small_font, fill="#FFFFFF")
        draw.text((165, 950), "等待淘宝客物料权限通过后替换为官方商品图", font=small_font, fill=ink)

    @staticmethod
    def _fit_cover(source: Image.Image, size: tuple[int, int]) -> Image.Image:
        target_w, target_h = size
        scale = max(target_w / source.width, target_h / source.height)
        resized = source.resize((int(source.width * scale), int(source.height * scale)))
        left = max((resized.width - target_w) // 2, 0)
        top = max((resized.height - target_h) // 2, 0)
        return resized.crop((left, top, left + target_w, top + target_h))

    def _multiline(self, draw: ImageDraw.ImageDraw, text: str, x: int, y: int, font: ImageFont.FreeTypeFont, fill: str, width: int, line_gap: int) -> None:
        for offset, line in enumerate(self._wrap(text, width)):
            draw.text((x, y + offset * line_gap), line, font=font, fill=fill)

    @staticmethod
    def _wrap(text: str, width: int) -> Iterable[str]:
        lines: list[str] = []
        for part in text.split("｜"):
            lines.extend(textwrap.wrap(part, width=width, replace_whitespace=False) or [part])
        return lines[:7]

    @staticmethod
    def _font(size: int) -> ImageFont.FreeTypeFont:
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

    @staticmethod
    def _render_storyboard_fallback(output: Path, scenes: list[dict]) -> None:
        storyboard = output.with_suffix(".storyboard.txt")
        storyboard.write_text("\n\n".join(f"{s['title']}\n{s['body']}\n{s['price']}" for s in scenes), encoding="utf-8")
        output.unlink(missing_ok=True)
