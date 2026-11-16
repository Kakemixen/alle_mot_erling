# Gunicorn settings for running the quiz on a real server:
#
#   gunicorn -c gunicorn.conf.py app:app
#
# Every open page keeps one live-update connection (/api/events) open, and
# with the "gthread" worker each one occupies a thread. So: one process
# (the live-update notifications live in memory and are not shared between
# processes) with plenty of threads – one per expected player/screen plus some
# headroom for normal requests.
import os

# Behind nginx (recommended, see deploy/nginx.conf): listen only locally.
# To expose gunicorn directly instead, set BIND=0.0.0.0:8000.
bind = os.environ.get("BIND", "127.0.0.1:8000")

workers = 1  # must stay 1, see above
worker_class = "gthread"
threads = int(os.environ.get("THREADS", 300))

# Waiting live-update connections send a keep-alive every 15 s; this is about
# the worker's own heartbeat, not request length, so 60 s is plenty.
timeout = 60
# On restart, give open connections a few seconds, then close them; the
# browsers reconnect by themselves.
graceful_timeout = 5

accesslog = "-"  # log requests to stdout (shows up in journalctl with systemd)
