from tieba_reply_stats.theme import DARK, LIGHT, map_color, resolve_palette


def test_palettes_and_accent():
    light = resolve_palette("light", "green")
    dark = resolve_palette("dark", "purple")
    assert light["window_bg"] == LIGHT["window_bg"]
    assert dark["window_bg"] == DARK["window_bg"]
    assert light["accent"] != dark["accent"]


def test_system_falls_back_to_light(monkeypatch):
    monkeypatch.setattr("tieba_reply_stats.theme.detect_system_theme", lambda: "light")
    assert resolve_palette("system", "blue")["window_bg"] == LIGHT["window_bg"]


def test_color_mapping_context():
    palette = resolve_palette("dark", "blue")
    assert map_color("bg", "#ffffff", palette) == palette["surface"]
    assert map_color("fg", "#ffffff", palette) == palette["accent_text"]
    assert map_color("fg", "#1F4E79", palette) == palette["accent"]
    assert map_color("bg", "#ffdede", palette) == palette["danger_bg"]
