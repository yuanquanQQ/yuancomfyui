from fpdf import FPDF
from pathlib import Path
import datetime

# 配置
BASE_DIR = Path(__file__).parent
SCREENSHOT_DIR = BASE_DIR / "screenshots"
OUTPUT_PDF = BASE_DIR / "YunComfyUI网页版设计方案.pdf"

# 中文字体路径 (Windows 微软雅黑)
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD_PATH = "C:/Windows/Fonts/msyhbd.ttc"

class PDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("msyh", "", 10)
            self.set_text_color(120, 120, 120)
            self.cell(0, 10, "YunComfyUI 网页版设计方案", 0, 0, "L")
            self.cell(0, 10, f"第 {self.page_no()} 页", 0, 0, "R")
            self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font("msyh", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"© {datetime.datetime.now().year} YunComfyUI", 0, 0, "C")

    def chapter_title(self, title, level=1):
        if level == 1:
            self.set_font("msyh", "B", 18)
            self.set_text_color(19, 121, 91)
            self.ln(10)
        elif level == 2:
            self.set_font("msyh", "B", 14)
            self.set_text_color(30, 41, 59)
            self.ln(8)
        elif level == 3:
            self.set_font("msyh", "B", 12)
            self.set_text_color(51, 65, 85)
            self.ln(5)
        self.cell(0, 10, title, 0, 1)
        self.set_draw_color(19, 121, 91)
        if level == 1:
            self.line(self.l_margin, self.get_y(), self.l_margin + 30, self.get_y())
            self.ln(5)

    def body_text(self, text):
        self.set_font("msyh", "", 11)
        self.set_text_color(51, 65, 85)
        self.multi_cell(0, 7, text)
        self.ln(3)

    def bullet_list(self, items):
        self.set_font("msyh", "", 11)
        self.set_text_color(51, 65, 85)
        bullet_w = 5
        for item in items:
            x = self.l_margin
            self.set_x(x)
            self.cell(bullet_w, 7, "•", new_x="RIGHT", new_y="TOP")
            w = self.w - self.r_margin - (x + bullet_w)
            self.multi_cell(w, 7, item, new_x="LMARGIN", new_y="NEXT")
        self.ln(3)

    def add_screenshot(self, image_path, caption):
        self.set_font("msyh", "", 10)
        self.set_text_color(100, 116, 139)
        # 计算图片尺寸，保持比例
        from PIL import Image
        with Image.open(image_path) as img:
            w, h = img.size
        max_w = self.w - self.l_margin - self.r_margin
        scale = max_w / w
        img_w = max_w
        img_h = h * scale
        if img_h > 240:
            scale = 240 / h
            img_h = 240
            img_w = w * scale
        x = (self.w - img_w) / 2
        self.image(str(image_path), x=x, w=img_w, h=img_h)
        self.ln(2)
        self.cell(0, 6, caption, 0, 1, "C")
        self.ln(8)

# 创建PDF
pdf = PDF(orientation="P", unit="mm", format="A4")
pdf.add_font("msyh", "", FONT_PATH)
pdf.add_font("msyh", "B", FONT_BOLD_PATH)
pdf.set_auto_page_break(auto=True, margin=20)

# ========== 封面 ==========
pdf.add_page()
pdf.ln(60)
pdf.set_font("msyh", "B", 32)
pdf.set_text_color(19, 121, 91)
pdf.cell(0, 20, "YunComfyUI", 0, 1, "C")
pdf.set_font("msyh", "B", 24)
pdf.set_text_color(30, 41, 59)
pdf.cell(0, 15, "网页版设计方案", 0, 1, "C")
pdf.ln(20)
pdf.set_font("msyh", "", 14)
pdf.set_text_color(100, 116, 139)
pdf.cell(0, 10, "支持移动端响应式设计", 0, 1, "C")
pdf.ln(80)
pdf.set_font("msyh", "", 12)
pdf.cell(0, 10, f"版本：v1.0", 0, 1, "C")
pdf.cell(0, 10, f"日期：{datetime.datetime.now().strftime('%Y年%m月%d日')}", 0, 1, "C")

# ========== 目录 ==========
pdf.add_page()
pdf.chapter_title("目录")
pdf.set_font("msyh", "", 12)
pdf.set_text_color(51, 65, 85)
toc = [
    "一、设计概述 ..................................................... 3",
    "二、方案一：轻量快用版 ........................................... 4",
    "三、方案二：专业工作台版 ......................................... 7",
    "四、方案三：沉浸式创作版 ........................................ 10",
    "五、方案对比与推荐 .............................................. 13",
]
for item in toc:
    pdf.cell(0, 10, item, 0, 1)

# ========== 设计概述 ==========
pdf.add_page()
pdf.chapter_title("一、设计概述")
pdf.body_text("本次设计为YunComfyUI云端AI创作工作台网页版本，核心目标是实现全平台适配，尤其是在手机移动端也能流畅完成创作流程。三个方案分别面向不同用户群体和使用场景，均满足响应式适配要求，在桌面、平板、手机端都能提供良好体验。")
pdf.chapter_title("设计目标", level=2)
pdf.bullet_list([
    "移动端优先：核心操作支持单手完成，适配手机触控交互",
    "功能对齐：完整覆盖现有桌面客户端所有核心能力",
    "性能优先：页面加载快，操作流畅，弱网环境可用",
    "体验一致：和现有客户端品牌视觉、操作逻辑保持连贯性",
])
pdf.chapter_title("适配范围", level=2)
pdf.bullet_list([
    "桌面端：1920×1080及以上分辨率，鼠标键盘交互",
    "平板端：7-13英寸屏幕，触控+键盘可选",
    "移动端：360-430px宽度手机屏幕，单手触控操作",
])

# ========== 方案一：轻量快用版 ==========
pdf.add_page()
pdf.chapter_title("二、方案一：轻量快用版")
pdf.chapter_title("方案定位", level=2)
pdf.body_text("面向普通用户和轻度创作者，以“快速生成”为核心目标，简化操作流程，降低使用门槛。用户打开即可快速选择常用功能，一键生成作品，适合手机端快速出图、碎片化时间使用场景。")
pdf.chapter_title("核心特性", level=2)
pdf.bullet_list([
    "极简首页设计：常用工作流直接展示在首页，1次点击即可进入生成页",
    "底部导航设计：移动端四个核心入口（首页/工作流/作品/我的），拇指可轻松触达",
    "大按钮大控件：所有操作按钮最小高度42px，适合触控点击",
    "进度可视化：任务进度实时展示，推送通知提醒完成",
    "桌面端自适应：卡片式布局，保持轻量简洁的视觉风格",
])
pdf.chapter_title("桌面端预览", level=2)
pdf.add_screenshot(SCREENSHOT_DIR / "方案1-轻量快用版-desktop.png", "图1：轻量快用版 桌面端效果")
pdf.chapter_title("移动端预览", level=2)
pdf.add_screenshot(SCREENSHOT_DIR / "方案1-轻量快用版-mobile.png", "图2：轻量快用版 移动端效果")
pdf.chapter_title("适用场景", level=2)
pdf.bullet_list([
    "C端普通用户，对AI创作不熟悉的新手用户",
    "需要快速生成简单作品，不需要复杂参数调整",
    "移动端使用为主，碎片化时间创作",
    "小程序、H5轻量版本首选方案",
])

# ========== 方案二：专业工作台版 ==========
pdf.add_page()
pdf.chapter_title("三、方案二：专业工作台版")
pdf.chapter_title("方案定位", level=2)
pdf.body_text("面向专业创作者和付费用户，完整复刻现有桌面客户端全部功能，三栏布局信息密度高，支持多任务管理、批量生成、素材库管理等专业功能，兼顾桌面端高效操作和移动端可用。")
pdf.chapter_title("核心特性", level=2)
pdf.bullet_list([
    "经典三栏布局：左侧工作流选择、中间参数配置、右侧状态面板，和现有客户端操作一致",
    "完整功能支持：批量生成、多账号调度、素材库管理、任务队列全功能保留",
    "响应式自适应：桌面三栏，平板两栏，移动端底部导航+抽屉菜单",
    "高信息密度：专业用户需要的参数、状态信息完整展示，减少页面跳转",
    "学习成本低：和现有Windows客户端操作逻辑完全一致，老用户零成本上手",
])
pdf.chapter_title("桌面端预览", level=2)
pdf.add_screenshot(SCREENSHOT_DIR / "方案2-专业工作台版-desktop.png", "图3：专业工作台版 桌面端效果")
pdf.chapter_title("移动端预览", level=2)
pdf.add_screenshot(SCREENSHOT_DIR / "方案2-专业工作台版-mobile.png", "图4：专业工作台版 移动端效果")
pdf.chapter_title("适用场景", level=2)
pdf.bullet_list([
    "专业付费用户，需要使用批量生成、多任务等高级功能",
    "现有Windows客户端用户平滑迁移到网页版",
    "桌面端使用为主，偶尔需要移动端查看任务进度",
    "企业用户、工作室批量生产场景",
])

# ========== 方案三：沉浸式创作版 ==========
pdf.add_page()
pdf.chapter_title("四、方案三：沉浸式创作版")
pdf.chapter_title("方案定位", level=2)
pdf.body_text("面向重度创作者和设计师群体，采用深色主题设计，最大化预览区域，减少UI干扰，让用户专注于创作本身。支持实时预览、版本对比、参数快速调整，适合长时间创作场景。")
pdf.chapter_title("核心特性", level=2)
pdf.bullet_list([
    "深色主题设计：减少长时间使用的视觉疲劳，色彩显示更准确",
    "大预览区设计：左侧70%区域为画布预览，右侧30%为参数面板，沉浸式体验",
    "快速风格预设：一键切换常用风格，提示词模板快速插入",
    "版本历史回溯：最近生成结果缩略图展示，一键复用参数重新生成",
    "毛玻璃质感：现代UI设计风格，视觉效果精致",
    "梯度按钮和边框：视觉层次分明，交互反馈清晰",
])
pdf.chapter_title("桌面端预览", level=2)
pdf.add_screenshot(SCREENSHOT_DIR / "方案3-沉浸式创作版-desktop.png", "图5：沉浸式创作版 桌面端效果")
pdf.chapter_title("移动端预览", level=2)
pdf.add_screenshot(SCREENSHOT_DIR / "方案3-沉浸式创作版-mobile.png", "图6：沉浸式创作版 移动端效果")
pdf.chapter_title("适用场景", level=2)
pdf.bullet_list([
    "设计师、艺术家等重度创作者，长时间使用软件",
    "对视觉效果和创作体验要求高的用户",
    "需要反复调整参数、对比生成结果的场景",
    "面向年轻用户群体的C端产品，追求时尚设计感",
])

# ========== 方案对比与推荐 ==========
pdf.add_page()
pdf.chapter_title("五、方案对比与推荐")
pdf.chapter_title("方案对比表", level=2)

# 对比表格
pdf.set_font("msyh", "B", 10)
pdf.set_fill_color(248, 250, 252)
pdf.set_draw_color(226, 232, 240)
# 表头
pdf.cell(35, 10, "对比维度", 1, 0, "C", fill=True)
pdf.cell(50, 10, "方案一：轻量快用版", 1, 0, "C", fill=True)
pdf.cell(50, 10, "方案二：专业工作台版", 1, 0, "C", fill=True)
pdf.cell(50, 10, "方案三：沉浸式创作版", 1, 1, "C", fill=True)

# 表格内容
pdf.set_font("msyh", "", 9)
rows = [
    ["适用人群", "新手/普通用户", "专业/老用户", "重度创作者/设计师"],
    ["移动端体验", "★★★★★ 极佳", "★★★★☆ 良好", "★★★★☆ 良好"],
    ["桌面端体验", "★★★☆☆ 一般", "★★★★★ 极佳", "★★★★★ 极佳"],
    ["功能完整度", "★★★☆☆ 核心功能", "★★★★★ 全功能", "★★★★☆ 创作为主"],
    ["开发复杂度", "低 (2-3周)", "中 (4-6周)", "中高 (5-7周)"],
    ["学习成本", "极低", "低(和客户端一致)", "中等"],
    ["视觉风格", "清新简洁", "专业稳重", "时尚酷炫"],
]
for row in rows:
    pdf.cell(35, 8, row[0], 1, 0, "C")
    pdf.cell(50, 8, row[1], 1, 0, "C")
    pdf.cell(50, 8, row[2], 1, 0, "C")
    pdf.cell(50, 8, row[3], 1, 1, "C")

pdf.ln(10)
pdf.chapter_title("推荐建议", level=2)
pdf.body_text("根据YunComfyUI当前的用户结构和产品定位，推荐选择以下两种路线之一：")
pdf.bullet_list([
    "推荐路线1（渐进式）：先实施方案一轻量快用版作为移动端H5入口，覆盖普通用户快速生成需求；后续实施方案二专业工作台版作为桌面端主站，满足专业用户需求，两个版本共享后端API。",
    "推荐路线2（统一版本）：直接实施方案二专业工作台版，虽然移动端不是最优体验，但可以一次性覆盖所有用户需求，开发量最可控，后续再逐步优化移动端交互体验。",
    "如果产品面向年轻用户群体、主打C端创作社区，推荐实施方案三沉浸式创作版，差异化视觉体验更容易获得用户好感。",
])
pdf.ln(20)
pdf.set_font("msyh", "", 10)
pdf.set_text_color(100, 116, 139)
pdf.cell(0, 10, "—— 文档结束 ——", 0, 1, "C")

# 保存PDF
pdf.output(OUTPUT_PDF)
print(f"PDF已生成: {OUTPUT_PDF}")
