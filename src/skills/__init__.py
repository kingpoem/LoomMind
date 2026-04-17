"""Declarative skills (StructuredTool) package."""

from .loader import load_all_skills, validate_skills_config

def list_skill_names() -> list[str]:
    return [str(getattr(t, "name", "(unknown)")) for t in load_all_skills()]


__all__ = ["load_all_skills", "validate_skills_config", "list_skill_names"]

