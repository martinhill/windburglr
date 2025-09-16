{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = [
    # Core language runtimes
    pkgs.python313

    # Database
    pkgs.postgresql_15
    # timescaledb is "unfree" and not strictly needed for development
    # pkgs.postgresqlPackages.timescaledb

    # Package managers
    pkgs.uv

    # Essential system tools
    pkgs.git
    pkgs.curl
    pkgs.wget
  ];

  shellHook = ''
    echo "🚀 WindBurglr development environment (shell.nix)"
    echo "Python: $(python --version)"
    echo "PostgreSQL: $(postgres --version)"
    echo "uv: $(uv --version)"

    # Set up PostgreSQL data directory if it doesn't exist
    export PGDATA="$PWD/.pgdata"
    export PGHOST="$PWD/.pgdata"
    export PGSOCKET="$PWD/.pgdata"
    export PGPORT="5433"
    export PGUSER="$(whoami)"
    export PGDATABASE="windburglr"
    export TEST_DATABASE_URL="postgresql://$PGUSER@/$PGDATABASE"

    if [ ! -d "$PGDATA" ]; then
      echo "🗄️  Initializing PostgreSQL database..."
      initdb -D "$PGDATA" -U "$PGUSER" --auth=trust --no-locale --encoding=UTF8

      # Configure PostgreSQL to use local socket
      echo "unix_socket_directories = '$PGDATA'" >> "$PGDATA/postgresql.conf"
      echo "port = $PGPORT" >> "$PGDATA/postgresql.conf"

      # Start PostgreSQL
      pg_ctl -D "$PGDATA" -l "$PGDATA/logfile" start

      # Wait for PostgreSQL to start and socket to be created
      echo "⏳ Waiting for PostgreSQL to start..."
      for i in {1..30}; do
        if [ -S "$PGDATA/.s.PGSQL.$PGPORT" ] || [ -S "/tmp/.s.PGSQL.$PGPORT" ]; then
          echo "✅ PostgreSQL socket found"
          break
        fi
        echo "Waiting... ($i/30)"
        sleep 1
      done

      # Verify PostgreSQL is running
      if pg_ctl -D "$PGDATA" status > /dev/null 2>&1; then
        echo "✅ PostgreSQL is running"

        # Create database with explicit user
        if createdb -U "$PGUSER" "$PGDATABASE"; then
          echo "🗄️  Database '$PGDATABASE' created successfully"

          # Run database setup
          echo "Setting up test database schema... (ignore extension not available error)"
          psql -U "$PGUSER" "$PGDATABASE" -f ../common/timescaledb_schema.sql
        else
          echo "❌ Failed to create database '$PGDATABASE'"
          echo "💡 Try: createdb -h $PGDATA -p $PGPORT -U $PGUSER $PGDATABASE"
        fi
      else
        echo "❌ Failed to start PostgreSQL"
        echo "📄 Check logs: $PGDATA/logfile"
      fi
    else
      # Start existing database
      if ! pg_ctl -D "$PGDATA" status > /dev/null 2>&1; then
        echo "🗄️  Starting PostgreSQL database..."
        pg_ctl -D "$PGDATA" -l "$PGDATA/logfile" start

        # Wait for socket to be created
        echo "⏳ Waiting for PostgreSQL to start..."
        for i in {1..30}; do
          if [ -S "$PGDATA/.s.PGSQL.5432" ] || [ -S "/tmp/.s.PGSQL.5432" ]; then
            echo "✅ PostgreSQL socket found"
            break
          fi
          sleep 1
        done
      fi
    fi

    # Set up Python virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
      echo "📦 Setting up Python virtual environment..."
      uv venv .venv
    fi

    # Activate virtual environment
    source .venv/bin/activate

    # Install Python dependencies if requirements have changed
    if [ ! -f ".venv/.deps-installed" ] || [ pyproject.toml -nt .venv/.deps-installed ]; then
      echo "📦 Installing Python dependencies..."
      uv sync --extra dev
      touch .venv/.deps-installed
    fi

    # Load environment variables to facilitate sentry-build-plugin for "npm run build" command
    if [[ -f .env.sentry-build-plugin ]]; then
        export $(cat .env.sentry-build-plugin | xargs)
    fi

    echo ""
    echo "✅ Environment ready! Available commands:"
    echo "  ./start.sh          - Start the application"
    echo "  make dev            - Start both backend and frontend"
    echo "  make test           - Run all tests"
    echo "  make lint           - Lint and format code"
    echo ""
    echo "🗄️  Database commands:"
    echo "  psql                - Connect to database"
    echo "  pg_ctl stop         - Stop database"
    echo "  pg_ctl restart      - Restart database"
    echo ""
    echo "📝 Development workflow:"
    echo "  3. Database: $TEST_DATABASE_URL"
    echo ""
  '';
}
