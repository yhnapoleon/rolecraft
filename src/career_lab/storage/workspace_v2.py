"""workspace persistence is owned solely by shared protocol V2Store.

This compatibility module exports public plan types only. It declares no table,
transaction, idempotency ledger or version clock. Install the workspace operations via
career_lab.workspace.extension.install_workspace_operations.
"""

from career_lab.storage.v2_store import V2Store, ObjectWrite, Mutation

__all__ = ["V2Store", "ObjectWrite", "Mutation"]
