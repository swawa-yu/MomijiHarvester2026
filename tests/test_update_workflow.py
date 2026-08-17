from pathlib import Path


def test_consumer_update_pull_request_is_created_as_draft():
    workflow = Path(".github/workflows/update-momiji2.yml").read_text(encoding="utf-8")

    assert 'gh pr create --repo swawa-yu/momiji2 --base develop --head "$BRANCH" --draft' in workflow
