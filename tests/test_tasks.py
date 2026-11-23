import pytest
from app.tasks import execute_job

def test_sum_numbers():
    assert execute_job("sum_numbers", {"numbers": [2, 3, 5]}) == {"sum": 10}

def test_word_count():
    assert execute_job("word_count", {"text": "hello backend world"}) == {"count": 3}

def test_rejects_bad_payload():
    with pytest.raises(ValueError, match="nonempty list"):
        execute_job("sum_numbers", {"numbers": []})
