from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    if response.status_code == 400 and isinstance(response.data, dict):
        response.status_code = 422
        response.data = {"errors": response.data}
    elif response.status_code == 401:
        response.data = {"error": "Token tidak ada, invalid, atau expired"}
    elif response.status_code == 403:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        response.data = {"error": str(detail or "Akses ditolak")}
    elif response.status_code == 404:
        response.data = {"error": "Resource tidak ditemukan"}
    return response
