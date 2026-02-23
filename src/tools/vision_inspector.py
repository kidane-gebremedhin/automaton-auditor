"""VisionInspector: optional image/screenshot analysis."""

from pathlib import Path

from src.state import Evidence


def inspect_images(image_paths: list[Path]) -> list[Evidence]:
    """Analyze images (screenshots, diagrams) for rubric-relevant content.

    TODO: Use vision-capable LLM (e.g. GPT-4V) to describe/analyze images.
    Extract evidence related to UI, architecture diagrams, etc.
    """
    # TODO: If image_paths provided, call vision model, return Evidence
    return []


def extract_images_from_pdf(pdf_path: str | Path) -> list[Path]:
    """Extract embedded images from PDF for vision analysis.

    TODO: Use docling or pdf2image to extract images from PDF.
    Return paths to temp image files.
    """
    # TODO: Extract images, save to temp dir, return paths
    return []
