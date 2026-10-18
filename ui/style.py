"""
全局界面样式（QSS）+ 使用教程内容
职责：
  1. 提供现代化浅色主题样式表 APP_STYLE，主窗口统一 setStyleSheet
  2. 提供使用教程 HTML（TUTORIAL_HTML），供"使用教程"按钮弹窗展示
  3. 不依赖任何业务逻辑
"""

# ---------- 全局样式表 ----------
# 设计语言：浅色背景 + 白色卡片 + 蓝色主色调 + 圆角控件
APP_STYLE = """
QWidget {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
    font-size: 10pt;
    color: #1f2937;
}
QMainWindow, QDialog { background: #f3f4f6; }

/* 卡片式分组框 */
QGroupBox {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 12px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #374151;
}

/* 按钮：默认白底，悬停变蓝 */
QPushButton {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background: #eff6ff; border-color: #2563eb; color: #2563eb; }
QPushButton:pressed { background: #dbeafe; }
QPushButton:disabled { color: #9ca3af; background: #f3f4f6; }

/* 一键生成：绿色大按钮 */
QPushButton#generate {
    background: #16a34a;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-size: 14pt;
    font-weight: bold;
    padding: 12px;
}
QPushButton#generate:hover { background: #15803d; color: #ffffff; }
QPushButton#generate:pressed { background: #166534; color: #ffffff; }

/* 智能粘贴：蓝色强调按钮 */
QPushButton#primary {
    background: #2563eb;
    color: #ffffff;
    border: none;
    font-weight: bold;
}
QPushButton#primary:hover { background: #1d4ed8; color: #ffffff; }
QPushButton#primary:pressed { background: #1e40af; color: #ffffff; }

/* 输入类控件统一白底圆角 */
QListWidget, QTableWidget, QTextEdit, QLineEdit, QComboBox {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    padding: 4px;
}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border-color: #2563eb; }

/* 业务列表 */
QListWidget::item { padding: 8px 10px; border-radius: 4px; }
QListWidget::item:selected { background: #2563eb; color: #ffffff; }
QListWidget::item:hover:!selected { background: #eff6ff; }

/* 表格 */
QTableWidget { gridline-color: #e5e7eb; }
QTableWidget::item { padding: 4px; }
QTableWidget::item:selected { background: #dbeafe; color: #1f2937; }
QHeaderView::section {
    background: #f9fafb;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    padding: 8px 6px;
    font-weight: bold;
    color: #374151;
}

/* 日志区：等宽 + 浅灰底 */
QTextEdit#log {
    background: #f9fafb;
    font-family: "Consolas", "Microsoft YaHei UI";
    font-size: 9pt;
    color: #4b5563;
}

/* 下拉框 */
QComboBox { padding: 5px 8px; }
QComboBox QAbstractItemView { selection-background-color: #2563eb; }

/* 分割条 */
QSplitter::handle { background: #e5e7eb; }
QSplitter::handle:horizontal { width: 3px; }

/* 标签透明底，避免遮住卡片背景 */
QLabel { background: transparent; }

/* 弹窗按钮盒 */
QDialogButtonBox QPushButton { min-width: 70px; }
"""


# ---------- 使用教程（HTML，富文本展示） ----------
TUTORIAL_HTML = """
<h2>使用教程</h2>
<p><b>整体流程：</b>设置目录 → 选择业务 → 粘贴/填写变量 → 一键生成</p>

<h3>一、首次使用（只需设置一次）</h3>
<ol>
<li>点击 <b>【选择模板根目录】</b>，选择存放模板的总文件夹（每类业务一个子文件夹）。</li>
<li>点击 <b>【选择输出根目录】</b>，选择生成文档的保存位置。</li>
</ol>

<h3>二、制作模板（重要）</h3>
<ul>
<li>在 Word（.docx）或 Excel（.xlsx）中，把需要填写的位置写成 <b>{{变量名}}</b>，例如：<code>{{姓名}}</code>、<code>{{身份证号}}</code>、<code>{{日期}}</code>。</li>
<li>可选变量写成 <b>{{变量名?}}</b>，例如 <code>{{备注?}}</code>；为空时不会阻止生成。</li>
<li>把同类模板放进模板根目录下的<b>同一个子文件夹</b>，子文件夹名就是"业务名"。</li>
<li>支持 .docx / .xlsx / .wps / .et（新版 WPS 格式）。</li>
</ul>

<h3>三、日常使用（10 秒完成一单）</h3>
<ol>
<li>左侧点击<b>业务名称</b>，右侧自动列出该业务所有变量；默认按模板填写顺序排列。</li>
<li>点击 <b>【智能粘贴解析】</b>（快捷键 Ctrl+Shift+V），把客户发来的原始文本整段粘贴进去，程序自动识别姓名、身份证号、手机号、地址、日期等字段，并提示模板还缺哪些变量。</li>
<li>核对右侧变量表，<b>双击单元格</b>可修改；黄色背景表示还没填。</li>
<li>点击 <b>【一键生成文档】</b>（快捷键 Ctrl+G）。生成前会检查空变量和“未知客户”，确认后完成；生成后可直接“打开输出目录”。</li>
<li>点击 <b>【下一单（清空）】</b> 开始下一位客户，或在【设置】中开启生成后自动清空。</li>
</ol>

<h3>四、批量生成（一次多人）</h3>
<p>在智能粘贴窗口中粘贴多人信息，每人一段，用空行分隔，或用独占一行的 <b>---</b> / <b>===</b> 分隔。程序会识别为多人模式，逐人生成各自的文档。每个人使用独立变量，不会带入上一位客户的数据。</p>

<h3>五、实用功能</h3>
<ul>
<li><b>日期格式</b>：在【设置】→ 日期格式中选择，例如 <b>YYYY年M月D日</b> 会输出“2026年1月1日”；起止时间会自动按同一格式填充。</li>
<li><b>变量排序</b>：默认按模板填写顺序；可在【设置】中切换为字典顺序。</li>
<li><b>应用上次数据</b>（Ctrl+R）：同一位客户办理多个业务时，一键复用上次内容；数据保存在本机，重启后仍可用，可在设置里清除。</li>
<li><b>统一变量名</b>：不同模板里“客户名称/客户名/姓名”写法不一致时，统一为标准变量名；修改前会自动备份，可点“撤销上次统一”恢复。</li>
<li><b>CSV导入</b>：自动识别 UTF-8 / GBK，导入前预览、可选表头；支持导出 CSV 模板。</li>
<li><b>整列粘贴</b>：从 Excel 复制一列值，在变量表选中起始行后 Ctrl+V，可批量填入。</li>
<li><b>重名策略</b>：同一客户重复生成时，可选“追加序号 / 覆盖 / 跳过”。</li>
<li><b>刷新业务列表</b>（F5）：模板文件夹有变动后重新扫描。</li>
</ul>

<h3>六、快捷键</h3>
<table border="0" cellpadding="4">
<tr><td><b>Ctrl+Shift+V</b></td><td>智能粘贴解析</td></tr>
<tr><td><b>Ctrl+G</b></td><td>一键生成文档</td></tr>
<tr><td><b>Ctrl+R</b></td><td>应用上次数据</td></tr>
<tr><td><b>F5</b></td><td>刷新业务列表</td></tr>
</table>
<p>快捷键可在 <b>【设置】</b> 中自定义。</p>

<h3>七、常见问题</h3>
<ul>
<li><b>生成的文件去哪了？</b>输出根目录下的“业务名_客户名_年月”子文件夹中；客户名会按“客户名 → 姓名 → 单位”自动兜底。</li>
<li><b>为什么是“未知客户”？</b>说明没有取到客户名。请确认模板里有 {{客户名}} 或 {{姓名}}，或在【设置】→ 输出命名中选择客户名变量。</li>
<li><b>变量没被替换？</b>检查模板中的 {{变量名}} 左右大括号是否完整、变量名是否与表中的一致；生成前的检查提示也会列出空变量。</li>
<li><b>备注为空也被提示？</b>把模板里的 {{备注}} 改成 {{备注?}}，它就会作为可选变量，不再阻止生成。</li>
<li><b>识别不准确？</b>粘贴文本尽量一行一项（如"姓名：张三"），识别率最高。</li>
<li><b>打不开/闪退？</b>查看程序同目录的 error.log；仍无法解决时，请在 GitHub Issues 中反馈。</li>
</ul>
"""
