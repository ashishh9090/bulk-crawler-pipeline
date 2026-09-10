"""Python bridge connecting the crawler pipeline with Phase III TypeScript Extraction Engine."""

import json
import os
import subprocess
from typing import Any, Dict, Optional


class LLMExtractionBridge:
    """Executes the Phase III Multi-Tier LLM Extraction Engine via CLI or subprocess."""

    def __init__(self, engine_dir: Optional[str] = None):
        if engine_dir is None:
            # Resolve relative to crawler directory
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.engine_dir = os.path.join(base_dir, "extraction_engine")
        else:
            self.engine_dir = engine_dir

    def extract(
        self,
        content: str,
        schema: str = "startup",
        source_url: Optional[str] = None,
        include_meta: bool = False,
    ) -> Dict[str, Any]:
        """Runs the extraction engine on content and returns canonical JSON dict."""
        cmd = ["node", "bin/extract.js", "--stdin", "--schema", schema]
        if source_url:
            cmd.extend(["--url", source_url])
        if include_meta:
            cmd.append("--meta")

        proc = subprocess.run(
            cmd,
            cwd=self.engine_dir,
            input=content,
            text=True,
            capture_output=True,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"LLM Extraction Engine failed (exit {proc.returncode}):\n{proc.stderr}"
            )

        return json.loads(proc.stdout)
