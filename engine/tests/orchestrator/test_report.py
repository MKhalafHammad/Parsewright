from parsewright.orchestrator.report import highlights


def test_highlights_are_offsets_into_the_raw_line():
    raw = 'user=alice src=192.0.2.1 msg="<script>alert(1)</script>"'
    spans = highlights(
        raw, {"user": "alice", "src": "192.0.2.1", "msg": "<script>alert(1)</script>"}
    )
    assert [raw[s["start"] : s["end"]] for s in spans] == [
        "alice",
        "192.0.2.1",
        "<script>alert(1)</script>",
    ]
    assert [s["field"] for s in spans] == ["user", "src", "msg"]


def test_highlights_never_overlap_and_skip_missing_values():
    spans = highlights("aaa bbb", {"x": "aaa bbb", "y": "aaa", "z": "missing"})
    assert spans == [{"start": 0, "end": 7, "field": "x"}]


def test_highlight_offsets_are_utf16_for_the_browser():
    raw = "😀 user=alice"  # one emoji: 1 code point, 2 UTF-16 units
    (span,) = highlights(raw, {"user": "alice"})
    assert (span["start"], span["end"]) == (8, 13)  # 2 (emoji) + 1 (space) + 5 ("user=")
    assert (
        raw.encode("utf-16-le")[span["start"] * 2 : span["end"] * 2].decode("utf-16-le") == "alice"
    )
