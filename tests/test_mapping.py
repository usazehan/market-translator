from src.pipeline.graph import run_pipeline

def test_sample_translation():
    out = run_pipeline(channel="amazon", catalog_path="data/samples/catalog_sample.csv", batch_size=2, dry_run=True, extra={})
    assert out["counts"]["input_items"] == 3
    assert out["counts"]["mapped"] == 3
    assert out["counts"]["valid"] >= 2
