from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from .registry import ToolRegistry


def query_sqlite(database: str, query: str) -> str:
    """Execute a SQL query against a SQLite database file."""
    p = Path(database)

    # Allow creating new databases
    if not p.exists() and not query.strip().upper().startswith(("CREATE", "ATTACH")):
        return json.dumps({"error": f"Database not found: {database}"})

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query)

        # Check if it's a SELECT/PRAGMA or data-modifying statement
        q_upper = query.strip().upper()
        if q_upper.startswith(("SELECT", "PRAGMA", "EXPLAIN")):
            rows = cursor.fetchmany(100)  # Cap at 100 rows
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            data = [dict(row) for row in rows]
            result = {
                "columns": columns,
                "row_count": len(data),
                "rows": data,
            }
            if len(data) == 100:
                result["truncated"] = True
        else:
            conn.commit()
            result = {
                "status": "ok",
                "rows_affected": cursor.rowcount,
            }

        conn.close()
        output = json.dumps(result, default=str, separators=(",", ":"))
        return output[:6_000] if len(output) > 6_000 else output

    except sqlite3.Error as e:
        return json.dumps({"error": f"SQLite error: {e}"})
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# -- Registration ------------------------------------------------------------

def register(registry: ToolRegistry):
    registry.register(
        name="query_sqlite",
        description="Execute a SQL query on a SQLite database file. SELECT returns rows (max 100). INSERT/UPDATE/DELETE returns rows_affected. Creates the database if it doesn't exist for CREATE statements.",
        parameters={
            "type": "object",
            "properties": {
                "database": {"type": "string", "description": "Absolute path to the SQLite database file"},
                "query": {"type": "string", "description": "SQL query to execute"},
            },
            "required": ["database", "query"],
        },
        handler=query_sqlite,
    )
