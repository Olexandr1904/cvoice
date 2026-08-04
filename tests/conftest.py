import json

import pytest


@pytest.fixture
def transcript(tmp_path):
    """Writes a Claude Code transcript and returns its path.

    By default it represents a turn that actually did something: the stop hook ignores
    turns with no tool use and little to say, because those are greetings.
    """

    def build(*texts, sidechain=False, used_tools=True):
        path = tmp_path / "transcript.jsonl"
        lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})]
        if used_tools:
            lines.append(
                json.dumps(
                    {
                        "type": "assistant",
                        "isSidechain": False,
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "tool_use", "name": "Bash", "input": {}}],
                        },
                    }
                )
            )
            lines.append(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
                    }
                )
            )
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
