"""storyboard 布尔解析回归：LLM 把 lipsync 写成字符串 "false" 时不能被当成 True。"""
import json

from mirage.app.pipeline.storyboard import _as_bool, _coerce_scenes


def test_as_bool_real_bools():
    assert _as_bool(True) is True
    assert _as_bool(False) is False


def test_as_bool_string_false_is_false():
    # 关键回归点：非空字符串 "false" 不能因 bool() 恒真而变 True
    for s in ("false", "False", "FALSE", "0", "", "否", "no"):
        assert _as_bool(s) is False, s


def test_as_bool_string_true():
    for s in ("true", "True", "1", "yes", "是", "真"):
        assert _as_bool(s) is True, s


def test_as_bool_none_and_numbers():
    assert _as_bool(None) is False
    assert _as_bool(0) is False
    assert _as_bool(1) is True


def test_coerce_scenes_lipsync_string_false():
    raw = json.dumps([{"image_prompt": "一个昏暗的房间", "lipsync": "false"}])
    scenes = _coerce_scenes(raw, 1)
    assert scenes[0]["lipsync"] is False


def test_coerce_scenes_lipsync_bool_true():
    raw = json.dumps([{"image_prompt": "一个昏暗的房间", "lipsync": True}])
    scenes = _coerce_scenes(raw, 1)
    assert scenes[0]["lipsync"] is True
