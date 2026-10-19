"""溢出自动缩小字号（版式保护的唯一例外）。

背景：
- 渲染器默认只改 w:t 文字，不碰任何格式属性，保证页数不变。
- 但当真实数据明显长于占位符（如 {{地址}} → 一串门牌号）时，格子里的文字
  必然多占几行，把表格最后一行挤到第二页。这是 Word 的正常换行。
- 用户明确允许这种情况作为例外：可以缩小字号来保住页数。

本模块提供这个例外能力，并且刻意保守：
1. 只处理表格单元格里的段落（正文段落通常不在分页敏感区，不动）；
2. 只在"填充后行数 > 填充前行数"时才动手，能放下就绝不缩小；
3. 用 QFontMetricsF 按实际字体度量估算行数，不是拍脑袋数字；
4. 二分查找最小可行缩放，尽量贴近原字号；
5. 有缩放下限（默认 0.7），低于下限说明数据太长，宁可保持溢出也不缩成蚂蚁字；
6. 只改 w:rPr/w:sz，不合并 run、不清空 run、不碰段落/表格/页面属性。

如果不想启用，在【设置】里关闭"内容超出格子时自动缩小字号"即可，
届时行为退回纯版式保护：一个字都不动，溢出由你自己在数据或模板里解决。
"""

import math
from typing import Any, Dict, List, Optional, Tuple

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"

# 缩放下限：最多缩到原字号的 70%，再小就不缩了（宁可溢出）
MIN_SCALE = 0.7
# 默认正文字号（twips 制下没写 sz 时的兜底，约五号字）
DEFAULT_FONT_HALF_PT = 21


def _tag(name: str) -> str:
    return f"{{{W_NS}}}{name}"


def _cell_text_width_pt(cell_element, font_size_pt: float) -> Optional[float]:
    """估算单元格可用文字宽度（磅）。

    取 tcW（dxa=二十分之一磅），减去左右边距（默认各 108 dxa ≈ 5.4pt）。
    拿不到宽度时返回 None，表示无法判断，不做缩小。
    """
    tc_pr = cell_element.find(_tag("tcPr"))
    if tc_pr is None:
        return None
    tc_w = tc_pr.find(_tag("tcW"))
    if tc_w is None:
        return None
    try:
        width_dxa = float(tc_w.get(_tag("w"), "0") or 0)
    except ValueError:
        return None
    if width_dxa <= 0:
        return None
    # dxa → pt
    width_pt = width_dxa / 20.0
    margin_pt = 10.8  # 左右各约 5.4pt
    usable = width_pt - margin_pt
    return usable if usable > 10 else None


def _paragraph_runs(p_element) -> List:
    """收集段落内所有 w:r（含超链接里的 run）。"""
    runs = list(p_element.iter(_tag("r")))
    return [r for r in runs if r.find(_tag("t")) is not None]


def _run_font_half_pt(run_element) -> int:
    r_pr = run_element.find(_tag("rPr"))
    if r_pr is not None:
        sz = r_pr.find(_tag("sz"))
        if sz is not None:
            try:
                return int(sz.get(_tag("val"), DEFAULT_FONT_HALF_PT))
            except ValueError:
                pass
    return DEFAULT_FONT_HALF_PT


def _paragraph_text(p_element) -> str:
    parts = []
    for node in p_element.iter(_tag("t")):
        if node.text:
            parts.append(node.text)
    return "".join(parts)


def _char_is_wide(ch: str) -> bool:
    """粗略判断是否为全角字符（CJK、全角标点等）。"""
    code = ord(ch)
    return (
        0x1100 <= code <= 0x115F
        or 0x2E80 <= code <= 0xA4CF
        or 0xAC00 <= code <= 0xD7A3
        or 0xF900 <= code <= 0xFAFF
        or 0xFE30 <= code <= 0xFE6F
        or 0xFF00 <= code <= 0xFF60
        or 0xFFE0 <= code <= 0xFFE6
    )


def _fallback_advance(ch: str, font_size_pt: float) -> float:
    """没有 QGuiApplication 时的保守字宽估计：全角≈1em，半角≈0.55em。"""
    return font_size_pt * (1.0 if _char_is_wide(ch) else 0.55)


def _estimate_lines(text: str, width_pt: float, font_size_pt: float, metrics_cache) -> int:
    """按字体度量估算文本在给定宽度下占几行。

    有 GUI 环境时用 QFontMetricsF 精确测量；无 GUI（如纯命令行/测试）时
    退化为全角/半角启发式，保证不崩溃且结果方向正确。
    """
    if not text or width_pt <= 0 or font_size_pt <= 0:
        return 1

    fm = None
    try:
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is not None:
            from PySide6.QtGui import QFont, QFontMetricsF

            key = round(font_size_pt, 1)
            fm = metrics_cache.get(key)
            if fm is None:
                font = QFont("Microsoft YaHei UI")
                font.setPointSizeF(font_size_pt)
                fm = QFontMetricsF(font)
                metrics_cache[key] = fm
    except Exception:
        fm = None

    if fm is not None:
        total_width = sum(fm.horizontalAdvance(ch) for ch in text)
    else:
        total_width = sum(_fallback_advance(ch, font_size_pt) for ch in text)
    return max(1, math.ceil(total_width / width_pt))


def fit_cell_paragraphs(
    cell_element,
    original_texts: Dict[int, str],
    variables: Dict[str, Any],
    shrink_enabled: bool,
) -> List[str]:
    """对一个单元格内的段落做溢出检测与字号缩小。

    :param cell_element: w:tc XML 元素
    :param original_texts: {段落序号: 填充前的纯文本}，用于计算"原来占几行"
    :param variables: 变量字典（仅用于判断是否真的发生了增长替换）
    :param shrink_enabled: 是否允许缩小字号
    :return: 调整日志列表（每条形如 "第3行：14→11 磅"）
    """
    adjustments: List[str] = []
    if not shrink_enabled:
        return adjustments

    paragraphs = [p for p in cell_element.iter(_tag("p"))]
    # 只处理直接属于本单元格的段落，跳过嵌套表格里的
    direct_paragraphs = [
        p for p in paragraphs
        if p.getparent() is not None and p.getparent().tag == _tag("tc")
    ]
    if not direct_paragraphs:
        return adjustments

    metrics_cache = {}
    for index, p_element in enumerate(direct_paragraphs):
        new_text = _paragraph_text(p_element)
        old_text = original_texts.get(index, "")
        if not new_text or new_text == old_text:
            continue
        # 只有变长才可能溢出
        if len(new_text) <= len(old_text):
            continue

        runs = _paragraph_runs(p_element)
        if not runs:
            continue
        base_half_pt = max(_run_font_half_pt(r) for r in runs)
        base_pt = base_half_pt / 2.0
        width_pt = _cell_text_width_pt(cell_element, base_pt)
        if width_pt is None:
            continue

        lines_before = _estimate_lines(old_text, width_pt, base_pt, metrics_cache)
        lines_after = _estimate_lines(new_text, width_pt, base_pt, metrics_cache)
        if lines_after <= lines_before:
            continue

        # 二分找最小缩放（最大 scale = 最接近原字号）；找不到就退到下限尽力缩小
        lo, hi = MIN_SCALE, 1.0
        best = None
        for _ in range(8):
            mid = (lo + hi) / 2.0
            trial_pt = base_pt * mid
            if _estimate_lines(new_text, width_pt, trial_pt, metrics_cache) <= lines_before:
                best = mid
                lo = mid  # 尝试更接近原字号
            else:
                hi = mid
        capped = False
        if best is None:
            # 缩到下限仍放不下：按用户授权尽力缩小到下限，并标记为"已尽量"
            best = MIN_SCALE
            capped = True

        target_half_pt = max(2, int(round(base_half_pt * best)))
        if target_half_pt >= base_half_pt:
            continue
        for run in runs:
            r_pr = run.find(_tag("rPr"))
            if r_pr is None:
                # 没有 rPr 的 run 继承样式字号，这里显式写入以覆盖
                from lxml import etree

                r_pr = etree.SubElement(run, _tag("rPr"))
                run.insert(0, r_pr)
            for sz_tag in ("sz", "szCs"):
                sz = r_pr.find(_tag(sz_tag))
                if sz is None:
                    from lxml import etree

                    sz = etree.SubElement(r_pr, _tag(sz_tag))
                sz.set(_tag("val"), str(target_half_pt))
        suffix_note = "，已尽量" if capped else ""
        adjustments.append(
            f"第{index + 1}行：{base_pt:g}→{target_half_pt / 2:g} 磅（防溢出{suffix_note}）"
        )
    return adjustments


def collect_cell_original_texts(cell_element) -> Dict[int, str]:
    """在替换前快照每个直接子段落的文本，供 fit_cell_paragraphs 对比。"""
    texts = {}
    index = 0
    for p in cell_element.iter(_tag("p")):
        parent = p.getparent()
        if parent is not None and parent.tag == _tag("tc"):
            texts[index] = _paragraph_text(p)
            index += 1
    return texts
