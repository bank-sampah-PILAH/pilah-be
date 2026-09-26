# ponytail: compat shim — canonical home is shared_kernel.health.
from shared_kernel.health import healthz  # noqa: F401

__all__ = ["healthz"]
