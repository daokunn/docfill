"""
全局界面样式（QSS）+ 使用教程内容
职责：
  1. 提供 4 套可切换的界面主题（墨青 / 明亮 / 深空 / 护眼），由调色板生成 QSS
  2. APP_STYLE 保持为默认主题样式，兼容旧代码直接引用
  3. 提供使用教程 HTML（TUTORIAL_HTML / build_tutorial_html，随主题配色）
  4. 不依赖业务逻辑；仅在 current_theme() 里按需读一次配置
"""

from typing import Dict

# ---------- 主题调色板 ----------
# 每套主题用相同的 31 个语义色令牌；QSS / 教程只引用令牌，切换主题不缺色。
DEFAULT_THEME = "ink"

_THEME_TOKENS = [
    "text", "text_strong", "text_muted", "text_soft",        # 正文 / 标题 / 次要 / 更淡
    "canvas", "surface", "surface_alt",                       # 画布 / 卡片 / 浅底
    "border", "border_strong", "control_border",              # 边框 / 深边框 / 控件边框
    "accent", "accent_hover", "accent_press", "accent_dark",  # 强调色及深浅态
    "accent_soft", "accent_soft_border", "accent_text",       # 强调色浅底 / 边 / 字
    "selection_bg", "selection_fg",                           # 选中底色 / 字
    "disabled_fg", "disabled_bg", "on_accent",                # 禁用字 / 底 / 强调色上的字
    "tooltip_bg", "tooltip_fg", "grid", "head_bg",            # 提示 / 网格 / 表头底
    "warn", "bad", "good", "warn_bg", "bad_bg", "good_bg",    # 语义色及浅底
    "scroll_thumb",                                            # 滚动条
]

THEMES = {
    "ink": {
        "label": "墨青（默认）",
        "colors": ["#24322e", "#16241f", "#87938e", "#6d7b75",
                   "#f6f7f5", "#ffffff", "#f4f7f5",
                   "#e6eae7", "#e2e7e3", "#d9dfdb",
                   "#0f766e", "#0d6a63", "#0b5a54", "#0b5a54",
                   "#e8f4f1", "#cbe6df", "#0b5a54",
                   "#bfe0d8", "#16241f",
                   "#b3bcb7", "#f4f5f3", "#ffffff",
                   "#24322e", "#ffffff", "#eef1ee", "#f4f7f5",
                   "#b45309", "#b91c1c", "#15803d",
                   "#fffbeb", "#fef2f2", "#ecfdf5", "#ccd5d0"],
    },
    "light": {
        "label": "明亮（白底蓝调）",
        "colors": ["#1f2937", "#111827", "#7c8a9a", "#5b6b7d",
                   "#f4f6f9", "#ffffff", "#eef2f7",
                   "#dbe3ec", "#cbd5e1", "#cbd5e1",
                   "#2563eb", "#1d4ed8", "#1e40af", "#1e3a8a",
                   "#e8f0fe", "#bfdbfe", "#1d4ed8",
                   "#dbeafe", "#111827",
                   "#a7b0bd", "#eef2f7", "#ffffff",
                   "#1f2937", "#ffffff", "#e5eaf1", "#f1f5f9",
                   "#b45309", "#b91c1c", "#15803d",
                   "#fffbeb", "#fef2f2", "#ecfdf5", "#c3cedb"],
    },
    "dark": {
        "label": "深空（夜间护眼）",
        "colors": ["#e6edf3", "#f0f6fc", "#8b949e", "#9aa7b4",
                   "#0d1117", "#161b22", "#1c232c",
                   "#30363d", "#3d444d", "#3d444d",
                   "#2ea043", "#3fb950", "#238636", "#1a7f37",
                   "#132a1c", "#21532e", "#7ee787",
                   "#1f6feb", "#ffffff",
                   "#6e7681", "#21262d", "#ffffff",
                   "#e6edf3", "#010409", "#21262d", "#1c232c",
                   "#d29922", "#f85149", "#3fb950",
                   "#2b2416", "#2d1418", "#10261a", "#484f58"],
    },
    "sepia": {
        "label": "护眼（暖黄纸感）",
        "colors": ["#4a3f35", "#3a3027", "#9c8c7b", "#8a7968",
                   "#f5efe2", "#fffaf0", "#efe6d5",
                   "#e3d7c1", "#d3c4a9", "#d9cbb2",
                   "#8a6d3b", "#7a5f31", "#6b5229", "#5c4522",
                   "#f0e4c8", "#dcc79b", "#5c4522",
                   "#e8d9b5", "#3a3027",
                   "#bfb3a0", "#efe6d5", "#fffaf0",
                   "#4a3f35", "#fffaf0", "#e8ddc7", "#f0e6d2",
                   "#a16207", "#b45309", "#4d7c0f",
                   "#faf3df", "#f9e8dd", "#eef3dc", "#c9b89c"],
    },
}
THEME_ORDER = ["ink", "light", "dark", "sepia"]


def palette(theme_id: str = DEFAULT_THEME) -> Dict[str, str]:
    """返回主题色令牌字典；未知主题回退默认。"""
    spec = THEMES.get(theme_id) or THEMES[DEFAULT_THEME]
    return dict(zip(_THEME_TOKENS, spec["colors"]))


def get_settings():
    """按需导入配置，避免 style 模块在纯测试环境里依赖配置单例。"""
    from config.settings import get_settings as _get_settings
    return _get_settings()


def current_theme() -> str:
    """读取当前主题；非法值回退默认，保证界面永不崩。"""
    try:
        value = str(get_settings().get("theme", DEFAULT_THEME) or DEFAULT_THEME)
    except Exception:
        return DEFAULT_THEME
    return value if value in THEMES else DEFAULT_THEME


def build_style(theme_id: str = DEFAULT_THEME) -> str:
    """按主题生成完整 QSS。QSS 无变量，用命名占位符逐个替换。"""
    p = palette(theme_id)
    return _QSS_TEMPLATE.format(**p)


def current_style() -> str:
    """按当前配置即时生成样式，供窗口 setStyleSheet 使用。"""
    return build_style(current_theme())


def current_tutorial_html() -> str:
    """按当前配置生成教程 HTML，深浅主题都清晰。"""
    return build_tutorial_html(current_theme())


# QSS 模板：{token} 占位符由 build_style 用主题色填充（花括号成对转义）
_QSS_TEMPLATE = """
/* ===== 基础 ===== */
QWidget {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 10pt;
    color: {text};
}}
QMainWindow, QDialog {{ background: {canvas}; }}

/* ===== 卡片：左侧细色脊是记忆点 ===== */
QGroupBox {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {text_strong}; font-weight: 600; }}
QFrame#topCard, QFrame#sideCard, QFrame#actionCard {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 12px;
}}
QFrame#topCard {{ padding: 2px; border-top: 2px solid {accent}; }}

/* ===== 排版层级 ===== */
QLabel {{ background: transparent; }}
QLabel#caption {{ color: {text_muted}; font-size: 8.5pt; }}
QLabel#pathValue {{ color: {text_strong}; font-weight: 600; font-size: 10pt; }}
QLabel#sectionTitle {{ color: {text_strong}; font-size: 12pt; font-weight: 700; }}
QLabel#sectionHint {{ color: {text_muted}; font-size: 9pt; }}
QLabel#coveragePill {{
    color: {accent_text}; background: {accent_soft}; border: 1px solid {accent_soft_border};
    border-radius: 10px; padding: 5px 11px; font-size: 9pt; font-weight: 600;
}}
QLabel#bizCount {{ color: {text_soft}; background: {surface_alt}; border-radius: 8px; padding: 2px 9px; font-size: 8.5pt; }}
QLabel#formSection {{
    color: {text_strong}; font-size: 10.5pt; font-weight: 600;
    background: {accent_soft}; border-left: 3px solid {accent};
    border-radius: 0 6px 6px 0; padding: 6px 10px; margin-top: 10px;
}}

/* ===== 按钮 ===== */
QPushButton {{
    background: {surface}; color: {text};
    border: 1px solid {control_border}; border-radius: 8px;
    padding: 7px 15px; font-size: 10.5pt;
}}
QPushButton:hover {{ background: {accent_soft}; border-color: {accent}; color: {accent}; }}
QPushButton:pressed {{ background: {accent_soft}; }}
QPushButton:disabled {{ color: {disabled_fg}; background: {disabled_bg}; border-color: {border}; }}
QPushButton:focus {{ outline: none; border-color: {accent}; }}
QPushButton#primary {{
    background: {accent}; color: {on_accent}; border: none; font-weight: 600;
    padding: 8px 16px;
}}
QPushButton#primary:hover {{ background: {accent_hover}; color: {on_accent}; }}
QPushButton#primary:pressed {{ background: {accent_press}; }}
QPushButton#primary:disabled {{ background: {accent_soft_border}; color: {on_accent}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid {control_border}; color: {text_soft}; }}
QPushButton#ghost:hover {{ background: {surface_alt}; border-color: {accent}; color: {text_strong}; }}
QPushButton#generate {{
    background: {accent}; color: {on_accent}; border: 1px solid {accent_dark};
    border-radius: 9px; font-size: 14pt; font-weight: 700; padding: 12px;
}}
QPushButton#generate:hover {{ background: {accent_hover}; border-color: {accent_dark}; }}
QPushButton#generate:pressed {{ background: {accent_press}; padding: 13px 12px 11px 12px; }}

/* ===== 输入类控件 ===== */
QLineEdit, QComboBox, QTextEdit, QSpinBox {{
    background: {surface}; color: {text_strong}; border: 1px solid {control_border}; border-radius: 7px; padding: 6px 9px;
    selection-background-color: {selection_bg}; selection-color: {selection_fg};
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QSpinBox:focus {{ border-color: {accent}; }}
QLineEdit:disabled, QComboBox:disabled {{ background: {disabled_bg}; color: {text_soft}; }}
QLineEdit:read-only {{ background: {surface_alt}; color: {text}; }}
QTableWidget QLineEdit, QTableView QLineEdit {{ background: {surface}; color: {text_strong}; selection-background-color: {selection_bg}; selection-color: {selection_fg}; }}
QLineEdit#searchBox {{ background: {surface_alt}; border: 1px solid {border}; border-radius: 8px; padding: 7px 11px; }}
QLineEdit#searchBox:focus {{ background: {surface}; border-color: {accent}; }}
QComboBox {{ padding: 6px 9px; }}
QComboBox QAbstractItemView {{ selection-background-color: {accent}; selection-color: {on_accent}; border: 1px solid {control_border}; background: {surface}; color: {text}; }}
QCheckBox {{ spacing: 7px; padding: 2px 0; color: {text}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {control_border}; background: {surface}; }}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QCheckBox::indicator:checked:hover {{ background: {accent_hover}; }}

/* ===== 业务列表 ===== */
QListWidget#bizList {{ background: transparent; border: none; padding: 2px; }}
QListWidget#bizList::item {{
    padding: 9px 11px; border-radius: 8px; margin: 2px 0; color: {text_strong};
    border-left: 3px solid transparent;
}}
QListWidget#bizList::item:selected {{ background: {accent_soft}; color: {accent_text}; font-weight: 600; border-left-color: {accent}; }}
QListWidget#bizList::item:hover:!selected {{ background: {surface_alt}; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 5px; color: {text}; }}
QListWidget::item:selected {{ background: {accent}; color: {on_accent}; }}
QListWidget::item:hover:!selected {{ background: {accent_soft}; }}

/* ===== 表格：细分隔线 + 清晰表头 ===== */
QTableWidget {{
    background: {surface}; border: 1px solid {border}; border-radius: 10px;
    gridline-color: {grid}; selection-background-color: {accent_soft}; selection-color: {selection_fg};
}}
QTableWidget::item {{ padding: 7px 8px; border-bottom: 1px solid {grid}; color: {text}; }}
QTableWidget::item:hover {{ background: {surface_alt}; }}
QTableWidget::item:selected {{ background: {selection_bg}; color: {selection_fg}; }}
QHeaderView::section {{
    background: {head_bg}; border: none; border-bottom: 1px solid {border_strong};
    padding: 9px 9px; font-weight: 600; color: {text_strong};
}}

/* ===== 日志区：等宽 + 浅底 ===== */
QTextEdit#log {{
    background: {surface_alt}; font-family: "Consolas", "Microsoft YaHei UI";
    font-size: 9pt; color: {text_soft}; border: 1px solid {border};
}}
QFrame#dropIndicator {{ border: 2px dashed {accent}; background: {accent_soft}; border-radius: 6px; }}

/* ===== 可拖动分隔条 ===== */
QSplitter::handle {{ background: {border_strong}; }}
QSplitter::handle:horizontal {{ width: 5px; }}
QSplitter::handle:vertical {{ height: 7px; }}
QSplitter::handle:hover {{ background: {accent}; }}

/* ===== 滚动条 ===== */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {scroll_thumb}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {scroll_thumb}; border-radius: 5px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ===== 其他 ===== */
QDialogButtonBox QPushButton {{ min-width: 76px; }}
QToolTip {{ background: {tooltip_bg}; color: {tooltip_fg}; border: none; padding: 5px 8px; border-radius: 5px; }}
QProgressBar {{ border: 1px solid {control_border}; border-radius: 6px; text-align: center; background: {surface}; color: {text}; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}
"""


# 默认主题样式：兼容旧代码里对 APP_STYLE 的直接引用
APP_STYLE = build_style(DEFAULT_THEME)


# ---------- 使用教程（HTML，随主题配色；富文本展示） ----------
def build_tutorial_html(theme_id: str = DEFAULT_THEME) -> str:
    """生成教程 HTML，配色跟随当前主题，深浅主题都清晰可读。"""
    p = palette(theme_id)
    return _TUTORIAL_TEMPLATE.format(**p)


_TUTORIAL_TEMPLATE = """
<style>
body {{ font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 11pt; color: {text}; background: {canvas}; line-height: 1.6; }}
h1 {{ font-size: 22pt; color: {text_strong}; margin-bottom: 4px; }}
h2 {{ font-size: 15pt; color: {accent_text}; margin-top: 22px; margin-bottom: 8px; }}
p {{ margin: 6px 0; }}
.lead {{ color: {text_soft}; }}
.small {{ color: {text_muted}; font-size: 9pt; }}
.tip {{ background: {accent_soft}; border-left: 4px solid {accent}; padding: 8px 10px; margin: 8px 0; }}
.warn {{ background: {warn_bg}; border-left: 4px solid {warn}; padding: 8px 10px; margin: 8px 0; }}
.ok {{ background: {good_bg}; border-left: 4px solid {good}; padding: 8px 10px; margin: 8px 0; }}
.bad {{ background: {bad_bg}; border-left: 4px solid {bad}; padding: 8px 10px; margin: 8px 0; }}
code {{ background: {surface_alt}; color: {accent_text}; padding: 1px 4px; }}
td, th {{ padding: 7px 10px; vertical-align: top; }}
th {{ background: {head_bg}; color: {text_strong}; }}
.step {{ background: {accent_soft}; border: 1px solid {accent_soft_border}; }}
</style>

<h1>第一次用？看这三步就够了</h1>
<p class="lead">不用懂"变量""正则""模板占位符"。你只要会三件事：<b>选文件夹、粘贴资料、点按钮</b>。一路照着做，两分钟就能出第一份文件。</p>

<table width="100%" cellspacing="6" cellpadding="10">
<tr>
<td width="33%" class="step">
<b>① 选两个文件夹</b><br/>
<span class="small">告诉程序模板在哪、结果放哪</span>
</td>
<td width="33%" class="step">
<b>② 粘贴客户资料</b><br/>
<span class="small">整段粘进去，程序自己拆</span>
</td>
<td width="33%" class="step">
<b>③ 点一键生成</b><br/>
<span class="small">一个窗看全结果，直接下一单</span>
</td>
</tr>
</table>

<div class="ok"><b>记住这句：</b>模板和输出分开放，粘贴完先看<b>黄色格子</b>（还没填的）， generation 前程序会再问你一次要不要继续。</div>

<h2>第 ① 步：告诉程序"模板在哪、结果放哪"</h2>
<p><b>模板文件夹</b>是放原始模板的总文件夹。它里面每个<b>子文件夹＝一项业务</b>，例如：</p>
<pre>模板文件夹/
├─ 公务卡申请/
│  ├─ 申请表.docx
│  └─ 信息登记表.xlsx
└─ 信用卡激活/
   └─ 激活申请表.docx</pre>
<ol>
<li>点顶部 <b>【目录设置…】</b>，在同一个窗口里选"模板文件夹"和"输出文件夹"。</li>
<li>每项业务会记住自己上次用的目录，下次自动带出；路径框也能直接手输或从下拉里选近期用过的。</li>
<li>输出目录选一个专门放结果的文件夹，例如 <code>D:/生成结果</code>。</li>
</ol>
<div class="warn"><b>注意：</b>输出目录不要选到模板文件夹里面，不然生成的文件会和模板混在一起，程序会拦住这种选择。</div>

<h2>第 ② 步：把客户资料粘进来</h2>
<ol>
<li>左边点一下要办的<b>业务名称</b>。</li>
<li>点青绿色的 <b>【粘贴识别】</b>（快捷键 Ctrl+Shift+V）。</li>
<li>把客户发来的整段文字粘进去，点 <b>【智能解析】</b>。</li>
<li>输入框和结果表之间有一条<b>可拖动的分隔线</b>：资料长时把中间那条线往下拖，输入区就变大；位置会自动记住。</li>
<li>看下方提示，比如"模板覆盖 5/8；待填写：出生日期、备注"，就知道还缺什么。</li>
<li>核对无误后点 <b>【确认填充】</b>。</li>
</ol>
<div class="tip"><b>黄色格子 = 还没填。</b>双击"值"单元格就能改；拿不准的可以先空着，生成前程序会再提醒一次。</div>
<div class="tip"><b>同一份资料两种叫法不会算错。</b>比如既写"身份证号"又写"证件号"、值一样，程序认成同一个，不再误报冲突。</div>

<h2>第 ③ 步：生成前确认 → 看结果 → 下一单</h2>
<ol>
<li>回主界面扫一眼变量表，把黄色格子补掉；补不齐也没关系，程序会问你。</li>
<li>点绿色大按钮 <b>【一键生成文档】</b>（Ctrl+G）。</li>
<li><b>有几项没填时的确认框：</b>变量少，就把这几个变量名<b>直接列在框里</b>给你看；变量多，先列前几个，再点框里的 <b>【详细查看】</b> <b>就地展开</b>看全部——<b>不会另开新窗口</b>。你看完自己决定点 <b>【仍然生成】</b>（空着的地方留空）还是 <b>【返回修改】</b>。模板里写了 <code>{{字段?}}</code> 的可选字段不算缺。</li>
<li>生成完<b>只弹一个结果窗</b>：顶上一条醒目状态带（全绿＝都成功，红色＝有问题），下面分区列出成功明细、生成失败、校验问题、移交清单情况，一屏看全，不用翻好几个窗口。</li>
<li>结果窗里点 <b>【打开输出目录】</b>，文件在"业务名_客户名_年月"文件夹里；点 <b>【下一单（清空）】</b>开始下一位。</li>
</ol>

<h2>界面配色：4 套主题随便换</h2>
<p>点顶部 <b>【设置】→ 常用 → 界面主题</b>，可选 <b>墨青（默认）、明亮、深空、护眼</b> 四套：久坐夜间推荐"深空"，白天眼睛敏感推荐"护眼"。<b>点确定立即生效</b>，所有窗口一起换，重启后仍保持你选的那套。</p>

<h2>一个人 / 一批人，两种用法</h2>
<table width="100%" cellspacing="0" cellpadding="8">
<tr><th width="26%">场景</th><th>怎么做</th></tr>
<tr><td><b>一个人、一份资料</b></td><td>按上面三步：粘贴 → 核对 → 一键生成。</td></tr>
<tr><td><b>一批人、资料分批到</b></td><td>点【批量填充】→【导入名单】选 Excel/CSV（第一行变量名，每行一个人）→ 用"状态：待补充"筛选、点【下一位待补充】逐人补 → 勾选后【生成选中文档】。</td></tr>
</table>
<div class="tip"><b>同单位只改姓名/证件号：</b>名单里右键某行 →【复制为新行】改两格即可；整列或选中行的相同内容用【批量设值…】，可选范围，默认跳过已生成行。</div>

<h2>生成完发现错了？看这里</h2>
<table width="100%" cellspacing="0" cellpadding="8">
<tr><th width="26%">遇到的问题</th><th>怎么做</th></tr>
<tr><td><b>数据填错了</b></td><td>点【历史数据…】选刚才那条 →【填入当前变量】，改完再生成。</td></tr>
<tr><td><b>编号不对 / 想跳号</b></td><td>看窗口左下角"下个编号"，点旁边【改编号…】直接输入下一次要用的号；默认只本次生效，要后面顺延去【设置 → 日期与编号】改成"同时改账本"。</td></tr>
<tr><td><b>移交清单没加上</b></td><td>结果窗红色区会写明。多半是清单正在 Excel 里开着：关掉 Excel 点结果窗【重试追加】即可，不用重新生成。</td></tr>
<tr><td><b>值好像填错了</b></td><td>变量校验默认开着，身份证位数/校验位、手机号格式这类错误会在确认框和结果窗指出，改完再生成。</td></tr>
</table>
<div class="warn"><b>注意：</b>【改编号…】只改"下一次生成"的号码，不会改已经生成的文件。</div>

<h2>常用开关（都在【设置】里，分 6 页，可滚动）</h2>
<ul>
<li><b>界面主题：</b>常用页第一项，4 套主题即时切换。</li>
<li><b>日期格式：</b>默认 <code>YYYY年M月D日</code>，输入 <code>20260101</code> 会写成"2026年1月1日"；【日期与编号】下方表格还能给单个变量（如"出生日期"）单独指定格式。</li>
<li><b>自动编号：</b>【配置自动编号…】勾选档案号/序号并填起始号；只有真生成文档时才 +1，不会断号。</li>
<li><b>打开与打印：</b>生成后自动打开全部/第一个/指定模板的文件，可设打印机、份数。</li>
<li><b>移交清单：</b>启用后每批按主键去重追加进同一张 Excel 台账，可指定自己的表头模板。</li>
<li><b>变量校验：</b>身份证/手机号/邮箱等开箱即用，默认开；也能写自己的正则规则。</li>
<li><b>批量填充 / 快捷键与数据：</b>多批次名单、批量设值、快捷键都在这里按需调整。</li>
<li><b>配置备份/恢复：</b>换电脑或升级前【导出配置包】，到新环境【导入配置包】，导入前自动备份当前配置。</li>
</ul>

<h2>模板怎么写（30 秒学会）</h2>
<p>在 Word 或 Excel 里，把要填的位置写成两个大括号加变量名：</p>
<pre>{{{{姓名}}}}    {{{{身份证号}}}}    {{{{手机号}}}}    {{{{申请日期}}}}</pre>
<table width="100%" cellspacing="0" cellpadding="6">
<tr><th>写法</th><th>意思</th></tr>
<tr><td><code>{{{{姓名}}}}</code></td><td>这里要填姓名（必填，空了会提醒）</td></tr>
<tr><td><code>{{{{备注?}}}}</code></td><td>可选字段，空着也能生成</td></tr>
<tr><td><code>${{姓名}}</code></td><td>另一种写法，效果一样</td></tr>
</table>
<div class="tip"><b>一个业务一个子文件夹。</b>同一业务下多个模板，同名变量只填一次。</div>

<h2>最容易卡住的 6 个问题</h2>
<table width="100%" cellspacing="0" cellpadding="6">
<tr><th width="38%">问题</th><th>怎么办</th></tr>
<tr><td>为什么文件夹是"未知客户"？</td><td>模板里没有客户名/姓名。填上，或【设置 → 客户名变量】选一个。</td></tr>
<tr><td>变量没被替换？</td><td>检查模板是不是写成 <code>{{{{变量名}}}}</code>；生成前提示的空变量也要补上。</td></tr>
<tr><td>备注为空也提示？</td><td>把模板里的 <code>{{{{备注}}}}</code> 改成 <code>{{{{备注?}}}}</code>，就成了可选字段。</td></tr>
<tr><td>总提示"冲突"？</td><td>同一字段两种叫法但值一样不会再算冲突；只有值真不一样才提示。若值跳到别的变量，检查【配置识别规则…】里是不是写了 <code>.*</code> 这种太宽的规则。</td></tr>
<tr><td>多人怎么粘贴？</td><td>每人一段、空行分隔，或用独占一行的 <code>---</code>；解析后逐人核对。</td></tr>
<tr><td>再导入一份名单，旧数据怎么混进来了？</td><td>默认新导入是<strong>新建批次</strong>，旧批次不动；顶部下拉可切回。要并入当前批次去【设置 → 批量填充】改。</td></tr>
</table>

<h2>记住这三句话</h2>
<div class="ok">
<b>1.</b> 模板和输出分开放。<br/>
<b>2.</b> 粘贴完先看黄色格子，缺了也能决定要不要继续生成。<br/>
<b>3.</b> 生成完点"下一单"。
</div>

<p class="small">作者 / 联系：daokunn · GitHub：github.com/daokunn/docfill<br/>
还是不会？把界面截图和 error.log 发到 GitHub Issues，我们会按这个教程继续改。</p>
"""

# 默认主题教程：兼容旧代码直接引用
TUTORIAL_HTML = build_tutorial_html(DEFAULT_THEME)
