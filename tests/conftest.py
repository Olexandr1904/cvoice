import json

import pytest


@pytest.fixture
def transcript(tmp_path):
    """Writes a Claude Code transcript and returns its path."""

    def build(*texts, sidechain=False):
        path = tmp_path / "transcript.jsonl"
        lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})]
        for text in texts:
            lines.append(
                json.dumps(
                    {
                        "type": "assistant",
                        "isSidechain": sidechain,
                        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
                    }
                )
            )
        path.write_text("\n".join(lines) + "\n")
        return path

    return build
