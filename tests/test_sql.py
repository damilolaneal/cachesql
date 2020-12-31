import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from sqlcache import __version__, sql, store, utils


def fake_read_sql(sql, con=None):
    query_hash = store.hash_query(sql)
    return pd.DataFrame(
        data=[[sql, query_hash]], columns=["query_string", "query_hash"]
    )


@patch.object(sql.pd, "read_sql", side_effect=fake_read_sql)
class TestDBConnector:
    def test__querydb(self, mock_read_sql, db, query_string):
        df = db._querydb(query_string)
        assert isinstance(df, pd.DataFrame)
        mock_read_sql.assert_called_once()

    def test_load_results_from_cache(self, mock_read_sql, db, query_string):
        """Test the cache fetches results from cache on a second call"""

        assert not db.exists_in_cache(query_string)
        assert (
            mock_read_sql.call_count == 0
        ), "'db._querydb' should not have been called up to this point"

        # First call should call the function and dump results to cache
        df1 = db.querydb(query_string=query_string)
        assert db.exists_in_cache(query_string)
        assert (
            mock_read_sql.call_count == 1
        ), "'db._querydb' should have been invoked by the cache mechanism"

        # Second call should load results from cache without calling the function
        df2 = db.querydb(query_string=query_string)
        assert mock_read_sql.call_count == 1, (
            "'db._querydb' should have not been been called any more. "
            "Results should have been loaded from cache"
        )
        assert df1.equals(df2)

    def test_force_results_to_cache(self, mock_read_sql, db, query_string):
        """Test the cache is refreshed with the force flag and a second function call"""

        assert not db.exists_in_cache(query_string)
        assert (
            mock_read_sql.call_count == 0
        ), "'db._querydb' should not have been called up to this point"

        # First call should call the function and dump results to cache
        _ = db.querydb(query_string=query_string)
        assert db.exists_in_cache(query_string)
        assert (
            mock_read_sql.call_count == 1
        ), "'db._querydb' should have been invoked by the cache mechanism"

        # Second call should call the function again and refresh results on cache
        _ = db.querydb(query_string=query_string, force=True)
        assert (
            mock_read_sql.call_count == 2
        ), "'db._querydb' should have been invoked again because of the use of force flag"

    def test_bypass_cache(self, mock_read_sql, db, query_string):
        """Test that bypassing the cache ignores previous calls and does not dump results"""

        assert not db.exists_in_cache(query_string)
        assert (
            mock_read_sql.call_count == 0
        ), "'db._querydb' should not have been called up to this point"

        # First call that should completely bypass the cache
        _ = db.querydb(query_string=query_string, cache=False)
        assert not db.exists_in_cache(
            query_string
        ), "Nothing should have been dumped to cache because of the bypass flag"
        assert (
            mock_read_sql.call_count == 1
        ), "'querydb' should have been invoked by the cache mechanism"

        # Second call that should dump the results to cache
        _ = db.querydb(query_string=query_string, cache=True)
        assert db.exists_in_cache(
            query_string
        ), "This time, results should have been dumped to cache"
        assert (
            mock_read_sql.call_count == 2
        ), "'querydb' should have been invoked again because nothing was saved on cache on previous call"

        # Third call that should ignore the already existing dumped results
        _ = db.querydb(query_string=query_string, cache=False)
        assert mock_read_sql.call_count == 3, (
            "'querydb' should have been invoked again because of "
            "the bypass flag that ignores existing results on cache"
        )

    def test_metadata(self, mock_read_sql, db, query_string):
        # First call should call the function and dump results to cache
        _ = db.querydb(query_string=query_string)
        assert db.exists_in_cache(query_string)
        assert (
            mock_read_sql.call_count == 1
        ), "'db._querydb' should have been invoked by the cache mechanism"

        metadata = db.store.load_metadata(query_string)
        assert metadata["db_name"] == db.name
        assert metadata["sqlcache"] == __version__
        assert metadata["username"] == db.engine.url.username or "unknown"
        assert metadata["query_string"] == utils.normalize_query(query_string)
        assert "executed_at" in metadata
        assert "duration" in metadata

    def test_querydb_independent_from_format(self, mock_read_sql, db):
        query1 = "select top 3 * from receipts"
        query2 = "SELECT top 3 * FROM receipts"

        assert not db.exists_in_cache(query1)
        assert (
            mock_read_sql.call_count == 0
        ), "'db._querydb' should not have been called up to this point"

        df1 = db.querydb(query_string=query1)
        assert db.exists_in_cache(query1)
        assert db.exists_in_cache(query2)
        assert (
            mock_read_sql.call_count == 1
        ), "'db._querydb' should have been invoked by the cache mechanism"

        # Second call should load results from cache without calling the function
        df2 = db.querydb(query_string=query2)
        assert mock_read_sql.call_count == 1, (
            "'db._querydb' should have not been been called any more. "
            "Results should have been loaded from cache"
        )
        assert df1.equals(df2)

    def test_db_session(self, mock_read_sql, db):
        """Test the cache fetches results from cache on a second call"""
        queries = [
            "select top 10 * from Receipts",
            "select top 20 * from Receipts",
            "select top 5 * from Receipts",
            "select top 25 * from Receipts",
        ]

        # Do the first three queries and assert they exist in the session
        for i in range(3):
            _ = db.querydb(query_string=queries[i])
            assert db.exists_in_cache(queries[i])
            assert (
                mock_read_sql.call_count == i + 1
            ), "'querydb' should have been invoked by the cache mechanism"
            assert (
                queries[i] in db.session
            ), "The query should have been stored on session"

        # Call again the first query and assert it is not duplicated in the session
        _ = db.querydb(query_string=queries[0])
        assert mock_read_sql.call_count == 3
        assert len(db.session) == 3
        assert set(queries[:3]) == db.session

    def test_export_import_session(self, mock_read_sql, tmp_path):
        db1a = sql.DB(
            name="db1a",
            uri="sqlite:///file:path/to/database1a?mode=ro&uri=true",
            cache_store=tmp_path / "cache1",
        )

        db1b = sql.DB(
            name="db1b",
            uri="sqlite:///file:path/to/database1b?mode=ro&uri=true",
            cache_store=tmp_path / "cache1",
        )

        db2 = sql.DB(
            name="db2",
            uri="sqlite:///file:path/to/database2?mode=ro&uri=true",
            cache_store=tmp_path / "cache2",
        )

        _ = db1a.querydb(query_string="select top 3 * from Receipts")
        _ = db1b.querydb(query_string="select top 6 * from Receipts")

        db1a.export_session(tmp_path / "cache.zip")
        db2.store.import_cache(tmp_path / "cache.zip")

        # cache2 should load only the query done by cache1a and not the query from cache1b.
        assert db2.store.list().shape[0] == 1
        assert db2.store.list().loc[0, "query_string"] == utils.normalize_query(
            "select top 3 * from Receipts"
        )

    def test_default_cache_location(self, mock_read_sql, tmp_path):
        previous_wd = os.getcwd()

        os.chdir(tmp_path)
        db = sql.DB(
            name="db",
            uri="sqlite:///file:path/to/database1a?mode=ro&uri=true",
        )
        assert db.store.cache_store == Path(tmp_path) / ".cache" / db.name
        os.chdir(previous_wd)

    def test_log(self, mock_read_sql, tmp_path, query_string, caplog):
        db_verbose = sql.DB(
            name="db_verbose",
            uri="sqlite:///file:path/to/database1a?mode=ro&uri=true",
            cache_store=tmp_path,
        )
        import logging

        # Make sure the library doesn't log anything by default
        _ = db_verbose.querydb(query_string, cache=False)
        assert len(caplog.records) == 0
        assert caplog.text == ""

        # Make sure that the library logs messages when configuration is set
        with caplog.at_level(logging.INFO):
            _ = db_verbose.querydb(query_string)
            assert len(caplog.records) == 3

            assert "Querying 'db_verbose'" in caplog.text
            assert "Finished in" in caplog.text
            assert "Results have been stored in cache" in caplog.text

            caplog.clear()

            _ = db_verbose.querydb(query_string)
            assert len(caplog.records) == 3

            assert "Querying 'db_verbose'" in caplog.text
            assert "Loading from cache." in caplog.text
            assert "The cached query was executed on the" in caplog.text
