from datetime import datetime

import pandas as pd
import pytest

from sqlcache import store


class TestParquetStore:
    def test_init(self, tmp_path):
        s = store.ParquetStore(cache_store=tmp_path)
        assert s.cache_store.exists()

    def test_get_filepaths(self, tmp_path, query_string):
        """Test the metadata and results cache file"""
        s = store.ParquetStore(cache_store=tmp_path)
        metadata_file = s.get_metadata_filepath(query_string)
        cache_file = s.get_cache_filepath(query_string)
        assert metadata_file.stem == store.hash_query(query_string)
        assert cache_file.stem == store.hash_query(query_string)
        assert metadata_file == tmp_path / (store.hash_query(query_string) + ".json")
        assert cache_file == tmp_path / (store.hash_query(query_string) + ".parquet")

    def test_dump_load_metadata(self, parquet_store, query_string, metadata):
        parquet_store.dump_metadata(query_string, metadata)
        assert parquet_store.get_metadata_filepath(query_string).exists()
        metadata_loaded = parquet_store.load_metadata(query_string)
        assert metadata == metadata_loaded

        with pytest.raises(ValueError) as excinfo:
            parquet_store.load_metadata("select * from dummy")
        assert f"Metadata for the given query_string does not exist." in str(
            excinfo.value
        )

    def test_dump_load_results(self, parquet_store, query_string, results):
        parquet_store.dump_results(query_string, results)
        assert parquet_store.get_cache_filepath(query_string).exists()
        results_loaded = parquet_store.load_results(query_string)
        assert results.equals(results_loaded)

        with pytest.raises(ValueError) as excinfo:
            parquet_store.load_results("select * from dummy")
        assert f"Cached results for the given query_string do not exist." in str(
            excinfo.value
        )

    def test_dump_load(self, parquet_store, query_string, results, metadata):
        parquet_store.dump(query_string, results, metadata)
        assert parquet_store.get_cache_filepath(query_string).exists()
        assert parquet_store.get_metadata_filepath(query_string).exists()
        results_loaded, metadata_loaded = parquet_store.load(query_string)
        assert results.equals(results_loaded)
        assert metadata == metadata_loaded

        with pytest.raises(ValueError) as excinfo:
            parquet_store.load("select * from dummy")
        assert f"Cached results for the given query_string do not exist." in str(
            excinfo.value
        )

    def test_exists_in_cache(self, parquet_store, query_string, metadata, results):
        """Test the function that asserts if there is cache for a given string"""
        assert not parquet_store.get_metadata_filepath(query_string).exists()
        assert not parquet_store.get_cache_filepath(query_string).exists()
        assert not parquet_store.exists(query_string)

        parquet_store.dump(query_string, results, metadata)

        assert parquet_store.get_metadata_filepath(query_string).exists()
        assert parquet_store.get_cache_filepath(query_string).exists()
        assert parquet_store.exists(query_string)

    def test_list_empty_store(self, parquet_store):
        store_content = parquet_store.list()
        assert store_content.shape == (0, 4)
        assert list(store_content.columns) == [
            "query_string",
            "cache_file",
            "executed_at",
            "duration",
        ]

    def test_list_store_with_one_element(
        self, parquet_store, query_string, metadata, results
    ):
        parquet_store.dump(query_string, results, metadata)
        store_content = parquet_store.list()
        assert store_content.shape == (1, 4)
        assert list(store_content.columns) == [
            "query_string",
            "cache_file",
            "executed_at",
            "duration",
        ]
        assert (
            store_content.loc[0, "cache_file"]
            == parquet_store.get_cache_filepath(query_string).name
        )
        assert store_content.loc[0, "query_string"] == query_string

    def test_export_import_cache(self, tmp_path, query_string, metadata, results):
        cache_store1 = tmp_path / "cache1"
        cache_store2 = tmp_path / "cache2"
        cache_export_file = tmp_path / "cache.zip"

        store1 = store.ParquetStore(cache_store=cache_store1)
        store2 = store.ParquetStore(cache_store=cache_store2)

        store1.dump(query_string, results, metadata)

        store1.export(cache_export_file)
        store2.import_cache(cache_export_file)

        assert store1.list().equals(store2.list())
