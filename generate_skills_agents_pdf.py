"""產生「技能與代理人清單.pdf」——彙整 `.claude/skills/*/SKILL.md` 的 7 個專案技能，
以及本 Claude Code 對話環境可呼叫的子代理人（Agent 工具的 subagent_type），
各自列出名稱／代號／功能／關鍵字提示詞。

跟 `generate_skills_doc.py`（技能清單.docx）是兩份獨立文件：那份只收錄專案技能，
這份額外加上「代理人」章節。PDF 排版比照 `pdf_report.py` 的做法——直接用 reportlab
platypus 繪製＋標楷體，不透過 xhtml2pdf（已知會讓中文整段變成缺字方框）。

**代理人清單是手動維護的**：Claude Code 的子代理人類型不是這個專案的檔案，沒有地方可以
動態讀取，這裡列的是撰寫當下（本對話環境）可用的 6 個代理人，之後如果環境新增/移除代理人
類型，要手動回來更新這份清單，不會自動同步。
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

SKILLS_DIR = Path(__file__).parent / ".claude" / "skills"
OUTPUT_PATH = Path(__file__).parent / "技能與代理人清單.pdf"

FONT_NAME = "KaiU"
FONT_PATH = r"C:\Windows\Fonts\kaiu.ttf"
BASE_FONT_SIZE = 14

if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
    pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_NAME, italic=FONT_NAME, boldItalic=FONT_NAME)

STYLE_TITLE = ParagraphStyle("title", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE + 10, leading=BASE_FONT_SIZE + 14, spaceAfter=10)
STYLE_H2 = ParagraphStyle("h2", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE + 4, leading=BASE_FONT_SIZE + 8, spaceBefore=16, spaceAfter=8, textColor=colors.HexColor("#1a3d6d"))
STYLE_SMALL = ParagraphStyle("small", fontName=FONT_NAME, fontSize=BASE_FONT_SIZE - 3, leading=BASE_FONT_SIZE + 1, textColor=colors.grey, spaceAfter=10)
STYLE_CELL = ParagraphStyle("cell", fontName=FONT_NAME, fontSize=11, leading=14)
STYLE_HEAD = ParagraphStyle("head", fontName=FONT_NAME, fontSize=11, leading=14, textColor=colors.white)

TABLE_HEAD_BG = colors.HexColor("#1a3d6d")
TABLE_GRID = colors.HexColor("#bbbbbb")

MODEL_LABEL = {
    "haiku": "haiku（機械式操作）",
    "sonnet": "sonnet（中等複雜度）",
    "opus": "opus（複雜診斷推理）",
}

# 本 Claude Code 對話環境可呼叫的子代理人（見系統提供的 Agent 工具說明），手動維護。
AGENTS = [
    {
        "name": "通用代理人",
        "code": "claude",
        "function": "沒有指定特定代理人類型時的預設代理人，可使用所有工具，處理不屬於其他專用代理人的任務。",
        "keywords": "FleetView 未輸入代理人名稱時的預設；「隨便找個代理人做」",
    },
    {
        "name": "Claude Code 使用說明代理人",
        "code": "claude-code-guide",
        "function": "回答 Claude Code CLI、Claude Agent SDK、Claude API（Messages API/Tool Runner）、Claude Tag（Slack）相關問題。",
        "keywords": "「Claude Code能不能…」「怎麼設定 hook」「MCP伺服器是什麼」「/install-slack-app怎麼用」",
    },
    {
        "name": "程式碼探索代理人",
        "code": "Explore",
        "function": "唯讀、快速定位程式碼：依模式找檔案、grep 關鍵字或符號、回答「X在哪裡定義／哪些檔案引用了Y」。",
        "keywords": "「幫我找一下…在哪裡」「這個function在哪個檔案」「搜尋所有用到…的地方」",
    },
    {
        "name": "通用型任務代理人",
        "code": "general-purpose",
        "function": "研究複雜問題、搜尋程式碼、執行多步驟任務；不確定能不能一次找到正確結果時使用。",
        "keywords": "「幫我研究一下…」「不確定要去哪裡找，你去查」「這個牽涉很多檔案，你去看」",
    },
    {
        "name": "軟體架構規劃代理人",
        "code": "Plan",
        "function": "設計實作策略：回傳步驟化計畫、指出關鍵檔案、討論架構取捨，不直接寫程式碼。",
        "keywords": "「幫我規劃一下怎麼做」「這個功能該怎麼設計」「先不要動手，想一下架構」",
    },
    {
        "name": "狀態列設定代理人",
        "code": "statusline-setup",
        "function": "設定使用者 Claude Code 的狀態列（status line）顯示內容。",
        "keywords": "「幫我設定狀態列」「status line 想顯示…」",
    },
]


def _parse_skill(path: Path) -> dict:
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
        "name": fields.get("name", path.parent.name),
        "code": f"/{fields.get('name', path.parent.name)}",
        "model": fields.get("model", "inherit"),
        "function": function or description,
        "keywords": "、".join(keywords) if keywords else "－",
    }


def _make_table(rows: list[list[str]], col_widths: list[float]) -> Table:
    header = [Paragraph(f"<b>{h}</b>", STYLE_HEAD) for h in rows[0]]
    body = [[Paragraph(cell, STYLE_CELL) for cell in row] for row in rows[1:]]
    table = Table([header] + body, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEAD_BG),
                ("GRID", (0, 0), (-1, -1), 0.5, TABLE_GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def build_pdf(path: Path = OUTPUT_PATH) -> Path:
    skills = sorted((_parse_skill(p) for p in SKILLS_DIR.glob("*/SKILL.md")), key=lambda s: s["name"])

    doc = SimpleDocTemplate(
        str(path),
        pagesize=landscape(A4),
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
    )

    flow = [
        Paragraph("AI 投資顧問專案 — 技能與代理人清單", STYLE_TITLE),
        Paragraph(
            "技能（Skills）是本專案 `.claude/skills/` 下的自訂快速指令；代理人（Agents）是 Claude Code 對話環境"
            "可呼叫的子代理人類型，跟本專案內容無關，是工具層級的通用能力。代理人清單為手動維護，環境更新後需回頭同步。",
            STYLE_SMALL,
        ),
        Paragraph("一、技能（Skills）", STYLE_H2),
    ]

    skill_rows = [["名稱", "代號", "使用模型", "功能", "關鍵字/提示詞"]]
    for s in skills:
        skill_rows.append([s["name"], s["code"], MODEL_LABEL.get(s["model"], s["model"]), s["function"], s["keywords"]])
    flow.append(_make_table(skill_rows, [3.2 * cm, 3.6 * cm, 3.4 * cm, 9.5 * cm, 8 * cm]))

    flow.append(Spacer(1, 14))
    flow.append(Paragraph("二、代理人（Agents）", STYLE_H2))

    agent_rows = [["名稱", "代號", "功能", "關鍵字/提示詞"]]
    for a in AGENTS:
        agent_rows.append([a["name"], a["code"], a["function"], a["keywords"]])
    flow.append(_make_table(agent_rows, [3.6 * cm, 4.2 * cm, 10.5 * cm, 9.4 * cm]))

    doc.build(flow)
    return path


if __name__ == "__main__":
    output = build_pdf()
    print(f"已產生 {output}")
