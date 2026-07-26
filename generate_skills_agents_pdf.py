"""產生「技能與代理人清單.pdf」——彙整**所有層級**的 Claude Code 技能（Skills）與代理人
（Agents）成單一表格：系統內建（Claude Code 對話環境的通用子代理人類型，跟本機/本專案內容
無關，層級代號1）、使用者層級（`~/.claude/skills/`／`~/.claude/agents/`，跨專案通用，層級
代號2）、專案層級（本專案 `.claude/skills/`，機器可讀，自動掃描，層級代號3）。層級代號依
使用者指定的順序（系統內建=1、使用者層級=2、專案層級=3）排序、由小到大列出。

跟 `generate_skills_doc.py`（技能清單.docx）是兩份獨立文件：那份只收錄專案技能、輸出 docx；
這份涵蓋全部三種層級、輸出 PDF，多了「層級」「類型」「涵蓋技能」欄位。PDF 排版比照
`pdf_report.py` 的做法——直接用 reportlab platypus 繪製＋標楷體，不透過 xhtml2pdf（已知會讓
中文整段變成缺字方框）。

**技能與代理人是兩種不同機制，用「類型」欄位區分**：技能（Skill）是用 `/名稱` 斜線指令觸發、
在主對話中依 SKILL.md 指示執行的固定流程；代理人（Agent）是透過 Agent 工具背景執行、有自己
獨立上下文的子任務執行者，沒有固定的斜線指令觸發詞。「涵蓋技能」欄位說明**代理人**的行為是否
建立在特定技能已驗證過的規則之上（例如 `yt-download-sync` 這個自訂代理人會先讀取
`rename-music-files`／`audio-normalize` 兩份 SKILL.md 沿用其命名/音量正規化規則，不是重新
發明一套）；技能本身不會涵蓋其他技能，這欄一律「－」。

**使用者層級／系統內建這兩塊是手動維護的**：`~/.claude/skills/`／`~/.claude/agents/` 不在
本專案目錄下，沒辦法像專案層級一樣自動掃描 SKILL.md；系統內建的子代理人類型也不是檔案，
沒有地方可以動態讀取。之後新增/修改技能或代理人，記得回頭手動同步 `USER_SKILLS`／
`USER_AGENTS`／`BUILTIN_AGENTS` 這三份清單。
"""

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

PROJECT_SKILLS_DIR = Path(__file__).parent / ".claude" / "skills"
OUTPUT_PATH = Path(__file__).parent / "技能與代理人清單.pdf"

FONT_NAME = "KaiU"
FONT_PATH = r"C:\Windows\Fonts\kaiu.ttf"
BASE_FONT_SIZE = 14

if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
    pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_NAME, italic=FONT_NAME, boldItalic=FONT_NAME)

STYLE_TITLE = ParagraphStyle("title", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE + 8, leading=BASE_FONT_SIZE + 12, spaceAfter=8)
STYLE_SMALL = ParagraphStyle("small", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE - 4, leading=BASE_FONT_SIZE, textColor=colors.grey, spaceAfter=10)
STYLE_CELL = ParagraphStyle("cell", fontName=FONT_NAME, fontSize=9, leading=12)
STYLE_HEAD = ParagraphStyle("head", fontName=FONT_NAME, fontSize=10, leading=12.5, textColor=colors.white)

TABLE_HEAD_BG = colors.HexColor("#1a3d6d")
TABLE_GRID = colors.HexColor("#bbbbbb")

# 層級代號：依使用者指定順序（系統內建=1、使用者層級=2、專案層級=3），由小到大排列。
LEVEL_CODE = {"系統內建": 1, "使用者層級": 2, "專案層級": 3}
LEVEL_BG = {
    "系統內建": colors.HexColor("#f1f1f1"),
    "使用者層級": colors.HexColor("#fef6e0"),
    "專案層級": colors.HexColor("#eaf2fb"),
}

MODEL_LABEL = {
    "haiku": "haiku（機械式操作）",
    "sonnet": "sonnet（中等複雜度）",
    "opus": "opus（複雜診斷推理）",
}

NOT_APPLICABLE = "－"

COLUMNS = ["層級", "類型", "名稱", "代號", "使用模型", "功能", "涵蓋技能", "關鍵字/提示詞"]
COL_WIDTHS = [1.9 * cm, 1.6 * cm, 2.6 * cm, 2.9 * cm, 2.2 * cm, 6.0 * cm, 2.9 * cm, 7.0 * cm]

# ── 使用者層級：~/.claude/skills/ 下的 5 個技能（跨專案通用，非 Stock_investment 專屬） ──────
# 這幾個技能的 SKILL.md 都沒有指定 model（沿用當前對話模型），跟本專案 CLAUDE.md
# 「一律指定 model」的規範不同──那條規範只針對本專案 `.claude/skills/`。
USER_SKILLS = [
    {
        "type": "技能", "name": "audio-normalize", "code": "/audio-normalize",
        "model_label": "inherit（未指定，沿用當前對話模型）",
        "function": "用 ffmpeg loudnorm(EBU R128) 將資料夾內所有影音檔音量正規化到一致水準，預設 -14 LUFS／-1.5 dBTP。",
        "covers": NOT_APPLICABLE,
        "keywords": "音量正規化、統一音量、調整音量到適中、音量太大聲太小聲不一致、批次調整音量",
    },
    {
        "type": "技能", "name": "rename-music-files", "code": "/rename-music-files",
        "model_label": "inherit（未指定，沿用當前對話模型）",
        "function": "將資料夾內從 YouTube(yt-dlp) 下載、命名雜亂的音樂/MV 檔案，批次改名為「歌手_歌曲名稱_[YouTube影片ID]」格式。",
        "covers": NOT_APPLICABLE,
        "keywords": "整理音樂檔名、改成歌手_歌曲名稱格式、批次重新命名音樂檔、檔名太亂幫我整理",
    },
    {
        "type": "技能", "name": "spec-doc", "code": "/spec-doc",
        "model_label": "inherit（未指定，沿用當前對話模型）",
        "function": "依公司 ERP 部門功能規格書範本樣式（標楷體、灰底表格、Heading 編號標題）產生 .docx 規格書。",
        "covers": NOT_APPLICABLE,
        "keywords": "製作規格書、規格書格式、像 XX 規格書那樣",
    },
    {
        "type": "技能", "name": "sync-download", "code": "/sync-download",
        "model_label": "inherit（未指定，沿用當前對話模型）",
        "function": "將 Git 遠端最新內容同步回本機（檢查本機是否乾淨→fetch→pull），本機有未 commit 變更則中止提醒。",
        "covers": NOT_APPLICABLE,
        "keywords": "同步下載",
    },
    {
        "type": "技能", "name": "sync-upload", "code": "/sync-upload",
        "model_label": "inherit（未指定，沿用當前對話模型）",
        "function": "本機變更上傳至 Git 遠端（add -A→自動產生繁中 commit 訊息→commit→push 到目前分支 upstream）。",
        "covers": NOT_APPLICABLE,
        "keywords": "同步上傳",
    },
]

# ── 使用者層級：~/.claude/agents/ 下的自訂代理人 ─────────────────────────────
USER_AGENTS = [
    {
        "type": "代理人", "name": "yt-download-sync",
        "code": "yt-download-sync（尚非正式 Agent 類型，目前由通用代理人代讀定義檔執行）",
        "model_label": "sonnet",
        "function": "給一個 YouTube 網址：下載影片→依「歌手_歌曲名稱_[YouTube影片ID]」規則命名"
                    "（無法可靠辨識時保留原標題，不亂猜）→音量正規化到一致水準（預設 -14 LUFS）。"
                    "只處理該次下載的單一檔案，不動資料夾內其他既有檔案。",
        "covers": "rename-music-files、audio-normalize（執行前會先讀取這兩份 SKILL.md，"
                  "沿用其已驗證過的命名/音量正規化規則，不是重新發明一套）",
        "keywords": "下載這個YouTube網址、幫我抓這首歌（並要求命名＋音量正規化）",
    },
]

# ── 系統內建：Claude Code 對話環境可呼叫的通用子代理人類型，跟本機/本專案內容無關 ──────────
BUILTIN_AGENTS = [
    {
        "type": "代理人", "name": "通用代理人", "code": "claude", "model_label": "（依環境設定，非本文件範疇）",
        "function": "沒有指定特定代理人類型時的預設代理人，可使用所有工具，處理不屬於其他專用代理人的任務。",
        "covers": NOT_APPLICABLE + "（通用工具能力，不建立在特定技能之上）",
        "keywords": "FleetView 未輸入代理人名稱時的預設；「隨便找個代理人做」",
    },
    {
        "type": "代理人", "name": "Claude Code 使用說明代理人", "code": "claude-code-guide", "model_label": "（依環境設定，非本文件範疇）",
        "function": "回答 Claude Code CLI、Claude Agent SDK、Claude API（Messages API/Tool Runner）、Claude Tag（Slack）相關問題。",
        "covers": NOT_APPLICABLE + "（通用工具能力，不建立在特定技能之上）",
        "keywords": "「Claude Code能不能…」「怎麼設定 hook」「MCP伺服器是什麼」「/install-slack-app怎麼用」",
    },
    {
        "type": "代理人", "name": "程式碼探索代理人", "code": "Explore", "model_label": "（依環境設定，非本文件範疇）",
        "function": "唯讀、快速定位程式碼：依模式找檔案、grep 關鍵字或符號、回答「X在哪裡定義／哪些檔案引用了Y」。",
        "covers": NOT_APPLICABLE + "（通用工具能力，不建立在特定技能之上）",
        "keywords": "「幫我找一下…在哪裡」「這個function在哪個檔案」「搜尋所有用到…的地方」",
    },
    {
        "type": "代理人", "name": "通用型任務代理人", "code": "general-purpose", "model_label": "（依環境設定，非本文件範疇）",
        "function": "研究複雜問題、搜尋程式碼、執行多步驟任務；不確定能不能一次找到正確結果時使用。",
        "covers": NOT_APPLICABLE + "（通用工具能力，不建立在特定技能之上）",
        "keywords": "「幫我研究一下…」「不確定要去哪裡找，你去查」「這個牽涉很多檔案，你去看」",
    },
    {
        "type": "代理人", "name": "軟體架構規劃代理人", "code": "Plan", "model_label": "（依環境設定，非本文件範疇）",
        "function": "設計實作策略：回傳步驟化計畫、指出關鍵檔案、討論架構取捨，不直接寫程式碼。",
        "covers": NOT_APPLICABLE + "（通用工具能力，不建立在特定技能之上）",
        "keywords": "「幫我規劃一下怎麼做」「這個功能該怎麼設計」「先不要動手，想一下架構」",
    },
    {
        "type": "代理人", "name": "狀態列設定代理人", "code": "statusline-setup", "model_label": "（依環境設定，非本文件範疇）",
        "function": "設定使用者 Claude Code 的狀態列（status line）顯示內容。",
        "covers": NOT_APPLICABLE + "（通用工具能力，不建立在特定技能之上）",
        "keywords": "「幫我設定狀態列」「status line 想顯示…」",
    },
]


def _parse_project_skill(path: Path) -> dict:
    """自動掃描本專案 `.claude/skills/*/SKILL.md`（跟 `generate_skills_doc.py` 相同的解析邏輯），
    這是唯一有機器可讀來源、可以自動同步的層級。"""
    text = path.read_text(encoding="utf-8")
    front_match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    front = front_match.group(1)

    fields = {}
    for line in front.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()

    description = fields.get("description", "")
    keywords = re.findall(r"「(.*?)」", description)
    function = re.sub(r"^當使用者說(「.*?」)+時，", "", description).strip()

    return {
        "type": "技能",
        "name": fields.get("name", path.parent.name),
        "code": f"/{fields.get('name', path.parent.name)}",
        "model_label": MODEL_LABEL.get(fields.get("model", "inherit"), fields.get("model", "inherit")),
        "function": function or description,
        "covers": NOT_APPLICABLE,
        "keywords": "、".join(keywords) if keywords else "－",
    }


def build_rows() -> list[tuple[str, dict]]:
    """回傳 [(層級, 資料dict), ...]，依 LEVEL_CODE 由小到大排序（系統內建→使用者層級→
    專案層級），同一層級內維持原始清單順序。"""
    rows: list[tuple[str, dict]] = []
    project_skills = sorted(
        (_parse_project_skill(p) for p in PROJECT_SKILLS_DIR.glob("*/SKILL.md")), key=lambda s: s["name"]
    )
    for a in BUILTIN_AGENTS:
        rows.append(("系統內建", a))
    for a in USER_AGENTS:
        rows.append(("使用者層級", a))
    for s in USER_SKILLS:
        rows.append(("使用者層級", s))
    for s in project_skills:
        rows.append(("專案層級", s))
    rows.sort(key=lambda r: LEVEL_CODE[r[0]])
    return rows


def build_pdf(path: Path = OUTPUT_PATH) -> Path:
    rows = build_rows()

    doc = SimpleDocTemplate(
        str(path), pagesize=landscape(A4),
        topMargin=1.3 * cm, bottomMargin=1.3 * cm, leftMargin=1.3 * cm, rightMargin=1.3 * cm,
    )

    flow = [
        Paragraph("AI 投資顧問專案 — 技能與代理人清單（全層級）", STYLE_TITLE),
        Paragraph(
            "層級代號：1＝系統內建（Claude Code 對話環境的通用子代理人類型，跟本機/本專案內容無關，"
            "手動維護）／2＝使用者層級（~/.claude/skills/、~/.claude/agents/，跨專案通用，手動維護）／"
            "3＝專案層級（本專案 .claude/skills/，自動掃描 SKILL.md）。"
            "「類型」欄位區分技能（Skill，用 /名稱 斜線指令觸發，在主對話中依 SKILL.md 執行固定流程）"
            "與代理人（Agent，透過 Agent 工具背景執行、有獨立上下文，沒有固定斜線指令）。"
            "「涵蓋技能」欄位只對代理人有意義，說明該代理人的行為是否建立在特定技能已驗證過的規則之上；"
            "技能本身不涵蓋其他技能，一律標示「－」。",
            STYLE_SMALL,
        ),
    ]

    header = [Paragraph(f"<b>{h}</b>", STYLE_HEAD) for h in COLUMNS]
    body = [
        [
            Paragraph(f"{LEVEL_CODE[level]}・{level}", STYLE_CELL),
            Paragraph(item["type"], STYLE_CELL),
            Paragraph(item["name"], STYLE_CELL),
            Paragraph(item["code"], STYLE_CELL),
            Paragraph(item["model_label"], STYLE_CELL),
            Paragraph(item["function"], STYLE_CELL),
            Paragraph(item["covers"], STYLE_CELL),
            Paragraph(item["keywords"], STYLE_CELL),
        ]
        for level, item in rows
    ]
    table = Table([header] + body, colWidths=COL_WIDTHS, repeatRows=1)

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
        ("GRID", (0, 0), (-1, -1), 0.5, TABLE_GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, (level, _item) in enumerate(rows, start=1):
        bg = LEVEL_BG.get(level)
        if bg:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
    table.setStyle(TableStyle(style_cmds))

    flow.append(table)
    flow.append(Spacer(1, 10))

    n_builtin = sum(1 for level, _ in rows if level == "系統內建")
    n_user = sum(1 for level, _ in rows if level == "使用者層級")
    n_project = sum(1 for level, _ in rows if level == "專案層級")
    n_skills = sum(1 for _level, item in rows if item["type"] == "技能")
    n_agents = sum(1 for _level, item in rows if item["type"] == "代理人")
    flow.append(Paragraph(
        f"共 {len(rows)} 項（技能 {n_skills} 個／代理人 {n_agents} 個）；"
        f"層級分布：1・系統內建 {n_builtin} 項／2・使用者層級 {n_user} 項／3・專案層級 {n_project} 項。",
        STYLE_SMALL,
    ))

    doc.build(flow)
    return path


if __name__ == "__main__":
    output = build_pdf()
    print(f"已產生 {output}")
