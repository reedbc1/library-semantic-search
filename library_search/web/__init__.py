"""Flask application factory for the library search web interface."""

import logging
from collections.abc import Callable
from typing import Any

from flask import Flask, render_template, request

from library_search.config import Settings
from library_search.errors import ApplicationError, InputValidationError
from library_search.search import search_catalog

logger = logging.getLogger(__name__)
SearchFunction = Callable[[Settings, str | None], list[dict[str, Any]]]


def create_app(
    settings: Settings | None = None,
    *,
    search_function: SearchFunction | None = None,
) -> Flask:
    resolved_settings = settings or Settings.from_env(
        require_openai_api_key=search_function is None
    )
    resolved_settings.validate(
        require_openai_api_key=search_function is None
    )
    application = Flask(__name__)
    application.config["SETTINGS"] = resolved_settings
    application.config["SEARCH_FUNCTION"] = search_function or search_catalog

    @application.get("/")
    def index():
        return render_template("index.html")

    @application.get("/search")
    def search():
        query = request.args.get("query")
        try:
            records = application.config["SEARCH_FUNCTION"](
                application.config["SETTINGS"], query
            )
        except InputValidationError as error:
            return str(error), 400
        except ApplicationError:
            logger.exception("search request failed")
            return "Search is temporarily unavailable.", 503
        return render_template("results.html", results=records)

    return application
