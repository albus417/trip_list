from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from io import BytesIO

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics

from .utils import yen


PAGE_BG = colors.HexColor("#FFF8F1")
BROWN = colors.HexColor("#735343")
DARK = colors.HexColor("#2F2F36")
MUTED = colors.HexColor("#7D6B61")
LINE = colors.HexColor("#D8C5B4")
BEIGE = colors.HexColor("#F4E8DA")
CARD = colors.HexColor("#FFFFFF")
PLAN_BG = colors.HexColor("#FFF8F1")
HOTEL_BG = colors.HexColor("#EEF6FF")
HOTEL_BLUE = colors.HexColor("#7AA7D9")


CATEGORY_ICONS = {
    "交通": "移動",
    "宿泊": "宿泊",
    "食事": "食事",
    "観光": "観光",
    "買い物": "買物",
    "チケット": "券",
    "その他": "他",
}


def _date_obj(value: str):
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        return None


def _date_label(value: str) -> str:
    d = _date_obj(value)
    if not d:
        return value or "日付未定"
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    return f"{d.month}/{d.day}<br/>{weekdays[d.weekday()]}"


def _date_label_inline(value: str) -> str:
    d = _date_obj(value)
    if not d:
        return value or "日付未定"
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    return f"{d.year}/{d.month}/{d.day}（{weekdays[d.weekday()]}）"


def _timeline_items(trip: dict) -> list[dict]:
    items = []

    for p in trip.get("plans", []):
        items.append({
            "type": "plan",
            "date": p.get("date", ""),
            "time": p.get("time", ""),
            "sort_time": p.get("time") or "99:98",
            "title": p.get("content", ""),
            "place": p.get("place", ""),
            "category": p.get("category", "その他"),
            "amount": yen(p.get("amount")),
            "memo": p.get("memo", ""),
        })

    for h in trip.get("hotels", []):
        items.append({
            "type": "hotel",
            "date": h.get("date", ""),
            "time": "",
            "sort_time": "99:99",
            "title": h.get("hotel", ""),
            "place": h.get("place", ""),
            "category": "宿泊",
            "amount": yen(h.get("amount")),
            "memo": h.get("memo", ""),
        })

    return sorted(
        items,
        key=lambda x: (
            x.get("date") or "9999-99-99",
            x.get("sort_time") or "99:98",
            1 if x.get("type") == "hotel" else 0,
        )
    )


def _trip_dates(trip: dict) -> list[date]:
    dates = []
    for item in _timeline_items(trip):
        d = _date_obj(item.get("date", ""))
        if d:
            dates.append(d)
    return sorted(dates)


def _trip_range(trip: dict) -> str:
    dates = _trip_dates(trip)
    if not dates:
        return "日程未定"
    start, end = dates[0], dates[-1]
    if start == end:
        return _date_label_inline(start.isoformat())
    return f"{_date_label_inline(start.isoformat())} 〜 {_date_label_inline(end.isoformat())}"


def _trip_days(trip: dict) -> int:
    dates = _trip_dates(trip)
    if not dates:
        return 0
    return (dates[-1] - dates[0]).days + 1


def _total_amount(trip: dict) -> int:
    total = 0
    for p in trip.get("plans", []):
        total += yen(p.get("amount"))
    for h in trip.get("hotels", []):
        total += yen(h.get("amount"))
    for o in trip.get("others", []):
        total += yen(o.get("amount"))
    return total


def _category_totals(trip: dict) -> dict[str, int]:
    totals = defaultdict(int)
    for p in trip.get("plans", []):
        totals[p.get("category", "その他")] += yen(p.get("amount"))
    for h in trip.get("hotels", []):
        totals["宿泊"] += yen(h.get("amount"))
    for o in trip.get("others", []):
        totals[o.get("category", "その他")] += yen(o.get("amount"))
    return dict(totals)


def _grouped_items(trip: dict) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for item in _timeline_items(trip):
        grouped[item.get("date", "")].append(item)
    return dict(grouped)


def _money(value: int) -> str:
    return f"{value:,}円"


def _make_styles():
    styles = getSampleStyleSheet()
    for k in styles.byName:
        styles[k].fontName = "HeiseiKakuGo-W5"

    styles.add(ParagraphStyle(
        name="CoverTitle",
        parent=styles["Title"],
        fontName="HeiseiKakuGo-W5",
        fontSize=30,
        leading=38,
        textColor=BROWN,
        alignment=1,
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="CoverSub",
        parent=styles["Normal"],
        fontName="HeiseiKakuGo-W5",
        fontSize=12,
        leading=18,
        textColor=MUTED,
        alignment=1,
    ))
    styles.add(ParagraphStyle(
        name="SectionTitle",
        parent=styles["Heading2"],
        fontName="HeiseiKakuGo-W5",
        fontSize=16,
        leading=22,
        textColor=BROWN,
        spaceBefore=8,
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="CardTitle",
        parent=styles["Heading3"],
        fontName="HeiseiKakuGo-W5",
        fontSize=11,
        leading=15,
        textColor=BROWN,
        alignment=1,
    ))
    styles.add(ParagraphStyle(
        name="Small",
        parent=styles["Normal"],
        fontName="HeiseiKakuGo-W5",
        fontSize=8,
        leading=11,
        textColor=DARK,
    ))
    styles.add(ParagraphStyle(
        name="TinyMuted",
        parent=styles["Normal"],
        fontName="HeiseiKakuGo-W5",
        fontSize=7,
        leading=9,
        textColor=MUTED,
    ))
    styles.add(ParagraphStyle(
        name="DayHeader",
        parent=styles["Normal"],
        fontName="HeiseiKakuGo-W5",
        fontSize=12,
        leading=16,
        textColor=BROWN,
        alignment=1,
    ))
    styles.add(ParagraphStyle(
        name="BoardCell",
        parent=styles["Normal"],
        fontName="HeiseiKakuGo-W5",
        fontSize=8,
        leading=10,
        textColor=DARK,
    ))
    return styles


def _card_table(title: str, lines: list[str], styles, width=230) -> Table:
    body = [[Paragraph(title, styles["CardTitle"])]]
    if lines:
        body.append([Paragraph("<br/>".join(lines), styles["Small"])])
    else:
        body.append([Paragraph("未入力", styles["TinyMuted"])])

    t = Table(body, colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), CARD),
        ("BOX", (0,0), (-1,-1), 0.7, LINE),
        ("ROUNDRECT", (0,0), (-1,-1), 8, LINE),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    return t


def _cover_page(story, trip: dict, settings: dict, styles):
    title = trip.get("title") or "無題の旅行"
    app_title = settings.get("app_title", "TripList") if isinstance(settings, dict) else str(settings or "TripList")
    members = settings.get("members", []) if isinstance(settings, dict) else []
    total = _total_amount(trip)
    people = max(1, len(members) or 2)

    story.append(Spacer(1, 24))
    story.append(Paragraph(title, styles["CoverTitle"]))
    story.append(Paragraph(_trip_range(trip), styles["CoverSub"]))
    story.append(Spacer(1, 22))

    overview = [
        f"・日程：{_trip_range(trip)}",
        f"・日数：{_trip_days(trip) or '未定'}日間",
        f"・予定数：{len(trip.get('plans', []))}件",
        f"・宿泊：{len(trip.get('hotels', []))}件",
    ]
    group_lines = [
        f"・メンバー：{'、'.join(members) if members else '未設定'}",
        f"・アプリ：{app_title}",
    ]

    if isinstance(settings, dict) and settings.get("anniversary_date"):
        try:
            d = datetime.fromisoformat(settings["anniversary_date"]).date()
            group_lines.append(f"・{settings.get('anniversary_name','記念日')}：{_date_label_inline(d.isoformat())}")
            group_lines.append(f"・記念日から：{(date.today() - d).days}日")
        except Exception:
            pass

    budget_lines = [
        f"・合計：{_money(total)}",
        f"・1人あたり：{_money(total // people)}",
        f"・人数：{people}人",
    ]

    hotel_lines = []
    for h in trip.get("hotels", [])[:6]:
        hotel_lines.append(f"・{_date_label_inline(h.get('date',''))}：{h.get('hotel','')}")

    top = Table([
        [
            _card_table("旅行概要", overview, styles, 250),
            _card_table("グループ情報", group_lines, styles, 250),
            _card_table("予算", budget_lines, styles, 180),
        ]
    ], colWidths=[260,260,190])
    top.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(top)
    story.append(Spacer(1, 14))

    if hotel_lines:
        story.append(_card_table("ホテル", hotel_lines, styles, width=725))
        story.append(Spacer(1, 10))

    story.append(Paragraph("素敵な旅になりますように。", styles["CoverSub"]))
    story.append(PageBreak())


def _schedule_board_page(story, trip: dict, styles):
    grouped = _grouped_items(trip)

    if not grouped:
        return

    story.append(Paragraph("手帳風タイムライン", styles["SectionTitle"]))
    story.append(Spacer(1, 5))

    days = sorted(grouped.keys())
    # 横A4なので、1ページにつき最大5日が見やすい。
    chunks = [days[i:i+5] for i in range(0, len(days), 5)]

    for chunk_index, chunk in enumerate(chunks):
        if chunk_index > 0:
            story.append(PageBreak())
            story.append(Paragraph("手帳風タイムライン（続き）", styles["SectionTitle"]))
            story.append(Spacer(1, 5))

        max_rows = max(len(grouped[d]) for d in chunk)
        header = [Paragraph(_date_label(d), styles["DayHeader"]) for d in chunk]
        rows = [header]

        for row_i in range(max_rows):
            row = []
            for d in chunk:
                if row_i < len(grouped[d]):
                    item = grouped[d][row_i]
                    if item["type"] == "hotel":
                        text = f"<b>宿泊</b>　{item.get('title','')}"
                        if item.get("place"):
                            text += f"<br/>場所：{item.get('place')}"
                    else:
                        category = CATEGORY_ICONS.get(item.get("category","その他"), item.get("category","その他"))
                        text = f"<b>{item.get('time','')}</b>　{item.get('title','')}　[{category}]"
                        if item.get("place"):
                            text += f"<br/>場所：{item.get('place')}"
                    row.append(Paragraph(text, styles["BoardCell"]))
                else:
                    row.append("")
            rows.append(row)

        col_width = 760 / max(1, len(chunk))
        table = Table(rows, colWidths=[col_width]*len(chunk), repeatRows=1)
        style_cmds = [
            ("FONTNAME", (0,0), (-1,-1), "HeiseiKakuGo-W5"),
            ("BACKGROUND", (0,0), (-1,0), BEIGE),
            ("TEXTCOLOR", (0,0), (-1,0), BROWN),
            ("GRID", (0,0), (-1,-1), 0.45, LINE),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ]

        for col_i, d in enumerate(chunk):
            for row_i, item in enumerate(grouped[d], start=1):
                if item["type"] == "hotel":
                    style_cmds.append(("BACKGROUND", (col_i, row_i), (col_i, row_i), HOTEL_BG))
                    style_cmds.append(("LEFTPADDING", (col_i, row_i), (col_i, row_i), 9))
                else:
                    style_cmds.append(("BACKGROUND", (col_i, row_i), (col_i, row_i), PLAN_BG))

        table.setStyle(TableStyle(style_cmds))
        story.append(table)


def _details_pages(story, trip: dict, settings: dict, styles):
    story.append(PageBreak())
    story.append(Paragraph("旅行詳細", styles["SectionTitle"]))

    rows = [["種類", "日付", "時間", "カテゴリ", "内容", "場所", "金額"]]
    for item in _timeline_items(trip):
        rows.append([
            "宿泊" if item["type"] == "hotel" else "予定",
            _date_label_inline(item.get("date","")),
            "宿泊" if item["type"] == "hotel" else item.get("time",""),
            item.get("category",""),
            item.get("title",""),
            item.get("place",""),
            _money(item.get("amount", 0)),
        ])

    for o in trip.get("others", []):
        rows.append(["その他", "", "", o.get("category","その他"), o.get("content",""), "", _money(yen(o.get("amount")))])

    if len(rows) == 1:
        story.append(Paragraph("予定はまだありません。", styles["Small"]))
    else:
        table = Table(rows, colWidths=[45, 85, 45, 55, 210, 220, 70], repeatRows=1)
        table.setStyle(TableStyle([
            ("FONTNAME", (0,0), (-1,-1), "HeiseiKakuGo-W5"),
            ("BACKGROUND", (0,0), (-1,0), BEIGE),
            ("TEXTCOLOR", (0,0), (-1,0), BROWN),
            ("GRID", (0,0), (-1,-1), 0.35, LINE),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("FONTSIZE", (0,0), (-1,-1), 7.5),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        story.append(table)

    story.append(Spacer(1, 12))

    total = _total_amount(trip)
    members = settings.get("members", []) if isinstance(settings, dict) else []
    people = max(1, len(members) or 2)
    category_totals = _category_totals(trip)

    budget_lines = [f"・合計：{_money(total)}", f"・1人あたり：{_money(total // people)}"]
    for k, v in category_totals.items():
        budget_lines.append(f"・{k}：{_money(v)}")

    packing = trip.get("packing", [])
    packing_lines = []
    for item in packing[:30]:
        mark = "済" if item.get("checked") else "□"
        packing_lines.append(f"・{mark} {item.get('name','')}")

    hotel_lines = []
    for h in trip.get("hotels", []):
        amount = yen(h.get("amount"))
        line = f"・{_date_label_inline(h.get('date',''))}：{h.get('hotel','')}"
        if h.get("place"):
            line += f"（{h.get('place')}）"
        if amount:
            line += f" {_money(amount)}"
        hotel_lines.append(line)

    bottom = Table([
        [
            _card_table("予算", budget_lines, styles, 230),
            _card_table("ホテル", hotel_lines, styles, 250),
            _card_table("持ち物", packing_lines, styles, 230),
        ]
    ], colWidths=[240,260,240])
    bottom.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(bottom)


def _draw_page_frame(canvas, doc):
    canvas.saveState()
    w, h = landscape(A4)
    canvas.setFillColor(PAGE_BG)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)

    canvas.setStrokeColor(colors.HexColor("#D8B48A"))
    canvas.setLineWidth(1)
    canvas.rect(18, 18, w-36, h-36, fill=0, stroke=1)

    canvas.setFont("HeiseiKakuGo-W5", 7)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(w-24, 10, f"TripList しおり  /  {doc.page}")
    canvas.restoreState()


def make_pdf(trip: dict, settings=None) -> BytesIO:
    """旅行のしおりPDFを作る。QR・写真なし版。"""
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    if settings is None:
        settings = {}
    if isinstance(settings, str):
        settings = {"app_title": settings}

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=32,
        leftMargin=32,
        topMargin=32,
        bottomMargin=32,
    )

    styles = _make_styles()

    story = []
    _cover_page(story, trip, settings, styles)
    _schedule_board_page(story, trip, styles)
    _details_pages(story, trip, settings, styles)

    doc.build(story, onFirstPage=_draw_page_frame, onLaterPages=_draw_page_frame)
    buf.seek(0)
    return buf
