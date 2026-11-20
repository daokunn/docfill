"""主题系统测试：多套内置主题、样式生成、向后兼容。"""

from ui.style import (
    APP_STYLE,
    DEFAULT_THEME,
    THEME_ORDER,
    THEMES,
    build_style,
    build_tutorial_html,
    current_theme,
    palette,
)


def test_multiple_themes_available():
    assert len(THEMES) >= 4
    assert DEFAULT_THEME in THEMES
    assert set(THEME_ORDER) == set(THEMES)


def test_each_theme_has_full_palette():
    tokens = set(palette(THEME_ORDER[0]))
    assert len(tokens) >= 20
    for theme_id in THEME_ORDER:
        spec = THEMES[theme_id]
        assert spec["label"]
        assert set(palette(theme_id)) == tokens
        assert all(isinstance(v, str) and v.startswith("#") for v in palette(theme_id).values())


def test_build_style_distinct_and_resolved():
    styles = [build_style(t) for t in THEME_ORDER]
    assert len(set(styles)) == len(styles), "每套主题样式必须不同"
    for sheet in styles:
        assert "QPushButton#generate" in sheet
        assert "QLabel#formSection" in sheet
        assert "${" not in sheet, "不能残留未替换的模板变量"


def test_default_style_matches_app_style():
    assert APP_STYLE == build_style(DEFAULT_THEME)


def test_unknown_theme_falls_back():
    assert build_style("__not_a_theme__") == build_style(DEFAULT_THEME)


def test_current_theme_is_valid(monkeypatch):
    import ui.style as style_module

    class FakeSettings:
        def get(self, key, default=None):
            return "dark" if key == "theme" else default

    monkeypatch.setattr(style_module, "get_settings", lambda: FakeSettings())
    assert current_theme() == "dark"
    # 非法值要回退，不能让界面崩掉
    class BadSettings:
        def get(self, key, default=None):
            return "???"
    monkeypatch.setattr(style_module, "get_settings", lambda: BadSettings())
    assert current_theme() == DEFAULT_THEME


def test_tutorial_html_renders_for_each_theme():
    for theme_id in THEME_ORDER:
        html = build_tutorial_html(theme_id)
        assert "第一次用" in html
        assert "看这三步就够了" in html
        assert "黄色格子" in html
        assert "详细查看" in html
        assert "主题" in html
