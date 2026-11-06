"""
Prompt loader for ORCAS versioned prompt YAML artifacts.

Changes vs previous version (M11)
-----------------------------------
* ``render`` now performs a single-pass substitution using a regex so that
  values containing ``{placeholder}`` patterns cannot introduce new
  substitutions.  This prevents prompt-injection via complaint text that
  happens to contain ``{evidence_ledger}`` or similar.
* The substitution order is determined by the template, not the loop, so
  there is no way for one value to inject into another slot.
"""

import os
import re
from typing import Any, Dict, Optional

import yaml


class PromptLoader:
    """Loads and formats versioned prompt YAML artifacts from the prompts/ directory."""

    def __init__(self, prompts_root: Optional[str] = None):
        if not prompts_root:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.prompts_root = base_dir
        else:
            self.prompts_root = prompts_root
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_prompt(self, name: str, version: str = "v1") -> Dict[str, Any]:
        key = f"{name}:{version}"
        if key in self._cache:
            return self._cache[key]

        file_path = os.path.join(self.prompts_root, name, f"{version}.yaml")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Prompt artifact not found at: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            self._cache[key] = data
            return data

    def render(self, name: str, version: str = "v1", **kwargs) -> str:
        """
        Load template and perform a single-pass substitution of ``{key}``
        placeholders.

        A single pass means that none of the substituted values can themselves
        trigger further placeholder expansion, even if they contain text like
        ``{evidence_ledger}``.  This prevents prompt-injection via complaint
        text (M11).
        """
        prompt_data = self.get_prompt(name, version)
        template: str = prompt_data.get("template", "")

        # Build a mapping of placeholder → replacement value (as strings)
        replacements = {k: str(v) for k, v in kwargs.items()}

        # Single regex pass: replace each {key} occurrence exactly once.
        # Any {text} not in ``replacements`` is left unchanged.
        def _replace(match: re.Match) -> str:
            key = match.group(1)
            return replacements.get(key, match.group(0))

        result = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", _replace, template)
        return result


prompt_loader = PromptLoader()
