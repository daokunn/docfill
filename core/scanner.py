"""
目录 & 模板扫描模块
职责：
  1. 扫描模板根目录下的一级子文件夹，每个子文件夹 = 一项业务
  2. 递归扫描业务文件夹内的模板文件（.docx/.xlsx/.wps/.et）
  3. 提取模板中的 {{变量名}} 标记
  4. 同一业务下多模板同名变量自动合并
仅做扫描与提取，不做填充、不做文本解析。
"""

import os
import re
import zipfile
from typing import Dict, List, Optional, Set, Tuple

# 支持的模板扩展名
TEMPLATE_EXTENSIONS = (".docx", ".xlsx", ".wps", ".et")

# 变量标记正则：兼容 {{变量名}} {{ 变量名 }} ${变量名} ${ 变量名 }
VAR_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}|\$\{\s*([^}]+?)\s*\}")


class TemplateInfo:
    """单个模板文件信息"""

    def __init__(self, name: str, path: str, rel_path: str):
        """单个模板文件信息"""
        self.name = name            # 文件名
        self.path = path            # 绝对路径
        self.rel_path = rel_path    # 相对于业务文件夹的相对路径（用于还原目录结构）
        self.variables: Set[str] = set()  # 该模板中提取的变量名集合
        self.variable_order: List[str] = []  # 模板中的首次出现顺序
        self.optional_variables: Set[str] = set()  # 带 ? 标记的可选变量
        self.error: Optional[str] = None  # 解析错误信息

    def to_dict(self) -> dict:
        """转为可序列化的字典（用于日志/调试）"""
        return {
            "name": self.name,
            "path": self.path,
            "rel_path": self.rel_path,
            "variables": sorted(self.variables),
            "variable_order": self.variable_order,
            "optional_variables": sorted(self.optional_variables),
            "error": self.error,
        }


class BusinessInfo:
    """业务信息：一个一级子文件夹 = 一项业务"""

    def __init__(self, name: str, path: str):
        """业务信息：一个一级子文件夹 = 一项业务"""
        self.name = name                    # 业务名称（文件夹名）
        self.path = path                    # 业务文件夹绝对路径
        self.templates: List[TemplateInfo] = []   # 该业务下所有模板
        self.variables: Set[str] = set()    # 合并后的变量清单（多模板同名变量合并）
        self.variable_order: List[str] = []  # 按模板出现顺序汇总的变量
        self.optional_variables: Set[str] = set()  # 所有模板都标记为可选的变量

    def to_dict(self) -> dict:
        """转为可序列化的字典"""
        return {
            "name": self.name,
            "path": self.path,
            "templates": [t.to_dict() for t in self.templates],
            "variables": sorted(self.variables),
            "variable_order": self.variable_order,
            "optional_variables": sorted(self.optional_variables),
        }


def split_optional_marker(raw_name: str) -> Tuple[str, bool]:
    """拆分变量名和可选标记：``备注?`` -> (``备注``, True)。"""
    name = str(raw_name or "").strip()
    optional = name.endswith("?")
    if optional:
        name = name[:-1].strip()
    return name, optional


def _merge_specs(base: List[Tuple[str, bool]], incoming: List[Tuple[str, bool]]) -> List[Tuple[str, bool]]:
    """按首次出现顺序合并变量；同名变量只要有一处必填，就保持必填。"""
    position = {name: index for index, (name, _optional) in enumerate(base)}
    for name, optional in incoming:
        if not name:
            continue
        if name in position:
            index = position[name]
            base[index] = (name, base[index][1] and optional)
        else:
            position[name] = len(base)
            base.append((name, optional))
    return base


def extract_variable_specs_from_text(text: str) -> List[Tuple[str, bool]]:
    """从文本中按出现顺序提取 (变量名, 是否可选)。"""
    specs: List[Tuple[str, bool]] = []
    for match in VAR_PATTERN.finditer(text or ""):
        raw_name = match.group(1) or match.group(2) or ""
        name, optional = split_optional_marker(raw_name)
        if name:
            specs = _merge_specs(specs, [(name, optional)])
    return specs


def extract_variables_from_text(text: str) -> Set[str]:
    """从文本中提取变量名（兼容旧调用，不含可选标记）。"""
    return {name for name, _optional in extract_variable_specs_from_text(text)}


def _iter_docx_texts(doc):
    """按正文段落、正文表格、页眉页脚顺序产出文本。"""
    for para in doc.paragraphs:
        yield para.text
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield cell.text
    for section in doc.sections:
        for para in section.header.paragraphs:
            yield para.text
        for para in section.footer.paragraphs:
            yield para.text


def _extract_docx_variable_specs(file_path: str) -> List[Tuple[str, bool]]:
    """从 .docx 文件按出现顺序提取变量规格（段落 + 表格 + 页眉页脚）。"""
    specs: List[Tuple[str, bool]] = []
    try:
        import docx
        doc = docx.Document(file_path)
        for text in _iter_docx_texts(doc):
            specs = _merge_specs(specs, extract_variable_specs_from_text(text))
    except Exception as e:
        raise RuntimeError(f"docx 解析失败：{e}")
    return specs


def _extract_xlsx_variable_specs(file_path: str) -> List[Tuple[str, bool]]:
    """从 .xlsx 文件按工作表/行/列顺序提取变量规格。"""
    specs: List[Tuple[str, bool]] = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, data_only=False, read_only=True)
        for sheet in wb.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.value is not None and isinstance(cell.value, str):
                        specs = _merge_specs(specs, extract_variable_specs_from_text(cell.value))
        wb.close()
    except Exception as e:
        raise RuntimeError(f"xlsx 解析失败：{e}")
    return specs


def _extract_zip_based_variable_specs(file_path: str) -> List[Tuple[str, bool]]:
    """
    尝试将 .wps/.et 作为 zip（新版 WPS 格式本质是 OOXML，即 docx/xlsx 改名）解析。
    读取 word/document.xml 或 xl/sharedStrings.xml 中的变量。
    """
    specs: List[Tuple[str, bool]] = []
    try:
        with zipfile.ZipFile(file_path, "r") as archive:
            names = archive.namelist()
            # WPS 文字（类 docx）
            if "word/document.xml" in names:
                xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
                specs = _merge_specs(specs, extract_variable_specs_from_text(_strip_xml_tags(xml)))
            # WPS 表格（类 xlsx）
            if "xl/sharedStrings.xml" in names:
                xml = archive.read("xl/sharedStrings.xml").decode("utf-8", errors="ignore")
                specs = _merge_specs(specs, extract_variable_specs_from_text(_strip_xml_tags(xml)))
            # 兜底：扫描所有 xml 文件
            if not specs:
                for name in names:
                    if name.endswith(".xml") or name.endswith(".rels"):
                        try:
                            content = archive.read(name).decode("utf-8", errors="ignore")
                            specs = _merge_specs(specs, extract_variable_specs_from_text(_strip_xml_tags(content)))
                        except Exception:
                            pass
    except zipfile.BadZipFile:
        raise RuntimeError("文件不是有效的压缩格式，可能是旧版 WPS 二进制格式，暂不支持")
    except Exception as e:
        raise RuntimeError(f"WPS/ET 解析失败：{e}")
    return specs


def _strip_xml_tags(xml_text: str) -> str:
    """去除 XML 标签，保留文本内容"""
    return re.sub(r"<[^>]+>", "", xml_text)


def extract_template_variable_specs(file_path: str) -> List[Tuple[str, bool]]:
    """根据扩展名提取变量，保留模板中的出现顺序和可选标记。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return _extract_docx_variable_specs(file_path)
    elif ext == ".xlsx":
        return _extract_xlsx_variable_specs(file_path)
    elif ext in (".wps", ".et"):
        return _extract_zip_based_variable_specs(file_path)
    return []


def extract_template_variables(file_path: str) -> Set[str]:
    """根据扩展名提取变量名集合（兼容旧调用）。"""
    return {name for name, _optional in extract_template_variable_specs(file_path)}


def _count_variables_in_text(text: str, name_map: Dict[str, str]) -> int:
    """统计文本中命中 name_map 的变量标记数量（忽略可选标记）。"""
    count = 0
    for match in VAR_PATTERN.finditer(text or ""):
        raw_name = match.group(1) or match.group(2) or ""
        name, _optional = split_optional_marker(raw_name)
        if name in name_map:
            count += 1
    return count


def count_variable_occurrences(file_path: str, name_map: Dict[str, str]) -> int:
    """统计模板中将被 name_map 修改的变量标记数量，用于修改前预览。

    只统计，不修改文件。
    """
    if not name_map:
        return 0
    ext = os.path.splitext(file_path)[1].lower()
    count = 0
    try:
        if ext == ".docx":
            import docx
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                count += _count_variables_in_text(para.text, name_map)
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for para in cell.paragraphs:
                            count += _count_variables_in_text(para.text, name_map)
            for section in doc.sections:
                for para in section.header.paragraphs:
                    count += _count_variables_in_text(para.text, name_map)
                for para in section.footer.paragraphs:
                    count += _count_variables_in_text(para.text, name_map)
        elif ext == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(file_path, data_only=False, read_only=True)
            for sheet in wb.worksheets:
                for row in sheet.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str):
                            count += _count_variables_in_text(cell.value, name_map)
            wb.close()
        elif ext in (".wps", ".et"):
            with zipfile.ZipFile(file_path, "r") as archive:
                for name in archive.namelist():
                    if name.endswith(".xml") or name.endswith(".rels"):
                        try:
                            text = archive.read(name).decode("utf-8", errors="ignore")
                        except Exception:
                            continue
                        count += _count_variables_in_text(_strip_xml_tags(text), name_map)
    except Exception:
        return count
    return count


def scan_businesses(template_root: str) -> List[BusinessInfo]:
    """
    扫描模板根目录，返回业务列表。
    一级子文件夹 = 业务，顺序沿用 OS 原生目录枚举顺序。
    """
    businesses: List[BusinessInfo] = []
    if not template_root or not os.path.isdir(template_root):
        return businesses

    # os.listdir 返回顺序即 OS 原生枚举顺序，不排序
    for entry in os.listdir(template_root):
        entry_path = os.path.join(template_root, entry)
        if os.path.isdir(entry_path):
            business = BusinessInfo(name=entry, path=entry_path)
            _scan_business_templates(business)
            businesses.append(business)
    return businesses


def _scan_business_templates(business: BusinessInfo) -> None:
    """递归扫描业务文件夹内的模板文件，提取变量并合并"""
    for root, _dirs, files in os.walk(business.path):
        # 文字表单优先于表格，变量顺序更接近人工填表顺序
        files.sort(key=lambda name: (
            0 if os.path.splitext(name)[1].lower() in (".docx", ".wps") else 1,
            name.lower(),
        ))
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in TEMPLATE_EXTENSIONS:
                continue
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, business.path)
            tmpl = TemplateInfo(name=fname, path=abs_path, rel_path=rel_path)
            specs: List[Tuple[str, bool]] = []
            try:
                specs = extract_template_variable_specs(abs_path)
                tmpl.variable_order = [name for name, _optional in specs]
                tmpl.variables = set(tmpl.variable_order)
                tmpl.optional_variables = {name for name, optional in specs if optional}
            except RuntimeError as e:
                tmpl.error = str(e)
            business.templates.append(tmpl)

            # 业务级变量按首次出现顺序汇总；只要有一处必填，整体就算必填
            for name, optional in specs if not tmpl.error else []:
                if name not in business.variables:
                    business.variable_order.append(name)
                    business.variables.add(name)
                    if optional:
                        business.optional_variables.add(name)
                elif not optional:
                    business.optional_variables.discard(name)


def ordered_variable_names(business: BusinessInfo, mode: str = "template") -> List[str]:
    """按用户设置返回变量顺序。

    - template：模板中首次出现的顺序（更像人工填表的顺序，默认）
    - alphabetical：按名称字典序
    """
    if mode == "alphabetical":
        return sorted(business.variables)

    ordered = [name for name in business.variable_order if name in business.variables]
    seen = set(ordered)
    for name in sorted(business.variables):
        if name not in seen:
            ordered.append(name)
    return ordered


def get_business_by_name(businesses: List[BusinessInfo], name: str) -> Optional[BusinessInfo]:
    """按名称查找业务"""
    for b in businesses:
        if b.name == name:
            return b
    return None


# ==================== 模板变量名重命名 ====================

def rename_variables_in_text(text: str, name_map: Dict[str, str]) -> str:
    """
    将文本中的变量名按 name_map 重命名。
    :param name_map: {旧变量名: 新变量名}
    :return: 重命名后的文本
    """
    def replacer(m: re.Match) -> str:
        raw_name = m.group(1) or m.group(2) or ""
        var_name, optional = split_optional_marker(raw_name)
        new_name = name_map.get(var_name, var_name)
        suffix = "?" if optional else ""
        # 保持原有的标记格式 {{ }} 或 ${ }，并保留可选标记
        if m.group(1) is not None:
            return "{{" + new_name + suffix + "}}"
        else:
            return "${" + new_name + suffix + "}"

    return VAR_PATTERN.sub(replacer, text or "")


def rename_variables_in_docx(file_path: str, name_map: Dict[str, str]) -> int:
    """
    重命名 .docx 文件中的变量名。
    :return: 实际修改的变量数量
    """
    import docx
    count = 0
    doc = docx.Document(file_path)

    def _rename_paragraph(para) -> int:
        nonlocal count
        if not para.runs:
            return 0
        full_text = "".join(run.text for run in para.runs)
        if not VAR_PATTERN.search(full_text):
            return 0
        new_text = rename_variables_in_text(full_text, name_map)
        if new_text != full_text:
            para.runs[0].text = new_text
            for run in para.runs[1:]:
                run.text = ""
            count += 1

    for para in doc.paragraphs:
        _rename_paragraph(para)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _rename_paragraph(para)
    for section in doc.sections:
        for para in section.header.paragraphs:
            _rename_paragraph(para)
        for para in section.footer.paragraphs:
            _rename_paragraph(para)

    if count > 0:
        doc.save(file_path)
    return count


def rename_variables_in_xlsx(file_path: str, name_map: Dict[str, str]) -> int:
    """
    重命名 .xlsx 文件中的变量名。
    :return: 实际修改的变量数量
    """
    import openpyxl
    count = 0
    wb = openpyxl.load_workbook(file_path)
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None and isinstance(cell.value, str):
                    if VAR_PATTERN.search(cell.value):
                        new_val = rename_variables_in_text(cell.value, name_map)
                        if new_val != cell.value:
                            cell.value = new_val
                            count += 1
    if count > 0:
        wb.save(file_path)
    wb.close()
    return count


def rename_variables_in_wps_et(file_path: str, name_map: Dict[str, str]) -> int:
    """
    重命名 .wps/.et 文件中的变量名（作为 zip/OOXML 处理）。
    :return: 实际修改的变量数量
    """
    import shutil
    import zipfile
    count = 0
    try:
        with zipfile.ZipFile(file_path, "r") as z:
            names = z.namelist()
            file_contents = {name: z.read(name) for name in names}
    except zipfile.BadZipFile:
        raise RuntimeError("文件不是有效的压缩格式，可能是旧版 WPS 二进制格式，暂不支持")

    for name in list(file_contents.keys()):
        if name.endswith(".xml") or name.endswith(".rels"):
            try:
                content = file_contents[name].decode("utf-8")
                if VAR_PATTERN.search(content):
                    new_content = rename_variables_in_text(content, name_map)
                    if new_content != content:
                        file_contents[name] = new_content.encode("utf-8")
                        count += 1
            except (UnicodeDecodeError, Exception):
                pass

    if count > 0:
        # 就地修改 zip
        tmp_path = file_path + ".tmp"
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for n, data in file_contents.items():
                zout.writestr(n, data)
        shutil.move(tmp_path, file_path)
    return count


def rename_variables_in_template(file_path: str, name_map: Dict[str, str]) -> int:
    """
    根据扩展名选择方式，重命名模板文件中的变量名。
    :param name_map: {旧变量名: 新变量名}
    :return: 实际修改的变量数量
    """
    if not name_map:
        return 0
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return rename_variables_in_docx(file_path, name_map)
    elif ext == ".xlsx":
        return rename_variables_in_xlsx(file_path, name_map)
    elif ext in (".wps", ".et"):
        return rename_variables_in_wps_et(file_path, name_map)
    return 0
