import os
import sys
import threading
from threading import Event as ThreadEvent

from app import create_app
from werkzeug.serving import make_server


app = create_app()


def _port():
    try:
        return int(os.getenv('CAMPUSPULSE_PORT', '5000'))
    except ValueError:
        return 5000


def _browser_mode_requested():
    return os.getenv('CAMPUSPULSE_BROWSER', '0') == '1' or '--browser' in sys.argv[1:]


def start_desktop_app():
    import webview

    port = _port()
    server = make_server('127.0.0.1', port, app)
    server_ready = ThreadEvent()

    def serve():
        server_ready.set()
        server.serve_forever()

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()
    server_ready.wait()

    webview.create_window(
        'CampusPulse',
        f'http://127.0.0.1:{port}',
        width=1280,
        height=800,
        min_size=(960, 640),
    )
    webview.start()
    server.shutdown()


if __name__ == '__main__':
    if _browser_mode_requested():
        app.run(
            host='127.0.0.1',
            port=_port(),
            debug=os.getenv('FLASK_DEBUG', '0') == '1',
            use_reloader=False,
        )
    else:
        start_desktop_app()
