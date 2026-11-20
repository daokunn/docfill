"""下载空模板的列来源测试（TDD）：以当前业务模板变量为准。"""

from output.roster_export import template_columns_for_download


def test_uses_template_vars_when_available():
    cols, differs = template_columns_for_download(
        template_vars=["姓名", "单位", "电话", "编号"],
        roster_columns=["姓名", "名字", "公司名", "库存号", "商户号"],
    )
    assert cols == ["姓名", "单位", "电话", "编号"]
    assert differs is True


def test_no_roster_columns_no_diff():
    cols, differs = template_columns_for_download(
        template_vars=["姓名", "单位"], roster_columns=[])
    assert cols == ["姓名", "单位"]
    assert differs is False


def test_same_columns_no_diff():
    cols, differs = template_columns_for_download(
        template_vars=["姓名", "单位"], roster_columns=["姓名", "单位"])
    assert cols == ["姓名", "单位"]
    assert differs is False


def test_falls_back_to_roster_when_no_template_vars():
    cols, differs = template_columns_for_download(
        template_vars=[], roster_columns=["姓名", "备注"])
    assert cols == ["姓名", "备注"]
    assert differs is False
