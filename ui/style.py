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
<style>
body { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 11pt; color: #1f2937; line-height: 1.6; }
h1 { font-size: 22pt; color: #111827; margin-bottom: 4px; }
h2 { font-size: 15pt; color: #1d4ed8; margin-top: 22px; margin-bottom: 8px; }
p { margin: 6px 0; }
.lead { color: #4b5563; }
.small { color: #6b7280; font-size: 9pt; }
.tip { background: #eff6ff; border-left: 4px solid #2563eb; padding: 8px 10px; margin: 8px 0; }
.warn { background: #fff7ed; border-left: 4px solid #f59e0b; padding: 8px 10px; margin: 8px 0; }
.ok { background: #f0fdf4; border-left: 4px solid #16a34a; padding: 8px 10px; margin: 8px 0; }
code { background: #f3f4f6; color: #be123c; padding: 1px 4px; }
td { padding: 6px 10px; vertical-align: top; }
</style>

<h1>第一次用？看这三步就够了</h1>
<p class="lead">不用懂“变量”“正则”“OOXML”。你只要会三件事：<b>选文件夹、粘贴资料、点按钮</b>。</p>

<table width="100%" cellspacing="0" cellpadding="8">
<tr>
<td width="33%" style="background:#eff6ff; border:1px solid #bfdbfe;">
<b>① 选两个文件夹</b><br/>
<span class="small">模板在哪，结果放哪</span>
</td>
<td width="33%" style="background:#eff6ff; border:1px solid #bfdbfe;">
<b>② 粘贴客户资料</b><br/>
<span class="small">自动识别，不用手拆</span>
</td>
<td width="33%" style="background:#eff6ff; border:1px solid #bfdbfe;">
<b>③ 点“一键生成”</b><br/>
<span class="small">生成完直接下一单</span>
</td>
</tr>
</table>

<h2>第 1 步：告诉程序“模板在哪、结果放哪”</h2>
<p><b>模板文件夹</b>是放原始模板的总文件夹。它里面每个子文件夹代表一项业务，例如：</p>
<pre>模板文件夹/
├─ 公务卡申请/
│  ├─ 申请表.docx
│  └─ 信息登记表.xlsx
└─ 信用卡激活/
   └─ 激活申请表.docx</pre>

<ol>
<li>点 <b>【选择模板根目录】</b>，选“模板文件夹”。</li>
<li>点 <b>【选择输出根目录】</b>，选一个专门放结果的文件夹，例如 <code>D:/生成结果</code>。</li>
</ol>

<div class="warn"><b>注意：</b>输出目录不要选到模板文件夹里面，否则生成的文件会和模板混在一起。程序会拦住这种选择。</div>

<h2>第 2 步：把客户资料粘进来</h2>
<ol>
<li>在左边点一下要办的<b>业务名称</b>。</li>
<li>点蓝色的 <b>【智能粘贴解析】</b>（快捷键 Ctrl+Shift+V）。</li>
<li>把客户发来的整段文字粘进去，点 <b>【智能解析】</b>。</li>
<li>看下方提示，例如“模板覆盖 5/8；待填写：出生日期、备注”，就知道还缺什么。</li>
<li>核对无误后点 <b>【确认填充】</b>。</li>
</ol>

<div class="tip"><b>黄色格子 = 还没填。</b>双击“值”单元格就能改；不确定的值可以先空着，生成前程序会再提醒一次。</div>

<h2>第 3 步：核对、生成、下一单</h2>
<ol>
<li>回到主界面，看一眼变量表，把黄色格子补掉。</li>
<li>点绿色大按钮 <b>【一键生成文档】</b>（Ctrl+G）。</li>
<li>如果弹出“生成前检查”，核对输出目录、模板数量、空变量和“未知客户”；没问题就点“仍然生成”。</li>
<li>生成完成后点 <b>【打开输出目录】</b>，文件在“业务名_客户名_年月”文件夹里。</li>
<li>点 <b>【下一单（清空）】</b>，开始下一位客户。</li>
</ol>

<div class="ok"><b>小技巧：</b>同一个客户办多个业务时，先办好一个，再点“应用上次数据”，不用重复粘贴。</div>

<h2>两种用法：一个人 / 一批人</h2>
<table cellspacing="0" cellpadding="8" width="100%">
<tr style="background:#f9fafb;"><td width="24%"><b>场景</b></td><td><b>怎么做</b></td></tr>
<tr><td><b>一个人、一份资料</b></td><td>按上面三步：粘贴 → 核对 → 一键生成。</td></tr>
<tr><td><b>一批人、资料分批到</b></td><td>点【人员名单】→【导入名单】选 Excel/CSV（第一行变量名，每行一个人）→ 用“状态：待补充”筛选，点【下一位待补充】逐人补 → 勾选后【生成选中文档】。</td></tr>
</table>

<div class="tip"><b>同单位只改姓名/证件号：</b>在名单里右键某一行 →【复制为新行】，再改两个格子即可。整列相同的内容（单位、日期、金额）可在列头右键 →【整列填入同一值】。</div>

<h2>新功能：让批量更省事</h2>
<ul>
<li><b>自动编号（档案号/序号）：</b>【设置】→【配置自动编号…】勾选变量并填起始号。只有真正生成文档时才 +1，没出的文档不占号，所以不会断号。主界面变量表里该格会显示下一个号并锁定，不用手填。生成错了可在同一窗口【回收最后一个号】。</li>
<li><b>自动打开/打印：</b>【设置】→【打开与打印…】可设置生成后打开全部文件、第一个文件，或勾选一个/多个模板只打开它们产出的新文件；还能选打印机、打印份数、静默打印。文件会保持打开，不自动关闭。</li>
<li><b>移交清单：</b>【设置】里启用后，每批生成会按主键去重，追加进同一张 Excel 移交清单；也可以指定自己的《移交表》模板作为表头。</li>
<li><b>识别规则：</b>智能粘贴窗口里点【配置识别规则…】，为规则库没有的变量写正则；有语法校验、样本试打和冲突提示，规则存本机，升级不覆盖。</li>
</ul>


<h2>模板怎么写（30 秒学会）</h2>
<p>在 Word 或 Excel 里，把要填的位置写成两个大括号加变量名：</p>
<pre>{{姓名}}    {{身份证号}}    {{手机号}}    {{申请日期}}</pre>

<table cellspacing="0" cellpadding="6" width="100%">
<tr style="background:#f9fafb;">
<td><b>写法</b></td><td><b>意思</b></td></tr>
<tr><td><code>{{姓名}}</code></td><td>这里要填姓名</td></tr>
<tr><td><code>{{备注?}}</code></td><td>可选字段，空着也能生成</td></tr>
<tr><td><code>${姓名}</code></td><td>另一种写法，效果一样</td></tr>
</table>

<div class="tip"><b>一个业务一个子文件夹。</b>同一个业务下的多个模板，同名变量只需要填一次。</div>

<h2>常用设置（设置窗口可上下滚动）</h2>
<ul>
<li><b>日期格式：</b>默认 <code>YYYY年M月D日</code>，输入 <code>20260101</code> 会生成“2026年1月1日”；也可以改成 <code>YYYY-MM-DD</code>。</li>
<li><b>自动编号：</b>【配置自动编号…】勾选档案号/序号并填起始号；格式随意，只把最后一段数字 +1。</li>
<li><b>打开与打印：</b>生成后自动打开全部/第一个/指定模板的文件，可设打印机、份数、静默打印。</li>
<li><b>移交清单：</b>启用后每批自动追加进 Excel 台账，可指定自己的汇总模板。</li>
<li><b>变量表排序：</b>默认按模板出现顺序；也可以切换为字典顺序。</li>
<li><b>客户名变量：</b>默认按“客户名 → 姓名 → 单位”自动找，避免“未知客户”。</li>
<li><b>溢出缩字号：</b>默认开启；只在内容比占位符长、必然多占行时缩小该格字号（最多到 70%），尽量保住页数。</li>
</ul>

<h2>最容易卡住的 6 个问题</h2>
<table cellspacing="0" cellpadding="6" width="100%">
<tr style="background:#f9fafb;"><td width="36%"><b>问题</b></td><td><b>怎么办</b></td></tr>
<tr><td>为什么文件夹是“未知客户”？</td><td>模板里没有客户名/姓名。填上姓名，或在【设置】→ 客户名变量里选一个。</td></tr>
<tr><td>变量没被替换？</td><td>检查模板里是不是写成 <code>{{变量名}}</code>；生成前提示的空变量也要补上。</td></tr>
<tr><td>备注为空也提示？</td><td>把模板里的 <code>{{备注}}</code> 改成 <code>{{备注?}}</code>，它就变成可选字段。</td></tr>
<tr><td>多人怎么粘贴？</td><td>每人一段，用空行分隔；或用独占一行的 <code>---</code>。解析后可以逐人核对。</td></tr>
<tr><td>CSV 导入乱码？</td><td>直接选 Excel 导出的 CSV 即可，程序会自动识别 UTF-8 / GBK，并先预览。</td></tr>
<tr><td>双击 exe 没反应？</td><td>首次启动要解压几秒，请稍等；仍失败就看同目录的 <code>error.log</code>。</td></tr>
</table>

<h2>记住这三句话</h2>
<div class="ok">
<b>1.</b> 模板和输出分开放。<br/>
<b>2.</b> 粘贴完先看黄色格子。<br/>
<b>3.</b> 生成完点“下一单”。
</div>

<p class="small">作者 / 联系：daokunn · GitHub：github.com/daokunn/docfill<br/>
还是不会？把界面截图和 error.log 发到 GitHub Issues，我们会按这个教程继续改。</p>
"""
