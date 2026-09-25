"""Additive schema changes: columns that exist in the models but not yet in a database.

create_all() creates missing tables but never alters existing ones. These helpers only add new nullable columns;
they never drop, rename or change data. Used by the upgrade-db command and for the demo sample's temporary copy.
"""
from sqlalchemy import inspect, text


def missing_columns(engine, metadata, tables=None):
    """ALTER TABLE statements for nullable model columns the database does not have yet, and the columns skipped."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    statements, skipped = [], []
    for table in metadata.sorted_tables:
        if table.name not in existing or (tables is not None and table.name not in tables):
            continue
        present = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            if not column.nullable:
                skipped.append(f"{table.name}.{column.name}")
                continue
            col_type = column.type.compile(dialect=engine.dialect)
            fk = next(iter(column.foreign_keys), None)
            ref = f" REFERENCES {fk.column.table.name}({fk.column.name})" if fk is not None else ""
            statements.append(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}{ref}")
    return statements, skipped


def apply(engine, statements):
    with engine.begin() as conn:
        for s in statements:
            conn.execute(text(s))
