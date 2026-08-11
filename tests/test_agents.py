from cvoice.agents import CLAUDE, CODEX, label_for


def test_claude_is_labelled_by_project_alone():
    """The label people already hear must not change for Claude."""
    assert label_for(CLAUDE, "billing-api") == "billing-api"


def test_codex_is_named_in_the_label():
    assert label_for(CODEX, "billing-api") == "Codex, billing-api"


def test_a_missing_project_still_names_the_agent():
    assert label_for(CODEX, "") == "Codex"


def test_a_missing_project_for_claude_is_empty():
    assert label_for(CLAUDE, "") == ""


def test_an_unknown_agent_is_treated_as_claude():
    """Old history entries have no agent field; they were all Claude."""
    assert label_for("", "billing-api") == "billing-api"
