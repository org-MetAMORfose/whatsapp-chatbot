#!/usr/bin/env bash
# Installs PostgreSQL, creates the database user and database, and applies schema.sql.
# Supports Ubuntu and Amazon Linux 2/2023.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration – override via environment variables before running
# ---------------------------------------------------------------------------
DB_NAME="${DB_NAME:-chatbot}"
DB_USER="${DB_USER:-chatbot}"
DB_PASSWORD="${DB_PASSWORD:-changeme}"
SCHEMA_FILE="$(dirname "$0")/schema.sql"

# ---------------------------------------------------------------------------
# Detect distro
# ---------------------------------------------------------------------------
detect_distro() {
    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        echo "$ID"
    else
        echo "unknown"
    fi
}

DISTRO=$(detect_distro)

# ---------------------------------------------------------------------------
# Install PostgreSQL
# ---------------------------------------------------------------------------
install_postgres() {
    echo ">>> Detected distro: $DISTRO"

    case "$DISTRO" in
        ubuntu | debian)
            echo ">>> Installing PostgreSQL (apt)..."
            sudo apt-get update -qq
            sudo apt-get install -y postgresql postgresql-contrib
            sudo systemctl enable postgresql
            sudo systemctl start postgresql
            ;;

        amzn)
            # Distinguish Amazon Linux 2 from Amazon Linux 2023
            if grep -q "VERSION_ID=\"2023\"" /etc/os-release 2>/dev/null; then
                echo ">>> Installing PostgreSQL (dnf – Amazon Linux 2023)..."
                sudo dnf install -y postgresql15 postgresql15-server
                sudo postgresql-setup --initdb
            else
                echo ">>> Installing PostgreSQL (amazon-linux-extras – Amazon Linux 2)..."
                sudo amazon-linux-extras enable postgresql14
                sudo yum install -y postgresql postgresql-server
                sudo postgresql-setup initdb
            fi
            sudo systemctl enable postgresql
            sudo systemctl start postgresql
            ;;

        *)
            echo "ERROR: Unsupported distro '$DISTRO'. Supported: ubuntu, debian, amzn." >&2
            exit 1
            ;;
    esac

    echo ">>> PostgreSQL installed and running."
}

# ---------------------------------------------------------------------------
# Create DB user and database
# ---------------------------------------------------------------------------
setup_database() {
    echo ">>> Creating user '$DB_USER' and database '$DB_NAME'..."

    sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE ROLE "$DB_USER" WITH LOGIN PASSWORD '$DB_PASSWORD';
    ELSE
        ALTER ROLE "$DB_USER" WITH PASSWORD '$DB_PASSWORD';
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE "$DB_NAME" OWNER "$DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')
\gexec
SQL

    echo ">>> User and database ready."
}

# ---------------------------------------------------------------------------
# Apply schema
# ---------------------------------------------------------------------------
apply_schema() {
    if [ ! -f "$SCHEMA_FILE" ]; then
        echo "WARNING: schema file not found at $SCHEMA_FILE, skipping." >&2
        return
    fi

    echo ">>> Applying schema from $SCHEMA_FILE..."
    sudo -u postgres psql -v ON_ERROR_STOP=1 -d "$DB_NAME" -f "$SCHEMA_FILE"
    echo ">>> Schema applied."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
install_postgres
setup_database
apply_schema

echo ""
echo "=== Done ==="
echo "  Database : $DB_NAME"
echo "  User     : $DB_USER"
echo "  Password : $DB_PASSWORD"
echo ""
echo "Connection string:"
echo "  postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME"
