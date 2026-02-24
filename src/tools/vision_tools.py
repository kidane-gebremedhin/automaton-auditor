"""VisionInspector tools: extract images from PDF, classify diagrams with multimodal model."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DiagramClassification = Literal["StateGraph diagram", "Linear pipeline", "Generic flowchart"]

DIAGRAM_PROMPT = (
    "Does this diagram show parallel fan-out/fan-in architecture? "
    "Reply with exactly one of: StateGraph diagram, Linear pipeline, Generic flowchart. "
    "StateGraph diagram = LangGraph-style with branching/parallel nodes. "
    "Linear pipeline = single sequential flow. "
    "Generic flowchart = other."
)


class DiagramResult(BaseModel):
    """Classification of a diagram image."""

    image_path: str
    classification: DiagramClassification
    raw_response: str = ""


def extract_images_from_pdf(path: str) -> tuple[list[str], Path | None]:
    """Extract images (figures, tables, pages) from PDF into temp files.

    Uses Docling with generate_picture_images and generate_page_images.
    Caller must call shutil.rmtree(cleanup_path) when done if cleanup_path is not None.

    Args:
        path: Path to PDF file.

    Returns:
        (image_paths, cleanup_path): list of paths to PNGs; cleanup_path is the
        temp dir to remove with shutil.rmtree when done, or None.
    """
    path_obj = Path(path).resolve()
    if not path_obj.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="vision_tools_"))
    image_paths: list[str] = []

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError:
        return image_paths, tmp_dir

    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = 2.0
    pipeline_options.generate_page_images = True
    pipeline_options.generate_picture_images = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(str(path_obj))
    doc_name = path_obj.stem
    doc = result.document

    # Page images
    pages = getattr(doc, "pages", None)
    if pages:
        for page_no, page in pages.items():
            img = getattr(page, "image", None)
            if img is not None and hasattr(img, "pil_image"):
                out = tmp_dir / f"{doc_name}-page-{page_no}.png"
                try:
                    img.pil_image.save(str(out), format="PNG")
                    image_paths.append(str(out))
                except Exception:
                    pass

    # Figures and tables via iterate_items
    PictureItem = TableItem = None
    try:
        from docling.document_core import PictureItem, TableItem
    except ImportError:
        try:
            from docling_core.types.doc import PictureItem, TableItem  # type: ignore
        except ImportError:
            pass

    if PictureItem is not None and TableItem is not None:
        it = getattr(doc, "iterate_items", None)
        if it is not None:
            pic_count = table_count = 0
            iter_gen = it() if callable(it) else (it or [])
            for element, _ in iter_gen:
                if isinstance(element, TableItem):
                    table_count += 1
                    out = tmp_dir / f"{doc_name}-table-{table_count}.png"
                    try:
                        im = element.get_image(doc)
                        if im is not None:
                            im.save(str(out), "PNG")
                            image_paths.append(str(out))
                    except Exception:
                        pass
                if isinstance(element, PictureItem):
                    pic_count += 1
                    out = tmp_dir / f"{doc_name}-picture-{pic_count}.png"
                    try:
                        im = element.get_image(doc)
                        if im is not None:
                            im.save(str(out), "PNG")
                            image_paths.append(str(out))
                    except Exception:
                        pass

    return image_paths, tmp_dir


def classify_diagram_with_vision(
    image_paths: list[str],
    prompt: str = DIAGRAM_PROMPT,
) -> list[DiagramResult]:
    """Send images to multimodal model and return classification per image.

    Uses OpenAI vision (gpt-4o or gpt-4-vision). Execution optional: if
    OPENAI_API_KEY is missing or request fails, returns Generic flowchart.
    """
    results: list[DiagramResult] = []
    valid: DiagramClassification = "Generic flowchart"

    for img_path in image_paths:
        path = Path(img_path)
        if not path.exists():
            results.append(DiagramResult(image_path=img_path, classification=valid, raw_response="file missing"))
            continue

        try:
            import base64

            client = __import__("openai").OpenAI()
            with path.open("rb") as f:
                b64 = base64.standard_b64encode(f.read()).decode("ascii")
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ],
                    }
                ],
                max_tokens=50,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if "StateGraph diagram" in raw:
                classification: DiagramClassification = "StateGraph diagram"
            elif "Linear pipeline" in raw:
                classification = "Linear pipeline"
            else:
                classification = "Generic flowchart"
            results.append(DiagramResult(image_path=img_path, classification=classification, raw_response=raw))
        except Exception:
            results.append(DiagramResult(image_path=img_path, classification=valid, raw_response=""))

    return results
