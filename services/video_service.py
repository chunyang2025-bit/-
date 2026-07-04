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
from app.models import BudgetResponse, DesignPlan, GenerateRequest, GeneratedVideo, ProductMatch, RenderedAsset
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
        render: Optional[RenderedAsset] = None,
    ) -> GeneratedVideo:
        filename = f"home_design_video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        output = self.settings.videos_dir / filename
        scenes = self._build_scenes(request, plan, matches, budget, render)
        self._attach_product_images(scenes, output.stem)
        narration = "。".join(scene["title"] + "，" + scene["body"] for scene in scenes)
        audio_path = await self.tts.synthesize(narration[:3600], filename.replace(".mp4", ".mp3"))
        render_clip = Path(render.render_video_path) if render and render.render_video_path else None
        self._render_movie(output, scenes, audio_path, render_clip)
        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError(f"视频生成失败，未生成有效 MP4：{output}")
        return GeneratedVideo(
            video_url=self.settings.public_url(f"/videos/{filename}"),
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
        render: Optional[RenderedAsset] = None,
    ) -> list[dict]:
        render_path = render.render_path if render else None
        render_clips = render.render_clips if render else []
        clip_map = {clip.title: clip.video_path for clip in render_clips}
        overall_clip = clip_map.get("overall") or next((clip.video_path for clip in render_clips if clip.kind == "overall"), None)
        scenes = [
            {
                "title": f"{request.area_sqm:g}㎡{request.decor_style.value}低成本改造",
                "body": plan.concept_summary,
                "price": "AI 家装动态方案 + 单品视频清单",
                "duration": 5,
                "kind": "cover",
                "render_path": render_path,
                "clip_path": overall_clip,
            },
        ]
        per_item = matches[: self.settings.render_product_clip_count]
        for match in per_item:
            product = match.products[0] if match.products else None
            template_key = self._template_key_for_item(match.design_item.name)
            scenes.append(
                {
                    "title": match.design_item.name,
                    "body": f"{match.design_item.material}｜{match.design_item.size}｜{match.design_item.scene}｜{match.design_item.role}",
                    "material": match.design_item.material,
                    "size": match.design_item.size,
                    "scene": match.design_item.scene,
                    "role": match.design_item.role,
                    "price": f"券后约 {product.final_price:.0f} 元" if product else "待匹配",
                    "shop": product.shop_name if product else "待匹配",
                    "sales": product.sales if product else 0,
                    "source": product.source if product else "无商品来源",
                    "is_realtime": bool(product and product.is_realtime),
                    "image_url": product.image_url if product else None,
                    "product_title": product.title if product and product.is_realtime else "",
                    "duration": 5,
                    "kind": "product",
                    "template_key": template_key,
                    "clip_path": clip_map.get(template_key) or clip_map.get(match.design_item.name),
                }
            )
        scenes.append(
            {
                "title": "预算汇总",
                "body": f"低配 {budget.low_plan.total_price:.0f} 元｜高配 {budget.high_plan.total_price:.0f} 元",
                "price": "价格以淘宝实时页面为准",
                "duration": 5,
                "kind": "budget",
            }
        )
        return scenes

    @staticmethod
    def _template_key_for_item(item_name: str) -> str:
        if any(word in item_name for word in ["沙发", "椅", "床", "凳"]):
            return "seating"
        if any(word in item_name for word in ["茶几", "桌", "柜", "架", "收纳"]):
            return "table_storage"
        if "灯" in item_name:
            return "lighting"
        if any(word in item_name for word in ["窗帘", "地毯", "抱枕", "床品", "毯"]):
            return "textile"
        return "decor"

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

    def _render_movie(self, output: Path, scenes: list[dict], audio_path: Optional[Path], render_clip: Optional[Path] = None) -> None:
        try:
            self._render_with_ffmpeg(output, scenes, audio_path, render_clip)
        except Exception as exc:
            self._render_storyboard_fallback(output, scenes)
            raise RuntimeError(
                "FFmpeg 无法生成 MP4，"
                f"已输出分镜文本：{output.with_suffix('.storyboard.txt')}，"
                f"错误日志：{output.with_suffix('.ffmpeg.log')}"
            ) from exc

    def _render_with_ffmpeg(self, output: Path, scenes: list[dict], audio_path: Optional[Path], render_clip: Optional[Path] = None) -> None:
        work_dir = self.settings.tmp_dir / output.stem
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            if any(scene.get("clip_path") and Path(scene["clip_path"]).exists() for scene in scenes):
                self._render_scene_clip_sequence(output, scenes, audio_path, work_dir)
                return

            if render_clip and render_clip.exists():
                try:
                    self._render_with_visual_background(output, scenes, audio_path, render_clip, work_dir)
                    return
                except Exception:
                    pass

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

            silent_slides = work_dir / "slides_silent.mp4"
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
                    str(silent_slides),
                ],
                output.with_suffix(".ffmpeg.log"),
            )

            silent_output = silent_slides
            if render_clip and render_clip.exists():
                merged_silent = work_dir / "merged_silent.mp4"
                self._prepend_video_clip(render_clip, silent_slides, merged_silent, output.with_suffix(".ffmpeg.log"))
                silent_output = merged_silent

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
            else:
                shutil.copyfile(silent_output, output)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _render_scene_clip_sequence(
        self,
        output: Path,
        scenes: list[dict],
        audio_path: Optional[Path],
        work_dir: Path,
    ) -> None:
        segment_paths: list[Path] = []
        width, height = self.settings.video_width, self.settings.video_height
        for index, scene in enumerate(scenes):
            duration = str(scene["duration"])
            segment_path = work_dir / f"segment_{index:02d}.mp4"
            clip_path = Path(scene["clip_path"]) if scene.get("clip_path") else None
            if clip_path and clip_path.exists():
                overlay_path = work_dir / f"overlay_{index:02d}.png"
                self._draw_overlay_scene(scene, index).save(overlay_path)
                filter_complex = (
                    f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},setsar=1,fps=24,trim=duration={duration},setpts=PTS-STARTPTS[bg];"
                    "[1:v]format=rgba,setpts=PTS-STARTPTS[ov];"
                    "[bg][ov]overlay=0:0:format=auto[v]"
                )
                self._run_ffmpeg(
                    [
                        "ffmpeg",
                        "-y",
                        "-stream_loop",
                        "-1",
                        "-i",
                        str(clip_path),
                        "-i",
                        str(overlay_path),
                        "-filter_complex",
                        filter_complex,
                        "-map",
                        "[v]",
                        "-t",
                        duration,
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        str(segment_path),
                    ],
                    output.with_suffix(".ffmpeg.log"),
                )
            else:
                frame_path = work_dir / f"scene_{index:02d}.png"
                self._draw_scene(scene, index).save(frame_path)
                self._run_ffmpeg(
                    [
                        "ffmpeg",
                        "-y",
                        "-loop",
                        "1",
                        "-t",
                        duration,
                        "-i",
                        str(frame_path),
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-r",
                        "24",
                        str(segment_path),
                    ],
                    output.with_suffix(".ffmpeg.log"),
                )
            segment_paths.append(segment_path)

        concat_file = work_dir / "segments.txt"
        concat_file.write_text("\n".join(f"file '{path}'" for path in segment_paths), encoding="utf-8")
        silent_output = work_dir / "scene_sequence_silent.mp4"
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
                "-c",
                "copy",
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
        else:
            shutil.copyfile(silent_output, output)

    def _render_with_visual_background(
        self,
        output: Path,
        scenes: list[dict],
        audio_path: Optional[Path],
        render_clip: Path,
        work_dir: Path,
    ) -> None:
        overlay_concat = work_dir / "overlay_concat.txt"
        overlay_paths = []
        for index, scene in enumerate(scenes):
            frame_path = work_dir / f"overlay_{index:02d}.png"
            self._draw_overlay_scene(scene, index).save(frame_path)
            overlay_paths.append(frame_path)

        lines = []
        for frame_path, scene in zip(overlay_paths, scenes):
            lines.append(f"file '{frame_path}'")
            lines.append(f"duration {scene['duration']}")
        lines.append(f"file '{overlay_paths[-1]}'")
        overlay_concat.write_text("\n".join(lines), encoding="utf-8")

        total_duration = round(sum(scene["duration"] for scene in scenes), 2)
        visual_silent = work_dir / "visual_silent.mp4"
        width, height = self.settings.video_width, self.settings.video_height
        filter_complex = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps=24,trim=duration={total_duration},setpts=PTS-STARTPTS[bg];"
            "[1:v]fps=24,format=rgba,setpts=PTS-STARTPTS[ov];"
            "[bg][ov]overlay=0:0:format=auto[v]"
        )
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(render_clip),
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(overlay_concat),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-t",
                str(total_duration),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(visual_silent),
            ],
            output.with_suffix(".ffmpeg.log"),
        )

        if audio_path and audio_path.exists():
            self._run_ffmpeg(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(visual_silent),
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
        else:
            shutil.copyfile(visual_silent, output)

    def _prepend_video_clip(self, render_clip: Path, slideshow: Path, output: Path, log_path: Path) -> None:
        width, height = self.settings.video_width, self.settings.video_height
        duration = str(min(max(self.settings.render_duration, 3), 15))
        filter_complex = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps=24[v0];"
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps=24[v1];"
            "[v0][v1]concat=n=2:v=1:a=0[v]"
        )
        self._run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-t",
                duration,
                "-i",
                str(render_clip),
                "-i",
                str(slideshow),
                "-filter_complex",
                filter_complex,
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(output),
            ],
            log_path,
        )

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
            render_path = scene.get("render_path")
            if render_path and Path(render_path).exists():
                render_image = Image.open(render_path).convert("RGB")
                render_image = self._fit_cover(render_image, (width, height))
                image.paste(render_image, (0, 0))
                overlay = Image.new("RGBA", (width, height), (0, 0, 0, 80))
                image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"), (0, 0))
                draw = ImageDraw.Draw(image)
            draw.rounded_rectangle([72, 150, width - 72, 455], radius=24, fill="#FFFFFF")
            self._multiline(draw, scene["title"], 112, 215, title_font, ink, 11, 88)
            self._multiline(draw, scene["body"], 92, 550, body_font, "#FFFFFF" if render_path else ink, 17, 62)
            draw.rounded_rectangle([92, 1210, width - 92, 1360], radius=18, fill=accent)
            self._multiline(draw, scene["price"], 132, 1248, price_font, "#FFFFFF", 13, 72)
        draw.text((92, height - 170), "商品来源・淘宝｜AI 自动生成｜价格以官网为准", font=small_font, fill=ink)
        draw.text((92, height - 115), "AI 设计方案仅供参考", font=small_font, fill=ink)
        return image

    def _draw_overlay_scene(self, scene: dict, index: int) -> Image.Image:
        width, height = self.settings.video_width, self.settings.video_height
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        title_font = self._font(66)
        body_font = self._font(38)
        price_font = self._font(58)
        small_font = self._font(26)
        accent = ["#D9633D", "#2F7A68", "#8060A8"][index % 3]

        if scene.get("kind") == "product":
            self._draw_product_overlay(image, draw, scene, title_font, body_font, price_font, small_font, accent)
        else:
            draw.rectangle([0, 0, width, 330], fill=(0, 0, 0, 96))
            draw.rounded_rectangle([56, 82, width - 56, 292], radius=24, fill=(255, 255, 255, 224))
            self._multiline(draw, scene["title"], 96, 118, title_font, "#17211C", 12, 78)
            draw.rectangle([0, height - 360, width, height], fill=(0, 0, 0, 120))
            draw.rounded_rectangle([72, height - 308, width - 72, height - 152], radius=22, fill=(255, 255, 255, 218))
            self._multiline(draw, scene["body"], 110, height - 276, body_font, "#17211C", 20, 52)
            draw.rounded_rectangle([92, height - 132, width - 92, height - 62], radius=16, fill=accent)
            self._multiline(draw, scene["price"], 128, height - 120, small_font, "#FFFFFF", 28, 36)

        draw.text((76, height - 34), "AI效果仅供参考｜价格以商品页面为准", font=small_font, fill="#FFFFFF")
        return image

    def _draw_product_overlay(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        scene: dict,
        title_font: ImageFont.FreeTypeFont,
        body_font: ImageFont.FreeTypeFont,
        price_font: ImageFont.FreeTypeFont,
        small_font: ImageFont.FreeTypeFont,
        accent: str,
    ) -> None:
        width, height = self.settings.video_width, self.settings.video_height
        image_path = scene.get("image_path")
        if image_path:
            product_image = Image.open(image_path).convert("RGBA")
            product_image = self._fit_cover(product_image.convert("RGB"), (430, 430)).convert("RGBA")
            frame = Image.new("RGBA", (470, 470), (255, 255, 255, 226))
            frame.paste(product_image, (20, 20))
            image.alpha_composite(frame, (72, 320))
        else:
            draw.rounded_rectangle([72, 320, 642, 400], radius=18, fill=(255, 255, 255, 218))
            draw.text((108, 342), "待替换淘宝官方商品图", font=small_font, fill="#17211C")

        draw.rectangle([0, height - 560, width, height], fill=(0, 0, 0, 124))
        draw.rounded_rectangle([56, height - 520, width - 56, height - 122], radius=28, fill=(255, 255, 255, 232))
        self._multiline(draw, scene["title"], 96, height - 486, title_font, "#17211C", 13, 76)

        material_line = f"材质：{scene.get('material', '')}    尺寸：{scene.get('size', '')}"
        self._multiline(draw, material_line, 96, height - 372, body_font, "#17211C", 22, 50)

        role_line = f"搭配作用：{scene.get('role', '')}"
        self._multiline(draw, role_line, 96, height - 302, body_font, "#17211C", 20, 50)

        product_title = scene.get("product_title") or ""
        if product_title:
            self._multiline(draw, product_title, 96, height - 236, small_font, "#4D4B45", 31, 34)

        draw.rounded_rectangle([96, height - 184, width - 96, height - 108], radius=18, fill=accent)
        self._multiline(draw, scene["price"], 128, height - 170, price_font, "#FFFFFF", 13, 62)

        if scene.get("is_realtime"):
            meta = f"{scene.get('shop', '')}｜销量 {scene.get('sales', 0)}｜{scene.get('source', '')}"
        else:
            meta = "淘宝客物料权限通过后自动替换真实商品图和链接"
        self._multiline(draw, meta, 96, height - 78, small_font, "#FFFFFF", 30, 32)

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

    @staticmethod
    def _render_storyboard_fallback(output: Path, scenes: list[dict]) -> None:
        storyboard = output.with_suffix(".storyboard.txt")
        storyboard.write_text("\n\n".join(f"{s['title']}\n{s['body']}\n{s['price']}" for s in scenes), encoding="utf-8")
        output.unlink(missing_ok=True)
