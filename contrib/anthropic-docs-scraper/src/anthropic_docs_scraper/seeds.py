"""Default seed URLs for the Anthropic docs scraper.

Anthropic exposes markdown versions of every docs page. These seeds cover the
API reference surfaces where endpoints are documented.
"""

DEFAULT_URLS: list[str] = [
    # Messages / core API
    "https://platform.claude.com/docs/en/api/messages.md",
    "https://platform.claude.com/docs/en/api/messages-count-tokens.md",
    "https://platform.claude.com/docs/en/api/messages-streaming.md",
    # Models
    "https://platform.claude.com/docs/en/api/models-list.md",
    "https://platform.claude.com/docs/en/api/models.md",
    # Batches
    "https://platform.claude.com/docs/en/api/creating-message-batches.md",
    "https://platform.claude.com/docs/en/api/retrieving-message-batches.md",
    "https://platform.claude.com/docs/en/api/listing-message-batches.md",
    "https://platform.claude.com/docs/en/api/canceling-message-batches.md",
    "https://platform.claude.com/docs/en/api/deleting-message-batches.md",
    "https://platform.claude.com/docs/en/api/retrieving-message-batch-results.md",
    # Files
    "https://platform.claude.com/docs/en/api/files-create.md",
    "https://platform.claude.com/docs/en/api/files-list.md",
    "https://platform.claude.com/docs/en/api/files-metadata.md",
    "https://platform.claude.com/docs/en/api/files-content.md",
    "https://platform.claude.com/docs/en/api/files-delete.md",
    # Rate limits / errors
    "https://platform.claude.com/docs/en/api/rate-limits.md",
    "https://platform.claude.com/docs/en/api/errors.md",
    # Admin API
    "https://platform.claude.com/docs/en/api/admin-api/apikeys/get-api-key.md",
    "https://platform.claude.com/docs/en/api/admin-api/apikeys/list-api-keys.md",
    "https://platform.claude.com/docs/en/api/admin-api/apikeys/update-api-keys.md",
    # Managed Agents API reference
    "https://platform.claude.com/docs/en/managed-agents/overview.md",
    "https://platform.claude.com/docs/en/managed-agents/quickstart.md",
    "https://platform.claude.com/docs/en/managed-agents/agent-setup.md",
    "https://platform.claude.com/docs/en/managed-agents/sessions.md",
    "https://platform.claude.com/docs/en/managed-agents/environments.md",
    "https://platform.claude.com/docs/en/managed-agents/events-and-streaming.md",
    "https://platform.claude.com/docs/en/managed-agents/tools.md",
    "https://platform.claude.com/docs/en/managed-agents/files.md",
    "https://platform.claude.com/docs/en/managed-agents/vaults.md",
]
