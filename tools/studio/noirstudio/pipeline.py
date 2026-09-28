"""Orchestration: spec -> voice -> captions -> visuals -> assembly -> metadata.

Every run writes a `report.json` with provenance: which engine produced each
scene (offline stub vs. live API), durations, the spec digest and versions, so
a rendered video can always be traced back to exactly what was approved.
"""

from __future__ import annotations

import json
import platform
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from . import __version__, assemble, ffmpeg, videogen, visuals, voice as voice_mod
from .brandkit import BrandKit, get_brand
from .captions import Word, to_ass, to_srt
from .publish import build_metadata, write_metadata
from .spec import Scene, VideoSpec, load_spec, resolve_asset

Log = Callable[[str], None]


@dataclass
class SceneRecord:
    id: str
    kind: str
    visual_source: str
    voice_source: str
    start: float
    duration: float
    words: int
    fallback: Optional[str] = None


@dataclass
class RenderResult:
    video: Path
    thumbnail: Path
    captions_ass: Path
    captions_srt: Path
    metadata_json: Path
    metadata_md: Path
    report: Path
    duration: float
    live: bool
    scenes: List[SceneRecord] = field(default_factory=list)


def _log_default(msg: str) -> None:
    print(msg, flush=True)


def render(
    spec: VideoSpec | Path | str,
    out_dir: Path | str,
    *,
    live: bool = False,
    generate_video: bool = False,
    keep_work: bool = True,
    log: Log = _log_default,
) -> RenderResult:
    if not isinstance(spec, VideoSpec):
        spec = load_spec(spec)
    brand: BrandKit = get_brand(spec.brand, spec.brand_overrides)
    out = Path(out_dir)
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    voice_engine = voice_mod.get_engine(live)
    video_engine = videogen.get_engine(live and generate_video)
    badge = None if live else "PREVIEW · NO VOICE"
    log(f"[noirstudio] {spec.id}: {len(spec.scenes)} scenes, brand={brand.name}, "
        f"voice={voice_engine.provider}, video={video_engine.provider}")

    avatar_img = resolve_asset(spec, spec.avatar_image) if spec.avatar_image else None

    clips: List[Path] = []
    all_words: List[Word] = []
    records: List[SceneRecord] = []
    scene_starts: List[Tuple[str, float]] = []
    cursor = 0.0

    for idx, scene in enumerate(spec.scenes, start=1):
        base = work / f"{idx:02d}_{scene.id}"
        # 1) voice
        wav = base.with_suffix(".wav")
        if scene.text.strip():
            vr = voice_engine.synthesize(scene.text, spec.voice, wav)
            duration = scene.duration or vr.duration
            words = [w.shifted(cursor) for w in vr.words if w.start < duration]
            voice_source = vr.provider
        else:
            duration = float(scene.duration or 2.0)
            ffmpeg.run(["-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{duration:.3f}",
                        "-c:a", "pcm_s16le", str(wav)])
            words, voice_source = [], "silence"
        if scene.duration and scene.duration > duration:
            duration = scene.duration
        # 2) visual
        visual_source, fallback = _render_visual(scene, spec, brand, avatar_img, video_engine, wav, base, badge, log)
        clip = base.with_suffix(".mp4")
        if visual_source.endswith(".mp4"):
            assemble.clip_from_video(Path(visual_source), wav, duration, spec.output, clip)
        else:
            assemble.clip_from_image(Path(visual_source), wav, duration, spec.output, clip, motion=scene.motion)
        clips.append(clip)
        all_words.extend(words)
        label = scene.title or (scene.text.strip()[:48] + ("…" if len(scene.text.strip()) > 48 else ""))
        scene_starts.append((label or scene.id, cursor))
        records.append(SceneRecord(scene.id, scene.kind, Path(visual_source).name, voice_source, cursor,
                                   duration, len(words), fallback))
        log(f"  scene {idx:02d} {scene.id:<10} {scene.kind:<7} {duration:6.2f}s  {len(words):3d} words"
            + (f"  (fallback: {fallback})" if fallback else ""))
        cursor += duration

    # 3) concat + captions + music
    joined = work / "joined.mp4"
    assemble.concat(clips, joined)
    ass_path = out / f"{spec.id}.ass"
    srt_path = out / f"{spec.id}.srt"
    ass_path.write_text(to_ass(all_words, brand, spec.output, spec.captions), encoding="utf-8")
    srt_path.write_text(to_srt(all_words, spec.captions.words_per_line, spec.captions.uppercase), encoding="utf-8")

    final_name = spec.output.filename or f"{spec.id}.mp4"
    final = out / final_name
    staged = work / "captioned.mp4"
    if spec.captions.enabled and spec.captions.mode != "none" and all_words:
        # Give libass only the caption font so family-name collisions between
        # weights can't pick a lighter cut.
        fonts_dir = work / "fonts"
        fonts_dir.mkdir(exist_ok=True)
        shutil.copyfile(brand.caption_font, fonts_dir / brand.caption_font.name)
        assemble.burn_captions(joined, ass_path, fonts_dir, staged)
    else:
        assemble.finalize_copy(joined, staged)
    if spec.music:
        assemble.mix_music(staged, resolve_asset(spec, spec.music), spec.music_gain_db, final)
    else:
        shutil.copyfile(staged, final)

    # 4) thumbnail + metadata + report
    total = ffmpeg.probe_duration(final)
    thumb = out / f"{spec.id}-thumbnail.png"
    visuals.render_thumbnail(spec, brand, thumb)
    meta = build_metadata(spec, brand, total, scene_starts)
    meta_json, meta_md = out / f"{spec.id}.metadata.json", out / f"{spec.id}.metadata.md"
    write_metadata(meta, meta_json, meta_md)

    report = out / f"{spec.id}.report.json"
    report.write_text(json.dumps({
        "noirstudio": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "spec_id": spec.id,
        "spec_digest": spec.digest(),
        "spec_path": spec.source_path,
        "brand": brand.name,
        "live": live,
        "generate_video": generate_video,
        "voice_engine": voice_engine.provider,
        "video_engine": video_engine.provider,
        "duration_seconds": round(total, 3),
        "words": len(all_words),
        "scenes": [r.__dict__ for r in records],
        "outputs": {k: str(v) for k, v in {
            "video": final, "thumbnail": thumb, "captions_ass": ass_path, "captions_srt": srt_path,
            "metadata_json": meta_json, "metadata_md": meta_md}.items()},
        "render_seconds": round(time.time() - t0, 2),
        "host": {"python": platform.python_version(), "ffmpeg": ffmpeg.ffmpeg_path()},
    }, indent=2), encoding="utf-8")

    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    log(f"[noirstudio] done: {final} ({total:.1f}s, {len(all_words)} caption words, "
        f"{time.time() - t0:.1f}s render)")
    return RenderResult(final, thumb, ass_path, srt_path, meta_json, meta_md, report, total, live, records)


def _render_visual(scene: Scene, spec: VideoSpec, brand: BrandKit, avatar_img: Optional[Path],
                   video_engine, wav: Path, base: Path, badge: Optional[str], log: Log) -> Tuple[str, Optional[str]]:
    """Return (path to png/mp4, fallback reason or None)."""
    png = base.with_suffix(".png")
    if scene.kind in ("image", "video") and scene.media:
        media = resolve_asset(spec, scene.media)
        if scene.kind == "video":
            return str(media), None
        return str(visuals.render_image_scene(media, spec.output, png)), None

    if scene.kind == "avatar":
        if avatar_img is None:
            reason = "no avatar_image in spec"
        else:
            try:
                got = video_engine.avatar(avatar_img, wav, base.with_name(base.name + "_avatar.mp4"))
                if got:
                    return str(got), None
                reason = "video engine offline"
            except Exception as exc:  # keep rendering; record the failure
                reason = f"avatar generation failed: {exc}"
        log(f"  ! {scene.id}: {reason}; using card")
        return str(visuals.render_card(scene, brand, spec.output, png, badge)), reason

    if scene.kind == "broll":
        try:
            got = video_engine.broll(scene.prompt or "", base.with_name(base.name + "_broll.mp4"),
                                     duration=int(round(scene.duration or 8)))
            if got:
                return str(got), None
            reason = "video engine offline"
        except Exception as exc:
            reason = f"b-roll generation failed: {exc}"
        log(f"  ! {scene.id}: {reason}; using card")
        return str(visuals.render_card(scene, brand, spec.output, png, badge)), reason

    return str(visuals.render_card(scene, brand, spec.output, png, badge)), None
