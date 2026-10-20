"""Catalog-owned typed core rows and exact ordered occurrence values.

A logical row may exceed a native chunk. Only explicit full logical reads
reassemble it; projected core reads never fetch occurrence data.
"""

from collections import OrderedDict
import base64
from copy import deepcopy
from hashlib import sha256

import pyarrow as pa
import pyarrow.compute as pc

from .immutable_metadata import MetadataObjects, encoded

FORMAT = "catalog-typed-occurrences-v1"
COUNT = "_catalog_occurrence_count"
ROW = "_catalog_physical_row"


def _layout(schema):
    if "source_occurrences" in schema.names:
        return None, schema.field("source_occurrences")
    if "source_values" in schema.names:
        field = schema.field("source_values")
        if pa.types.is_struct(field.type) and "source_occurrences" in [
            f.name for f in field.type
        ]:
            return "source_values", field.type.field("source_occurrences")
    return None


def _occurrences(table, layout):
    parent, _ = layout
    array = (
        table[parent].combine_chunks().field("source_occurrences")
        if parent
        else table["source_occurrences"].combine_chunks()
    )
    return array


def core_table(table):
    """Replace only the repeated field; retain original schema fields/metadata."""
    layout = _layout(table.schema)
    if layout is None:
        return table
    if COUNT in table.schema.names or ROW in table.schema.names:
        raise ValueError("Catalog logical schema uses reserved occurrence fields")
    parent, _ = layout
    original = _occurrences(table, layout)
    if parent:
        field = table.schema.field(parent)
        values = table[parent].combine_chunks()
        fields = [f for f in field.type if f.name != "source_occurrences"]
        reduced = pa.StructArray.from_arrays(
            [values.field(f.name) for f in fields], fields=fields, mask=values.is_null()
        )
        result = table.set_column(
            table.schema.get_field_index(parent),
            field.with_type(pa.struct(fields)),
            reduced,
        )
    else:
        result = table.drop(["source_occurrences"])
    return result.append_column(
        COUNT, pc.list_value_length(original).cast(pa.int64())
    ).append_column(ROW, pa.array(range(len(table)), type=pa.int64()))


def core_bytes(table):
    return core_table(table).nbytes


def fits_chunk(table, *, max_rows, max_bytes):
    """Bound both retained logical values and physical core; isolate giant rows."""
    return (
        len(table) <= max_rows
        and core_bytes(table) <= max_bytes
        and (table.nbytes <= max_bytes or len(table) == 1)
    )


def row_bytes(batch):
    """Additive exact Arrow row accounting without repeated wide-row slicing."""
    base, variable = 0, []
    for column in batch.columns:
        constant = column.null_count == len(column)
        if constant and pa.types.is_list(column.type):
            constant = column.offsets[0].as_py() == column.offsets[-1].as_py()
        if constant and pa.types.is_string(column.type):
            offsets = memoryview(column.buffers()[1]).cast("i")
            constant = offsets[column.offset] == offsets[column.offset + len(column)]
        if constant and not (
            pa.types.is_list(column.type)
            or pa.types.is_string(column.type)
            or pa.types.is_integer(column.type)
            or pa.types.is_floating(column.type)
            or pa.types.is_boolean(column.type)
            or pa.types.is_temporal(column.type)
            or pa.types.is_decimal(column.type)
            or pa.types.is_fixed_size_binary(column.type)
            or pa.types.is_null(column.type)
        ):
            constant = False
        if constant:
            base += column.slice(0, 1).nbytes
        else:
            variable.append(column)
    return [
        base + sum(column.slice(i, 1).nbytes for column in variable)
        for i in range(len(batch))
    ]


def _source_projection(table, output_schema, source_columns):
    if source_columns is None:
        return table
    field = output_schema.field("source_values")
    original = table["source_values"].combine_chunks()
    fields = list(field.type)
    values = pa.StructArray.from_arrays(
        [original.field(f.name) for f in fields], fields=fields, mask=original.is_null()
    )
    return table.set_column(
        output_schema.get_field_index("source_values"), field, values
    )


class _ArrayOccurrences:
    def __init__(self, values):
        self.values = values

    def __len__(self):
        return len(self.values)

    def __iter__(self):
        if len(self.values):
            yield self.values


class Occurrences:
    """Repeatable original struct chunks; length never deduplicates occurrences."""

    def __init__(self, owner, pin, schema, row, count):
        self.owner, self.pin, self.schema, self.row, self.count = (
            owner,
            pin,
            schema,
            row,
            count,
        )

    def __len__(self):
        return self.count

    def __iter__(self):
        return self.owner._occurrence_batches(
            self.pin, self.schema, self.row, self.count
        )


class CatalogRows:
    def __init__(self, *, native, store):
        self.native, self.store = native, store
        self.objects = MetadataObjects(
            store, "catalog-occurrences-v1", max_cache_entries=16
        )
        self._cached = None
        self._children = OrderedDict()
        self.rows_read = self.bytes_read = 0
        self.candidate_rows_submitted = self.candidate_arrow_bytes = 0

    def _run_native(self, table, **request):
        release = self.native.run_table(table, **request)
        self.candidate_rows_submitted += len(table)
        self.candidate_arrow_bytes += table.nbytes
        return release

    def _record_read(self, batch):
        self.rows_read += len(batch)
        self.bytes_read += batch.nbytes

    def _node(self, values, *, parts=False):
        summaries = (
            [
                dict(
                    first=v["index"],
                    parts=1,
                    rows=v["rows"],
                    owner_min=v["owner_min"],
                    owner_max=v["owner_max"],
                )
                for v in values
            ]
            if parts
            else [v["summary"] for v in values]
        )
        summary = dict(
            first=summaries[0]["first"],
            parts=sum(v["parts"] for v in summaries),
            rows=sum(v["rows"] for v in summaries),
            owner_min=min(v["owner_min"] for v in summaries),
            owner_max=max(v["owner_max"] for v in summaries),
        )
        page = dict(
            format=FORMAT,
            summary=summary,
            **({"parts": values} if parts else {"children": values}),
        )
        return dict(self.objects.put(page), summary=summary)

    def write(
        self,
        table,
        *,
        dataset,
        operation,
        definition,
        max_rows,
        max_bytes,
        owner_column="source_id",
    ):
        if (
            type(max_rows) is not int
            or max_rows < 1
            or type(max_bytes) is not int
            or max_bytes < 1
        ):
            raise ValueError("Catalog row budgets must be positive integers")
        if not fits_chunk(table, max_rows=max_rows, max_bytes=max_bytes):
            raise ValueError(
                "Catalog logical/core chunk exceeds its retained byte budget"
            )
        layout = _layout(table.schema)
        if layout is None:
            if len(table) > max_rows or table.nbytes > max_bytes:
                raise ValueError("Catalog core exceeds its native chunk budget")
            return self._run_native(
                table, dataset=dataset, operation=operation, definition=definition
            )
        core = core_table(table).combine_chunks()
        if len(core) > max_rows or core.nbytes > max_bytes:
            raise ValueError("Catalog core exceeds its native chunk budget")
        ids = core[owner_column].to_pylist()
        if len(set(ids)) != len(ids) or any(
            not isinstance(v, str) or not v for v in ids
        ):
            raise ValueError("Catalog occurrence owners must be nonempty and unique")
        original = _occurrences(table, layout)
        field = layout[1]
        if not pa.types.is_list(field.type) or not pa.types.is_struct(
            field.type.value_type
        ):
            raise ValueError(
                "Catalog occurrences require the original list of struct type"
            )
        child_schema = pa.schema(
            [
                pa.field("owner_row", pa.int64(), nullable=False),
                pa.field("owner_id", pa.string(), nullable=False),
                pa.field("occurrence_order", pa.int64(), nullable=False),
                pa.field("value", field.type.value_type),
            ]
        )
        pending, size, pending_rows, part_count, occurrence_count, levels = (
            [],
            0,
            0,
            0,
            0,
            [],
        )

        def push(level, reference):
            while len(levels) <= level:
                levels.append([])
            levels[level].append(reference)
            if len(levels[level]) == 16:
                node = self._node(levels[level])
                levels[level] = []
                push(level + 1, node)

        def flush():
            nonlocal pending, size, pending_rows, part_count
            if not pending:
                return
            values = pa.concat_tables(pending).combine_chunks()
            release = self._run_native(
                values,
                dataset=f"{dataset}-occ-{part_count}",
                operation=operation,
                definition=FORMAT,
            )
            orders = values["owner_row"].to_pylist()
            part = dict(
                index=part_count,
                release=release,
                rows=len(values),
                arrow_bytes=values.nbytes,
                owner_min=min(orders),
                owner_max=max(orders),
            )
            push(0, self._node([part], parts=True))
            part_count += 1
            pending = []
            size = 0
            pending_rows = 0

        for position, value in enumerate(original):
            if not value.is_valid:
                continue
            values = value.values
            start = 0
            while start < len(values):
                # Find a byte-bounded prefix without materializing Python structs.
                take = min(max_rows, len(values) - start)

                def child(count):
                    return pa.Table.from_arrays(
                        [
                            pa.array([position] * count, type=pa.int64()),
                            pa.array([ids[position]] * count),
                            pa.array(range(start, start + count), type=pa.int64()),
                            values.slice(start, count),
                        ],
                        schema=child_schema,
                    )

                piece = child(take)
                while piece.nbytes > max_bytes and take > 1:
                    take = max(1, take // 2)
                    piece = child(take)
                if piece.nbytes > max_bytes:
                    raise ValueError(
                        "One catalog occurrence exceeds its native chunk budget"
                    )
                if pending and (
                    pending_rows + take > max_rows or size + piece.nbytes > max_bytes
                ):
                    flush()
                pending.append(piece)
                size += piece.nbytes
                pending_rows += take
                occurrence_count += take
                start += take
                if pending_rows == max_rows:
                    flush()
        flush()
        roots = [reference for level in reversed(levels) for reference in level]
        while len(roots) > 16:
            roots = [self._node(roots[i : i + 16]) for i in range(0, len(roots), 16)]
        root = self._node(roots) if roots else None
        release = self._run_native(
            core,
            dataset=dataset,
            operation=operation,
            definition=FORMAT + "-" + definition,
        )
        descriptor = dict(
            format=FORMAT,
            schema=base64.b64encode(table.schema.serialize()).decode(),
            owner_column=owner_column,
            rows=len(table),
            occurrences=occurrence_count,
            parts=part_count,
            root=root,
            max_rows=max_rows,
            max_bytes=max_bytes,
        )
        descriptor["binding"] = sha256(
            encoded(dict(core=release, descriptor=descriptor))
        ).hexdigest()
        return dict(release, catalog_rows=descriptor)

    def _checked(self, pin, schema):
        descriptor = deepcopy(pin.get("catalog_rows"))
        if descriptor is None:
            return None
        core = {key: value for key, value in pin.items() if key != "catalog_rows"}
        binding = descriptor.pop("binding", None)
        if (
            binding
            != sha256(encoded(dict(core=core, descriptor=descriptor))).hexdigest()
        ):
            raise ValueError("Catalog occurrence descriptor binding differs")
        if descriptor.get("format") != FORMAT or not _layout(schema):
            raise ValueError("Catalog occurrence format differs")
        saved = pa.ipc.read_schema(
            pa.BufferReader(base64.b64decode(descriptor["schema"], validate=True))
        )
        if not saved.equals(schema, check_metadata=True):
            raise ValueError("Catalog occurrence logical schema differs")
        if any(
            type(descriptor.get(k)) is not int or descriptor[k] < 0
            for k in ("rows", "occurrences", "parts")
        ) or any(
            type(descriptor.get(k)) is not int or descriptor[k] < 1
            for k in ("max_rows", "max_bytes")
        ):
            raise ValueError("Invalid catalog occurrence descriptor counts")
        if (descriptor["root"] is None) != (descriptor["parts"] == 0) or descriptor[
            "rows"
        ] > descriptor["max_rows"]:
            raise ValueError("Catalog occurrence part coverage differs")
        return core, descriptor

    def _core(self, pin, schema):
        checked = self._checked(pin, schema)
        if checked is None:
            return None
        release, descriptor = checked
        key = sha256(encoded(pin)).hexdigest()
        if self._cached and self._cached[0] == key:
            return self._cached[1], descriptor
        empty = pa.Table.from_batches([], schema=schema)
        physical = core_table(empty).schema
        tables = []
        rows = size = 0
        with self.native.source_batches(release, schema=physical) as reader:
            if not reader.schema.equals(physical, check_metadata=False):
                raise ValueError("Catalog core schema differs")
            for batch in reader:
                self._record_read(batch)
                rows += len(batch)
                size += batch.nbytes
                if rows > descriptor["max_rows"] or size > descriptor["max_bytes"]:
                    raise ValueError("Catalog core exceeds selected physical budget")
                tables.append(batch)
        table = (
            pa.Table.from_batches(tables, schema=physical).sort_by(ROW).combine_chunks()
        )
        if rows != descriptor["rows"] or table[ROW].to_pylist() != list(range(rows)):
            raise ValueError("Catalog core row coverage differs")
        ids = table[descriptor["owner_column"]].to_pylist()
        counts = table[COUNT].to_pylist()
        if (
            len(set(ids)) != rows
            or any(not isinstance(v, str) or not v for v in ids)
            or any(v is not None and (type(v) is not int or v < 0) for v in counts)
            or sum(v or 0 for v in counts) != descriptor["occurrences"]
        ):
            raise ValueError("Catalog occurrence owner/count coverage differs")
        total = 0
        for part in self._parts(descriptor):
            if (
                type(part.get("rows")) is not int
                or not 0 < part["rows"] <= descriptor["max_rows"]
                or not 0 <= part["owner_min"] <= part["owner_max"] < rows
            ):
                raise ValueError("Catalog occurrence part owner coverage differs")
            total += part["rows"]
        if total != descriptor["occurrences"]:
            raise ValueError("Catalog occurrence complete coverage differs")
        self._owner_positions = {
            identity: position for position, identity in enumerate(ids)
        }
        self._cached = key, table
        return table, descriptor

    def _parts(self, descriptor, row=None):
        index = 0

        def walk(reference, depth=0):
            nonlocal index
            if depth > 64:
                raise ValueError("Catalog occurrence directory depth exceeds bound")
            summary = reference.get("summary", {})
            if (
                summary.get("first") != index
                or type(summary.get("parts")) is not int
                or summary["parts"] < 1
            ):
                raise ValueError("Catalog occurrence directory coverage differs")
            if (
                row is not None
                and not summary["owner_min"] <= row <= summary["owner_max"]
            ):
                index += summary["parts"]
                return
            node = self.objects.read(reference)
            if (
                node.get("format") != FORMAT
                or node.get("summary") != summary
                or ("parts" in node) == ("children" in node)
            ):
                raise ValueError("Catalog occurrence directory differs")
            values = node.get("parts", node.get("children"))
            if not isinstance(values, list) or not 0 < len(values) <= 16:
                raise ValueError("Invalid catalog occurrence directory page")
            ranges = (
                values if "parts" in node else [value["summary"] for value in values]
            )
            if summary["owner_min"] != min(v["owner_min"] for v in ranges) or summary[
                "owner_max"
            ] != max(v["owner_max"] for v in ranges):
                raise ValueError("Catalog occurrence directory owner range differs")
            first = index
            total = 0
            if "parts" in node:
                for part in values:
                    if part.get("index") != index:
                        raise ValueError("Catalog occurrence part ordering differs")
                    index += 1
                    total += part["rows"]
                    if row is None or part["owner_min"] <= row <= part["owner_max"]:
                        yield part
            else:
                for child in values:
                    total += child["summary"]["rows"]
                    yield from walk(child, depth + 1)
            if index - first != summary["parts"] or total != summary["rows"]:
                raise ValueError("Catalog occurrence directory count differs")

        if descriptor["root"] is not None:
            yield from walk(descriptor["root"])
        if index != descriptor["parts"]:
            raise ValueError("Catalog occurrence part count differs")

    def _legacy_table(self, pin, schema):
        # Existing exact unsplit native pins are already limited by the prior
        # catalog format. This adapter retains that one bounded historical pin.
        key = sha256(encoded(pin) + schema.serialize().to_pybytes()).hexdigest()
        if getattr(self, "_legacy_key", None) == key:
            return self._legacy_values
        batches = []
        rows = size = 0
        with self.native.source_batches(pin, schema=schema) as reader:
            if not reader.schema.equals(schema, check_metadata=False):
                raise ValueError("Catalog logical schema differs")
            for batch in reader:
                self._record_read(batch)
                rows += len(batch)
                size += batch.nbytes
                if rows > 8192 or size > 16 << 20:
                    raise ValueError(
                        "Historical catalog pin exceeds its physical budget"
                    )
                batches.append(batch)
        table = pa.Table.from_batches(batches, schema=schema).combine_chunks()
        self._legacy_key, self._legacy_values = key, table
        return table

    def occurrences(self, pin, *, schema, owner_id):
        if _layout(schema) is None:
            return None
        if "catalog_rows" not in pin:
            table = self._legacy_table(pin, schema)
            parent, field = _layout(schema)
            columns = [
                name
                for name in ("source_id", "document_id")
                if name in table.column_names
            ]
            matching = [
                i
                for i in range(len(table))
                if any(table[name][i].as_py() == owner_id for name in columns)
            ]
            if len(matching) != 1:
                raise ValueError(
                    "Historical catalog occurrence owner is absent or ambiguous"
                )
            value = _occurrences(table, _layout(schema))[matching[0]]
            if not value.is_valid:
                return None
            return _ArrayOccurrences(value.values)
        core, descriptor = self._core(pin, schema)
        try:
            row = self._owner_positions[owner_id]
        except KeyError as error:
            raise ValueError("Catalog occurrence owner is absent") from error
        count = core[COUNT][row].as_py()
        return None if count is None else Occurrences(self, pin, schema, row, count)

    def _occurrence_batches(self, pin, schema, row, count):
        core, descriptor = self._core(pin, schema)
        field = _layout(schema)[1]
        child_schema = pa.schema(
            [
                pa.field("owner_row", pa.int64(), nullable=False),
                pa.field("owner_id", pa.string(), nullable=False),
                pa.field("occurrence_order", pa.int64(), nullable=False),
                pa.field("value", field.type.value_type),
            ]
        )
        if count == 0:
            return
        expected = 0
        for part in self._parts(descriptor, row):
            cache_key = sha256(encoded(part)).hexdigest()
            values = self._children.get(cache_key)
            if values is None:
                batches = []
                rows = size = 0
                with self.native.source_batches(
                    part["release"], schema=child_schema
                ) as reader:
                    if not reader.schema.equals(child_schema, check_metadata=False):
                        raise ValueError("Catalog occurrence child schema differs")
                    for batch in reader:
                        self._record_read(batch)
                        rows += len(batch)
                        size += batch.nbytes
                        if (
                            rows > descriptor["max_rows"]
                            or size > descriptor["max_bytes"]
                        ):
                            raise ValueError(
                                "Catalog occurrence child exceeds physical budget"
                            )
                        batches.append(batch)
                values = (
                    pa.Table.from_batches(batches, schema=child_schema)
                    .sort_by(
                        [("owner_row", "ascending"), ("occurrence_order", "ascending")]
                    )
                    .combine_chunks()
                )
                if (
                    rows != part["rows"]
                    or type(part.get("arrow_bytes")) is not int
                    or not 0 < part["arrow_bytes"] <= descriptor["max_bytes"]
                ):
                    raise ValueError("Catalog occurrence child size/count differs")
                owner_rows = values["owner_row"].to_pylist()
                owner_ids = values["owner_id"].to_pylist()
                if (
                    not owner_rows
                    or min(owner_rows) != part["owner_min"]
                    or max(owner_rows) != part["owner_max"]
                    or any(
                        type(r) is not int
                        or not 0 <= r < len(core)
                        or identity != core[descriptor["owner_column"]][r].as_py()
                        for r, identity in zip(owner_rows, owner_ids)
                    )
                ):
                    raise ValueError("Catalog occurrence child owner differs")
                self._children[cache_key] = values
                if len(self._children) > 2:
                    self._children.popitem(last=False)
            self._children.move_to_end(cache_key)
            selected = values.filter(
                pc.equal(values["owner_row"], row)
            ).combine_chunks()
            orders = selected["occurrence_order"].to_pylist()
            if (
                orders != list(range(expected, expected + len(selected)))
                or expected + len(selected) > count
            ):
                raise ValueError("Catalog occurrence ordinal coverage differs")
            expected += len(selected)
            if len(selected):
                yield selected["value"].chunk(0)
        if expected != count:
            raise ValueError("Catalog occurrence length differs")

    def read(self, pin, *, schema, columns=None, source_columns=None):
        columns = schema.names if columns is None else list(columns)
        output = pa.schema(
            [schema.field(name) for name in columns], metadata=schema.metadata
        )
        if source_columns is not None:
            source_field = output.field("source_values")
            fields = [source_field.type.field(name) for name in source_columns]
            output = output.set(
                output.get_field_index("source_values"),
                source_field.with_type(pa.struct(fields)),
            )
        if "catalog_rows" not in pin:
            context = (
                self._legacy_table(pin, schema).to_reader()
                if _layout(schema) is not None
                else self.native.source_batches(pin, schema=schema)
            )
            with context as reader:
                for batch in reader:
                    if _layout(schema) is None:
                        self._record_read(batch)
                    actual = batch.schema
                    if "_catalog_order" in schema.names:
                        if (
                            "_catalog_order" not in actual.names
                            or not pa.types.is_int64(
                                actual.field("_catalog_order").type
                            )
                        ):
                            raise ValueError("Native catalog order field must be int64")
                        actual = actual.remove(actual.get_field_index("_catalog_order"))
                        expected = schema.remove(
                            schema.get_field_index("_catalog_order")
                        )
                    else:
                        expected = schema
                    if not actual.equals(expected, check_metadata=False):
                        raise ValueError("Catalog logical schema differs")
                    selected = pa.Table.from_batches([batch.select(columns)])
                    selected = _source_projection(selected, output, source_columns)
                    yield pa.RecordBatch.from_arrays(
                        [selected[name].combine_chunks() for name in columns],
                        schema=output,
                    )
            return
        core, descriptor = self._core(pin, schema)
        parent, field = _layout(schema)
        needed = (
            (
                parent in columns
                and (source_columns is None or field.name in source_columns)
            )
            if parent
            else field.name in columns
        )
        if not needed:
            selected = core.select(columns)
            selected = _source_projection(selected, output, source_columns)
            for batch in selected.to_batches():
                yield pa.RecordBatch.from_arrays(batch.columns, schema=output)
            return
        for row in range(len(core)):
            count = core[COUNT][row].as_py()
            if count is None:
                array = pa.nulls(1, type=field.type)
            else:
                chunks = list(self._occurrence_batches(pin, schema, row, count))
                values = (
                    pa.concat_arrays(chunks)
                    if chunks
                    else pa.array([], type=field.type.value_type)
                )
                array = pa.ListArray.from_arrays(
                    pa.array([0, count], type=pa.int32()), values, type=field.type
                )
            logical = core.slice(row, 1).drop([COUNT, ROW])
            if parent:
                source = logical[parent].combine_chunks()
                original = schema.field(parent)
                fields = list(original.type)
                struct = pa.StructArray.from_arrays(
                    [
                        array if f.name == field.name else source.field(f.name)
                        for f in fields
                    ],
                    fields=fields,
                    mask=source.is_null(),
                )
                logical = logical.set_column(
                    schema.get_field_index(parent), original, struct
                )
            else:
                logical = logical.add_column(
                    schema.get_field_index(field.name), field, array
                )
            logical = _source_projection(
                logical.select(columns), output, source_columns
            )
            yield pa.RecordBatch.from_arrays(
                [logical[name].combine_chunks() for name in columns], schema=output
            )
