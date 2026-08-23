from abc import ABC, abstractmethod


class CRMBackend(ABC):
    """Outbound CRM boundary; local SQLite remains the workflow source of truth."""

    @abstractmethod
    def upsert_account(self, domain, payload, remote_id=None):
        """Return the remote record ID after creating or updating an account."""
