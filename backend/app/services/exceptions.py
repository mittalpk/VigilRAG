"""Shared service-layer exceptions for VigilRAG backend (US-036)."""


class ConnectorUnavailableError(Exception):
    """Raised when a source connector cannot be reached or is intentionally disabled.

    Catching this per connector enables graceful degradation: exclude that
    connector's chunks from the merged result set and surface a
    ``source_availability_warning`` instead of failing the request with 5xx.
    """

    def __init__(self, connector_name: str, reason: str = ""):
        self.connector_name = connector_name
        self.reason = reason or f"{connector_name} connector unavailable"
        super().__init__(self.reason)

    @property
    def warning_code(self) -> str:
        """Canonical warning token used in API responses (e.g. github-unavailable)."""
        name = self.connector_name.strip().lower().replace("_", "-").replace(" ", "-")
        if name.endswith("-unavailable"):
            return name
        if name in ("github", "github-repo", "github_repo"):
            return "github-unavailable"
        if name in ("wiki", "confluence", "confluence-wiki", "confluence_wiki"):
            return "wiki-unavailable"
        if name in ("database", "database-schema", "database_schema"):
            return "database-unavailable"
        return f"{name}-unavailable"
