from calendar import monthrange
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from typing import cast
from uuid import UUID

from django.db.models import QuerySet, Sum
from django.http import HttpRequest
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from api.models import DetailTransaksi, Transaksi


def export_excel(
    queryset: QuerySet[Transaksi], request: HttpRequest | None = None
) -> tuple[bytes, str]:
    wb = Workbook()
    _fill_summary_export_sheet(cast(Worksheet, wb.active), queryset)
    _fill_raw_export_sheet(wb.create_sheet("Riwayat Transaksi"), queryset, request)
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue(), f"PILAH_Laporan_{_month_label()}.xlsx"


def _month_label() -> str:
    return timezone.localdate().strftime("%B_%Y")


def _fill_summary_export_sheet(ws: Worksheet, queryset: QuerySet[Transaksi]) -> None:
    ws.title = "Laporan"
    ws.append(["Jenis", "Sampah", "Harga per kg", "Jumlah kg", "Total"])
    rows = (
        DetailTransaksi.objects.filter(transaksi__in=queryset)
        .values("kategori_snapshot", "nama_sampah_snapshot", "harga_snapshot")
        .annotate(total_kg=Sum("berat"))
        .order_by("kategori_snapshot", "nama_sampah_snapshot")
    )
    current_row = 2
    for row in rows:
        ws.append(
            [
                row["kategori_snapshot"],
                row["nama_sampah_snapshot"],
                float(row["harga_snapshot"]),
                float(row["total_kg"]),
                f"=C{current_row}*D{current_row}",
            ]
        )
        current_row += 1
    ws.append(["", "", "", "TOTAL", f"=SUM(E2:E{current_row - 1})"])
    for column in ["A", "B", "C", "D", "E"]:
        ws.column_dimensions[column].width = 22


def _fill_raw_export_sheet(
    ws: Worksheet, queryset: QuerySet[Transaksi], request: HttpRequest | None = None
) -> None:
    ws.title = "Riwayat Transaksi"
    ws.merge_cells("A1:J1")
    ws.merge_cells("A2:J2")
    ws["A1"] = "PILAH - Riwayat Transaksi"
    ws["A2"] = _export_filter_label(queryset, request)
    ws.append([])
    ws.append(
        [
            "No",
            "Tanggal",
            "Waktu",
            "Nama Nasabah",
            "ID Nasabah",
            "Jenis Sampah",
            "Berat (kg)",
            "Harga/kg (Rp)",
            "Subtotal (Rp)",
            "Saldo Setelah Transaksi (Rp)",
        ]
    )

    details = (
        DetailTransaksi.objects.filter(transaksi__in=queryset)
        .select_related("transaksi__nasabah")
        .order_by("-transaksi__tanggal", "id")
    )
    saldo_after_by_transaction = _saldo_after_by_transaction(queryset)
    for number, item in enumerate(details, start=1):
        local_datetime = timezone.localtime(item.transaksi.tanggal)
        ws.append(
            [
                number,
                local_datetime.strftime("%d/%m/%Y"),
                local_datetime.strftime("%H:%M"),
                item.transaksi.nasabah.nama,
                item.transaksi.nasabah.nomor,
                item.nama_sampah_snapshot,
                float(item.berat),
                int(item.harga_snapshot),
                int(item.subtotal),
                int(saldo_after_by_transaction[item.transaksi_id]),
            ]
        )

    _style_raw_export_sheet(ws)


def _saldo_after_by_transaction(queryset: QuerySet[Transaksi]) -> dict[UUID, Decimal]:
    target_transactions = list(queryset.select_related("bank_sampah").order_by("tanggal", "id"))
    if not target_transactions:
        return {}

    target_ids = {trans.id for trans in target_transactions}
    nasabah_ids = {trans.nasabah_id for trans in target_transactions}
    latest_transaction = target_transactions[-1]
    bank_sampah = latest_transaction.bank_sampah
    running_balances = {nasabah_id: Decimal("0.00") for nasabah_id in nasabah_ids}
    saldo_after = {}

    transactions = (
        Transaksi.objects.filter(
            bank_sampah=bank_sampah,
            nasabah_id__in=nasabah_ids,
            tanggal__lte=latest_transaction.tanggal,
        )
        .only("id", "nasabah_id", "total_nilai", "tanggal")
        .order_by("nasabah_id", "tanggal", "id")
    )
    for trans in transactions:
        running_balances[trans.nasabah_id] += trans.total_nilai
        if trans.id in target_ids:
            saldo_after[trans.id] = running_balances[trans.nasabah_id]

    return saldo_after


def _export_filter_label(queryset: QuerySet[Transaksi], request: HttpRequest | None) -> str:
    first_transaction = queryset.first()
    bank_name = first_transaction.bank_sampah.nama if first_transaction else "-"
    downloaded_at = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    period_label = "Semua Periode"
    if request:
        period_label = _period_label(request)
    return f"Filter periode: {period_label}   |   Bank Sampah: {bank_name}   |   Diunduh: {downloaded_at}"


def _period_label(request: HttpRequest) -> str:
    periode = request.GET.get("periode", "hari_ini")
    today = timezone.localdate()
    if periode == "hari_ini":
        return f"Hari Ini ({today.strftime('%d/%m/%Y')})"
    if periode == "minggu_ini":
        start = today - timedelta(days=today.weekday())
        return f"Minggu Ini ({start.strftime('%d/%m/%Y')} - {today.strftime('%d/%m/%Y')})"
    if periode == "bulan_ini":
        end_day = monthrange(today.year, today.month)[1]
        return f"Bulan Ini (1 - {end_day} {_month_name(today.month)} {today.year})"
    if periode == "bulan_lalu":
        first_this_month = today.replace(day=1)
        previous_month = first_this_month - timedelta(days=1)
        end_day = monthrange(previous_month.year, previous_month.month)[1]
        return (
            f"Bulan Lalu (1 - {end_day} {_month_name(previous_month.month)} {previous_month.year})"
        )
    if periode == "custom":
        start_date = request.GET.get("dari_tanggal", "")
        end_date = request.GET.get("sampai_tanggal", "")
        return f"Custom ({start_date} - {end_date})"
    return "Semua Periode"


def _month_name(month: int) -> str:
    return [
        "Januari",
        "Februari",
        "Maret",
        "April",
        "Mei",
        "Juni",
        "Juli",
        "Agustus",
        "September",
        "Oktober",
        "November",
        "Desember",
    ][month - 1]


def _style_raw_export_sheet(ws: Worksheet) -> None:
    ws.freeze_panes = "A5"
    widths = {
        "A": 5,
        "B": 13,
        "C": 9,
        "D": 18,
        "E": 13,
        "F": 16,
        "G": 11,
        "H": 13,
        "I": 13,
        "J": 28,
    }
    for column, width in widths.items():
        ws.column_dimensions[column].width = width

    title_fill = PatternFill("solid", fgColor="166534")
    subtitle_fill = PatternFill("solid", fgColor="DCFCE7")
    header_fill = PatternFill("solid", fgColor="16A34A")
    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    ws["A1"].fill = title_fill
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws["A2"].font = Font(size=10, color="374151")
    ws["A2"].fill = subtitle_fill
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 22

    for row in ws.iter_rows(min_row=1, max_row=2, min_col=1, max_col=10):
        for cell in row:
            cell.fill = title_fill if cell.row == 1 else subtitle_fill

    for cell in ws[4]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row in ws.iter_rows(min_row=5, max_row=ws.max_row, min_col=1, max_col=10):
        for cell in row:
            cell.border = border
            cell.alignment = Alignment(vertical="center")
        row[0].alignment = Alignment(horizontal="center", vertical="center")
        row[6].number_format = "0.##"
        for cell in row[7:10]:
            cell.number_format = "#,##0"
