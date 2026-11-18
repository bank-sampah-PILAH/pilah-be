"""Keep every query contributing to an exported workbook on one snapshot."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, transaction


@contextmanager
def export_snapshot() -> Iterator[None]:
    # An outermost transaction is required: PostgreSQL cannot change isolation
    # after a caller has already read data. Fail rather than silently exporting
    # under an enclosing READ COMMITTED transaction.
    with transaction.atomic(durable=True):
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        yield
