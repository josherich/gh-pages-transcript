import json
import os
import copy
from typing import Dict, List, Any, Optional, Union, Callable
from pathlib import Path

from selector import compile_document_selector

class LocalStorageDb:
    """Python implementation of LocalStorageDb using JSON files instead of localStorage"""

    def __init__(self, options: Optional[Dict] = None, success: Optional[Callable] = None, error: Optional[Callable] = None):
        self.collections: Dict[str, 'Collection'] = {}
        self.namespace: Optional[str] = None
        self.storage_path: str = "."

        if options:
            if options.get('namespace'):
                self.namespace = options['namespace']
            if options.get('storage_path'):
                self.storage_path = options['storage_path']

        # Ensure storage directory exists
        Path(self.storage_path).mkdir(parents=True, exist_ok=True)

        if success:
            success(self)

    def add_collection(self, name: str, success: Optional[Callable] = None, error: Optional[Callable] = None):
        """Add a collection to the database"""
        namespace = None
        if self.namespace:
            namespace = f"{self.namespace}.{name}"

        collection = Collection(name, namespace, self.storage_path)
        setattr(self, name, collection)
        self.collections[name] = collection

        if success:
            success()

    def remove_collection(self, name: str, success: Optional[Callable] = None, error: Optional[Callable] = None):
        """Remove a collection from the database"""
        if self.namespace:
            # Remove all JSON files related to this collection
            storage_dir = Path(self.storage_path)
            pattern = f"{self.namespace}.{name}"

            for file_path in storage_dir.glob(f"{pattern}*"):
                try:
                    file_path.unlink()
                except OSError:
                    pass

        if hasattr(self, name):
            delattr(self, name)
        if name in self.collections:
            del self.collections[name]

        if success:
            success()

    def get_collection_names(self) -> List[str]:
        """Get names of all collections"""
        return list(self.collections.keys())


class Collection:
    """Collection class that stores data in memory and optionally persists to JSON files"""

    def __init__(self, name: str, namespace: Optional[str] = None, storage_path: str = "."):
        self.name = name
        self.namespace = namespace
        self.storage_path = storage_path

        self.items: Dict[str, Dict] = {}
        self.upserts: Dict[str, Dict] = {}  # Pending upserts by _id
        self.removes: Dict[str, Dict] = {}  # Pending removes by _id
        self.item_namespace: Optional[str] = None

        # Load from JSON files if namespace is provided
        if namespace:
            self.load_storage()

    def _get_file_path(self, suffix: str) -> str:
        """Get file path for storage"""
        if self.namespace:
            return os.path.join(self.storage_path, f"{self.namespace}_{suffix}.json")
        return os.path.join(self.storage_path, f"{self.name}_{suffix}.json")

    def load_storage(self):
        """Load data from JSON files"""
        if not self.namespace:
            return

        self.item_namespace = f"{self.namespace}_"

        # Load items
        items_file = self._get_file_path("items")
        if os.path.exists(items_file):
            try:
                with open(items_file, 'r') as f:
                    items_data = json.load(f)
                    for item in items_data:
                        if '_id' in item:
                            self.items[item['_id']] = item
            except (json.JSONDecodeError, IOError):
                pass

        # Load upserts
        upserts_file = self._get_file_path("upserts")
        if os.path.exists(upserts_file):
            try:
                with open(upserts_file, 'r') as f:
                    upserts_data = json.load(f)
                    for upsert in upserts_data:
                        doc_id = upsert['doc']['_id']
                        self.upserts[doc_id] = upsert
            except (json.JSONDecodeError, IOError):
                pass

        # Load removes
        removes_file = self._get_file_path("removes")
        if os.path.exists(removes_file):
            try:
                with open(removes_file, 'r') as f:
                    removes_data = json.load(f)
                    self.removes = {item['_id']: item for item in removes_data}
            except (json.JSONDecodeError, IOError):
                pass

    def find(self, selector: Any = None, options: Optional[Dict] = None):
        """Find documents matching selector"""
        return FindResult(self, selector, options)

    def find_one(self, selector: Any = None, options: Optional[Dict] = None,
                success: Optional[Callable] = None, error: Optional[Callable] = None):
        """Find one document matching selector"""
        if callable(options):
            options, success, error = {}, options, success

        options = options or {}

        # Promise-like behavior for Python
        if success is None:
            results = self._find_fetch(selector, options)
            return results[0] if results else None

        # Callback style
        def handle_results(results):
            if success:
                success(results[0] if results else None)

        return self.find(selector, options).fetch(handle_results, error)

    def _find_fetch(self, selector: Any, options: Dict) -> List[Dict]:
        """Internal method to fetch documents"""
        if self.namespace:
            self.load_storage()
        # Deep clone to prevent modification
        results = copy.deepcopy(list(self.items.values()))
        return self._process_find(results, selector, options)

    def _process_find(self, docs: List[Dict], selector: Any, options: Dict) -> List[Dict]:
        """Process find query with proper sorting implementation"""
        results = list(filter(compile_document_selector(selector), docs))

        # Apply sorting
        if options.get('sort'):
            sort_fn = self._compile_sort(options['sort'])
            from functools import cmp_to_key
            results = sorted(results, key=cmp_to_key(sort_fn))

        # Apply skip
        if options.get('skip'):
            results = results[options['skip']:]

        # Apply limit
        if options.get('limit'):
            results = results[:options['limit']]

        return results

    @staticmethod
    def _compile_sort(spec: Any):
        """Compile sort specification into a comparison function"""
        sort_spec_parts = []

        if isinstance(spec, list):
            for item in spec:
                if isinstance(item, str):
                    sort_spec_parts.append({
                        'lookup': Collection._make_lookup_function(item),
                        'ascending': True
                    })
                else:
                    sort_spec_parts.append({
                        'lookup': Collection._make_lookup_function(item[0]),
                        'ascending': item[1] != "desc"
                    })
        elif isinstance(spec, dict):
            for key, value in spec.items():
                sort_spec_parts.append({
                    'lookup': Collection._make_lookup_function(key),
                    'ascending': value >= 0
                })
        else:
            raise ValueError(f"Bad sort specification: {spec}")

        if not sort_spec_parts:
            return lambda a, b: 0

        def reduce_value(branch_values: List[Any], find_min: bool) -> Any:
            """Find min or max value from branch values"""
            reduced = None
            first = True

            for branch_value in branch_values:
                # Value not an array? Pretend it is.
                if not isinstance(branch_value, list):
                    branch_value = [branch_value]

                # Value is empty array? Treat as undefined
                if isinstance(branch_value, list) and len(branch_value) == 0:
                    branch_value = [None]

                for value in branch_value:
                    if first:
                        reduced = value
                        first = False
                    else:
                        cmp_result = Collection._cmp(reduced, value)
                        if (find_min and cmp_result > 0) or (not find_min and cmp_result < 0):
                            reduced = value

            return reduced

        def sort_comparator(a: Any, b: Any) -> int:
            """Compare two documents according to sort specification"""
            for spec_part in sort_spec_parts:
                a_value = reduce_value(spec_part['lookup'](a), spec_part['ascending'])
                b_value = reduce_value(spec_part['lookup'](b), spec_part['ascending'])
                compare = Collection._cmp(a_value, b_value)

                if compare != 0:
                    return compare if spec_part['ascending'] else -compare

            return 0

        return sort_comparator

    @staticmethod
    def _make_lookup_function(key: str):
        """Create a lookup function for a given key path"""
        dot_location = key.find('.')

        if dot_location == -1:
            first = key
            lookup_rest = None
            next_is_numeric = False
        else:
            first = key[:dot_location]
            rest = key[dot_location + 1:]
            lookup_rest = Collection._make_lookup_function(rest)
            # Check if next part is numeric (array index)
            import re
            next_is_numeric = bool(re.match(r'^\d+(\.|$)', rest))

        def lookup_fn(doc: Any) -> List[Any]:
            if doc is None:
                return [None]

            first_level = doc.get(first) if isinstance(doc, dict) else None

            # We don't branch at the final level
            if not lookup_rest:
                return [first_level]

            # Empty array and we're not done - won't find anything
            if isinstance(first_level, list) and len(first_level) == 0:
                return [None]

            # For each result at this level, finish lookup on rest of key
            if not isinstance(first_level, list) or next_is_numeric:
                first_level = [first_level]

            # Flatten results from all branches
            results = []
            for item in first_level:
                results.extend(lookup_rest(item))

            return results

        return lookup_fn

    @staticmethod
    def _cmp(a: Any, b: Any) -> int:
        """Compare two values MongoDB-style"""
        # Handle None/null values
        if a is None and b is None:
            return 0
        if a is None:
            return -1
        if b is None:
            return 1

        # Type-based ordering (simplified MongoDB ordering)
        type_order = {
            type(None): 0,
            bool: 1,
            int: 2,
            float: 2,
            str: 3,
            list: 4,
            dict: 5
        }

        a_type_order = type_order.get(type(a), 6)
        b_type_order = type_order.get(type(b), 6)

        if a_type_order != b_type_order:
            return -1 if a_type_order < b_type_order else 1

        # Same types - compare values
        if a < b:
            return -1
        elif a > b:
            return 1
        else:
            return 0

    def upsert(self, docs: Union[Dict, List[Dict]], bases: Optional[Union[Dict, List[Dict]]] = None,
              success: Optional[Callable] = None, error: Optional[Callable] = None):
        """Insert or update documents"""
        if success is None:
            # Synchronous mode
            return self._upsert_sync(docs, bases)

        # Callback mode
        try:
            result = self._upsert_sync(docs, bases)
            if success:
                success(result)
        except Exception as e:
            if error:
                error(e)

    def _upsert_sync(self, docs: Union[Dict, List[Dict]], bases: Optional[Union[Dict, List[Dict]]] = None):
        """Synchronous upsert implementation"""
        if not isinstance(docs, list):
            docs = [docs]
            single_doc = True
        else:
            single_doc = False

        if bases is not None and not isinstance(bases, list):
            bases = [bases]

        # Keep independent copies to prevent modification
        docs = copy.deepcopy(docs)

        items = []
        for i, doc in enumerate(docs):
            base = None
            if bases and i < len(bases):
                base = bases[i]
            elif doc.get('_id') in self.upserts:
                base = self.upserts[doc['_id']].get('base')
            elif doc.get('_id') in self.items:
                base = self.items[doc['_id']]

            items.append({'doc': doc, 'base': base})

        for item in items:
            doc = item['doc']
            if '_id' not in doc:
                # Generate ID if not present
                import uuid
                doc['_id'] = str(uuid.uuid4())

            # Replace/add
            self._put_item(doc)
            self._put_upsert(item)

        return docs[0] if single_doc else docs

    def remove(self, id_or_selector: Union[str, Dict], success: Optional[Callable] = None,
              error: Optional[Callable] = None):
        """Remove documents"""
        if success is None:
            # Synchronous mode
            return self._remove_sync(id_or_selector)

        # Callback mode
        try:
            self._remove_sync(id_or_selector)
            if success:
                success()
        except Exception as e:
            if error:
                error(e)

    def _remove_sync(self, id_or_selector: Union[str, Dict]):
        """Synchronous remove implementation"""
        # Handle selector-based removal
        if isinstance(id_or_selector, dict):
            results = self._find_fetch(id_or_selector, {})
            for doc in results:
                self._remove_sync(doc['_id'])
            return

        doc_id = id_or_selector

        if doc_id in self.items:
            self._put_remove(self.items[doc_id])
            self._delete_item(doc_id)
            self._delete_upsert(doc_id)
        else:
            self._put_remove({'_id': doc_id})

    def _put_item(self, doc: Dict):
        """Store item in memory and persist to file"""
        self.items[doc['_id']] = doc
        if self.namespace:
            self._save_items()

    def _delete_item(self, doc_id: str):
        """Remove item from memory and file"""
        if doc_id in self.items:
            del self.items[doc_id]
            if self.namespace:
                self._save_items()

    def _put_upsert(self, upsert: Dict):
        """Store upsert in memory and persist to file"""
        doc_id = upsert['doc']['_id']
        self.upserts[doc_id] = upsert
        if self.namespace:
            self._save_upserts()

    def _delete_upsert(self, doc_id: str):
        """Remove upsert from memory and file"""
        if doc_id in self.upserts:
            del self.upserts[doc_id]
            if self.namespace:
                self._save_upserts()

    def _put_remove(self, doc: Dict):
        """Store remove in memory and persist to file"""
        self.removes[doc['_id']] = doc
        if self.namespace:
            self._save_removes()

    def _delete_remove(self, doc_id: str):
        """Remove from removes and file"""
        if doc_id in self.removes:
            del self.removes[doc_id]
            if self.namespace:
                self._save_removes()

    def _save_items(self):
        """Save items to JSON file"""
        items_file = self._get_file_path("items")
        try:
            with open(items_file, 'w') as f:
                json.dump(list(self.items.values()), f, indent=2)
        except IOError:
            pass

    def _save_upserts(self):
        """Save upserts to JSON file"""
        upserts_file = self._get_file_path("upserts")
        try:
            with open(upserts_file, 'w') as f:
                json.dump(list(self.upserts.values()), f, indent=2)
        except IOError:
            pass

    def _save_removes(self):
        """Save removes to JSON file"""
        removes_file = self._get_file_path("removes")
        try:
            with open(removes_file, 'w') as f:
                json.dump(list(self.removes.values()), f, indent=2)
        except IOError:
            pass

    def pending_upserts(self, success: Optional[Callable] = None):
        """Get pending upserts"""
        result = list(self.upserts.values())
        if success:
            success(result)
        return result

    def pending_removes(self, success: Optional[Callable] = None):
        """Get pending removes"""
        result = list(self.removes.keys())
        if success:
            success(result)
        return result

    def seed(self, docs: Union[Dict, List[Dict]], success: Optional[Callable] = None):
        """Add documents without overwriting existing ones"""
        if not isinstance(docs, list):
            docs = [docs]

        for doc in docs:
            doc_id = doc.get('_id')
            if doc_id and doc_id not in self.items and doc_id not in self.removes:
                self._put_item(doc)

        if success:
            success()

    def cache_one(self, doc: Dict, success: Optional[Callable] = None, error: Optional[Callable] = None):
        """Cache one document"""
        return self.cache_list([doc], success, error)

    def cache_list(self, docs: List[Dict], success: Optional[Callable] = None, error: Optional[Callable] = None):
        """Cache multiple documents"""
        for doc in docs:
            doc_id = doc.get('_id')
            if doc_id and doc_id not in self.upserts and doc_id not in self.removes:
                existing = self.items.get(doc_id)

                # Handle _rev versioning
                if not existing or not doc.get('_rev') or not existing.get('_rev') or doc['_rev'] > existing['_rev']:
                    self._put_item(doc)

        if success:
            success()


class FindResult:
    """Result object for find operations"""

    def __init__(self, collection: Collection, selector: Any, options: Optional[Dict]):
        self.collection = collection
        self.selector = selector
        self.options = options or {}

    def fetch(self, success: Optional[Callable] = None, error: Optional[Callable] = None):
        """Fetch the results"""
        if success is None:
            # Synchronous mode
            return self.collection._find_fetch(self.selector, self.options)

        # Callback mode
        try:
            results = self.collection._find_fetch(self.selector, self.options)
            success(results)
        except Exception as e:
            if error:
                error(e)

