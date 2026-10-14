"""Nasabah riwayat statement: data assembly for the PDF export.

Assembles one nasabah's riwayat aktivitas (setoran + pencairan merged,
chronological, running saldo) into the data the renderer draws. Rendering
itself lives in render.py; HTTP concerns stay in the nasabah view. Money
formatting follows shared_kernel/kalkulasi.py (rupiah penuh, ROUND_DOWN).

The saldo walk always covers the member's FULL history: periode selects which
events are displayed, while saldo_awal stays the saldo accumulated before the
window — a "Bulan Ini" statement still opens with the correct opening balance.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from api.models import DetailTransaksi, Nasabah, Pencairan, Transaksi
from apps.ledger.api import apply_period
from apps.reporting import exporter
from shared_kernel.kalkulasi import bulatkan_rupiah

# The statement is a report, not an API timezone: labels are always WIB
# regardless of overrides to the project timezone.
_WIB = ZoneInfo("Asia/Jakarta")

# ponytail: full-history walk per statement (one nasabah, hundreds of events);
# switch to window aggregates if a member ever reaches thousands of events.

# Hard cap on displayed rows: the export renders the window into one PDF, and
# an uncapped all-time export degrades worse than linearly with history size.
# Hitting the cap asks the user for a narrower periode instead of silently
# truncating.
MAX_DISPLAYED_ROWS = 2000

_TIPE_LABELS = {"setoran": "Setoran", "pencairan": "Pencairan", "semua": "Semua"}

# PIL-246's month-window values: not yet known to apply_period, which would
# silently export all history under a label that promises a range. Reject
# until PIL-246 teaches the shared filter (and period_label) these values.
_NOT_YET_KNOWN_PERIODS = {"1_bulan", "3_bulan", "6_bulan", "12_bulan"}


class StatementPeriodError(ValueError):
    """A periode/tipe request this statement cannot serve (unknown month
    window, reversed custom range, oversized window).

    Subclassing ValueError keeps `apply_period`'s parse failures in the same
    family, while letting the export view distinguish them from any
    ValueError raised during rendering — rendering failures must surface as
    a 500, not a 400 echoing renderer internals.
    """


def _periode_label(request: HttpRequest) -> str:
    """Label for this export's window. ``period_label`` defaults to "Hari Ini",
    which is only true for the XLSX exports whose filter defaults there; this
    export defaults to no filter, so an omitted param must say all time."""
    if not request.GET.get("periode"):
        return "Semua Periode"
    return exporter.period_label(request)


@dataclass(frozen=True)
class _StatementEvent:
    """One merged ledger event awaiting the running-saldo walk."""

    tanggal: datetime
    is_setoran: bool
    event_id: UUID
    delta: Decimal  # saldo change; setoran positive, pencairan negative
    snapshot: Decimal | None  # pencairan receipt saldo (after the event)
    keterangan: str
    debit: Decimal
    kredit: Decimal


@dataclass(frozen=True)
class ItemRow:
    """One DetailTransaksi snapshot rendered as a setoran's sub-row."""

    kategori: str
    nama: str
    harga: Decimal
    berat: Decimal
    subtotal: Decimal


@dataclass(frozen=True)
class MutationRow:
    """One row of the mutation table (bank-statement style)."""

    id: UUID
    tanggal: datetime
    tipe: str  # "Setoran" | "Pencairan"
    keterangan: str
    debit: Decimal  # pencairan nominal (money out)
    kredit: Decimal  # setoran total_nilai (money in)
    saldo: Decimal  # running saldo after this event
    items: list[ItemRow] = field(default_factory=list)


@dataclass(frozen=True)
class StatementData:
    bank_nama: str
    bank_alamat: str
    bank_kota: str
    bank_no_hp: str
    nasabah_nama: str
    nasabah_email: str
    nasabah_no_hp: str
    nasabah_alamat: str
    nomor_anggota: str
    periode_label: str
    tipe_label: str
    diunduh: str
    saldo_awal: Decimal
    total_setoran: Decimal
    total_pencairan: Decimal
    saldo_akhir: Decimal
    rows: list[MutationRow] = field(default_factory=list)


def export_statement_pdf(member: Nasabah, request: HttpRequest) -> tuple[bytes, str] | None:
    """Build the nasabah statement PDF.

    Reads ``periode`` (+ ``dari_tanggal``/``sampai_tanggal`` for custom),
    ``tipe`` (semua/setoran/pencairan) and ``tema`` from the request params.
    Returns ``(bytes, filename)``, or ``None`` when the chosen window holds no
    activity (the view maps that to 400, matching the XLSX export convention).
    Raises ``StatementPeriodError`` (a ValueError) for a request the
    statement cannot serve: a PIL-246 month-window ``periode`` the shared
    filter cannot apply yet, a reversed custom range, or a window holding
    more rows than ``MAX_DISPLAYED_ROWS``. Rendering failures raise other
    exceptions and must surface as a 500, never a 400.
    """
    periode = request.GET.get("periode")
    if periode in _NOT_YET_KNOWN_PERIODS:
        raise StatementPeriodError(f"Periode '{periode}' belum tersedia untuk laporan ini.")
    data = build_statement(member, request)
    if not data.rows:
        return None
    # Late import: render.py imports this module's dataclasses (circular at
    # import time is avoided by resolving render only at call time).
    from apps.reporting.render import render_statement

    return render_statement(data, request.GET.get("tema", "pilah")), _filename(member)


def build_statement(member: Nasabah, request: HttpRequest) -> StatementData:
    """Assemble the statement data; rows carry computed running saldo."""
    setoran_qs = _filter_window(
        Transaksi.objects.filter(nasabah=member, bank_sampah=member.bank_sampah), request
    )
    pencairan_qs = _filter_window(
        Pencairan.objects.filter(nasabah=member, bank_sampah=member.bank_sampah), request
    )
    window = set(setoran_qs.values_list("id", flat=True)) | set(
        pencairan_qs.values_list("id", flat=True)
    )

    tipe = request.GET.get("tipe", "semua")
    if tipe not in _TIPE_LABELS:
        tipe = "semua"

    rows = _merge_with_running_saldo(
        Transaksi.objects.filter(nasabah=member, bank_sampah=member.bank_sampah),
        Pencairan.objects.filter(nasabah=member, bank_sampah=member.bank_sampah),
    )

    # Displayed rows: in the periode window and matching the tipe filter.
    # The index of the first displayed row is tracked in the same pass —
    # `rows.index(first)` would rescan the list once per export.
    displayed: list[MutationRow] = []
    first_index = 0
    for index, row in enumerate(rows):
        if row.id in window and (tipe == "semua" or row.tipe.lower() == tipe):
            if not displayed:
                first_index = index
            displayed.append(row)

    if len(displayed) > MAX_DISPLAYED_ROWS:
        raise StatementPeriodError(
            f"Periode ini memuat lebih dari {MAX_DISPLAYED_ROWS} transaksi — "
            "gunakan periode yang lebih sempit."
        )

    # Saldo just before the first displayed event: the walk's value prior to
    # it. The walk list is chronological, so it is the previous row's saldo
    # (or 0 before any event).
    saldo_awal = rows[first_index - 1].saldo if displayed and first_index > 0 else Decimal(0)

    return StatementData(
        bank_nama=member.bank_sampah.nama,
        bank_alamat=member.bank_sampah.alamat,
        bank_kota=member.bank_sampah.kota,
        bank_no_hp=member.bank_sampah.no_hp_pic,
        nasabah_nama=member.nama,
        nasabah_email=member.email,
        nasabah_no_hp=member.no_hp,
        nasabah_alamat=member.alamat,
        nomor_anggota=member.nomor,
        periode_label=_periode_label(request),
        tipe_label=_TIPE_LABELS[tipe],
        diunduh=timezone.localtime(timezone.now(), _WIB).strftime("%d/%m/%Y %H:%M"),
        saldo_awal=bulatkan_rupiah(saldo_awal),
        total_setoran=bulatkan_rupiah(sum((row.kredit for row in displayed), Decimal(0))),
        total_pencairan=bulatkan_rupiah(sum((row.debit for row in displayed), Decimal(0))),
        saldo_akhir=bulatkan_rupiah(displayed[-1].saldo if displayed else saldo_awal),
        rows=_with_detail_subrows(displayed),
    )


def _merge_with_running_saldo(
    setoran_qs: QuerySet[Transaksi], pencairan_qs: QuerySet[Pencairan]
) -> list[MutationRow]:
    """Merge both ledgers and walk the running saldo in one chronological pass.

    Sort key replicates BalanceService.saldo_at exactly (apps/ledger/
    services.py): at equal tanggal a setoran applies before a pencairan. The
    pencairan saldo delta (saldo_sesudah - saldo_sebelum, negative) is used
    for the walk instead of nominal, so the saldo lands on the stored Saldo
    even for legacy sen rows.
    """
    # One merged chronological stream: (tanggal, setoran_first, id, delta,
    # snapshot_or_none, payload); the walk below fills each row's saldo.
    events: list[_StatementEvent] = []

    for event in setoran_qs.only("id", "tanggal", "total_nilai", "catatan"):
        events.append(
            _StatementEvent(
                tanggal=event.tanggal,
                is_setoran=True,
                event_id=event.id,
                delta=event.total_nilai,
                snapshot=None,
                keterangan=event.catatan or "Setoran sampah",
                debit=Decimal(0),
                kredit=bulatkan_rupiah(event.total_nilai),
            )
        )
    for cairan in pencairan_qs.only(
        "id", "tanggal", "nominal", "saldo_sebelum", "saldo_sesudah", "metode", "keterangan"
    ):
        events.append(
            _StatementEvent(
                tanggal=cairan.tanggal,
                is_setoran=False,
                event_id=cairan.id,
                # Money out: saldo goes down (sign rule of the XLSX exporter's
                # merge, exporter._saldo_after_by_transaction).
                delta=cairan.saldo_sesudah - cairan.saldo_sebelum,
                # Snapshot wins: it is what the receipt recorded.
                snapshot=cairan.saldo_sesudah,
                keterangan=cairan.keterangan
                or f"Pencairan ({cairan.get_metode_display().lower()})",
                debit=cairan.nominal,
                kredit=Decimal(0),
            )
        )

    # Setoran first at equal tanggal: False < True sorts a setoran's slot first.
    events.sort(key=lambda event: (event.tanggal, not event.is_setoran, event.event_id))

    saldo = Decimal(0)
    rows: list[MutationRow] = []
    for item in events:
        saldo += item.delta
        after = item.snapshot if item.snapshot is not None else saldo
        if item.snapshot is not None:
            # Snapshot wins: it is what the receipt recorded. Rebase the walk
            # onto it so a legacy payout with no prior setoran (where the
            # unanchored walk would stay below the stored saldo) keeps every
            # later row and the final saldo consistent with the ledger.
            saldo = after
        rows.append(
            MutationRow(
                id=item.event_id,
                tanggal=item.tanggal,
                tipe="Setoran" if item.is_setoran else "Pencairan",
                keterangan=item.keterangan,
                debit=item.debit,
                kredit=item.kredit,
                saldo=bulatkan_rupiah(after),
            )
        )
    return rows


def _with_detail_subrows(rows: list[MutationRow]) -> list[MutationRow]:
    """Attach DetailTransaksi snapshots to setoran rows (super detail)."""
    setoran_ids = [row.id for row in rows if row.tipe == "Setoran"]
    if not setoran_ids:
        return rows
    grouped: dict[UUID, list[ItemRow]] = {}
    for item in DetailTransaksi.objects.filter(transaksi_id__in=setoran_ids).order_by("id"):
        grouped.setdefault(item.transaksi_id, []).append(
            ItemRow(
                kategori=item.kategori_snapshot,
                nama=item.nama_sampah_snapshot,
                harga=item.harga_snapshot,
                berat=item.berat,
                subtotal=bulatkan_rupiah(item.subtotal),
            )
        )
    return [_rebuild(row, grouped.get(row.id, [])) for row in rows]


def _rebuild(row: MutationRow, items: list[ItemRow]) -> MutationRow:
    return MutationRow(
        id=row.id,
        tanggal=row.tanggal,
        tipe=row.tipe,
        keterangan=row.keterangan,
        debit=row.debit,
        kredit=row.kredit,
        saldo=row.saldo,
        items=items,
    )


def _filter_window(
    queryset: QuerySet[Transaksi] | QuerySet[Pencairan], request: HttpRequest
) -> QuerySet[Transaksi] | QuerySet[Pencairan]:
    try:
        return apply_period(queryset, request, default=None)  # type: ignore[return-value]
    except ValueError as exc:
        # apply_period signals a bad periode (e.g. a reversed custom range)
        # via ValueError; re-tag it so the view's period-only catch keeps
        # separating request errors from rendering errors.
        raise StatementPeriodError(str(exc)) from exc


def _filename(member: Nasabah) -> str:
    return f"Riwayat_Aktivitas_{member.nomor}.pdf"
