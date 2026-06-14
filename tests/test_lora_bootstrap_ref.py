"""回归:lora_bootstrap._find_ref_face 不再因未定义 _IMG_EXTS 抛 NameError。

修复前:lora_bootstrap.py 裸用 _IMG_EXTS(只 import 了 lora_train 模块、没引入该常量)，
一旦 _ref/ 下有参考脸,_find_ref_face 第一次循环即 NameError → PuLID 单脸自举必崩。
"""
from mirage.app.pipeline.lora_bootstrap import _IMG_EXTS, _find_ref_face


def test_img_exts_defined():
    assert isinstance(_IMG_EXTS, tuple) and ".png" in _IMG_EXTS


def test_find_ref_face_returns_uploaded_face(tmp_path):
    ref_dir = tmp_path / "_ref"
    ref_dir.mkdir()
    face = ref_dir / "face.png"
    face.write_bytes(b"\x89PNG\r\n")            # 占位字节即可，函数只看扩展名
    assert _find_ref_face(str(tmp_path)) == str(face)


def test_find_ref_face_none_when_no_ref(tmp_path):
    assert _find_ref_face(str(tmp_path)) is None
