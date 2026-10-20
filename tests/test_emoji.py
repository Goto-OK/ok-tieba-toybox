from tieba_gui import decode_display, display_text


def test_display_uses_raw_emoji():
    assert display_text("😀") == "😀"
    assert display_text("🙂abc") == "🙂abc"


def test_code_input_decodes_to_raw_emoji():
    assert decode_display("[U+1F600]") == "😀"
    assert decode_display("[u+1f600]") == "😀"
