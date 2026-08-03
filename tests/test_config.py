from cvoice.config import Config, load, save
from cvoice.state import Paths


def test_defaults_are_neutral(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    config = load(paths)

    assert config.language == "en"
    assert config.mode == "notify"
    assert config.engine == "edge"


def test_load_reads_values(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    paths.config_file.write_text(
        'language = "uk"\n'
        'mode = "both"\n'
        'engine = "say"\n'
        "[edge]\n"
        'voice = "uk-UA-PolinaNeural"\n'
        'rate = "+10%"\n'
        "[say]\n"
        'voice = "Lesya"\n'
        "rate = 190\n"
    )

    config = load(paths)

    assert config.language == "uk"
    assert config.mode == "both"
    assert config.engine == "say"
    assert config.edge_voice == "uk-UA-PolinaNeural"
    assert config.edge_rate == "+10%"
    assert config.say_voice == "Lesya"
    assert config.say_rate == 190


def test_save_then_load_roundtrips(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    save(paths, Config(language="uk", mode="voice", say_rate=200))

    config = load(paths)
    assert config.language == "uk"
    assert config.mode == "voice"
    assert config.say_rate == 200


def test_unknown_mode_falls_back_to_off(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    paths.config_file.write_text('mode = "shout"\n')

    assert load(paths).mode == "off"


from cvoice.config import clear_scope, resolve_mode, scope_file, set_scope


def test_global_default_applies_when_no_scope_set(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude", default_mode="notify")

    assert mode == "notify"


def test_alias_scope_overrides_global(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "alias", ".claude-work", "off")

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude-work", default_mode="voice")

    assert mode == "off"


def test_project_scope_overrides_alias(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "alias", ".claude", "off")
    set_scope(paths, "project", "/work/app", "voice")

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude", default_mode="notify")

    assert mode == "voice"


def test_scope_for_another_project_is_ignored(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "project", "/work/other", "voice")

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude", default_mode="off")

    assert mode == "off"


def test_clear_scope_falls_back_to_broader_level(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "project", "/work/app", "voice")
    clear_scope(paths, "project", "/work/app")

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude", default_mode="notify")

    assert mode == "notify"


def test_snoozed_forces_off(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "project", "/work/app", "both")

    mode = resolve_mode(
        paths, project_dir="/work/app", namespace=".claude", default_mode="both", snoozed=True
    )

    assert mode == "off"


def test_scope_file_name_is_filesystem_safe(tmp_path):
    paths = Paths(root=tmp_path)

    path = scope_file(paths, "project", "/Users/me/My Repo")

    assert path.parent == paths.scopes_dir
    assert "/" not in path.name
    assert " " not in path.name
