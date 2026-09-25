"""WSGI entry point for production servers and Google Cloud Run."""

from app import create_app


app = create_app()
