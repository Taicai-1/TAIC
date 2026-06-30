from folder_import import resolve_folder_for_path, run_folder_import, split_relative_path


def test_split_relative_path_basic():
    assert split_relative_path("Contrats/2024/bail.pdf") == (["Contrats", "2024"], "bail.pdf")
    assert split_relative_path("bail.pdf") == ([], "bail.pdf")
    assert split_relative_path("a\\b\\c.txt") == (["a", "b"], "c.txt")
    assert split_relative_path("./x/../y/z.txt") == (["y"], "z.txt")
    assert split_relative_path("") == ([], "")


class _FakeTree:
    """In-memory folder store for testing find/create callbacks."""

    def __init__(self):
        self.rows = {}  # id -> (parent_id, name)
        self._next = 1

    def find_child(self, parent_id, name):
        for fid, (pid, nm) in self.rows.items():
            if pid == parent_id and nm == name:
                return fid
        return None

    def create_child(self, parent_id, name):
        fid = self._next
        self._next += 1
        self.rows[fid] = (parent_id, name)
        return fid


def test_resolve_folder_for_path_creates_chain():
    tree = _FakeTree()
    cache = {}
    leaf = resolve_folder_for_path(["A", "B"], None, tree.find_child, tree.create_child, cache)
    assert tree.rows[leaf] == (tree.find_child(None, "A"), "B")
    # empty segments -> destination itself
    assert resolve_folder_for_path([], 7, tree.find_child, tree.create_child, cache) == 7


def test_resolve_folder_for_path_merges_existing():
    tree = _FakeTree()
    a = tree.create_child(None, "A")
    cache = {}
    leaf = resolve_folder_for_path(["A", "B"], None, tree.find_child, tree.create_child, cache)
    # "A" reused (merge), "B" created under it
    assert tree.rows[leaf][0] == a
    assert len([r for r in tree.rows.values() if r == (None, "A")]) == 1


def test_resolve_folder_for_path_caches():
    tree = _FakeTree()
    calls = {"create": 0}
    orig_create = tree.create_child

    def counting_create(p, n):
        calls["create"] += 1
        return orig_create(p, n)

    cache = {}
    resolve_folder_for_path(["A", "B"], None, tree.find_child, counting_create, cache)
    resolve_folder_for_path(["A", "B", "C"], None, tree.find_child, counting_create, cache)
    # A and B created once (cache hit on 2nd call), C created once -> 3 creates total
    assert calls["create"] == 3


def test_run_folder_import_skips_unsupported_no_empty_folders():
    tree = _FakeTree()
    ingested = []

    def is_supported(filename, content):
        return filename.endswith(".pdf")

    def ingest_file(filename, content, folder_id):
        ingested.append((filename, folder_id))

    statuses = []

    def set_status(total, done, skipped, failed, root_folder_id, status):
        statuses.append((done, skipped, failed, status))

    items = [
        ("a.pdf", "Root/Sub/a.pdf", b"x"),
        ("b.exe", "Root/Empty/b.exe", b"x"),  # unsupported -> skipped, "Empty" never created
        ("c.pdf", "Root/Sub/c.pdf", b"x"),
    ]
    summary = run_folder_import(items, None, tree.find_child, tree.create_child, ingest_file, is_supported, set_status)
    assert summary["done"] == 2 and summary["skipped"] == 1 and summary["failed"] == 0
    assert summary["total"] == 3
    # no "Empty" folder created (lazy creation only on supported files)
    assert not any(nm == "Empty" for (_, nm) in tree.rows.values())
    # root_folder_id is the "Root" folder
    assert tree.rows[summary["root_folder_id"]] == (None, "Root")
    assert statuses[-1][3] == "completed"


def test_run_folder_import_counts_failures():
    tree = _FakeTree()

    def ingest_file(filename, content, folder_id):
        raise RuntimeError("boom")

    summary = run_folder_import(
        [("a.pdf", "R/a.pdf", b"x")],
        None,
        tree.find_child,
        tree.create_child,
        ingest_file,
        lambda *a: True,
        lambda *a: None,
    )
    assert summary["failed"] == 1 and summary["done"] == 0
