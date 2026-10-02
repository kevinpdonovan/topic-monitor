from engine.pipeline.dedupe import cluster_news, dedupe, merge_versions, work_key
from engine.pipeline.items import make_item


def test_work_key_is_always_computable_for_titled_items():
    # Regression test for the bug found in insubordinate-terminal production
    # data (data/runs/2026-W40/candidates.json): two Zenodo re-uploads of the
    # same work, each with a different DOI, both silently missing work_key,
    # reached the review issue as two separate checkboxes instead of being
    # merged. work_key() must never be skippable — every item with a title
    # gets one.
    item = make_item(title="BRICS and the transformation of the global political economy", source_type="report", connector="test", doi="10.5281/zenodo.22855615")
    assert work_key(item)


def test_merge_versions_collapses_same_work_different_doi():
    a = make_item(
        title="BRICS and the transformation of the global political economy",
        source_type="report", connector="test",
        doi="10.5281/zenodo.22855615", authors=["Jane Smith"],
    )
    b = make_item(
        title="BRICS and the Transformation of the Global Political Economy",  # case differs
        source_type="report", connector="test",
        doi="10.5281/zenodo.22855616", authors=["Jane Smith"],  # different re-upload DOI
    )
    kept, merged_count = merge_versions([a, b])
    assert merged_count == 1
    assert len(kept) == 1


def test_merge_versions_prefers_the_richer_record():
    thin = make_item(title="Designing retail CBDC systems", source_type="working_paper", connector="a", authors=["A Author"])
    rich = make_item(
        title="Designing retail CBDC systems", source_type="article", connector="b",
        authors=["A Author"], abstract="A long and useful abstract " * 5, doi="10.1/xyz",
    )
    kept, merged_count = merge_versions([thin, rich])
    assert merged_count == 1
    assert kept[0]["doi"] == "10.1/xyz"
    assert kept[0]["source_type"] == "article"


def test_cluster_news_groups_syndicated_coverage():
    a = make_item(title="Nigeria central bank expands eNaira pilot program nationwide", source_type="news", connector="rss", url="https://outlet-a.com/story", venue="Outlet A")
    b = make_item(title="Nigeria central bank expands eNaira pilot programme nationwide", source_type="news", connector="rss", url="https://outlet-b.com/story", venue="Outlet B")
    kept, merged_count = cluster_news([a, b])
    assert merged_count == 1
    assert len(kept) == 1


def test_dedupe_reports_duplicate_rate():
    a = make_item(title="A unique work about CBDC design", source_type="article", connector="openalex", doi="10.1/same")
    b = make_item(title="A Unique Work About CBDC Design", source_type="article", connector="gdelt", doi="10.1/SAME")  # same DOI, different case -> exact id match
    c = make_item(title="A completely different unrelated paper", source_type="article", connector="openalex", doi="10.1/other")
    result = dedupe([a, b, c])
    assert result["stats"]["input"] == 3
    assert result["stats"]["output"] == 2
    assert result["stats"]["exact_merged"] == 1
    assert 0 < result["stats"]["duplicate_rate"] < 1
