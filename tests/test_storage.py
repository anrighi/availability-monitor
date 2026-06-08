import tempfile
import unittest
from pathlib import Path

from availability_monitor import storage


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_file = storage.db_path_for_data_dir(Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_state_items_round_trip(self) -> None:
        storage.add_state_items(self.db_file, ["a", "b"])
        storage.add_state_items(self.db_file, ["b", "c"])
        self.assertEqual(storage.list_state_items(self.db_file), {"a", "b", "c"})
        storage.clear_state_items(self.db_file)
        self.assertEqual(storage.list_state_items(self.db_file), set())

    def test_execution_log(self) -> None:
        storage.ensure_defaults(
            self.db_file,
            default_settings={"foo": "bar"},
            allowed_keys=frozenset({"foo"}),
        )
        exec_id = storage.start_execution(self.db_file)
        storage.finish_execution(
            self.db_file,
            exec_id,
            exit_code=0,
            summary={"ok": True},
        )
        rows = storage.list_executions(self.db_file)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exit_code"], 0)
        self.assertEqual(rows[0]["summary"]["ok"], True)


if __name__ == "__main__":
    unittest.main()
