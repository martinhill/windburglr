{
  description = "WindBurglr development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        # Matches production (Aiven, PostgreSQL 18). The Apache-licensed TimescaleDB build is free,
        # unlike the TSL build, and covers everything the schema uses (create_hypertable).
        postgresql = pkgs.postgresql_18.withPackages (p: [ p.timescaledb-apache ]);

        basePackages = [
          pkgs.python313
          postgresql
          pkgs.uv
          pkgs.git
          pkgs.curl
        ];

        # Environment only: no side effects, so it is cheap to load on every command
        # (direnv, agent shells). Start the database explicitly with `scripts/db.sh up`.
        mkShell = extraPackages: pkgs.mkShell {
          packages = basePackages ++ extraPackages;
          # On Linux, prebuilt (manylinux) wheels such as greenlet need libstdc++, which the
          # Nix Python can't find by itself
          LD_LIBRARY_PATH = pkgs.lib.optionalString pkgs.stdenv.hostPlatform.isLinux
            (pkgs.lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib ]);
          shellHook = ''
            source "$(git rev-parse --show-toplevel)/scripts/dev-env.sh"
          '';
        };
      in
      {
        devShells = {
          default = mkShell [ ];
          scraper = mkShell [ ];
          webapp = mkShell [ pkgs.nodejs_24 pkgs.pyright ];
        };
      });
}
