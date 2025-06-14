import re
from typing import Any, Callable, List, Dict, Union
from datetime import datetime
import json


def is_array(x: Any) -> bool:
    """Check if value is an array (list) but not binary data."""
    return isinstance(x, list)


def any_if_array(x: Any, f: Callable) -> bool:
    """Apply function to array elements or single value."""
    if is_array(x):
        return any(f(item) for item in x)
    return f(x)


def any_if_array_plus(x: Any, f: Callable) -> bool:
    """Apply function to value, or if array, to any element."""
    if f(x):
        return True
    return is_array(x) and any(f(item) for item in x)


def has_operators(value_selector: Dict) -> bool:
    """Check if selector contains MongoDB operators (keys starting with $)."""
    if not isinstance(value_selector, dict):
        return False

    operators = None
    for key in value_selector:
        is_operator = key.startswith('$')
        if operators is None:
            operators = is_operator
        elif operators != is_operator:
            raise ValueError(f"Inconsistent selector: {value_selector}")

    return operators or False


def compile_value_selector(value_selector: Any) -> Callable:
    """Compile a value selector into a matching function."""
    if value_selector is None:
        return lambda value: any_if_array(value, lambda x: x is None)

    # Non-object primitives
    if not isinstance(value_selector, (dict, list)) and not isinstance(value_selector, re.Pattern):
        return lambda value: any_if_array(value, lambda x: x == value_selector)

    # Regular expressions
    if isinstance(value_selector, re.Pattern):
        return lambda value: (
            value is not None and
            any_if_array(value, lambda x: isinstance(x, str) and value_selector.search(x))
        )

    # Arrays
    if is_array(value_selector):
        return lambda value: (
            is_array(value) and
            any_if_array_plus(value, lambda x: deep_equal(value_selector, x))
        )

    # Objects with operators
    if has_operators(value_selector):
        operator_functions = []
        for operator, operand in value_selector.items():
            if operator not in VALUE_OPERATORS:
                raise ValueError(f"Unrecognized operator: {operator}")
            operator_functions.append(
                VALUE_OPERATORS[operator](operand, value_selector.get('$options'))
            )
        return lambda value: all(f(value) for f in operator_functions)

    # Literal object comparison
    return lambda value: any_if_array(value, lambda x: deep_equal(value_selector, x))


def deep_equal(a: Any, b: Any) -> bool:
    """Deep equality comparison."""
    if type(a) != type(b):
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(deep_equal(a[k], b[k]) for k in a.keys())
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(deep_equal(a[i], b[i]) for i in range(len(a)))
    return a == b


def get_type(v: Any) -> int:
    """Get MongoDB-style type code for value."""
    if isinstance(v, (int, float)):
        return 1
    if isinstance(v, str):
        return 2
    if isinstance(v, bool):
        return 8
    if isinstance(v, list):
        return 4
    if v is None:
        return 10
    if isinstance(v, re.Pattern):
        return 11
    if callable(v):
        return 13
    if isinstance(v, datetime):
        return 9
    return 3  # object


def get_type_order(t: int) -> int:
    """Get sort order for MongoDB types."""
    type_orders = {
        1: 1,   # number
        2: 2,   # string
        3: 3,   # object
        4: 4,   # array
        5: 5,   # binary
        8: 7,   # bool
        9: 8,   # date
        10: 0,  # null
        11: 9,  # regexp
        13: 100 # function
    }
    return type_orders.get(t, -1)


def mongo_compare(a: Any, b: Any) -> int:
    """Compare two values using MongoDB ordering semantics."""
    if a is None and b is None:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1

    ta, tb = get_type(a), get_type(b)
    oa, ob = get_type_order(ta), get_type_order(tb)

    if oa != ob:
        return -1 if oa < ob else 1

    if ta != tb:
        raise ValueError("Missing type coercion logic")

    if ta == 1:  # number
        return (a > b) - (a < b)
    if ta == 2:  # string
        return (a > b) - (a < b)
    if ta == 3:  # object
        def to_array(obj):
            result = []
            for k, v in obj.items():
                result.extend([k, v])
            return result
        return mongo_compare(to_array(a), to_array(b))
    if ta == 4:  # array
        for i in range(max(len(a), len(b))):
            if i >= len(a):
                return -1
            if i >= len(b):
                return 1
            cmp = mongo_compare(a[i], b[i])
            if cmp != 0:
                return cmp
        return 0
    if ta == 8:  # boolean
        return (a > b) - (a < b)
    if ta == 10:  # null
        return 0

    raise ValueError(f"Sorting not supported for type {ta}")


# Logical operators
LOGICAL_OPERATORS = {
    '$and': lambda sub_selector: (
        lambda doc: (
            is_array(sub_selector) and len(sub_selector) > 0 and
            all(compile_document_selector(sel)(doc) for sel in sub_selector)
        ) if is_array(sub_selector) and len(sub_selector) > 0
        else (_ for _ in ()).throw(ValueError("$and must be nonempty array"))
    ),

    '$or': lambda sub_selector: (
        lambda doc: (
            is_array(sub_selector) and len(sub_selector) > 0 and
            any(compile_document_selector(sel)(doc) for sel in sub_selector)
        ) if is_array(sub_selector) and len(sub_selector) > 0
        else (_ for _ in ()).throw(ValueError("$or must be nonempty array"))
    ),

    '$nor': lambda sub_selector: (
        lambda doc: (
            is_array(sub_selector) and len(sub_selector) > 0 and
            not any(compile_document_selector(sel)(doc) for sel in sub_selector)
        ) if is_array(sub_selector) and len(sub_selector) > 0
        else (_ for _ in ()).throw(ValueError("$nor must be nonempty array"))
    ),

    '$where': lambda selector_value: (
        lambda doc: eval(selector_value, {'doc': doc}) if isinstance(selector_value, str)
        else selector_value(doc)
    )
}


# Value operators
VALUE_OPERATORS = {
    '$in': lambda operand, options=None: (
        lambda value: (
            is_array(operand) and
            any_if_array_plus(value, lambda x: x in operand)
        ) if is_array(operand) else (_ for _ in ()).throw(ValueError("$in operand must be array"))
    ),

    '$all': lambda operand, options=None: (
        lambda value: (
            is_array(operand) and is_array(value) and
            all(any(deep_equal(op_elt, val_elt) for val_elt in value) for op_elt in operand)
        ) if is_array(operand) else (_ for _ in ()).throw(ValueError("$all operand must be array"))
    ),

    '$lt': lambda operand, options=None: (
        lambda value: any_if_array(value, lambda x: mongo_compare(x, operand) < 0)
    ),

    '$lte': lambda operand, options=None: (
        lambda value: any_if_array(value, lambda x: mongo_compare(x, operand) <= 0)
    ),

    '$gt': lambda operand, options=None: (
        lambda value: any_if_array(value, lambda x: mongo_compare(x, operand) > 0)
    ),

    '$gte': lambda operand, options=None: (
        lambda value: any_if_array(value, lambda x: mongo_compare(x, operand) >= 0)
    ),

    '$ne': lambda operand, options=None: (
        lambda value: not any_if_array_plus(value, lambda x: deep_equal(x, operand))
    ),

    '$nin': lambda operand, options=None: (
        lambda value: (
            is_array(operand) and
            (value is None or not VALUE_OPERATORS['$in'](operand)(value))
        ) if is_array(operand) else (_ for _ in ()).throw(ValueError("$nin operand must be array"))
    ),

    '$exists': lambda operand, options=None: (
        lambda value: operand == (value is not None)
    ),

    '$mod': lambda operand, options=None: (
        lambda value: (
            len(operand) == 2 and
            any_if_array(value, lambda x: isinstance(x, (int, float)) and x % operand[0] == operand[1])
        )
    ),

    '$size': lambda operand, options=None: (
        lambda value: is_array(value) and len(value) == operand
    ),

    '$type': lambda operand, options=None: (
        lambda value: value is not None and any_if_array(value, lambda x: get_type(x) == operand)
    ),

    '$regex': lambda operand, options=None: (
        lambda value: (
            value is not None and
            any_if_array(value, lambda x: isinstance(x, str) and
                        re.search(operand if isinstance(operand, str) else operand.pattern,
                                x, re.IGNORECASE if options and 'i' in options else 0))
        )
    ),

    '$options': lambda operand, options=None: lambda value: True,

    '$elemMatch': lambda operand, options=None: (
        lambda value: (
            is_array(value) and
            any(compile_document_selector(operand)(x) for x in value)
        )
    ),

    '$not': lambda operand, options=None: (
        lambda value: not compile_value_selector(operand)(value)
    ),

    '$near': lambda operand, options=None: lambda value: True,
    '$geoIntersects': lambda operand, options=None: lambda value: True
}


def make_lookup_function(key: str) -> Callable:
    """Create a lookup function for a dot-notation key."""
    dot_location = key.find('.')

    if dot_location == -1:
        first = key
        lookup_rest = None
        next_is_numeric = False
    else:
        first = key[:dot_location]
        rest = key[dot_location + 1:]
        lookup_rest = make_lookup_function(rest)
        next_is_numeric = bool(re.match(r'^\d+(\.|$)', rest))

    def lookup(doc):
        if doc is None:
            return [None]

        first_level = doc.get(first) if isinstance(doc, dict) else None

        if not lookup_rest:
            return [first_level]

        if is_array(first_level) and len(first_level) == 0:
            return [None]

        if not is_array(first_level) or next_is_numeric:
            first_level = [first_level]

        result = []
        for item in first_level:
            result.extend(lookup_rest(item))
        return result

    return lookup


def compile_document_selector(doc_selector: Any) -> Callable[[Dict], bool]:
    """Compile a document selector into a matching function."""
    if not isinstance(doc_selector, dict):
        return lambda doc: True

    per_key_selectors = []

    for key, sub_selector in doc_selector.items():
        if key.startswith('$'):
            if key not in LOGICAL_OPERATORS:
                raise ValueError(f"Unrecognized logical operator: {key}")
            per_key_selectors.append(LOGICAL_OPERATORS[key](sub_selector))
        else:
            lookup_func = make_lookup_function(key)
            value_selector_func = compile_value_selector(sub_selector)

            def key_matcher(doc, lookup=lookup_func, value_func=value_selector_func):
                branch_values = lookup(doc)
                return any(value_func(val) for val in branch_values)

            per_key_selectors.append(key_matcher)

    return lambda doc: all(selector(doc) for selector in per_key_selectors)


def compile_selector(selector: Any) -> Callable[[Dict], bool]:
    """Compile a selector into a document matching function."""
    if callable(selector):
        return lambda doc: selector(doc)

    # Shorthand for _id matching
    if not isinstance(selector, dict):
        return lambda doc: doc.get('_id') == selector

    # Protect against dangerous selectors
    if not selector or ('_id' in selector and not selector['_id']):
        return lambda doc: False

    # Invalid top-level types
    if isinstance(selector, (bool, list)):
        raise ValueError(f"Invalid selector: {selector}")

    return compile_document_selector(selector)


def compile_sort(spec: Union[Dict, List]) -> Callable:
    """Compile a sort specification into a comparison function."""
    sort_spec_parts = []

    if isinstance(spec, list):
        for item in spec:
            if isinstance(item, str):
                sort_spec_parts.append({
                    'lookup': make_lookup_function(item),
                    'ascending': True
                })
            else:
                sort_spec_parts.append({
                    'lookup': make_lookup_function(item[0]),
                    'ascending': item[1] != 'desc'
                })
    elif isinstance(spec, dict):
        for key, value in spec.items():
            sort_spec_parts.append({
                'lookup': make_lookup_function(key),
                'ascending': value >= 0
            })
    else:
        raise ValueError(f"Bad sort specification: {spec}")

    if not sort_spec_parts:
        return lambda a, b: 0

    def reduce_value(branch_values, find_min):
        reduced = None
        first = True

        for branch_value in branch_values:
            if not is_array(branch_value):
                branch_value = [branch_value]
            if is_array(branch_value) and len(branch_value) == 0:
                branch_value = [None]

            for value in branch_value:
                if first:
                    reduced = value
                    first = False
                else:
                    cmp = mongo_compare(reduced, value)
                    if (find_min and cmp > 0) or (not find_min and cmp < 0):
                        reduced = value
        return reduced

    def compare_docs(a, b):
        for spec_part in sort_spec_parts:
            a_value = reduce_value(spec_part['lookup'](a), spec_part['ascending'])
            b_value = reduce_value(spec_part['lookup'](b), spec_part['ascending'])
            compare = mongo_compare(a_value, b_value)
            if compare != 0:
                return compare if spec_part['ascending'] else -compare
        return 0

    return compare_docs


def matches(selector: Any, doc: Dict) -> bool:
    """Test if a document matches a selector."""
    return compile_selector(selector)(doc)
