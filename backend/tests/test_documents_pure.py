"""rain.modules.documents.service -- the pure helpers behind tag parsing,
change-detection, diff summaries, and webhook-refresh JSON extraction.
No DB: these are plain str/list -> str/list/bool transforms, unlike the
rest of the module (create_document, refresh_from_webhook, etc.), which
needs a real session and is covered instead by the document integration
tests in test_integration.py."""
from __future__ import annotations

from rain.modules.documents.service import (
    _MAX_TAGS,
    _content_changed,
    _diff_summary,
    _extract_json_text,
    parse_tags,
)


# -- parse_tags --------------------------------------------------------

def test_parse_tags_trims_and_splits():
    assert parse_tags(" security , oncall ,compliance") == ["security", "oncall", "compliance"]


def test_parse_tags_drops_empty_pieces():
    assert parse_tags("security,,  ,oncall") == ["security", "oncall"]


def test_parse_tags_dedupes_case_insensitively_keeping_first_spelling():
    assert parse_tags("Security, security, SECURITY") == ["Security"]


def test_parse_tags_empty_string_gives_empty_list():
    assert parse_tags("") == []
    assert parse_tags("   ") == []


def test_parse_tags_caps_at_max_tags():
    raw = ",".join(f"tag{i}" for i in range(_MAX_TAGS + 10))
    tags = parse_tags(raw)
    assert len(tags) == _MAX_TAGS
    assert tags[0] == "tag0"


def test_parse_tags_caps_tag_length():
    long_tag = "x" * 200
    tags = parse_tags(long_tag)
    assert len(tags[0]) == 50


# -- _content_changed ----------------------------------------------------

def test_content_changed_true_when_old_is_none():
    assert _content_changed(None, "anything") is True


def test_content_changed_false_for_identical_text():
    assert _content_changed("line one\nline two", "line one\nline two") is False


def test_content_changed_ignores_trailing_newline_only_difference():
    """The exact regression this function's docstring documents: a stored
    file's trailing newline shouldn't make a re-save look like an edit."""
    assert _content_changed("line one\nline two\n", "line one\nline two") is False
    assert _content_changed("line one\nline two", "line one\nline two\n") is False


def test_content_changed_true_for_a_real_trailing_blank_line():
    assert _content_changed("line one\nline two", "line one\nline two\n\n") is True


def test_content_changed_true_for_different_content():
    assert _content_changed("old text", "new text") is True


# -- _diff_summary -------------------------------------------------------

def test_diff_summary_no_difference():
    assert _diff_summary("same", "same") == "(no textual difference)"


def test_diff_summary_none_old_text_treated_as_empty():
    summary = _diff_summary(None, "new line")
    assert "+new line" in summary


def test_diff_summary_shows_added_and_removed_lines():
    summary = _diff_summary("keep\nremove me", "keep\nadd me")
    assert "-remove me" in summary
    assert "+add me" in summary


def test_diff_summary_truncates_long_diffs():
    old_text = "\n".join(f"line{i}" for i in range(100))
    new_text = "\n".join(f"changed{i}" for i in range(100))
    summary = _diff_summary(old_text, new_text)
    assert "more diff line" in summary


# -- _extract_json_text ---------------------------------------------------

def test_extract_json_text_invalid_json_falls_back_to_raw():
    text, note = _extract_json_text("not json at all", None)
    assert text == "not json at all"
    assert note is not None and "valid JSON" in note


def test_extract_json_text_no_path_pretty_prints_whole_object():
    text, note = _extract_json_text('{"a": 1, "b": 2}', None)
    assert note is None
    assert text == '{\n  "a": 1,\n  "b": 2\n}'


def test_extract_json_text_with_matching_path_extracts_string_value():
    text, note = _extract_json_text('{"status": {"message": "all clear"}}', "$.status.message")
    assert note is None
    assert text == "all clear"


def test_extract_json_text_with_matching_path_pretty_prints_non_string_value():
    text, note = _extract_json_text('{"counts": {"open": 3, "closed": 5}}', "$.counts")
    assert note is None
    assert text == '{\n  "open": 3,\n  "closed": 5\n}'


def test_extract_json_text_path_matching_nothing_falls_back_to_whole_object():
    text, note = _extract_json_text('{"a": 1}', "$.nonexistent")
    assert note is not None and "matched nothing" in note
    assert text == '{\n  "a": 1\n}'


def test_extract_json_text_invalid_jsonpath_falls_back_to_whole_object():
    text, note = _extract_json_text('{"a": 1}', "$[[[not valid")
    assert note is not None and "Invalid JSONPath" in note
    assert text == '{\n  "a": 1\n}'
