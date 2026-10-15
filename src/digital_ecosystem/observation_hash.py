"""Byte-equivalent M4 fingerprints with local serialization caches for observers.

The numerical core and its fingerprint implementation are unchanged. This avoids
repeated JSON encoder construction for the same IDs, keys and list headers in a
large population. It does not cache state between observations.
"""

import copy
import hashlib
import math

import numpy as np

from .state import canonical_json


def fingerprint_fast(state):
    digest = hashlib.sha256()
    strings, integers, headers, arrays, keys = {}, {}, {}, {}, {}
    update = digest.update

    def visit(value):
        kind = type(value)
        if kind is float and math.isfinite(value):
            update(float.__repr__(value).encode())
        elif kind is int:
            encoded = integers.get(value)
            if encoded is None:
                encoded = str(value).encode()
                if len(integers) < 4096:
                    integers[value] = encoded
            update(encoded)
        elif kind is str:
            encoded = strings.get(value)
            if encoded is None:
                encoded = canonical_json(value)
                if len(strings) < 4096:
                    strings[value] = encoded
            update(encoded)
        elif isinstance(value, np.ndarray):
            update(b"array")
            key = (value.dtype, value.shape)
            metadata = arrays.get(key)
            if metadata is None:
                metadata = canonical_json(
                    [value.dtype.descr if value.dtype.fields else value.dtype.str, value.shape]
                )
                arrays[key] = metadata
            update(metadata)
            update(value.tobytes(order="C"))
        elif isinstance(value, dict):
            update(b"dict")
            for key in sorted(value):
                # Composite keys can compare equal while their JSON encodings
                # differ (e.g. (True,) and (1,)); only cache exact string keys.
                cache_key = key if type(key) is str else None
                encoded = keys.get(cache_key)
                if encoded is None:
                    encoded = canonical_json(key)
                    if cache_key is not None and len(keys) < 4096:
                        keys[cache_key] = encoded
                update(encoded)
                visit(value[key])
        elif isinstance(value, (list, tuple)):
            length = len(value)
            header = headers.get(length)
            if header is None:
                header = b'["list",' + str(length).encode() + b"]"
                headers[length] = header
            update(header)
            for item in value:
                visit(item)
        elif value is None:
            update(b"null")
        elif isinstance(value, bool):
            update(b"true" if value else b"false")
        elif isinstance(value, int):
            encoded = integers.get(value)
            if encoded is None:
                encoded = int.__repr__(value).encode()
                if len(integers) < 4096:
                    integers[value] = encoded
            update(encoded)
        elif isinstance(value, float) and math.isfinite(value):
            # json's finite-float encoder uses float.__repr__, including subclasses.
            update(float.__repr__(value).encode())
        elif isinstance(value, str):
            encoded = strings.get(value)
            if encoded is None:
                encoded = canonical_json(value)
                if len(strings) < 4096:
                    strings[value] = encoded
            update(encoded)
        else:
            update(canonical_json(value))

    visit(state)
    return digest.hexdigest()


def engine_fingerprint(simulation):
    # The M4 engine digest explicitly excludes delivery queues. Omit them
    # before capture so pending birth genomes are not deeply copied and then
    # immediately discarded. The shallow shell is never run or returned;
    # core capture still detaches every numerical field in exactly the M4 way.
    shell = copy.copy(simulation)
    shell.events = []
    shell.pending_genomes = {}
    state = shell.to_state()
    state.pop("events")
    state.pop("pending_genomes")
    state["config"].pop("checkpoint")
    return fingerprint_fast(state)
