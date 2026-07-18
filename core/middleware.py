from .health import healthz, readyz


class InternalProbeMiddleware:
    """Serve exact probe paths before proxy TLS and Host-header validation.

    Container and target-group health checks commonly use a private IP as the
    Host header over the internal HTTP hop. Only the two generic probe payloads
    bypass the normal middleware chain; every application route retains strict
    ALLOWED_HOSTS and HTTPS enforcement.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info == '/healthz/':
            return healthz(request)
        if request.path_info == '/readyz/':
            return readyz(request)
        return self.get_response(request)
