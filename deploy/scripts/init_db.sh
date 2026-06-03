#!/bin/bash
# ============================================
# Database Initialization Script
# ============================================
# Run after docker-compose up to seed initial data
# ============================================

set -e

echo "Initializing OpenClaw Sandbox RPG database..."

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
until docker exec sandbox-rpg-postgres pg_isready -U rpg_user -d sandbox_rpg; do
    sleep 2
done

echo "PostgreSQL is ready."

# Run backend migrations (will be implemented in backend module)
# docker exec sandbox-rpg-backend alembic upgrade head

# Load default world package
echo "Loading default world package (D&D 5e Forgotten Realms)..."
# docker exec sandbox-rpg-backend python -m backend.scripts.load_world worlds/dnd_5e_forgotten_realms.yaml

echo "Database initialization complete!"
echo ""
echo "Next steps:"
echo "  1. Access frontend: http://localhost:5173"
echo "  2. Access API docs: http://localhost:8000/docs"
echo "  3. Check logs: docker-compose logs -f"
