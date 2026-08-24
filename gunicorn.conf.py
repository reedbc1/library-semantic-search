wsgi_app = "library_search.web:create_app()"
bind = "0.0.0.0:8001"
workers = 4
accesslog = "-"
