"""Process composition root for HTTP and workflow entrypoints."""

from .container import ApplicationContainer, get_application_container

__all__ = ["ApplicationContainer", "get_application_container"]
