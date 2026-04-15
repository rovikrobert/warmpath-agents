"""Fernet encryption for Contact PII columns.

EncryptedString / EncryptedText — SQLAlchemy TypeDecorators that
transparently encrypt on write and decrypt on read.  Business logic
sees plaintext; the database stores ciphertext.

compute_blind_index() — HMAC-SHA256 deterministic hash for exact-match
lookups on encrypted columns (suppression system, dedup).

**IMPORTANT**: SQL-level operations (ILIKE, LIKE, ==, !=, etc.) on
encrypted columns operate on ciphertext and produce wrong results.
Always load rows first and filter in Python where the ORM decrypts.
The Comparator subclass below logs warnings if SQL-level text
comparisons are generated, to catch this mistake early.
"""

import hashlib
import hmac
import logging
import warnings

from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.sql.expression import ColumnElement
from sqlalchemy.types import TypeDecorator

from app.config import settings
from app.utils.hashing import hash_for_suppression

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached Fernet singleton — avoids creating a new instance per value
# ---------------------------------------------------------------------------

_fernet: Fernet | None = None
_fernet_checked = False


def _get_fernet() -> Fernet | None:
    """Return the cached Fernet instance, or None if ENCRYPTION_KEY is empty."""
    global _fernet, _fernet_checked
    if not _fernet_checked:
        key = settings.ENCRYPTION_KEY
        if not key:
            logger.warning("ENCRYPTION_KEY not set — PII stored as plaintext")
            _fernet = None
        else:
            _fernet = Fernet(key.encode())
        _fernet_checked = True
    return _fernet


class _EncryptedComparator(TypeDecorator.Comparator):  # type: ignore[type-arg]
    """Warn when SQL-level text comparisons are used on encrypted columns.

    SQL operators like ILIKE, LIKE, ==, != operate on ciphertext in the
    database and will never match plaintext search terms.  Load rows first
    and filter in Python where the ORM decrypts transparently.
    """

    def _warn(self, op: str) -> None:
        col = getattr(self.expr, "key", self.expr)
        warnings.warn(
            f"SQL-level {op}() on encrypted column '{col}' operates on "
            "ciphertext — results will be wrong. Filter in Python instead.",
            stacklevel=4,
        )

    def ilike(self, other: object, **kw: object) -> ColumnElement[bool]:
        self._warn("ilike")
        return super().ilike(other, **kw)  # type: ignore[arg-type]

    def like(self, other: object, **kw: object) -> ColumnElement[bool]:
        self._warn("like")
        return super().like(other, **kw)  # type: ignore[arg-type]

    def contains(self, other: object, **kw: object) -> ColumnElement[bool]:
        self._warn("contains")
        return super().contains(other, **kw)  # type: ignore[arg-type]

    def startswith(self, other: object, **kw: object) -> ColumnElement[bool]:
        self._warn("startswith")
        return super().startswith(other, **kw)  # type: ignore[arg-type]

    def endswith(self, other: object, **kw: object) -> ColumnElement[bool]:
        self._warn("endswith")
        return super().endswith(other, **kw)  # type: ignore[arg-type]


class EncryptedString(TypeDecorator):
    """VARCHAR replacement that Fernet-encrypts on bind and decrypts on load.

    Stores as TEXT because ciphertext is longer than the original value.
    When ENCRYPTION_KEY is empty the column behaves like plain Text().
    """

    impl = Text
    cache_ok = True
    comparator_factory = _EncryptedComparator

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        f = _get_fernet()
        if f is None:
            return value
        return f.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect) -> str | None:
        if value is None:
            return None
        f = _get_fernet()
        if f is None:
            return value
        try:
            return f.decrypt(value.encode()).decode()
        except Exception:
            # Graceful fallback: pre-encryption plaintext rows survive migration.
            # Fernet tokens always start with "gAAAAA" so real plaintext will
            # fail decryption and fall through here.
            return value


class EncryptedText(TypeDecorator):
    """Text replacement for longer fields (notes, how_you_know)."""

    impl = Text
    cache_ok = True
    comparator_factory = _EncryptedComparator

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        f = _get_fernet()
        if f is None:
            return value
        return f.encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect) -> str | None:
        if value is None:
            return None
        f = _get_fernet()
        if f is None:
            return value
        try:
            return f.decrypt(value.encode()).decode()
        except Exception:
            return value


def compute_blind_index(value: str) -> str:
    """HMAC-SHA256 deterministic hash for exact-match lookups.

    Falls back to plain SHA-256 (existing suppression hashing) when
    BLIND_INDEX_KEY is not configured.
    """
    key = settings.BLIND_INDEX_KEY
    if not key:
        return hash_for_suppression(value)
    return hmac.new(
        key.encode(), value.lower().strip().encode(), hashlib.sha256
    ).hexdigest()
