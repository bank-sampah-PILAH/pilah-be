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
    Image,
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
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title="Laporan Riwayat Aktivitas",
        author=data.bank_nama,
    )
    doc.build(
        _flowables(data, theme),
        canvasmaker=NumberedCanvas,
    )
    return stream.getvalue()


def _flowables(data: StatementData, theme: Theme) -> list[object]:
    styles = dict(_STYLES)
    styles["subrow"].textColor = theme.subrow_text

    story: list[object] = []

    # --- Header band: logo + bank name + statement title.
    header = Table(
        [
            [
                _logo(),
                Paragraph(
                    f"{data.bank_nama}<br/>Laporan Riwayat Aktivitas",
                    ParagraphStyle(
                        "ht",
                        fontName="Inter-Bold",
                        fontSize=11,
                        leading=14,
                        textColor=theme.primary_text,
                        alignment=2,
                    ),
                ),
            ]
        ],
        colWidths=[_TABLE_W * 0.4, _TABLE_W * 0.6],
    )
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), theme.primary),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    story.append(header)
    story.append(Spacer(1, 8))

    # --- Info grid.
    info = Table(
        [
            [
                Paragraph("Nama", styles["label"]),
                Paragraph(": " + data.nasabah_nama, styles["value"]),
                Paragraph("No. Anggota", styles["label"]),
                Paragraph(": " + data.nomor_anggota, styles["value"]),
            ],
            [
                Paragraph("Periode", styles["label"]),
                Paragraph(": " + data.periode_label, styles["value"]),
                Paragraph("Tipe", styles["label"]),
                Paragraph(": " + data.tipe_label, styles["value"]),
            ],
            [
                Paragraph("Diunduh", styles["label"]),
                Paragraph(": " + data.diunduh, styles["value"]),
                Paragraph("", styles["label"]),
                Paragraph("", styles["value"]),
            ],
        ],
        colWidths=[_TABLE_W * 0.15, _TABLE_W * 0.35, _TABLE_W * 0.15, _TABLE_W * 0.35],
    )
    info.setStyle(
        TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)])
    )
    story.append(info)
    story.append(Spacer(1, 8))

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


def _logo() -> Image:
    """The PILAH leaf logo (mobile assets), scaled for the header band."""
    resource = resources.files("apps.reporting") / "fonts" / "logo.png"
    with resources.as_file(resource) as path:
        return Image(str(path), width=14 * mm, height=14 * mm)
