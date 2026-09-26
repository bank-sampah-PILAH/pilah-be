"""Regression safety net for the modular-monolith refactor.

Each subdirectory mirrors one bounded context, so the api/ split is
mechanical: move tests/<domain>/ alongside its module. Every test locks an
HTTP contract (status codes + response shapes, never message wording).

Rules: black-box HTTP only; shared setup lives in regression/helpers.py;
one domain per directory; platform/ holds what belongs to no domain.
"""
