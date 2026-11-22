"""构建配置回归测试：保证精简掉的冗余大文件规则不被误删。

onefile 模式启动慢的根因是每次启动都要解压 exe 里的全部依赖，
因此 gzip 体积直接决定首屏速度。下面这些文件本项目从不使用，
必须在打包时被剔除。
"""
import ast
import os

SPEC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build.spec")


def _read_spec_lines():
    with open(SPEC, encoding="utf-8") as f:
        return f.readlines()


def test_exclude_opengl_software_renderer():
    """纯表格界面用不到软件 OpenGL，opengl32sw.dll 7.3MB 必须剔除。"""
    text = "".join(_read_spec_lines())
    assert "opengl32sw.dll" in text, "opengl32sw.dll 未列入剔除规则，会白增 7MB 解压负担"


def test_exclude_pil_unused_codecs():
    """项目只用 PNG/ICO，PIL 的 avif/webp 编解码器（合计 >4MB）可剔除。"""
    text = "".join(_read_spec_lines())
    assert "_avif" in text, "PIL _avif 未剔除"
    assert "_webp" in text, "PIL _webp 未剔除"


def test_spec_syntax_valid():
    """build.spec 是合法 Python 语法（改完别把打包弄崩）。"""
    text = "".join(_read_spec_lines())
    ast.parse(text, filename=SPEC)
