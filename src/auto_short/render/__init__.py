"""Short composition / renderer (CP7, docs/decisions/CP7-render-contract.md)."""

from .stage import RenderError, RenderResult, run_render

__all__ = ["RenderError", "RenderResult", "run_render"]
