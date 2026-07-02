import shutil
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

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
                "body": "真实可买软装清单，一键生成视频与采购表",
                "price": "真实商品溯源",
                "duration": 4,
            },
            {
                "title": "整体方案",
                "body": plan.concept_summary,
                "price": request.video_focus.value,
                "duration": 8,
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
                    "duration": item_duration,
                }
            )
        scenes.append(
            {
                "title": "预算汇总",
                "body": f"低配 {budget.low_plan.total_price:.0f} 元｜高配 {budget.high_plan.total_price:.0f} 元",
                "price": "价格以淘宝实时页面为准",
                "duration": 8,
            }
        )
        scenes.append(
            {
                "title": "合规声明",
                "body": "AI 设计方案仅供参考。商品来源淘宝官方在售商品。本内容由 AI 自动生成。",
                "price": "可导出采购 Excel",
                "duration": 5,
            }
        )
        return scenes

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
                    "-vsync",
                    "vfr",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    "24",
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
        draw.rounded_rectangle([72, 170, width - 72, 430], radius=24, fill="#FFFFFF")
        self._multiline(draw, scene["title"], 112, 215, title_font, ink, 11, 88)
        self._multiline(draw, scene["body"], 92, 560, body_font, ink, 17, 62)
        draw.rounded_rectangle([92, 1210, width - 92, 1360], radius=18, fill=accent)
        self._multiline(draw, scene["price"], 132, 1248, price_font, "#FFFFFF", 13, 72)
        draw.text((92, height - 170), "商品来源・淘宝｜AI 自动生成｜价格以官网为准", font=small_font, fill=ink)
        draw.text((92, height - 115), "AI 设计方案仅供参考", font=small_font, fill=ink)
        return image

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
