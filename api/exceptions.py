# ponytail: compat shim — canonical home is shared_kernel.exceptions.
from shared_kernel.exceptions import api_exception_handler  # noqa: F401

__all__ = ["api_exception_handler"]
