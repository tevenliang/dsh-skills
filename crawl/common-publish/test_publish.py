"""common-publish smoke test（重写于 2026-07-27）。

只覆盖纯函数级验证，避免依赖图片物化等未实现模块。
重点验证文件名按 UTF-8 字节安全截断（Linux ext4 上限 255 字节），
这是 2026-07-27 修复的关键点（旧逻辑按字符数截断，中文标题会突破字节上限）。
"""
import publish_vault as p


def test_bytes_truncate():
    # 近 200 个汉字，远超 255 字节上限
    title = "2026-07-26_" + "马斯克绝对是这个世纪最厉害的资本高手" * 8
    out = p._sanitize_filename(title)
    full = (out + ".md").encode("utf-8")
    assert len(full) <= 255, f"文件名超长: {len(full)} 字节"
    assert out.startswith("20260726_"), "日期前缀被截断"


def test_illegal_chars():
    out = p._sanitize_filename("a/b:c*d?e")
    for ch in "/:*?":
        assert ch not in out, f"非法字符未替换: {ch}"


def test_short_passthrough():
    out = p._sanitize_filename("2026-07-23_正常标题")
    assert out == "20260723_正常标题", out


def test_float_title():
    # 防御 title 为 float 的边界情况
    out = p._sanitize_filename(20260723.0)
    assert isinstance(out, str)


if __name__ == "__main__":
    test_bytes_truncate()
    test_illegal_chars()
    test_short_passthrough()
    test_float_title()
    print("OK: common-publish smoke test passed (4 cases)")
