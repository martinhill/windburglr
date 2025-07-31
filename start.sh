# start nginx
pkill nginx

nginx -e /home/runner/${REPL_SLUG}/logs/error.log -c /home/runner/${REPL_SLUG}/nginx.conf

# start FastAPI app
cd webapp-fastapi
python main.py