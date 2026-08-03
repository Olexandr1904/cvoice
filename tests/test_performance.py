import subprocess
import sys
import time

BUDGET_SECONDS = 0.6


def _run_hook(name, payload, env_home):
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "claude_voice.cli", "hook", name],
        input=payload,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(env_home), "CLAUDE_VOICE_HOME": str(env_home)},
    )
    return time.monotonic() - start, result


def test_question_hook_returns_within_budget(tmp_path):
    elapsed, result = _run_hook(
        "question",
        '{"session_id": "s", "tool_name": "Bash", "tool_input": {}}',
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert elapsed < BUDGET_SECONDS, f"hook took {elapsed:.2f}s"


def test_prompt_submit_hook_prints_nothing(tmp_path):
    _, result = _run_hook("prompt-submit", '{"session_id": "s"}', tmp_path)

    assert result.stdout == ""


def test_heavy_modules_are_not_imported_by_hooks():
    """edge-tts pulls in aiohttp; importing it on every hook would blow the budget."""
    code = (
        "import sys; import claude_voice.cli as cli; "
        "assert 'edge_tts' not in sys.modules, sorted(m for m in sys.modules if 'edge' in m)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
