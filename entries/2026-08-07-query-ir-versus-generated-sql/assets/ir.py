"""Prototype compiler: query IR -> DuckDB SQL over the projection.

Enough of the grammar to answer the question the write-up asks: does compiling produce
the fast idiom by construction, and does it agree with hand-written SQL?
"""

import pyarrow as pa

from ord_schema import projection

_CMP = {"eq": "=", "ne": "<>", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}


def _field(current, name):
    """Returns the Arrow field ``name`` within a schema or struct type."""
    if isinstance(current, pa.Schema):
        return current.field(name)
    if pa.types.is_struct(current):
        return current.field(name)
    raise ValueError(f"cannot descend into {current} looking for {name!r}")


def _step(expr, listed, current, part, root=None):
    """Descends one path component, returning (expr, listed, type)."""
    field = _field(current, part)
    if expr is None:
        access = part if root is None else f"{root}.{part}"
        inner = field.type
    elif not listed:
        access, inner = f"{expr}.{part}", field.type
    else:
        access, inner = f"list_transform({expr}, x -> x.{part})", field.type
    if pa.types.is_map(inner):
        access = f"map_values({access})" if not listed else f"flatten({access})"
        return access, True, inner.item_type
    if pa.types.is_list(inner):
        access = f"flatten({access})" if listed else access
        return access, True, inner.value_type
    return access, listed, inner


def resolve(path, schema=projection.SCHEMA, root=None):
    """Returns (expr, listed, type) for a dotted path, validated against the schema.

    ``root`` is the bound variable a nested quantifier evaluates against; paths inside
    an exists/forall are relative to the element it binds.
    """
    expr, listed, current = None, False, schema
    for part in path.split("."):
        expr, listed, current = _step(expr, listed, current, part, root)
        root = None
    return expr, listed, current


def compile_predicate(node, scope=None, schema=projection.SCHEMA):
    """Compiles one predicate node to a boolean DuckDB expression."""
    op = node["op"]
    if op in ("and", "or"):
        joined = f" {op.upper()} ".join(
            compile_predicate(c, scope, schema) for c in node["clauses"]
        )
        return f"({joined})"
    if op == "not":
        return f"(NOT {compile_predicate(node['clause'], scope, schema)})"
    if op in ("exists", "forall"):
        expr, listed, inner = resolve(node["path"], schema, scope)
        if not listed:
            raise ValueError(f"{node['path']} is not a repeated level")
        var = f"e{node.get('depth', 0)}"
        body = compile_predicate(node["where"], var, inner)
        if op == "exists":
            return f"len(list_filter({expr}, {var} -> {body})) > 0"
        return f"len(list_filter({expr}, {var} -> NOT ({body}))) = 0"
    expr, listed, leaf = resolve(node["path"], schema, scope)
    if listed:
        raise ValueError(
            f"{node['path']} crosses a repeated level; wrap it in exists/forall so the "
            "quantifier is stated rather than assumed"
        )
    if op == "is_null":
        return f"{expr} IS NULL"
    if op == "not_null":
        return f"{expr} IS NOT NULL"
    value = node["value"]
    literal = f"${value['compound']}" if "compound" in value else repr(value["literal"])
    if op == "contains":
        return f"contains({expr}, {literal})"
    return f"{expr} {_CMP[op]} {literal}"


def compile_query(query, table="reactions", schema=projection.SCHEMA):
    """Compiles a whole query to SQL."""
    aggregate = query.get("aggregate")
    if aggregate:
        groups = [resolve(p, schema)[0] for p in aggregate.get("group_by", [])]
        measures = []
        for measure in aggregate["measures"]:
            path = measure.get("path")
            argument = resolve(path, schema)[0] if path else "*"
            measures.append(f"{measure['fn']}({argument}) AS {measure['as']}")
        select = ", ".join(groups + measures)
    else:
        select = "reaction_id"
    sql = f"SELECT {select} FROM {table}"
    if query.get("where"):
        sql += f" WHERE {compile_predicate(query['where'], None, schema)}"
    if aggregate and aggregate.get("group_by"):
        sql += " GROUP BY " + ", ".join(str(i + 1) for i in range(len(groups)))
    if query.get("order_by"):
        sql += " ORDER BY " + ", ".join(
            f"{o['key']}{' DESC' if o.get('desc') else ''}" for o in query["order_by"]
        )
    if query.get("limit"):
        sql += f" LIMIT {int(query['limit'])}"
    return sql
