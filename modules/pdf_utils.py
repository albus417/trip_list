from __future__ import annotations
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase import pdfmetrics
from .utils import yen


def make_pdf(trip: dict, app_title: str = "TripList") -> BytesIO:
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    for k in styles.byName:
        styles[k].fontName = "HeiseiKakuGo-W5"
    story = []
    story.append(Paragraph(app_title, styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"旅行名：{trip.get('title','無題')}", styles["Heading2"]))
    story.append(Spacer(1, 12))
    rows = [["種類", "日付", "時間", "内容", "場所", "金額"]]
    total = 0
    for p in trip.get("plans", []):
        a = yen(p.get("amount")); total += a
        rows.append(["予定", p.get("date",""), p.get("time",""), p.get("content",""), p.get("place",""), f"{a:,}円"])
    for h in trip.get("hotels", []):
        a = yen(h.get("amount")); total += a
        rows.append(["宿泊", h.get("date",""), "", h.get("hotel",""), h.get("place",""), f"{a:,}円"])
    for o in trip.get("others", []):
        a = yen(o.get("amount")); total += a
        rows.append(["その他", "", "", o.get("content",""), "", f"{a:,}円"])
    table = Table(rows, colWidths=[45, 70, 45, 170, 130, 70])
    table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "HeiseiKakuGo-W5"), ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.4, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"合計：{total:,}円", styles["Heading3"]))
    packing = trip.get("packing", [])
    if packing:
        story.append(Spacer(1, 12)); story.append(Paragraph("持ち物", styles["Heading3"]))
        for item in packing:
            mark = "✓" if item.get("checked") else "□"
            story.append(Paragraph(f"{mark} {item.get('name','')}", styles["Normal"]))
    doc.build(story)
    buf.seek(0)
    return buf
