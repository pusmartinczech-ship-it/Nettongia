from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

try:
    import pymupdf
except ImportError:  # PyMuPDF before 1.24
    import fitz as pymupdf

TILE_JOB_FORMAT = "openpdf-editor-tile-render"
TILE_JOB_SCHEMA_VERSION = 1
MAX_DESCRIPTOR_BYTES = 1024 * 1024
MAX_TILES_PER_JOB = 64
MAX_TILE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class RenderedTile:
    """One validated RGB page tile positioned in target-scale scene pixels."""

    requested_rect: tuple[int, int, int, int]
    x: int
    y: int
    width: int
    height: int
    stride: int
    samples: bytes


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The tile-render result is too large.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _rect(value: object, name: str) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"Invalid tile-render field: {name}.")
    if any(type(item) is not int for item in value):
        raise ValueError(f"Invalid tile-render field: {name}.")
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= 1_000_000 and 0 <= y0 < y1 <= 1_000_000):
        raise ValueError(f"Invalid tile-render field: {name}.")
    return x0, y0, x1, y1


def prepare_tile_job(
    workspace: str | Path,
    source_path: str | Path,
    page_index: int,
    scale: float,
    tile_rects: Iterable[tuple[int, int, int, int]],
    *,
    edits=(),
    inserted_images=(),
    deleted_images=(),
    inserted_texts=(),
) -> tuple[Path, Path]:
    from .engine import PdfEngine
    from .recovery import RecoverySnapshot, write_recovery_snapshot

    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
    if not source.is_file():
        raise ValueError("The tile-render source does not exist.")
    if type(page_index) is not int or page_index < 0:
        raise ValueError("Invalid tile-render page index.")
    scale = float(scale)
    if not math.isfinite(scale) or not 0.25 <= scale <= 4.0:
        raise ValueError("Invalid tile-render scale.")
    rects = tuple(tuple(rect) for rect in tile_rects)
    edits = tuple(edits)
    inserted_images = tuple(inserted_images)
    deleted_images = tuple(deleted_images)
    inserted_texts = tuple(inserted_texts)
    if not rects or len(rects) > MAX_TILES_PER_JOB:
        raise ValueError("Invalid tile-render rectangle count.")
    for index, rect in enumerate(rects):
        _rect(list(rect), f"tile_rects[{index}]")

    state_path = root / "state.openpdf-recovery"
    result_path = root / "result.json"
    output_dir = root / "tiles"
    output_dir.mkdir()
    write_recovery_snapshot(
        state_path,
        RecoverySnapshot(
            # The recovery codec supplies the project's already hardened
            # mutation/asset schema. The actual source is kept once per open
            # document and referenced separately, so this tiny valid PDF is
            # only a schema carrier and avoids copying a large source per tile.
            pdf_bytes=PdfEngine.blank_document_bytes(36, 36),
            edits=edits,
            inserted_texts=inserted_texts,
            signatures=(),
            inserted_images=inserted_images,
            deleted_images=deleted_images,
            document_path=None,
            save_target_path=None,
            current_page=page_index,
            render_scale=scale,
        ),
    )
    has_mutations = any((edits, inserted_images, deleted_images, inserted_texts))
    payload = {
        "format": TILE_JOB_FORMAT,
        "schema_version": TILE_JOB_SCHEMA_VERSION,
        "source_path": str(source),
        "state_path": str(state_path),
        "result_path": str(result_path),
        "output_dir": str(output_dir),
        "page_index": page_index,
        "scale": scale,
        "has_mutations": has_mutations,
        "tile_rects": [list(rect) for rect in rects],
    }
    _write_json_atomic(root / "job.json", payload)
    return root / "job.json", result_path


def _read_job(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The tile-render job is too large.")
    try:
        job = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The tile-render job is damaged.") from exc
    if not isinstance(job, dict) or job.get("format") != TILE_JOB_FORMAT:
        raise ValueError("The tile-render job format is invalid.")
    if job.get("schema_version") != TILE_JOB_SCHEMA_VERSION:
        raise ValueError("The tile-render job version is not supported.")
    for name in ("source_path", "state_path", "result_path", "output_dir"):
        value = job.get(name)
        if not isinstance(value, str) or not value or len(value) > 32_768:
            raise ValueError(f"Invalid tile-render field: {name}.")
    page_index = job.get("page_index")
    if type(page_index) is not int or page_index < 0:
        raise ValueError("Invalid tile-render page index.")
    scale = job.get("scale")
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise ValueError("Invalid tile-render scale.")
    if not math.isfinite(float(scale)) or not 0.25 <= float(scale) <= 4.0:
        raise ValueError("Invalid tile-render scale.")
    if not isinstance(job.get("has_mutations"), bool):
        raise ValueError("Invalid tile-render field: has_mutations.")
    rects = job.get("tile_rects")
    if not isinstance(rects, list) or not rects or len(rects) > MAX_TILES_PER_JOB:
        raise ValueError("Invalid tile-render rectangle count.")
    job["tile_rects"] = [_rect(value, f"tile_rects[{index}]") for index, value in enumerate(rects)]
    return job


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_tile_job(job_path: str | Path) -> int:
    result_path: Path | None = None
    document = None
    engine = None
    try:
        job = _read_job(job_path)
        result_path = Path(job["result_path"])
        output_dir = Path(job["output_dir"])
        if job["has_mutations"]:
            from .engine import PdfEngine
            from .recovery import read_recovery_snapshot, validate_recovery_assets

            snapshot = read_recovery_snapshot(job["state_path"])
            validate_recovery_assets(snapshot)
            engine = PdfEngine()
            engine.open(job["source_path"])
            document = engine.build_document(
                snapshot.edits,
                (),
                snapshot.inserted_images,
                snapshot.deleted_images,
                snapshot.inserted_texts,
            )
            engine.close()
            engine = None
        else:
            document = pymupdf.open(job["source_path"])
        page_index = job["page_index"]
        if page_index >= document.page_count:
            raise ValueError("The tile-render page index is out of range.")
        page = document[page_index]
        scale = float(job["scale"])
        matrix = pymupdf.Matrix(scale, scale)
        rendered = []
        for index, requested_rect in enumerate(job["tile_rects"]):
            x0, y0, x1, y1 = requested_rect
            clip = pymupdf.Rect(x0 / scale, y0 / scale, x1 / scale, y1 / scale).intersect(page.rect)
            if clip.is_empty:
                continue
            pixmap = page.get_pixmap(matrix=matrix, clip=clip, alpha=False, annots=True)
            samples = bytes(pixmap.samples)
            if len(samples) > MAX_TILE_BYTES:
                raise ValueError("A rendered tile exceeds the safety limit.")
            name = f"tile-{index:03d}.rgb"
            output = output_dir / name
            output.write_bytes(samples)
            rendered.append(
                {
                    "requested_rect": list(requested_rect),
                    "x": pixmap.x,
                    "y": pixmap.y,
                    "width": pixmap.width,
                    "height": pixmap.height,
                    "stride": pixmap.stride,
                    "file": name,
                    "size": len(samples),
                    "sha256": _sha256(samples),
                }
            )
        _write_json_atomic(
            result_path,
            {"format": TILE_JOB_FORMAT, "status": "succeeded", "tiles": rendered},
        )
        return 0
    except Exception as exc:
        if result_path is not None:
            try:
                _write_json_atomic(
                    result_path,
                    {"format": TILE_JOB_FORMAT, "status": "failed", "error": str(exc)},
                )
            except OSError:
                pass
        return 1
    finally:
        if document is not None:
            document.close()
        if engine is not None:
            engine.close()


def read_tile_result(path: str | Path) -> tuple[list[RenderedTile] | None, str | None]:
    result_path = Path(path)
    raw = result_path.read_bytes()
    if len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("The tile-render result is too large.")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The tile-render result is damaged.") from exc
    if not isinstance(result, dict) or result.get("format") != TILE_JOB_FORMAT:
        raise ValueError("The tile-render result is invalid.")
    if result.get("status") == "failed":
        return None, str(result.get("error") or "The tile-render process failed.")
    tiles = result.get("tiles")
    if result.get("status") != "succeeded" or not isinstance(tiles, list) or len(tiles) > MAX_TILES_PER_JOB:
        raise ValueError("The tile-render result is invalid.")
    output_dir = result_path.parent / "tiles"
    rendered: list[RenderedTile] = []
    for index, item in enumerate(tiles):
        if not isinstance(item, dict):
            raise ValueError("The tile-render result is invalid.")
        requested_rect = _rect(item.get("requested_rect"), f"tiles[{index}].requested_rect")
        values = [item.get(name) for name in ("x", "y", "width", "height", "stride", "size")]
        if any(type(value) is not int for value in values):
            raise ValueError("The tile-render result is invalid.")
        x, y, width, height, stride, size = values
        if width < 1 or height < 1 or stride < width * 3 or size != stride * height or size > MAX_TILE_BYTES:
            raise ValueError("The tile-render result is invalid.")
        name = item.get("file")
        digest = item.get("sha256")
        if not isinstance(name, str) or name != f"tile-{index:03d}.rgb":
            raise ValueError("The tile-render result is invalid.")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("The tile-render result is invalid.")
        samples = (output_dir / name).read_bytes()
        if len(samples) != size or _sha256(samples) != digest:
            raise ValueError("The tile-render output failed integrity validation.")
        rendered.append(RenderedTile(requested_rect, x, y, width, height, stride, samples))
    return rendered, None


def main() -> int:
    import sys

    if len(sys.argv) != 2:
        return 2
    return run_tile_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
