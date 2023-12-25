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
        pkgs.python310
        pkgs.python310Packages.flask
        pkgs.python310Packages.waitress
        pkgs.python310Packages.psycopg2
    ];
}
