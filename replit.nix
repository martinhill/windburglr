{ pkgs }:
let
    nginxModified = pkgs.nginx.overrideAttrs (oldAttrs: rec {
        configureFlags = oldAttrs.configureFlags ++ [
            "--http-client-body-temp-path=/home/runner/windburglr/cache/client_body"
            "--http-proxy-temp-path=/home/runner/windburglr/cache/proxy"
            "--http-fastcgi-temp-path=/home/runner/windburglr/cache/fastcgi"
            "--http-uwsgi-temp-path=/home/runner/windburglr/cache/uwsgi"
            "--http-scgi-temp-path=/home/runner/windburglr/cache/scgi"
         ];
    });

in {
    deps = [
        nginxModified
        pkgs.python313
        pkgs.python313Packages.flask
        pkgs.python313Packages.waitress
        pkgs.python313Packages.psycopg2
        pkgs.python313Packages.fastapi
        pkgs.python313Packages.uvicorn
        pkgs.python313Packages.websockets
        pkgs.python313Packages.jinja2
        pkgs.python313Packages.sqlmodel
        pkgs.python313Packages.asyncpg
    ];
}
