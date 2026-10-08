"""PDF rendering for the nasabah riwayat statement.

Theme tokens + the platypus document build. Themes change colors only — the
layout (header band, info grid, summary strip, mutation table with item
sub-rows, numbered footer) is shared, so any theme renders identically
structurally. Everything the renderer knows about Django is nothing: it draws
StatementData, plain data.

Fonts: vendored Inter (OFL, see fonts/OFL.txt). Registered at module import —
once per worker process, deterministic under gunicorn; the guard makes dev
auto-reload safe.
"""

from dataclasses import dataclass
from decimal import Decimal
from html import escape
from importlib import resources
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
)
from reportlab.platypus.paragraph import Paragraph

from apps.reporting.statement import MutationRow, StatementData
from shared_kernel.kalkulasi import format_ribuan

if "Inter" not in pdfmetrics.getRegisteredFontNames():
    _fonts_dir = resources.files("apps.reporting") / "fonts"
    with resources.as_file(_fonts_dir) as _dir:  # zip-safe lookup; unpacked normally
        pdfmetrics.registerFont(TTFont("Inter", str(Path(_dir) / "Inter-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("Inter-Bold", str(Path(_dir) / "Inter-Bold.ttf")))


@dataclass(frozen=True)
class Theme:
    primary: colors.HexColor  # header band + table header fill
    primary_text: colors.HexColor
    zebra: colors.HexColor  # alternate-row fill
    grid: colors.HexColor  # table line color
    subrow_text: colors.HexColor  # item sub-row muted color
    accent: colors.HexColor  # summary block accents


THEMES: dict[str, Theme] = {
    # Classic navy bank-mutation statement.
    "ledger": Theme(
        primary=colors.HexColor("#1B2A4A"),
        primary_text=colors.HexColor("#FFFFFF"),
        zebra=colors.HexColor("#EEF1F6"),
        grid=colors.HexColor("#C9D2E0"),
        subrow_text=colors.HexColor("#6B7590"),
        accent=colors.HexColor("#1B2A4A"),
    ),
    # PILAH green brand.
    "pilah": Theme(
        primary=colors.HexColor("#166534"),
        primary_text=colors.HexColor("#FFFFFF"),
        zebra=colors.HexColor("#ECFDF5"),
        grid=colors.HexColor("#BBE7CC"),
        subrow_text=colors.HexColor("#5B7B66"),
        accent=colors.HexColor("#166534"),
    ),
    # Modern minimal: white space, hairlines, dark text.
    "minimal": Theme(
        primary=colors.HexColor("#111827"),
        primary_text=colors.HexColor("#FFFFFF"),
        zebra=colors.HexColor("#FAFAFA"),
        grid=colors.HexColor("#E5E7EB"),
        subrow_text=colors.HexColor("#9CA3AF"),
        accent=colors.HexColor("#111827"),
    ),
    # Fintech: dark strip, colored summary chips.
    "fintech": Theme(
        primary=colors.HexColor("#0F172A"),
        primary_text=colors.HexColor("#38BDF8"),
        zebra=colors.HexColor("#F1F5F9"),
        grid=colors.HexColor("#CBD5E1"),
        subrow_text=colors.HexColor("#64748B"),
        accent=colors.HexColor("#0EA5E9"),
    ),
    # Warm recycle: earthy palette for the kampung bank sampah identity.
    "warm-recycle": Theme(
        primary=colors.HexColor("#7C4A21"),
        primary_text=colors.HexColor("#FFF8EE"),
        zebra=colors.HexColor("#F7EFE3"),
        grid=colors.HexColor("#D9C4A5"),
        subrow_text=colors.HexColor("#8A7358"),
        accent=colors.HexColor("#A16207"),
    ),
}

_PAGE_W, _PAGE_H = A4
_MARGIN = 15 * mm
_TABLE_W = _PAGE_W - 2 * _MARGIN
_RADIUS = 6  # subtle rounded corners shared by every boxed element

_STYLES = {
    "label": ParagraphStyle("label", fontName="Inter", fontSize=8, leading=10),
    "value": ParagraphStyle("value", fontName="Inter-Bold", fontSize=8, leading=10),
    "cell": ParagraphStyle("cell", fontName="Inter", fontSize=8, leading=10),
    "cell_right": ParagraphStyle(
        "cell_right", fontName="Inter", fontSize=8, leading=10, alignment=2
    ),
    "subrow": ParagraphStyle(
        "subrow",
        fontName="Inter",
        fontSize=7,
        leading=9,
        textColor=None,  # set per theme
    ),
}


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    """Dynamic text as a Paragraph: escaped.

    Paragraph bodies parse as XML — a bank or nasabah named "A & B Sampah"
    or one containing "<" aborts the whole export otherwise. Labels the code
    writes itself stay literal (they carry ``<br/>`` in the header band).
    """
    return Paragraph(escape(text), style)


class NumberedCanvas(Canvas):  # type: ignore[misc]  # reportlab has no stubs; Canvas resolves Any
    """Standard two-phase pattern: collect page states, draw footers on save."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, object]] = []

    def showPage(self) -> None:  # noqa: N802  (reportlab API name)
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        theme = THEMES["ledger"]  # footer stays neutral across themes
        self.setFont("Inter", 7)
        self.setFillColor(colors.HexColor("#6B7280"))
        self.drawRightString(
            _PAGE_W - _MARGIN, _MARGIN * 0.6, f"Halaman {self._pageNumber} dari {total}"
        )
        self.drawString(_MARGIN, _MARGIN * 0.6, "Dihasilkan oleh PILAH")
        self.setStrokeColor(theme.grid)
        self.setLineWidth(0.4)
        self.line(_MARGIN, _MARGIN * 0.6 + 10, _PAGE_W - _MARGIN, _MARGIN * 0.6 + 10)


def render_statement(data: StatementData, theme_key: str) -> bytes:
    theme = THEMES.get(theme_key, THEMES["pilah"])

    stream = BytesIO()
    # Chrome height: header band + info grid + summary + spacers, so the
    # mutation frame starts below the repeated chrome on every page.
    chrome_h = 14 * mm + 4 * mm + 30 * mm + 4 * mm + 12 * mm + 3 * mm + 6 * mm
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN + chrome_h,
        bottomMargin=_MARGIN,
        title="Laporan Riwayat Aktivitas",
        author=data.bank_nama,
    )

    def draw_chrome(canvas: Canvas, _doc: SimpleDocTemplate) -> None:
        _page_chrome(canvas, data, theme)

    doc.build(
        _flowables(data, theme),
        onFirstPage=draw_chrome,
        onLaterPages=draw_chrome,
        canvasmaker=NumberedCanvas,
    )
    return stream.getvalue()


def _flowables(data: StatementData, theme: Theme) -> list[object]:
    # Sub-row tone comes from the theme, so pass a fresh style copy.
    styles = dict(_STYLES)
    styles["subrow"].textColor = theme.subrow_text
    return [_mutation_table(data.rows, theme, styles)]


def _page_chrome(canvas: Canvas, data: StatementData, theme: Theme) -> None:
    """Header band + info grid + summary strip, drawn on every page.

    Platypus repeats headers via an onPage callback, not story flowables —
    the flowable path renders once, on page 1 only (the bug this replaced).
    Everything draws at absolute canvas coordinates, mirrored around the
    top margin; the mutation table lives in the frame below it.
    """
    header_h = 14 * mm
    top = _PAGE_H - 15 * mm  # top margin line
    x_start = _MARGIN

    # --- Header band.
    canvas.saveState()
    canvas.setFillColor(theme.primary)
    canvas.roundRect(x_start, top - header_h, _TABLE_W, header_h, _RADIUS, stroke=0, fill=1)
    logo = _logo_file()
    if logo:
        canvas.drawImage(
            logo,
            x_start + 6 * mm,
            top - header_h + (header_h - 10 * mm) / 2,
            width=10 * mm,
            height=10 * mm,
            mask="auto",
        )
    canvas.setFillColor(theme.primary_text)
    canvas.setFont("Inter-Bold", 11)
    canvas.drawRightString(
        x_start + _TABLE_W - 6 * mm, top - header_h / 2 - 4, "Laporan Riwayat Aktivitas"
    )
    canvas.drawRightString(x_start + _TABLE_W - 6 * mm, top - header_h / 2 + 6, data.bank_nama)
    canvas.restoreState()

    # --- Info grid, label:value pairs in two columns.
    grid_h = 30 * mm
    grid_top = top - header_h - 4 * mm
    labels_left = ["Nama", "No. Anggota", "Email", "No. HP", "Periode", "Diunduh"]
    values_left = [
        data.nasabah_nama,
        data.nomor_anggota,
        data.nasabah_email,
        data.nasabah_no_hp,
        data.periode_label,
        data.diunduh,
    ]
    labels_right = ["Bank Sampah", "Alamat Bank", "No. HP Bank", "Alamat", "Tipe", ""]
    values_right = [
        data.bank_nama,
        _bank_alamat(data),
        data.bank_no_hp,
        data.nasabah_alamat,
        data.tipe_label,
        "",
    ]
    row_h = grid_h / 6
    canvas.saveState()
    for i in range(6):
        y = grid_top - (i + 1) * row_h
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.setFont("Inter", 8)
        canvas.drawString(x_start, y, labels_left[i])
        canvas.drawString(x_start + _TABLE_W * 0.5, y, labels_right[i])
        canvas.setFillColor(colors.HexColor("#111827"))
        canvas.setFont("Inter-Bold", 8)
        canvas.drawString(x_start + 18 * mm, y, _clip(values_left[i], 40))
        canvas.drawString(x_start + _TABLE_W * 0.5 + 22 * mm, y, _clip(values_right[i], 40))
    canvas.restoreState()

    # --- Summary strip: saldo awal / setoran / pencairan / saldo akhir.
    strip_top = grid_top - grid_h - 4 * mm
    strip_h = 12 * mm
    cell_w = _TABLE_W / 4
    captions = ["Saldo Awal", "Total Setoran", "Total Pencairan", "Saldo Akhir"]
    amounts = [data.saldo_awal, data.total_setoran, data.total_pencairan, data.saldo_akhir]
    canvas.saveState()
    for i, (caption, amount) in enumerate(zip(captions, amounts, strict=True)):
        x = x_start + i * cell_w
        canvas.setFillColor(theme.zebra)
        canvas.roundRect(x, strip_top - strip_h, cell_w - 2, strip_h, _RADIUS, stroke=0, fill=1)
        canvas.setStrokeColor(theme.accent)
        canvas.setLineWidth(0.5)
        canvas.roundRect(x, strip_top - strip_h, cell_w - 2, strip_h, _RADIUS, stroke=1, fill=0)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.setFont("Inter", 8)
        canvas.drawString(x + 8, strip_top - strip_h + 6, caption)
        canvas.setFillColor(colors.HexColor("#111827"))
        canvas.setFont("Inter-Bold", 9)
        canvas.drawString(x + 8, strip_top - 6, "Rp " + format_ribuan(amount))
    canvas.restoreState()

    canvas.saveState()
    canvas.setStrokeColor(theme.grid)
    canvas.setLineWidth(0.4)
    canvas.line(
        _MARGIN, strip_top - strip_h - 3 * mm, _PAGE_W - _MARGIN, strip_top - strip_h - 3 * mm
    )
    canvas.restoreState()


def _bank_alamat(data: StatementData) -> str:
    return " ".join(part for part in (data.bank_alamat, data.bank_kota) if part) or "-"


def _clip(text: str, limit: int) -> str:
    """Truncate long names to keep absolute-drawn chrome inside its band."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _logo_file() -> str | None:
    """Path of the leaf logo asset, None when the resource can't resolve
    (e.g. zip imports) — the band draws without it."""
    try:
        with resources.as_file(resources.files("apps.reporting") / "fonts" / "logo.png") as path:
            return str(path)
    except Exception:  # noqa: BLE001 — a missing logo must not abort an export
        return None


def _mutation_table(
    rows: list[MutationRow], theme: Theme, styles: dict[str, ParagraphStyle]
) -> Table:
    head_style = ParagraphStyle(
        "th", fontName="Inter-Bold", fontSize=8, leading=10, textColor=theme.primary_text
    )
    num_style = ParagraphStyle("num", parent=styles["cell"], alignment=2)

    table_data: list[list[Paragraph]] = [
        [
            Paragraph("Tanggal", head_style),
            Paragraph("Keterangan", head_style),
            Paragraph("Debit (Rp)", head_style),
            Paragraph("Kredit (Rp)", head_style),
            Paragraph("Saldo (Rp)", head_style),
        ]
    ]
    style_cmds: list[tuple[object, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), theme.primary),
        ("GRID", (0, 0), (-1, -1), 0.4, theme.grid),
        ("ROUNDEDCORNERS", [_RADIUS, _RADIUS, _RADIUS, _RADIUS]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]

    row_index = 1
    zebra_on = False
    for row in rows:
        tanggal = row.tanggal.strftime("%d/%m/%Y")
        table_data.append(
            [
                Paragraph(tanggal, styles["cell"]),
                Paragraph(escape(row.keterangan), styles["cell"]),
                Paragraph(format_ribuan(row.debit) if row.debit else "", num_style),
                Paragraph(format_ribuan(row.kredit) if row.kredit else "", num_style),
                Paragraph(format_ribuan(row.saldo), num_style),
            ]
        )
        if zebra_on:
            style_cmds.append(("BACKGROUND", (0, row_index), (-1, row_index), theme.zebra))
        zebra_on = not zebra_on
        row_index += 1

        # Item sub-rows (super detail): muted, indented, no zebra.
        for item in row.items:
            text = (
                f"• {escape(item.kategori)} – {escape(item.nama)} "
                f"({item_berat(item.berat)} × Rp {format_ribuan(item.harga)})"
            )
            table_data.append(
                [
                    Paragraph("", styles["cell"]),
                    Paragraph(text, styles["subrow"]),
                    Paragraph("", styles["cell"]),
                    Paragraph(format_ribuan(item.subtotal), styles["subrow"]),
                    Paragraph("", styles["cell"]),
                ]
            )
            row_index += 1

    return Table(
        table_data,
        colWidths=[_TABLE_W * w for w in (0.14, 0.42, 0.14, 0.15, 0.15)],
        repeatRows=1,
        style=TableStyle(style_cmds),
    )


def item_berat(berat: Decimal) -> str:
    return f"{berat.normalize()} kg"
