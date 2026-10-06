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
    Spacer,
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


class NumberedCanvas(Canvas):  # type: ignore[misc]  # reportlab has no stubs; Canvas resolves Any
    """Two-phase canvas: footers (with page total) and the repeated page
    header are drawn on save(), once every page's state is collected."""

    def __init__(
        self,
        *args: object,
        header_data: tuple[str, str, str, str, str, str] | None = None,
        theme: Theme | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, object]] = []
        self._header_data = header_data
        self._theme = theme or THEMES["pilah"]

    def showPage(self) -> None:  # noqa: N802  (reportlab API name)
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_repeated_header()
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_repeated_header(self) -> None:
        """Compact band on every page: logo, bank, title, nasabah info.

        Like a bank's mutation letter, the statement stays identifiable on
        page 2+: who, which bank, which periode — drawn on the canvas so it
        repeats even as the mutation table splits across pages.
        """
        if not self._header_data:
            return
        bank_nama, nasabah_nama, nomor, periode, tipe, diunduh = self._header_data
        band_top = _PAGE_H - _MARGIN
        band_h = 27 * mm
        self.setFillColor(self._theme.primary)
        self.roundRect(_MARGIN, band_top - band_h, _TABLE_W, band_h, _RADIUS, stroke=0, fill=1)

        # Logo on a white chip so its transparency reads on any theme.
        self.setFillColor(colors.white)
        self.roundRect(
            _MARGIN + 4 * mm,
            band_top - band_h + 4 * mm,
            13 * mm,
            16 * mm,
            _RADIUS,
            stroke=0,
            fill=1,
        ) if False else None
        self.drawImage(
            _logo_path(),
            _MARGIN + 5 * mm,
            band_top - band_h + 4.6 * mm,
            width=11 * mm,
            height=11.5 * mm,
            mask="auto",
        )

        self.setFillColor(self._theme.primary_text)
        self.setFont("Inter-Bold", 11)
        self.drawRightString(_PAGE_W - _MARGIN - 5 * mm, band_top - 8 * mm, bank_nama)
        self.setFont("Inter-Bold", 9)
        self.drawRightString(
            _PAGE_W - _MARGIN - 5 * mm, band_top - 14 * mm, "Laporan Riwayat Aktivitas"
        )

        self.setFillColor(self._theme.primary_text)
        info_x = _MARGIN + 22 * mm
        self.setFont("Inter", 7.5)
        self.drawString(info_x, band_top - 8 * mm, f"Nama: {nasabah_nama}")
        self.drawString(info_x, band_top - 13 * mm, f"No. Anggota: {nomor}")
        self.drawString(info_x, band_top - 18 * mm, f"Diunduh: {diunduh}")
        self.drawString(info_x + 52 * mm, band_top - 8 * mm, f"Periode: {periode}")
        self.drawString(info_x + 52 * mm, band_top - 13 * mm, f"Tipe: {tipe}")

    def _draw_footer(self, total: int) -> None:
        theme = self._theme
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
    # The header band + info grid live on the canvas (repeated on every page,
    # bank-letter style), so text content starts below them: topMargin reserves
    # their space.
    top_margin = _MARGIN + 26 * mm
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=top_margin,
        bottomMargin=_MARGIN,
        title="Laporan Riwayat Aktivitas",
        author=data.bank_nama,
    )
    doc.build(
        _flowables(data, theme),
        canvasmaker=lambda *args, **kwargs: NumberedCanvas(
            *args,
            header_data=(
                data.bank_nama,
                data.nasabah_nama,
                data.nomor_anggota,
                data.periode_label,
                data.tipe_label,
                data.diunduh,
            ),
            theme=theme,
            **kwargs,
        ),
    )
    return stream.getvalue()


def _flowables(data: StatementData, theme: Theme) -> list[object]:
    styles = dict(_STYLES)
    styles["subrow"].textColor = theme.subrow_text

    story: list[object] = []

    # --- Summary strip: 4 cells.
    summary = Table(
        [
            [
                Paragraph("Saldo Awal", styles["label"]),
                Paragraph("Total Setoran", styles["label"]),
                Paragraph("Total Pencairan", styles["label"]),
                Paragraph("Saldo Akhir", styles["label"]),
            ],
            [
                Paragraph("Rp " + format_ribuan(data.saldo_awal), styles["value"]),
                Paragraph("Rp " + format_ribuan(data.total_setoran), styles["value"]),
                Paragraph("Rp " + format_ribuan(data.total_pencairan), styles["value"]),
                Paragraph("Rp " + format_ribuan(data.saldo_akhir), styles["value"]),
            ],
        ],
        colWidths=[_TABLE_W / 4] * 4,
    )
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), theme.zebra),
                ("ROUNDEDCORNERS", [_RADIUS, _RADIUS, _RADIUS, _RADIUS]),
                ("BOX", (0, 0), (0, -1), 0.5, theme.accent),
                ("BOX", (1, 0), (1, -1), 0.5, theme.accent),
                ("BOX", (2, 0), (2, -1), 0.5, theme.accent),
                ("BOX", (3, 0), (3, -1), 0.5, theme.accent),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary)
    story.append(Spacer(1, 12))

    # --- Mutation table with detail sub-rows.
    story.append(_mutation_table(data.rows, theme, styles))
    return story


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
                Paragraph(row.keterangan, styles["cell"]),
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
                f"• {item.kategori} – {item.nama} "
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


def _logo_path() -> str:
    """Filesystem path of the vendored PILAH leaf logo (mobile assets)."""
    resource = resources.files("apps.reporting") / "fonts" / "logo.png"
    with resources.as_file(resource) as path:
        return str(path)
