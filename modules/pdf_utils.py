from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from io import BytesIO

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics

from .utils import yen


def _date_label(value: str) -> str:
    try:
        d = datetime.fromisoformat(value).date()
        weekdays = ["月", "火", "水", "木", "金", "土", "日"]
        return f"{d.month}/{d.day}（{weekdays[d.weekday()]}）"
    except Exception:
        return value or "日付未定"


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
            "category": p.get("category", ""),
            "amount": yen(p.get("amount")),
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
        })

    return sorted(
        items,
        key=lambda x: (
            x.get("date") or "9999-99-99",
            x.get("sort_time") or "99:98",
            1 if x.get("type") == "hotel" else 0,
        )
    )


def _build_schedule_board(trip: dict, styles) -> Table | None:
    grouped = defaultdict(list)
    for item in _timeline_items(trip):
        grouped[item.get("date", "")].append(item)

    if not grouped:
        return None

    days = sorted(grouped.keys())
    # 1ページに最大7日。旅行が長い場合は、最初の7日をボード表示し、詳細表で全件表示する。
    days = days[:7]

    header = [Paragraph(_date_label(d), styles["DayHeader"]) for d in days]
    body = []

    max_rows = max(len(grouped[d]) for d in days)
    for row_i in range(max_rows):
        row = []
        for d in days:
            if row_i < len(grouped[d]):
                item = grouped[d][row_i]
                if item["type"] == "hotel":
                    text = f"🏨 宿泊<br/>{item.get('title','')}"
                    if item.get("place"):
                        text += f"<br/>📍 {item.get('place')}"
                else:
                    text = f"{item.get('time','')} {item.get('title','')}"
                    if item.get("place"):
                        text += f"<br/>📍 {item.get('place')}"
                row.append(Paragraph(text, styles["BoardCell"]))
            else:
                row.append("")
        body.append(row)

    data = [header] + body
    col_width = 760 / max(1, len(days))
    table = Table(data, colWidths=[col_width] * len(days), repeatRows=1)

    style_cmds = [
        ("FONTNAME", (0,0), (-1,-1), "HeiseiKakuGo-W5"),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F4E8DA")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#735343")),
        ("GRID", (0,0), (-1,-1), 0.45, colors.HexColor("#D8C5B4")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]

    # 宿泊セルは淡い青にする。
    for col_i, d in enumerate(days):
        for row_i, item in enumerate(grouped[d], start=1):
            if item["type"] == "hotel":
                style_cmds.append(("BACKGROUND", (col_i, row_i), (col_i, row_i), colors.HexColor("#EEF6FF")))
            else:
                style_cmds.append(("BACKGROUND", (col_i, row_i), (col_i, row_i), colors.HexColor("#FFF8F1")))

    table.setStyle(TableStyle(style_cmds))
    return table


def make_pdf(trip: dict, app_title: str = "TripList") -> BytesIO:
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=28,
        leftMargin=28,
        topMargin=28,
        bottomMargin=28,
    )

    styles = getSampleStyleSheet()
    for k in styles.byName:
        styles[k].fontName = "HeiseiKakuGo-W5"

    styles.add(ParagraphStyle(
        name="DayHeader",
        parent=styles["Normal"],
        fontName="HeiseiKakuGo-W5",
        fontSize=10,
        leading=13,
        alignment=1,
        textColor=colors.HexColor("#735343"),
    ))
    styles.add(ParagraphStyle(
        name="BoardCell",
        parent=styles["Normal"],
        fontName="HeiseiKakuGo-W5",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#2F2F36"),
    ))

    story = []
    story.append(Paragraph(app_title, styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"旅行名：{trip.get('title','無題')}", styles["Heading2"]))
    story.append(Spacer(1, 12))

    board = _build_schedule_board(trip, styles)
    if board:
        story.append(Paragraph("日付別スケジュール表", styles["Heading2"]))
        story.append(Spacer(1, 6))
        story.append(board)
        story.append(PageBreak())

    story.append(Paragraph("タイムライン詳細", styles["Heading2"]))
    story.append(Spacer(1, 8))

    rows = [["種類", "日付", "時間", "内容", "場所", "金額"]]
    total = 0

    for item in _timeline_items(trip):
        a = yen(item.get("amount"))
        total += a
        rows.append([
            "宿泊" if item["type"] == "hotel" else "予定",
            item.get("date", ""),
            "宿泊" if item["type"] == "hotel" else item.get("time", ""),
            item.get("title", ""),
            item.get("place", ""),
            f"{a:,}円",
        ])

    for o in trip.get("others", []):
        a = yen(o.get("amount"))
        total += a
        rows.append(["その他", "", "", o.get("content",""), "", f"{a:,}円"])

    table = Table(rows, colWidths=[45, 70, 45, 260, 210, 70], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "HeiseiKakuGo-W5"),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.4, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"合計：{total:,}円", styles["Heading3"]))

    packing = trip.get("packing", [])
    if packing:
        story.append(Spacer(1, 12))
        story.append(Paragraph("持ち物", styles["Heading3"]))
        for item in packing:
            mark = "✓" if item.get("checked") else "□"
            story.append(Paragraph(f"{mark} {item.get('name','')}", styles["Normal"]))

    doc.build(story)
    buf.seek(0)
    return buf
